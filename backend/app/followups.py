"""Seguimientos: «avísame si el cliente no contesta en X días».

Se crean al responder (enviando desde la app o copiando el borrador). Cuando vence el plazo y el cliente no ha
escrito nada nuevo en esa conversación, aparece en la bandeja «Sin responder» de quien lo pidió. Si el cliente
contesta antes, el seguimiento se resuelve solo.
"""

from .db import get_conn, rows
from .errors import NotFound

# Mensaje nuevo del cliente en la conversación después de crear el seguimiento.
_ANSWERED = """EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = f.conversation_id
                         AND m.direction = 'in' AND m.id > f.after_message_id)"""


def create(conversation_id: int, user_id: int, days: int) -> dict:
    with get_conn() as conn:
        last = conn.execute("SELECT max(id) AS id FROM messages WHERE conversation_id = ?", (conversation_id,)).fetchone()
        if last is None or last["id"] is None:
            raise NotFound("Conversación no encontrada o vacía")
        # Un seguimiento por persona y conversación: el nuevo sustituye al anterior.
        conn.execute("DELETE FROM follow_ups WHERE conversation_id = ? AND user_id = ?", (conversation_id, user_id))
        row = conn.execute(
            f"""INSERT INTO follow_ups (conversation_id, user_id, after_message_id, due_at)
                VALUES (?, ?, ?, localtimestamp(0) + interval '{int(days)} days') RETURNING id, due_at""",
            (conversation_id, user_id, last["id"])).fetchone()
    return dict(row)


def due(user_id: int) -> list[dict]:
    """Seguimientos vencidos del usuario cuyo cliente sigue sin contestar. Borra los ya resueltos."""
    with get_conn() as conn:
        conn.execute(f"DELETE FROM follow_ups f WHERE f.user_id = ? AND {_ANSWERED}", (user_id,))
        return rows(conn.execute(
            """SELECT f.id, f.conversation_id, f.due_at, f.created_at, c.channel, c.client_id, cl.name AS client,
                      m.id AS message_id, m.body, m.sent_at
                 FROM follow_ups f
                 JOIN conversations c ON c.id = f.conversation_id
                 JOIN clients cl ON cl.id = c.client_id
                 JOIN messages m ON m.id = f.after_message_id
                WHERE f.user_id = ? AND f.due_at <= localtimestamp
                ORDER BY f.due_at""", (user_id,)))


def delete(follow_up_id: int, user_id: int) -> None:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM follow_ups WHERE id = ? AND user_id = ?", (follow_up_id, user_id))
    if not cur.rowcount:
        raise NotFound("Seguimiento no encontrado")
