"""Seguimientos («avísame si el cliente no contesta»)."""
from ..db import Conn, rows

# Mensaje nuevo del cliente en la conversación después de crear el seguimiento.
_ANSWERED = """EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = f.conversation_id
                         AND m.direction = 'in' AND m.id > f.after_message_id)"""


def last_message_id(conn: Conn, conversation_id: int) -> int | None:
    return conn.execute("SELECT max(id) FROM messages WHERE conversation_id = ?", (conversation_id,)).fetchone()[0]


def delete_for_user(conn: Conn, conversation_id: int, user_id: int) -> None:
    conn.execute("DELETE FROM follow_ups WHERE conversation_id = ? AND user_id = ?", (conversation_id, user_id))


def insert(conn: Conn, conversation_id: int, user_id: int, after_message_id: int, days: int) -> dict:
    return dict(conn.execute(
        """INSERT INTO follow_ups (conversation_id, user_id, after_message_id, due_at)
           VALUES (?, ?, ?, localtimestamp(0) + make_interval(days => ?)) RETURNING id, due_at""",
        (conversation_id, user_id, after_message_id, days)).fetchone())


def delete_answered(conn: Conn, user_id: int) -> None:
    conn.execute(f"DELETE FROM follow_ups f WHERE f.user_id = ? AND {_ANSWERED}", (user_id,))


def list_due(conn: Conn, user_id: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT f.id, f.conversation_id, f.due_at, f.created_at, c.channel, c.client_id, cl.name AS client,
                  m.id AS message_id, m.body, m.sent_at
             FROM follow_ups f
             JOIN conversations c ON c.id = f.conversation_id
             JOIN clients cl ON cl.id = c.client_id
             JOIN messages m ON m.id = f.after_message_id
            WHERE f.user_id = ? AND f.due_at <= localtimestamp
            ORDER BY f.due_at""", (user_id,)))


def delete(conn: Conn, follow_up_id: int, user_id: int) -> bool:
    return conn.execute("DELETE FROM follow_ups WHERE id = ? AND user_id = ?", (follow_up_id, user_id)).rowcount > 0
