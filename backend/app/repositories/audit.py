"""Registro de accesos y acciones delicadas, y datos completos de un cliente (exportar y borrar)."""
from ..db import Conn, rows

# ---------------------------------------------------------------- Registro

def logged_recently(conn: Conn, user_id: int, action: str, client_id: int | None, minutes: int) -> bool:
    """¿Ya hay una entrada igual (usuario, acción, cliente) en los últimos `minutes` minutos?"""
    return conn.execute(
        """SELECT 1 FROM audit_log WHERE user_id = ? AND action = ? AND client_id IS NOT DISTINCT FROM ?
             AND created_at > localtimestamp - make_interval(mins => ?)""",
        (user_id, action, client_id, minutes)).fetchone() is not None


def client_name(conn: Conn, client_id: int) -> str | None:
    row = conn.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
    return row["name"] if row else None


def insert(conn: Conn, user_id: int, action: str, client_id: int | None, client_name: str | None,
           detail: str | None) -> None:
    conn.execute("INSERT INTO audit_log (user_id, action, client_id, client_name, detail) VALUES (?, ?, ?, ?, ?)",
                 (user_id, action, client_id, client_name, detail))


def list_entries(conn: Conn, limit: int, user_id: int | None = None, action: str | None = None) -> list[dict]:
    """Entradas más recientes primero; sin `user_id` / `action` no se filtra por ellos."""
    sql = """SELECT a.id, a.created_at, a.action, a.client_id, a.client_name, a.detail, u.name AS user
               FROM audit_log a LEFT JOIN users u ON u.id = a.user_id WHERE 1 = 1"""
    args: list = []
    if user_id:
        sql += " AND a.user_id = ?"
        args.append(user_id)
    if action:
        sql += " AND a.action = ?"
        args.append(action)
    sql += " ORDER BY a.id DESC LIMIT ?"
    args.append(limit)
    return rows(conn.execute(sql, args))


# ---------------------------------------------------------------- Datos de un cliente (exportar y borrar)

def get_client(conn: Conn, client_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


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


def delete_client(conn: Conn, client_id: int) -> None:
    """Borra el cliente; la base de datos borra en cascada todo lo que cuelga de él."""
    conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
