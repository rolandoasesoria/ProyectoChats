"""Usuarios, contraseñas y sesiones de inicio de sesión.

- Contraseñas: hash scrypt con sal aleatoria (biblioteca estándar, sin dependencias extra).
- Sesiones: token aleatorio en una cookie HttpOnly; en la base de datos solo se guarda su hash SHA-256.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie

from .config import config
from .db import get_conn
from .errors import Conflict, Forbidden, InvalidInput, NotAuthenticated, NotFound, TooManyAttempts
from .repositories import sessions as sessions_repo
from .repositories import users as users_repo

COOKIE_NAME = "pc_session"
SESSION_DAYS = 30
# La cookie se marca como Secure automáticamente si la petición llega por HTTPS;
# COOKIE_SECURE=true la fuerza siempre (recomendado en producción).
COOKIE_SECURE = config.security.cookie_secure
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128  # evita que una contraseña enorme se use para saturar el servidor

# Protección contra fuerza bruta: en una ventana de LOCK_MINUTES, como mucho
# MAX_FAILS_PER_USER fallos por usuario y MAX_FAILS_PER_IP fallos por dirección IP.
LOCK_MINUTES = config.security.login_lock_minutes
MAX_FAILS_PER_USER = config.security.login_max_fails_per_user
MAX_FAILS_PER_IP = config.security.login_max_fails_per_ip

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


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
        raise InvalidInput(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvalidInput(f"La contraseña no puede tener más de {MAX_PASSWORD_LENGTH} caracteres.")


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
        for key, value, limit in (("username", username.lower(), MAX_FAILS_PER_USER),
                                  ("ip", ip, MAX_FAILS_PER_IP)):
            # El intento que activó el bloqueo es el N-ésimo más reciente; el bloqueo dura hasta que caduque.
            failed_at = sessions_repo.nth_recent_failure_at(conn, key, value, since, limit)
            if failed_at:
                unlock = datetime.fromisoformat(failed_at).replace(tzinfo=timezone.utc) \
                    + timedelta(minutes=LOCK_MINUTES)
                minutes = max(1, round((unlock - datetime.now(timezone.utc)).total_seconds() / 60))
                raise TooManyAttempts(f"Demasiados intentos fallidos. Vuelve a intentarlo en {minutes} min "
                                      "o pide a un administrador que restablezca tu contraseña.")


def _record_failure(username: str, ip: str) -> None:
    with get_conn() as conn:
        sessions_repo.purge_failures_before(conn, _minutes_ago(LOCK_MINUTES * 4))
        sessions_repo.insert_failure(conn, username, ip, _now())


def clear_failures(username: str) -> None:
    with get_conn() as conn:
        sessions_repo.delete_failures(conn, username)


def login(username: str, password: str, ip: str) -> tuple[str, dict]:
    """Devuelve (token, usuario) o lanza 401/429. El mensaje no revela si el usuario existe."""
    username = username.strip()
    _check_lockout(username, ip)
    with get_conn() as conn:
        row = users_repo.get_with_password_by_username(conn, username)
    valid = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
    if not row or not valid or not row["active"]:
        _record_failure(username, ip)
        raise NotAuthenticated("Usuario o contraseña incorrectos.")
    clear_failures(username)
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        sessions_repo.purge_expired(conn, _now())
        sessions_repo.insert(conn, _token_hash(token), row["id"], expires)
    user = dict(row)
    user.pop("password_hash")
    return token, user


def logout(token: str | None) -> None:
    if token:
        with get_conn() as conn:
            sessions_repo.delete(conn, _token_hash(token))


def end_all_sessions(user_id: int, except_token: str | None = None) -> None:
    """Cierra todas las sesiones del usuario (p. ej. al cambiar la contraseña)."""
    keep = _token_hash(except_token) if except_token else ""
    with get_conn() as conn:
        sessions_repo.delete_for_user(conn, user_id, keep)


def current_user(pc_session: str | None = Cookie(None)) -> dict:
    """Dependencia de FastAPI: usuario autenticado o 401."""
    if not pc_session:
        raise NotAuthenticated("Inicia sesión para continuar.")
    with get_conn() as conn:
        user = sessions_repo.active_user(conn, _token_hash(pc_session), _now())
    if not user:
        raise NotAuthenticated("La sesión ha caducado. Vuelve a iniciar sesión.")
    return user


def require_admin(user: dict) -> dict:
    if user["role"] != "admin":
        raise Forbidden("Solo los administradores pueden hacer esto.")
    return user


def list_users() -> list[dict]:
    with get_conn() as conn:
        return users_repo.list_all(conn)


def list_team() -> list[dict]:
    """Miembros activos del equipo (id y nombre), por orden alfabético."""
    with get_conn() as conn:
        return users_repo.list_team(conn)


def find_user_id_by_username(username: str) -> int | None:
    with get_conn() as conn:
        return users_repo.id_by_username(conn, username)


def create_user(username: str, name: str, password: str, email: str | None = None,
                role: str = "user") -> dict:
    validate_password(password)
    username = username.strip()
    if not username:
        raise InvalidInput("El nombre de usuario es obligatorio.")
    with get_conn() as conn:
        if users_repo.username_exists(conn, username):
            raise Conflict("Ese nombre de usuario ya existe.")
        if email and users_repo.email_exists(conn, email):
            raise Conflict("Ese email ya está en uso.")
        user_id = users_repo.insert(conn, username, name.strip() or username, email or None,
                                    hash_password(password), role)
        return users_repo.get(conn, user_id)


def update_user(user_id: int, **fields) -> dict:
    """Actualiza campos permitidos. `password` se guarda como hash y cierra las sesiones abiertas."""
    allowed = {"name", "email", "role", "active", "theme", "tour_version"}
    # Los indicadores (active) se guardan como 0/1: PostgreSQL no convierte booleanos a número solo.
    updates = {k: int(v) if isinstance(v, bool) else v
               for k, v in fields.items() if k in allowed and v is not None}
    password = fields.get("password")
    if password:
        validate_password(password)
        updates["password_hash"] = hash_password(password)
    with get_conn() as conn:
        users_repo.update(conn, user_id, updates)
        row = users_repo.get(conn, user_id)
    if not row:
        raise NotFound("Usuario no encontrado.")
    if password or fields.get("active") == 0:
        end_all_sessions(user_id, except_token=fields.get("keep_token"))
    if password and row["username"]:
        clear_failures(row["username"])  # restablecer la contraseña desbloquea la cuenta
    return row


def change_password(user_id: int, current_password: str, new_password: str, keep_token: str | None) -> None:
    """Cambio de contraseña por el propio usuario: exige la actual y cierra sus demás sesiones abiertas."""
    with get_conn() as conn:
        stored = users_repo.password_hash(conn, user_id)
    if not verify_password(current_password, stored):
        raise InvalidInput("La contraseña actual no es correcta.")
    # Cierra las demás sesiones abiertas del usuario, pero no la actual.
    update_user(user_id, password=new_password, keep_token=keep_token)
