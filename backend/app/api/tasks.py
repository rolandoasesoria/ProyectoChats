"""Tareas."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import notes, tasks
from ..errors import NotFound
from .deps import CurrentUser, client_or_404

router = APIRouter()


@router.get("/api/tasks")
def list_tasks(user: CurrentUser, scope: Literal["mine", "all"] = "mine",
               status: Literal["open", "done", "all"] = "open", client_id: int | None = None):
    return tasks.list_tasks(client_id=client_id, assignee_id=user["id"] if scope == "mine" else None,
                            status=None if status == "all" else status)


DatePattern = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_date: str | None = DatePattern
    assignee_user_id: int | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    due_date: str | None = DatePattern
    assignee_user_id: int | None = None
    status: Literal["open", "done"] | None = None


@router.post("/api/clients/{client_id}/tasks")
def add_task(client_id: int, req: TaskIn, user: CurrentUser):
    client_or_404(client_id)
    task = tasks.create_task(client_id, req.title, req.due_date, req.assignee_user_id, user["id"])
    notes.notify_task_assigned(task, user)
    return task


@router.patch("/api/tasks/{task_id}")
def update_task(task_id: int, req: TaskUpdate, user: CurrentUser):
    before = tasks.get_task(task_id)
    if not before:
        raise NotFound("Tarea no encontrada")
    # Solo se tocan los campos enviados (así se puede quitar la fecha o el responsable enviando null).
    task = tasks.update_task(task_id, {k: getattr(req, k) for k in req.model_fields_set})
    if task["assignee_user_id"] != before["assignee_user_id"]:
        notes.notify_task_assigned(task, user)
    return task


@router.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, _: CurrentUser):
    tasks.delete_task(task_id)
    return {"ok": True}
