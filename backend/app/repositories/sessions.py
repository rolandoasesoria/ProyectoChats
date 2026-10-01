"""Sesiones de inicio de sesión e intentos fallidos de entrar."""
from ..db import Conn
from .users import U_FIELDS

# Por qué se cuentan los intentos fallidos: columna (o expresión) fija del código para cada clave.
_FAILURE_KEYS = {"username": "lower(username)", "ip": "ip"}


# ---------------------------------------------------------------- Intentos fallidos

def nth_recent_failure_at(conn: Conn, key: str, value: str, since: str, n: int) -> str | None:
    """Fecha del n-ésimo intento fallido más reciente desde `since` para ese usuario o IP (None si hay menos)."""
    column = _FAILURE_KEYS[key]
    row = conn.execute(
        f"""SELECT created_at FROM login_failures WHERE {column} = ? AND created_at > ?
             ORDER BY created_at DESC LIMIT 1 OFFSET ?""",
        (value, since, n - 1),
    ).fetchone()
    return row["created_at"] if row else None


def purge_failures_before(conn: Conn, before: str) -> None:
    conn.execute("DELETE FROM login_failures WHERE created_at < ?", (before,))


def insert_failure(conn: Conn, username: str, ip: str, created_at: str) -> None:
    conn.execute("INSERT INTO login_failures (username, ip, created_at) VALUES (?, ?, ?)",
                 (username, ip, created_at))


def delete_failures(conn: Conn, username: str) -> None:
    conn.execute("DELETE FROM login_failures WHERE lower(username) = lower(?)", (username,))


# ---------------------------------------------------------------- Sesiones

def purge_expired(conn: Conn, now: str) -> None:
    conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))


def insert(conn: Conn, token_hash: str, user_id: int, expires_at: str) -> None:
    conn.execute("INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                 (token_hash, user_id, expires_at))


def delete(conn: Conn, token_hash: str) -> None:
    conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))


def delete_for_user(conn: Conn, user_id: int, except_token_hash: str) -> None:
    conn.execute("DELETE FROM auth_sessions WHERE user_id = ? AND token_hash != ?", (user_id, except_token_hash))


def active_user(conn: Conn, token_hash: str, now: str) -> dict | None:
    """Usuario activo dueño de una sesión que no ha caducado."""
    row = conn.execute(
        f"""SELECT {U_FIELDS}
              FROM auth_sessions s JOIN users u ON u.id = s.user_id
             WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
        (token_hash, now),
    ).fetchone()
    return dict(row) if row else None
