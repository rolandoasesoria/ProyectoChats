"""IA que responde: conversaciones pendientes de tratar, propuestas y respuestas, y chats con la IA pausada."""
from ..db import Conn, rows


def candidates(conn: Conn, window_from: str, human_from: str | None, sent_from: str, max_sent: int) -> list[dict]:
    """Conversaciones de WhatsApp cuyo último mensaje es del cliente y está dentro de la ventana de respuesta
    (`window_from`), que la IA aún no ha tratado, sin la IA pausada, sin mensajes de una persona del equipo desde
    `human_from` (None = da igual) y con menos de `max_sent` respuestas de la IA desde `sent_from`."""
    human_sql = """ AND NOT EXISTS (SELECT 1 FROM messages h WHERE h.conversation_id = c.id AND h.direction = 'out'
                                       AND h.by_ai = 0 AND h.sent_at >= ?)""" if human_from else ""
    return rows(conn.execute(
        f"""
        SELECT c.id AS conversation_id, c.client_id, c.owner_user_id, last.id AS message_id
          FROM conversations c
          JOIN LATERAL (SELECT m.id, m.direction, m.sent_at FROM messages m WHERE m.conversation_id = c.id
                         ORDER BY m.sent_at DESC, m.id DESC LIMIT 1) last ON TRUE
         WHERE c.channel = 'whatsapp' AND last.direction = 'in' AND last.sent_at >= ?
           AND c.dismissed_message_id IS DISTINCT FROM last.id
           AND NOT EXISTS (SELECT 1 FROM ai_replies r WHERE r.conversation_id = c.id AND r.message_id = last.id)
           AND NOT EXISTS (SELECT 1 FROM ai_paused_conversations p WHERE p.conversation_id = c.id)
           AND (SELECT count(*) FROM ai_replies r WHERE r.conversation_id = c.id AND r.status = 'sent'
                  AND r.created_at >= ?) < ?
           {human_sql}
        """,
        (window_from, sent_from, max_sent, *([human_from] if human_from else [])),
    ))


def conversation(conn: Conn, conversation_id: int) -> dict | None:
    """Dueño, canal y cliente de la conversación, y el responsable del cliente."""
    row = conn.execute(
        """SELECT c.id, c.owner_user_id, c.channel, c.client_id, cl.assignee_user_id
             FROM conversations c JOIN clients cl ON cl.id = c.client_id WHERE c.id = ?""",
        (conversation_id,)).fetchone()
    return dict(row) if row else None


def insert(conn: Conn, conversation_id: int, message_id: int, status: str, text: str = "", reason: str = "") -> int | None:
    """Registra lo que ha hecho la IA con ese mensaje; None si otro proceso ya lo había tratado."""
    row = conn.execute(
        """INSERT INTO ai_replies (conversation_id, message_id, status, text, reason) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (conversation_id, message_id) DO NOTHING RETURNING id""",
        (conversation_id, message_id, status, text, reason)).fetchone()
    return row[0] if row else None


def get(conn: Conn, reply_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM ai_replies WHERE id = ?", (reply_id,)).fetchone()
    return dict(row) if row else None


def lock_pending(conn: Conn, reply_id: int) -> dict | None:
    """La propuesta, si sigue pendiente (bloqueada para que dos personas no la envíen a la vez)."""
    row = conn.execute("SELECT * FROM ai_replies WHERE id = ? AND status = 'pending' FOR UPDATE", (reply_id,)).fetchone()
    return dict(row) if row else None


def set_status(conn: Conn, reply_id: int, status: str, user_id: int | None = None, text: str | None = None) -> None:
    conn.execute(
        """UPDATE ai_replies SET status = ?, decided_by = ?, decided_at = localtimestamp(0), text = coalesce(?, text)
            WHERE id = ?""", (status, user_id, text, reply_id))


def count_pending_for_owner(conn: Conn, user_id: int) -> int:
    """Propuestas de la IA esperando que las revise quien lleva la conversación."""
    return conn.execute(
        """SELECT count(*) FROM ai_replies r JOIN conversations c ON c.id = r.conversation_id
            WHERE r.status = 'pending' AND c.owner_user_id = ?""", (user_id,)).fetchone()[0]


def pending_for(conn: Conn, conversation_id: int) -> dict | None:
    """La propuesta pendiente de la conversación (la más reciente)."""
    row = conn.execute(
        """SELECT * FROM ai_replies WHERE conversation_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1""",
        (conversation_id,)).fetchone()
    return dict(row) if row else None


def discard_stale(conn: Conn, conversation_id: int, keep_id: int) -> None:
    """Al llegar otro mensaje del cliente, las propuestas anteriores pendientes dejan de tener sentido."""
    conn.execute("UPDATE ai_replies SET status = 'discarded' WHERE conversation_id = ? AND status = 'pending' AND id != ?",
                 (conversation_id, keep_id))


def is_paused(conn: Conn, conversation_id: int) -> bool:
    return conn.execute("SELECT 1 FROM ai_paused_conversations WHERE conversation_id = ?",
                        (conversation_id,)).fetchone() is not None


def set_paused(conn: Conn, conversation_id: int, paused: bool, user_id: int) -> None:
    if paused:
        conn.execute("""INSERT INTO ai_paused_conversations (conversation_id, paused_by) VALUES (?, ?)
                        ON CONFLICT (conversation_id) DO NOTHING""", (conversation_id, user_id))
    else:
        conn.execute("DELETE FROM ai_paused_conversations WHERE conversation_id = ?", (conversation_id,))
