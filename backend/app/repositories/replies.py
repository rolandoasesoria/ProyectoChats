"""Respuestas guardadas y macros, y los datos del cliente que se usan para rellenarlas."""
from ..db import Conn, rows

# Columnas que se pueden escribir: sus nombres se pegan en la consulta (los valores van como parámetros).
COLUMNS = ("title", "shortcut", "body", "set_status", "add_tag", "mark_done")


def _check_columns(fields: dict) -> None:
    unknown = set(fields) - set(COLUMNS)
    if unknown:
        raise ValueError(f"Columnas no válidas: {', '.join(sorted(unknown))}")


def list_all(conn: Conn) -> list[dict]:
    return rows(conn.execute(
        """SELECT r.id, r.title, r.shortcut, r.body, r.set_status, r.add_tag, r.mark_done = 1 AS mark_done,
                  r.created_by, u.name AS author
             FROM saved_replies r LEFT JOIN users u ON u.id = r.created_by
            ORDER BY lower(r.title)"""))


def shortcut_taken(conn: Conn, shortcut: str, reply_id: int | None = None) -> bool:
    """¿Otra respuesta (distinta de `reply_id`) ya usa este atajo?"""
    return conn.execute("SELECT 1 FROM saved_replies WHERE lower(shortcut) = ? AND id IS DISTINCT FROM ?",
                        (shortcut, reply_id)).fetchone() is not None


def insert(conn: Conn, fields: dict, created_by: int) -> int:
    _check_columns(fields)
    return conn.execute(
        f"INSERT INTO saved_replies ({', '.join(fields)}, created_by) VALUES ({', '.join('?' * len(fields))}, ?) RETURNING id",
        [*fields.values(), created_by]).lastrowid


def update(conn: Conn, reply_id: int, fields: dict) -> None:
    _check_columns(fields)
    conn.execute(f"UPDATE saved_replies SET {', '.join(f'{k} = ?' for k in fields)}, updated_at = localtimestamp(0) "
                 "WHERE id = ?", [*fields.values(), reply_id])


def delete(conn: Conn, reply_id: int) -> None:
    conn.execute("DELETE FROM saved_replies WHERE id = ?", (reply_id,))


# ---------------------------------------------------------------- Datos del cliente para rellenar las variables

def client(conn: Conn, client_id: int) -> dict | None:
    row = conn.execute("SELECT id, name, company FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def client_facts(conn: Conn, client_id: int) -> list[dict]:
    """Datos clave de la ficha (sin los descartados)."""
    return rows(conn.execute(
        "SELECT label, value FROM client_facts WHERE client_id = ? AND origin != 'dismissed'", (client_id,)))


def client_tags(conn: Conn, client_id: int) -> list[str]:
    return [r["tag"] for r in conn.execute("SELECT tag FROM client_tags WHERE client_id = ?", (client_id,))]


def last_incoming_message_id(conn: Conn, conversation_id: int, client_id: int) -> int | None:
    """Último mensaje del cliente en esa conversación (que debe ser suya)."""
    row = conn.execute(
        """SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE c.id = ? AND c.client_id = ? AND m.direction = 'in' ORDER BY m.sent_at DESC, m.id DESC LIMIT 1""",
        (conversation_id, client_id)).fetchone()
    return row["id"] if row else None
