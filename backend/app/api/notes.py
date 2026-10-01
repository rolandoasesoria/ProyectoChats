"""Notas internas y avisos."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import notes
from ..errors import Forbidden, NotFound
from .deps import CurrentUser, client_or_404

router = APIRouter()


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


def _note_or_404(note_id: int) -> dict:
    note = notes.get_note(note_id)
    if not note:
        raise NotFound("Nota no encontrada")
    return note


@router.get("/api/clients/{client_id}/notes")
def list_notes(client_id: int, _: CurrentUser):
    client_or_404(client_id)
    return notes.list_notes(client_id)


@router.post("/api/clients/{client_id}/notes")
def add_note(client_id: int, req: NoteIn, user: CurrentUser):
    client_or_404(client_id)
    return notes.add_note(client_id, user, req.body.strip())


@router.patch("/api/notes/{note_id}")
def edit_note(note_id: int, req: NoteIn, user: CurrentUser):
    if _note_or_404(note_id)["user_id"] != user["id"]:
        raise Forbidden("Solo quien escribió la nota puede editarla.")
    return notes.update_note(note_id, user, req.body.strip())


@router.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user: CurrentUser):
    if _note_or_404(note_id)["user_id"] != user["id"] and user["role"] != "admin":
        raise Forbidden("Solo quien escribió la nota (o un administrador) puede borrarla.")
    notes.delete_note(note_id)
    return {"ok": True}


@router.get("/api/notifications")
def notifications(user: CurrentUser):
    return notes.list_notifications(user["id"])


class ReadRequest(BaseModel):
    ids: list[int] | None = None  # sin ids: marcar todos como leídos


@router.post("/api/notifications/read")
def read_notifications(req: ReadRequest, user: CurrentUser):
    notes.mark_read(user["id"], req.ids)
    return notes.list_notifications(user["id"])
