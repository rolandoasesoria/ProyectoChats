"""Consultas del panel de actividad (solo lectura)."""
from ..db import Conn, rows


def messages_in_order(conn: Conn) -> list[dict]:
    """Todos los mensajes ordenados por conversación y fecha (para calcular los tiempos de respuesta)."""
    return rows(conn.execute(
        """SELECT m.conversation_id, m.direction, m.sent_at, c.owner_user_id, c.channel
             FROM messages m JOIN conversations c ON c.id = m.conversation_id
            ORDER BY m.conversation_id, m.sent_at, m.id"""))


def received_by_day_and_channel(conn: Conn, since: str) -> list[dict]:
    return rows(conn.execute(
        """SELECT to_char(m.sent_at, 'YYYY-MM-DD') AS day, c.channel, count(*) AS n
             FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE m.direction = 'in' AND m.sent_at >= ? GROUP BY day, c.channel""", (since,)))


def count_sent(conn: Conn, since: str) -> int:
    return conn.execute("SELECT count(*) FROM messages WHERE direction = 'out' AND sent_at >= ?", (since,)).fetchone()[0]


def count_active_clients(conn: Conn, since: str) -> int:
    return conn.execute(
        """SELECT count(DISTINCT c.client_id) FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE m.sent_at >= ?""", (since,)).fetchone()[0]


def clients_by_status(conn: Conn) -> dict[str, int]:
    return {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM clients GROUP BY status")}


def active_users(conn: Conn) -> list[dict]:
    return rows(conn.execute("SELECT id, name FROM users WHERE active = 1 ORDER BY name"))


def open_tasks(conn: Conn) -> list[dict]:
    return rows(conn.execute(
        "SELECT assignee_user_id, due_date FROM tasks WHERE status = 'open'"))


def clients_per_assignee(conn: Conn) -> dict[int, int]:
    return {r["assignee_user_id"]: r["n"] for r in conn.execute(
        "SELECT assignee_user_id, count(*) AS n FROM clients WHERE assignee_user_id IS NOT NULL GROUP BY assignee_user_id")}
