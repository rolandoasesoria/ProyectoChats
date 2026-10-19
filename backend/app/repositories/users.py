"""Usuarios del equipo."""
from ..db import Conn, rows

# Datos públicos del usuario (nunca el hash de la contraseña).
USER_FIELDS = "id, name, email, username, role, active, theme, tour_version, can_view_team_chats, avatar_version"
# Los mismos, con el alias «u» (para consultas que unen users con otras tablas).
U_FIELDS = ", ".join("u." + f.strip() for f in USER_FIELDS.split(","))

# Columnas que se pueden cambiar con update(): se pegan en la consulta, así que solo se aceptan estas.
_UPDATABLE = {"name", "email", "role", "active", "theme", "tour_version", "password_hash", "can_view_team_chats"}


def get(conn: Conn, user_id: int) -> dict | None:
    row = conn.execute(f"SELECT {USER_FIELDS} FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_with_password_by_username(conn: Conn, username: str) -> dict | None:
    row = conn.execute(f"SELECT {USER_FIELDS}, password_hash FROM users WHERE lower(username) = lower(?)",
                       (username,)).fetchone()
    return dict(row) if row else None


def password_hash(conn: Conn, user_id: int) -> str | None:
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["password_hash"] if row else None


def list_all(conn: Conn) -> list[dict]:
    return rows(conn.execute(f"SELECT {USER_FIELDS} FROM users ORDER BY name"))


def list_team(conn: Conn) -> list[dict]:
    """Miembros activos (id, nombre y huella de su foto), por orden alfabético."""
    return rows(conn.execute("SELECT id, name, avatar_version FROM users WHERE active = 1 ORDER BY name"))


def list_active_for_mentions(conn: Conn) -> list[dict]:
    """Usuarios activos con nombre y usuario, para reconocer las @menciones."""
    return rows(conn.execute("SELECT id, name, username FROM users WHERE active = 1"))


def id_by_username(conn: Conn, username: str) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()
    return row["id"] if row else None


def username_exists(conn: Conn, username: str) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone() is not None


def email_exists(conn: Conn, email: str, except_id: int = 0) -> bool:
    """¿Lo usa ya otro usuario? (`except_id`: el que lo cambia, que puede volver a guardar el suyo)."""
    return conn.execute("SELECT 1 FROM users WHERE lower(email) = lower(?) AND id <> ?",
                        (email, except_id)).fetchone() is not None


def insert(conn: Conn, username: str, name: str, email: str | None, password_hash: str, role: str,
           can_view_team_chats: bool = False) -> int:
    return conn.execute(
        """INSERT INTO users (username, name, email, password_hash, role, can_view_team_chats)
           VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
        (username, name, email, password_hash, role, int(can_view_team_chats)),
    ).lastrowid


def update(conn: Conn, user_id: int, updates: dict) -> None:
    """Cambia las columnas de `updates` (sin nada que cambiar no hace nada)."""
    if not updates:
        return
    unknown = set(updates) - _UPDATABLE
    if unknown:
        raise ValueError(f"columnas no permitidas: {sorted(unknown)}")
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE users SET {sets} WHERE id = ?", [*updates.values(), user_id])


def get_avatar(conn: Conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT mime, data FROM user_avatars WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def put_avatar(conn: Conn, user_id: int, mime: str, data: str, version: str) -> None:
    conn.execute("""INSERT INTO user_avatars (user_id, mime, data) VALUES (?, ?, ?)
                    ON CONFLICT (user_id) DO UPDATE SET mime = excluded.mime, data = excluded.data""",
                 (user_id, mime, data))
    conn.execute("UPDATE users SET avatar_version = ? WHERE id = ?", (version, user_id))


def delete_avatar(conn: Conn, user_id: int) -> None:
    conn.execute("DELETE FROM user_avatars WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE users SET avatar_version = '' WHERE id = ?", (user_id,))
