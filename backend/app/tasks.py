"""Tareas: compromisos con los clientes, creados a mano o propuestos por la IA (ver insights.py)."""
from .db import get_conn
from .errors import NotFound
from .repositories import tasks as repo


def list_tasks(client_id: int | None = None, assignee_id: int | None = None,
               status: str | None = None) -> list[dict]:
    with get_conn() as conn:
        return repo.list_filtered(conn, client_id, assignee_id, status)


def get_task(task_id: int) -> dict | None:
    with get_conn() as conn:
        return repo.get(conn, task_id)


def create_task(client_id: int, title: str, due_date: str | None, assignee_user_id: int | None,
                user_id: int) -> dict:
    """Tarea manual. Sin responsable, se la queda quien la crea."""
    with get_conn() as conn:
        task_id = repo.insert_manual(conn, client_id, title.strip(), due_date, assignee_user_id or user_id, user_id)
    return get_task(task_id)


def update_task(task_id: int, fields: dict) -> dict:
    """Cambia solo los campos de `fields` (así se puede quitar la fecha o el responsable con None).

    El título y el estado son obligatorios: un None en ellos se ignora."""
    fields = {k: v for k, v in fields.items() if not (k in ("title", "status") and v is None)}
    with get_conn() as conn:
        if not repo.get(conn, task_id):
            raise NotFound("Tarea no encontrada")
        repo.update(conn, task_id, fields)
        return repo.get(conn, task_id)


def delete_task(task_id: int) -> None:
    with get_conn() as conn:
        if not repo.delete(conn, task_id):
            raise NotFound("Tarea no encontrada")
