"""Análisis de clientes con IA: el resultado guardado (resumen, prioridad, ánimo) y las lecturas que se le
pasan a la IA como contexto (cliente, mensajes, equipo, conversación a la que se responde)."""
from ..db import Conn, rows

# ---------------------------------------------------------------- Resultado del análisis


def get(conn: Conn, client_id: int) -> dict | None:
    row = conn.execute(
        """SELECT summary, analyzed_at, last_message_id, priority, mood, priority_reason
             FROM client_analysis WHERE client_id = ?""", (client_id,)
    ).fetchone()
    return dict(row) if row else None


def save(conn: Conn, client_id: int, summary: str, last_message_id: int, priority: str | None, mood: str | None,
         priority_reason: str | None) -> None:
    conn.execute(
        """INSERT INTO client_analysis (client_id, summary, last_message_id, priority, mood, priority_reason,
                                       analyzed_at)
           VALUES (?, ?, ?, ?, ?, ?, localtimestamp(0))
           ON CONFLICT(client_id) DO UPDATE SET summary = excluded.summary,
               last_message_id = excluded.last_message_id, priority = excluded.priority, mood = excluded.mood,
               priority_reason = excluded.priority_reason, analyzed_at = excluded.analyzed_at""",
        (client_id, summary, last_message_id, priority, mood, priority_reason),
    )


def count_messages_after(conn: Conn, client_id: int, message_id: int) -> int:
    """Mensajes del cliente (todas sus conversaciones) posteriores a `message_id`."""
    return conn.execute(
        """SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE c.client_id = ? AND m.id > ?""",
        (client_id, message_id),
    ).fetchone()[0]


# ---------------------------------------------------------------- Contexto para la IA

def client(conn: Conn, client_id: int) -> dict | None:
    row = conn.execute("SELECT id, name, company FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def client_notice_target(conn: Conn, client_id: int) -> dict | None:
    """Nombre del cliente y su responsable, para avisarle."""
    row = conn.execute("SELECT name, assignee_user_id FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def recent_client_messages(conn: Conn, client_id: int, limit: int) -> list[dict]:
    """Los `limit` mensajes más recientes del cliente en todos los canales, en orden cronológico."""
    return rows(conn.execute(
        """SELECT * FROM (
               SELECT m.id, m.direction, m.sender, m.body, m.sent_at, c.channel, c.owner_user_id, u.name AS owner
                 FROM messages m JOIN conversations c ON c.id = m.conversation_id
                 JOIN users u ON u.id = c.owner_user_id
                WHERE c.client_id = ? ORDER BY m.sent_at DESC, m.id DESC LIMIT ?
           ) ORDER BY sent_at, id""",
        (client_id, limit),
    ))


def active_users(conn: Conn) -> list[dict]:
    return rows(conn.execute("SELECT id, name FROM users WHERE active = 1"))


def conversation(conn: Conn, conversation_id: int) -> dict | None:
    row = conn.execute(
        """SELECT c.id, c.channel, c.subject, c.client_id, cl.name AS client, u.name AS owner
             FROM conversations c JOIN clients cl ON cl.id = c.client_id
             JOIN users u ON u.id = c.owner_user_id WHERE c.id = ?""", (conversation_id,)).fetchone()
    return dict(row) if row else None


def conversation_thread(conn: Conn, conversation_id: int) -> list[dict]:
    """Los 40 últimos mensajes de la conversación, en orden cronológico."""
    return rows(conn.execute(
        """SELECT * FROM (SELECT direction, sender, body, sent_at FROM messages WHERE conversation_id = ?
                           ORDER BY sent_at DESC, id DESC LIMIT 40) ORDER BY sent_at""", (conversation_id,)))


def other_channel_messages(conn: Conn, client_id: int, conversation_id: int) -> list[dict]:
    """Los 20 últimos mensajes del cliente en sus otras conversaciones, en orden cronológico."""
    return rows(conn.execute(
        """SELECT * FROM (SELECT m.direction, m.sender, m.body, m.sent_at, c.channel FROM messages m
                           JOIN conversations c ON c.id = m.conversation_id
                          WHERE c.client_id = ? AND c.id != ? ORDER BY m.sent_at DESC LIMIT 20)
           ORDER BY sent_at""", (client_id, conversation_id)))
