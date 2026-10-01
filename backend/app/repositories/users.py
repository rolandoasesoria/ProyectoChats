"""Usuarios del equipo."""
from ..db import Conn, rows

# Datos públicos del usuario (nunca el hash de la contraseña).
USER_FIELDS = "id, name, email, username, role, active, theme, tour_version"
# Los mismos, con el alias «u» (para consultas que unen users con otras tablas).
U_FIELDS = ", ".join("u." + f.strip() for f in USER_FIELDS.split(","))

# Columnas que se pueden cambiar con update(): se pegan en la consulta, así que solo se aceptan estas.
_UPDATABLE = {"name", "email", "role", "active", "theme", "tour_version", "password_hash"}


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
    """Miembros activos (id y nombre), por orden alfabético."""
    return rows(conn.execute("SELECT id, name FROM users WHERE active = 1 ORDER BY name"))


def list_active_for_mentions(conn: Conn) -> list[dict]:
    """Usuarios activos con nombre y usuario, para reconocer las @menciones."""
    return rows(conn.execute("SELECT id, name, username FROM users WHERE active = 1"))


def list_contacts(conn: Conn) -> list[dict]:
    """Todos los usuarios con id, nombre y email, por orden alfabético."""
    return rows(conn.execute("SELECT id, name, email FROM users ORDER BY name"))


def id_by_username(conn: Conn, username: str) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()
    return row["id"] if row else None


def username_exists(conn: Conn, username: str) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone() is not None


def email_exists(conn: Conn, email: str) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone() is not None


def insert(conn: Conn, username: str, name: str, email: str | None, password_hash: str, role: str) -> int:
    return conn.execute(
        "INSERT INTO users (username, name, email, password_hash, role) VALUES (?, ?, ?, ?, ?) RETURNING id",
        (username, name, email, password_hash, role),
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
