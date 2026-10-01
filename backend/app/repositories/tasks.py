"""Tareas (compromisos con los clientes), creadas a mano o por la IA."""
from ..db import Conn, rows

_SELECT = """SELECT t.id, t.client_id, cl.name AS client, t.title, t.due_date, t.status, t.origin,
                    t.source_message_id, t.assignee_user_id, u.name AS assignee, t.created_at, t.done_at
               FROM tasks t JOIN clients cl ON cl.id = t.client_id
               LEFT JOIN users u ON u.id = t.assignee_user_id"""

# Columnas que se pueden cambiar con update(): sus nombres van en el texto de la consulta, así que solo se
# admiten estos.
UPDATABLE = ("title", "due_date", "assignee_user_id", "status")


def list_filtered(conn: Conn, client_id: int | None = None, assignee_id: int | None = None,
                  status: str | None = None) -> list[dict]:
    sql = _SELECT + " WHERE 1 = 1"
    args: list = []
    if client_id is not None:
        sql += " AND t.client_id = ?"
        args.append(client_id)
    if assignee_id is not None:
        sql += " AND t.assignee_user_id = ?"
        args.append(assignee_id)
    if status:
        sql += " AND t.status = ?"
        args.append(status)
    # Primero las abiertas; dentro, las que vencen antes (las que no tienen fecha, al final).
    sql += " ORDER BY t.status = 'done', t.due_date IS NULL, t.due_date, t.id DESC"
    return rows(conn.execute(sql, args))


def get(conn: Conn, task_id: int) -> dict | None:
    row = conn.execute(_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def list_brief(conn: Conn, client_id: int) -> list[dict]:
    """Todas las tareas del cliente, abiertas y hechas, con lo justo para el análisis."""
    return rows(conn.execute(
        "SELECT id, title, status, due_date FROM tasks WHERE client_id = ? ORDER BY id", (client_id,)))


def insert_manual(conn: Conn, client_id: int, title: str, due_date: str | None, assignee_user_id: int,
                  created_by: int) -> int:
    return conn.execute(
        """INSERT INTO tasks (client_id, title, due_date, assignee_user_id, origin, created_by)
           VALUES (?, ?, ?, ?, 'manual', ?) RETURNING id""",
        (client_id, title, due_date, assignee_user_id, created_by),
    ).lastrowid


def insert_ai(conn: Conn, client_id: int, tasks: list[dict]) -> None:
    """Cada tarea: title, due_date, assignee_user_id, source_message_id."""
    conn.executemany(
        """INSERT INTO tasks (client_id, title, due_date, assignee_user_id, origin, source_message_id)
           VALUES (?, ?, ?, ?, 'ai', ?)""",
        [(client_id, t["title"], t["due_date"], t["assignee_user_id"], t["source_message_id"]) for t in tasks],
    )


def complete(conn: Conn, task_ids: list[int]) -> None:
    """Marca como hechas las tareas indicadas que sigan abiertas."""
    conn.executemany(
        "UPDATE tasks SET status = 'done', done_at = localtimestamp(0) WHERE id = ? AND status = 'open'",
        [(i,) for i in task_ids],
    )


def update(conn: Conn, task_id: int, fields: dict) -> None:
    """Cambia solo las columnas de `fields` (de UPDATABLE). Si cambia el estado, también la fecha de hecha."""
    unknown = set(fields) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"Columnas no editables: {sorted(unknown)}")
    sets = [f"{column} = ?" for column in fields]  # nombres de la lista UPDATABLE, no datos del usuario
    if "status" in fields:
        sets.append("done_at = " + ("localtimestamp(0)" if fields["status"] == "done" else "NULL"))
    if sets:
        conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", [*fields.values(), task_id])


def delete(conn: Conn, task_id: int) -> bool:
    return conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount > 0
