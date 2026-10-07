"""Registro de accesos y acciones delicadas."""
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
