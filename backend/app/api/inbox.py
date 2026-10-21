"""Bandeja «Sin responder»: posponer, seguimientos y marcar como atendido."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import ai_reply, audit, auth, followups, mailbox, search
from .. import inbox as unanswered_inbox
from ..errors import Forbidden, InvalidInput, NotFound
from .deps import CurrentUser

router = APIRouter()


@router.get("/api/me/counts")
def nav_counts(user: CurrentUser):
    """Contadores de la barra lateral que no calcula la pantalla: chats con mensajes sin leer (o marcados como no
    leídos; los silenciados y los archivados no cuentan) y propuestas de la IA por revisar (la bandeja y las tareas ya
    las carga la pantalla)."""
    unread = [c for c in search.chat_list(user["id"], "mine", "", True) if not c["muted"] and not c["archived"]]
    return {"unread_chats": len(unread), "unread_mail": mailbox.unread_count(user),
            "ai_pending": ai_reply.pending_count(user["id"]),
            "ai_enabled": bool(ai_reply.get_settings()["enabled"])}


@router.get("/api/inbox/counts")
def inbox_counts(user: CurrentUser):
    """Cuántas conversaciones esperan respuesta: mías y de todo el equipo (solo números, sin contenido)."""
    return {"mine": len(unanswered_inbox.unanswered(user["id"], "mine")), "team": len(unanswered_inbox.unanswered(user["id"], "team"))}


@router.get("/api/inbox")
def inbox(user: CurrentUser, scope: Literal["mine", "team"] = "mine", snoozed: bool = False):
    """Bandeja "Sin responder": conversaciones cuyo último mensaje es del cliente (o las pospuestas)."""
    if scope == "team":
        if not auth.can_view_team_chats(user):
            raise Forbidden("Para ver la bandeja de todo el equipo hace falta que un administrador te dé permiso.")
        audit.log(user["id"], "team_inbox", throttle=True)
    return unanswered_inbox.unanswered(user["id"], scope, snoozed)


class SnoozeRequest(BaseModel):
    until: datetime
    message_id: int


@router.post("/api/conversations/{conversation_id}/snooze")
def snooze(conversation_id: int, req: SnoozeRequest, _: CurrentUser):
    """Pospone la conversación: vuelve a la bandeja en esa fecha, o antes si el cliente escribe."""
    until = req.until.astimezone(timezone.utc).replace(tzinfo=None) if req.until.tzinfo else req.until
    if until <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise InvalidInput("La fecha tiene que ser futura.")
    if not unanswered_inbox.snooze(conversation_id, until.isoformat(timespec="seconds"), req.message_id):
        raise NotFound("Conversación no encontrada")
    return {"ok": True}


@router.delete("/api/conversations/{conversation_id}/snooze")
def unsnooze(conversation_id: int, _: CurrentUser):
    if not unanswered_inbox.snooze(conversation_id, None):
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
    if not unanswered_inbox.dismiss_unanswered(conversation_id, req.message_id):
        raise NotFound("Conversación no encontrada")
    return {"ok": True}
