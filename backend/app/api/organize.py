"""Organizar los chats como en WhatsApp: fijar, archivar, silenciar y marcar como no leído (cada uno su lista),
mensajes destacados y lo compartido en cada chat (fotos y vídeos, documentos y enlaces)."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from .. import audit, chat_organize
from .deps import CurrentUser, client_or_404

router = APIRouter()


class ChatPrefs(BaseModel):
    pinned: bool | None = None
    archived: bool | None = None
    mute: Literal["8h", "week", "always", "off"] | None = None
    unread: bool | None = None


@router.put("/api/chats/{client_id}/prefs")
def chat_prefs(client_id: int, req: ChatPrefs, user: CurrentUser):
    """Cómo ve el usuario el chat del cliente en su lista. Devuelve cómo queda."""
    client_or_404(client_id)
    return chat_organize.update(user, client_id, pinned=req.pinned, archived=req.archived, mute=req.mute,
                                unread=req.unread)


class StarRequest(BaseModel):
    starred: bool


@router.post("/api/messages/{message_id}/star")
def star_message(message_id: int, req: StarRequest, user: CurrentUser):
    return chat_organize.star(user["id"], message_id, req.starred)


@router.get("/api/starred")
def starred_messages(user: CurrentUser):
    """Los mensajes destacados del usuario en todos los chats, el último destacado primero."""
    return chat_organize.starred(user["id"])


@router.get("/api/clients/{client_id}/starred")
def client_starred(client_id: int, user: CurrentUser):
    client_or_404(client_id)
    return chat_organize.starred(user["id"], client_id)


@router.get("/api/clients/{client_id}/shared")
def client_shared(client_id: int, user: CurrentUser, scope: Literal["mine", "team"] = "mine"):
    """Fotos y vídeos, documentos y enlaces compartidos en las conversaciones del cliente (en el alcance)."""
    client_or_404(client_id)
    if scope == "team":
        audit.log(user["id"], "team_messages", client_id, throttle=True)
    return chat_organize.shared(client_id, user["id"], scope)
