"""Respuestas guardadas y macros."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import replies
from .deps import CurrentUser

router = APIRouter()


class ReplyIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    shortcut: str | None = Field(None, max_length=31)
    body: str = Field(min_length=1, max_length=5000)
    set_status: Literal["lead", "active", "issue", "inactive"] | None = None
    add_tag: str | None = Field(None, max_length=40)
    mark_done: bool = False


class ReplyUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=100)
    shortcut: str | None = Field(None, max_length=31)
    body: str | None = Field(None, min_length=1, max_length=5000)
    set_status: Literal["lead", "active", "issue", "inactive"] | None = None
    add_tag: str | None = Field(None, max_length=40)
    mark_done: bool | None = None


@router.get("/api/replies")
def list_replies(_: CurrentUser):
    return replies.list_replies()


@router.post("/api/replies")
def create_reply(req: ReplyIn, user: CurrentUser):
    return replies.create(req.model_dump(), user["id"])


@router.patch("/api/replies/{reply_id}")
def update_reply(reply_id: int, req: ReplyUpdate, user: CurrentUser):
    # Solo los campos enviados: así se puede quitar el atajo, el estado o la etiqueta enviando null.
    return replies.update(reply_id, {k: getattr(req, k) for k in req.model_fields_set}, user)


@router.delete("/api/replies/{reply_id}")
def delete_reply(reply_id: int, user: CurrentUser):
    replies.delete(reply_id, user)
    return {"ok": True}


class UseReplyRequest(BaseModel):
    client_id: int
    conversation_id: int | None = None


@router.post("/api/replies/{reply_id}/use")
def use_reply(reply_id: int, req: UseReplyRequest, user: CurrentUser):
    """Texto con las variables rellenas para el borrador; si es una macro, aplica sus acciones."""
    return replies.use(reply_id, req.client_id, req.conversation_id, user)
