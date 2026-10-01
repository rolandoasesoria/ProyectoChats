"""Asistentes: el de datos de clientes y la mascota de ayuda."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import agent, chats
from .deps import CurrentUser, claude_errors, client_or_404

router = APIRouter()


Kind = Literal["agent", "help"]


@router.get("/api/conversations/{kind}")
def get_conversation(kind: Kind, user: CurrentUser, client_id: int | None = None):
    """Conversación activa del usuario (con un cliente, general o con la mascota) para mostrarla."""
    session = chats.active_session(user["id"], kind, client_id if kind == "agent" else None, create=False)
    return {"turns": chats.turns(session["id"]) if session else []}


@router.get("/api/conversations/agent/clients")
def clients_with_conversation(user: CurrentUser):
    return chats.clients_with_conversation(user["id"])


class ResetRequest(BaseModel):
    client_id: int | None = None


@router.post("/api/conversations/{kind}/reset")
def reset_conversation(kind: Kind, req: ResetRequest, user: CurrentUser):
    """'Nueva conversación': archiva la actual."""
    chats.archive(user["id"], kind, req.client_id if kind == "agent" else None)
    return {"ok": True}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)  # límite para evitar abusos de coste
    client_id: int | None = None


def _run_and_save(user: dict, kind: str, client_id: int | None, text: str, run) -> dict:
    session = chats.active_session(user["id"], kind, client_id)
    with chats.locked(session["id"]):
        messages = chats.reload_messages(session["id"])
        with claude_errors():
            result = run(messages)
        # Solo se guarda si Claude respondió; si falló, el historial queda como estaba.
        chats.save_exchange(session["id"], messages, text, result["reply"], result["tool_calls"])
    return result


@router.post("/api/chat")
def chat(req: ChatRequest, user: CurrentUser):
    """Asistente de datos. Cada conversación pertenece a un cliente (o a ninguno = general)."""
    client = client_or_404(req.client_id)
    return _run_and_save(user, "agent", req.client_id, req.message,
                         lambda messages: agent.chat(messages, user, req.message, client))


@router.post("/api/help")
def help_chat(req: ChatRequest, user: CurrentUser):
    """Mascota de ayuda: dudas generales sobre el uso de la app."""
    return _run_and_save(user, "help", None, req.message,
                         lambda messages: agent.help_chat(messages, req.message))
