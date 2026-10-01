"""Bandeja «Sin responder»: posponer, seguimientos y marcar como atendido."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import audit, followups, search
from ..errors import InvalidInput, NotFound
from .deps import CurrentUser

router = APIRouter()


@router.get("/api/inbox/counts")
def inbox_counts(user: CurrentUser):
    """Cuántas conversaciones esperan respuesta: mías y de todo el equipo (solo números, sin contenido)."""
    return {"mine": len(search.unanswered(user["id"], "mine")), "team": len(search.unanswered(user["id"], "team"))}


@router.get("/api/inbox")
def inbox(user: CurrentUser, scope: Literal["mine", "team"] = "mine", snoozed: bool = False):
    """Bandeja "Sin responder": conversaciones cuyo último mensaje es del cliente (o las pospuestas)."""
    if scope == "team":
        audit.log(user["id"], "team_inbox", throttle=True)
    return search.unanswered(user["id"], scope, snoozed)


class SnoozeRequest(BaseModel):
    until: datetime
    message_id: int


@router.post("/api/conversations/{conversation_id}/snooze")
def snooze(conversation_id: int, req: SnoozeRequest, _: CurrentUser):
    """Pospone la conversación: vuelve a la bandeja en esa fecha, o antes si el cliente escribe."""
    until = req.until.astimezone(timezone.utc).replace(tzinfo=None) if req.until.tzinfo else req.until
    if until <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise InvalidInput("La fecha tiene que ser futura.")
    if not search.snooze(conversation_id, until.isoformat(timespec="seconds"), req.message_id):
        raise NotFound("Conversación no encontrada")
    return {"ok": True}


@router.delete("/api/conversations/{conversation_id}/snooze")
def unsnooze(conversation_id: int, _: CurrentUser):
    if not search.snooze(conversation_id, None):
        raise NotFound("Conversación no encontrada")
    return {"ok": True}


class FollowUpRequest(BaseModel):
    days: int = Field(ge=1, le=60)


@router.post("/api/conversations/{conversation_id}/follow-up")
def create_follow_up(conversation_id: int, req: FollowUpRequest, user: CurrentUser):
    """«Avísame si no contesta en X días»."""
    return followups.create(conversation_id, user["id"], req.days)


@router.get("/api/follow-ups")
def due_follow_ups(user: CurrentUser):
    """Seguimientos vencidos: clientes que no han contestado en el plazo."""
    return followups.due(user["id"])


@router.delete("/api/follow-ups/{follow_up_id}")
def delete_follow_up(follow_up_id: int, user: CurrentUser):
    followups.delete(follow_up_id, user["id"])
    return {"ok": True}


class DismissRequest(BaseModel):
    message_id: int


@router.post("/api/conversations/{conversation_id}/dismiss")
def dismiss(conversation_id: int, req: DismissRequest, _: CurrentUser):
    """Marca como atendido (no necesita respuesta). Si el cliente vuelve a escribir, reaparece."""
    if not search.dismiss_unanswered(conversation_id, req.message_id):
        raise NotFound("Conversación no encontrada")
    return {"ok": True}
