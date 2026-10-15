"""Protección de datos: mensajes con datos sensibles, borrado de mensajes antiguos (retención) y datos completos de
un cliente (exportar y borrar)."""
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


# ---------------------------------------------------------------- Datos de un cliente (exportar y borrar)

def client_conversations(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT c.id, c.channel, c.subject, c.created_at, u.name AS owner FROM conversations c
             JOIN users u ON u.id = c.owner_user_id WHERE c.client_id = ? ORDER BY c.id""", (client_id,)))


def conversation_messages(conn: Conn, conversation_id: int) -> list[dict]:
    return rows(conn.execute(
        "SELECT direction, sender, body, sent_at FROM messages WHERE conversation_id = ? ORDER BY sent_at, id",
        (conversation_id,)))


def client_summary(conn: Conn, client_id: int) -> dict | None:
    row = conn.execute("SELECT summary, analyzed_at FROM client_analysis WHERE client_id = ?",
                       (client_id,)).fetchone()
    return dict(row) if row else None


def client_identities(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute("SELECT channel, handle FROM client_identities WHERE client_id = ?", (client_id,)))


def client_tags(conn: Conn, client_id: int) -> list[str]:
    return [r["tag"] for r in conn.execute("SELECT tag FROM client_tags WHERE client_id = ?", (client_id,))]


def client_properties(conn: Conn, client_id: int) -> list[dict]:
    """Propiedades de contacto rellenadas (DNI, fechas…), con su nombre."""
    return rows(conn.execute(
        """SELECT p.label, v.value, v.updated_at FROM client_property_values v
             JOIN contact_properties p ON p.id = v.property_id
            WHERE v.client_id = ? ORDER BY p.position, p.id""", (client_id,)))


def client_facts(conn: Conn, client_id: int) -> list[dict]:
    """Datos del cliente, salvo los descartados."""
    return rows(conn.execute(
        "SELECT label, value, origin, updated_at FROM client_facts WHERE client_id = ? AND origin != 'dismissed'",
        (client_id,)))


def client_tasks(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        "SELECT title, due_date, status, created_at, done_at FROM tasks WHERE client_id = ?", (client_id,)))


def client_notes(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT n.body, n.created_at, u.name AS author FROM client_notes n
             LEFT JOIN users u ON u.id = n.user_id WHERE n.client_id = ?""", (client_id,)))


def client_documents(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT filename, mime, size, message_id, created_at, extracted_text FROM attachments
            WHERE client_id = ?""", (client_id,)))


def count_conversations(conn: Conn, client_id: int) -> int:
    return conn.execute("SELECT count(*) FROM conversations WHERE client_id = ?", (client_id,)).fetchone()[0]


def count_messages(conn: Conn, client_id: int) -> int:
    return conn.execute(
        """SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE c.client_id = ?""", (client_id,)).fetchone()[0]
