"""Notas internas del equipo sobre un cliente."""
from ..db import Conn, rows

# Columnas de una nota con su autor (lista fija del código).
_FIELDS = """n.id, n.client_id, n.body, n.created_at, n.updated_at, n.user_id, u.name AS author"""


def list_for_client(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        f"""SELECT {_FIELDS} FROM client_notes n LEFT JOIN users u ON u.id = n.user_id
            WHERE n.client_id = ? ORDER BY n.id DESC""", (client_id,)))


def get(conn: Conn, note_id: int) -> dict | None:
    row = conn.execute(f"""SELECT {_FIELDS} FROM client_notes n LEFT JOIN users u ON u.id = n.user_id
                           WHERE n.id = ?""", (note_id,)).fetchone()
    return dict(row) if row else None


def get_raw(conn: Conn, note_id: int) -> dict | None:
    """Cliente y texto de la nota, sin autor."""
    row = conn.execute("SELECT client_id, body FROM client_notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else None


def insert(conn: Conn, client_id: int, user_id: int, body: str) -> int:
    return conn.execute("INSERT INTO client_notes (client_id, user_id, body) VALUES (?, ?, ?) RETURNING id",
                        (client_id, user_id, body)).lastrowid


def update_body(conn: Conn, note_id: int, body: str) -> None:
    conn.execute("UPDATE client_notes SET body = ?, updated_at = localtimestamp(0) WHERE id = ?", (body, note_id))


def delete(conn: Conn, note_id: int) -> None:
    conn.execute("DELETE FROM client_notes WHERE id = ?", (note_id,))


def client_name(conn: Conn, client_id: int) -> str | None:
    """Nombre del cliente de la nota, para el texto de los avisos."""
    row = conn.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
    return row["name"] if row else None
