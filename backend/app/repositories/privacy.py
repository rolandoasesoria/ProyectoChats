"""Protección de datos: mensajes con datos sensibles y borrado de mensajes antiguos (retención)."""
from ..db import Conn, rows

# Mensajes enviados o recibidos hace más de N meses (N es el único parámetro).
_OLD_MESSAGE = "sent_at < localtimestamp - make_interval(months => ?)"


def client_messages(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT m.id, m.body, m.sent_at, m.sender, c.channel FROM messages m
             JOIN conversations c ON c.id = m.conversation_id WHERE c.client_id = ? ORDER BY m.sent_at""",
        (client_id,)))


def message_with_client(conn: Conn, message_id: int) -> dict | None:
    row = conn.execute(
        """SELECT m.body, c.client_id FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = ?""", (message_id,)).fetchone()
    return dict(row) if row else None


def set_message_body(conn: Conn, message_id: int, body: str) -> None:
    conn.execute("UPDATE messages SET body = ? WHERE id = ?", (body, message_id))


# ---------------------------------------------------------------- Retención

def count_old_messages(conn: Conn, months: int) -> int:
    return conn.execute(f"SELECT count(*) FROM messages WHERE {_OLD_MESSAGE}", (months,)).fetchone()[0]


def old_attachment_paths(conn: Conn, months: int) -> list[str]:
    return [r["path"] for r in conn.execute(
        f"SELECT path FROM attachments WHERE message_id IN (SELECT id FROM messages WHERE {_OLD_MESSAGE})", (months,))]


def delete_old_attachments(conn: Conn, months: int) -> None:
    conn.execute(f"DELETE FROM attachments WHERE message_id IN (SELECT id FROM messages WHERE {_OLD_MESSAGE})",
                 (months,))


def delete_old_messages(conn: Conn, months: int) -> int:
    return conn.execute(f"DELETE FROM messages WHERE {_OLD_MESSAGE}", (months,)).rowcount


def delete_empty_conversations(conn: Conn) -> int:
    return conn.execute(
        "DELETE FROM conversations c WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)"
    ).rowcount
