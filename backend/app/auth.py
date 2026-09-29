"""Usuarios, contraseñas y sesiones de inicio de sesión.

- Contraseñas: hash scrypt con sal aleatoria (biblioteca estándar, sin dependencias extra).
- Sesiones: token aleatorio en una cookie HttpOnly; en la base de datos solo se guarda su hash SHA-256.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, HTTPException

from .db import get_conn, rows

COOKIE_NAME = "pc_session"
SESSION_DAYS = 30
# La cookie se marca como Secure automáticamente si la petición llega por HTTPS;
# COOKIE_SECURE=true la fuerza siempre (recomendado en producción).
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128  # evita que una contraseña enorme se use para saturar el servidor

# Protección contra fuerza bruta: en una ventana de LOCK_MINUTES, como mucho
# MAX_FAILS_PER_USER fallos por usuario y MAX_FAILS_PER_IP fallos por dirección IP.
LOCK_MINUTES = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))
MAX_FAILS_PER_USER = int(os.getenv("LOGIN_MAX_FAILS_PER_USER", "5"))
MAX_FAILS_PER_IP = int(os.getenv("LOGIN_MAX_FAILS_PER_IP", "20"))

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
USER_FIELDS = "id, name, email, username, role, active, theme, tour_version"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt_hex, digest_hex = stored.split("$")
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(400, f"La contraseña no puede tener más de {MAX_PASSWORD_LENGTH} caracteres.")


# Hash de relleno: si el usuario no existe se verifica contra él igualmente, para que el tiempo
# de respuesta no delate qué nombres de usuario existen.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _check_lockout(username: str, ip: str) -> None:
    """Lanza 429 si el usuario o la IP han superado el número de intentos fallidos permitidos."""
    since = _minutes_ago(LOCK_MINUTES)
    with get_conn() as conn:
        for column, value, limit in (("username", username, MAX_FAILS_PER_USER), ("ip", ip, MAX_FAILS_PER_IP)):
            # El intento que activó el bloqueo es el N-ésimo más reciente; el bloqueo dura hasta que caduque.
            row = conn.execute(
                f"""SELECT created_at FROM login_failures WHERE {column} = ? AND created_at > ?
                     ORDER BY created_at DESC LIMIT 1 OFFSET ?""",
                (value, since, limit - 1),
            ).fetchone()
            if row:
                unlock = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) \
                    + timedelta(minutes=LOCK_MINUTES)
                minutes = max(1, round((unlock - datetime.now(timezone.utc)).total_seconds() / 60))
                raise HTTPException(
                    429, f"Demasiados intentos fallidos. Vuelve a intentarlo en {minutes} min "
                         "o pide a un administrador que restablezca tu contraseña.")


def _record_failure(username: str, ip: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM login_failures WHERE created_at < ?", (_minutes_ago(LOCK_MINUTES * 4),))
        conn.execute("INSERT INTO login_failures (username, ip, created_at) VALUES (?, ?, ?)",
                     (username, ip, _now()))


def clear_failures(username: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM login_failures WHERE username = ?", (username,))


def login(username: str, password: str, ip: str) -> tuple[str, dict]:
    """Devuelve (token, usuario) o lanza 401/429. El mensaje no revela si el usuario existe."""
    username = username.strip()
    _check_lockout(username, ip)
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {USER_FIELDS}, password_hash FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
    valid = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
    if not row or not valid or not row["active"]:
        _record_failure(username, ip)
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    clear_failures(username)
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (_now(),))
        conn.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_token_hash(token), row["id"], expires),
        )
    user = dict(row)
    user.pop("password_hash")
    return token, user


def logout(token: str | None) -> None:
    if token:
        with get_conn() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_token_hash(token),))


def end_all_sessions(user_id: int, except_token: str | None = None) -> None:
    """Cierra todas las sesiones del usuario (p. ej. al cambiar la contraseña)."""
    keep = _token_hash(except_token) if except_token else ""
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep))


def current_user(pc_session: str | None = Cookie(None)) -> dict:
    """Dependencia de FastAPI: usuario autenticado o 401."""
    if not pc_session:
        raise HTTPException(401, "Inicia sesión para continuar.")
    with get_conn() as conn:
        row = conn.execute(
            f"""SELECT {', '.join('u.' + f.strip() for f in USER_FIELDS.split(','))}
                  FROM auth_sessions s JOIN users u ON u.id = s.user_id
                 WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
            (_token_hash(pc_session), _now()),
        ).fetchone()
    if not row:
        raise HTTPException(401, "La sesión ha caducado. Vuelve a iniciar sesión.")
    return dict(row)


def require_admin(user: dict) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Solo los administradores pueden hacer esto.")
    return user


def list_users() -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute(f"SELECT {USER_FIELDS} FROM users ORDER BY name"))


def create_user(username: str, name: str, password: str, email: str | None = None,
                role: str = "user") -> dict:
    validate_password(password)
    username = username.strip()
    if not username:
        raise HTTPException(400, "El nombre de usuario es obligatorio.")
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone():
            raise HTTPException(409, "Ese nombre de usuario ya existe.")
        if email and conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "Ese email ya está en uso.")
        user_id = conn.execute(
            "INSERT INTO users (username, name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            (username, name.strip() or username, email or None, hash_password(password), role),
        ).lastrowid
        return dict(conn.execute(f"SELECT {USER_FIELDS} FROM users WHERE id = ?", (user_id,)).fetchone())


def update_user(user_id: int, **fields) -> dict:
    """Actualiza campos permitidos. `password` se guarda como hash y cierra las sesiones abiertas."""
    allowed = {"name", "email", "role", "active", "theme", "tour_version"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    password = fields.get("password")
    if password:
        validate_password(password)
        updates["password_hash"] = hash_password(password)
    with get_conn() as conn:
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE users SET {sets} WHERE id = ?", [*updates.values(), user_id])
        row = conn.execute(f"SELECT {USER_FIELDS} FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Usuario no encontrado.")
    if password or fields.get("active") == 0:
        end_all_sessions(user_id, except_token=fields.get("keep_token"))
    if password and row["username"]:
        clear_failures(row["username"])  # restablecer la contraseña desbloquea la cuenta
    return dict(row)
