"""IA que responde: su configuración (administradores), «Probar la IA» y, en cada chat, pausarla y decidir sobre
sus propuestas."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import ai_reply, audit
from .deps import AdminUser, CurrentUser

router = APIRouter()


@router.get("/api/ai-reply/settings")
def get_settings(_: CurrentUser):
    return ai_reply.get_settings()


class AISettings(BaseModel):
    enabled: bool | None = None
    mode: Literal["supervised", "auto"] | None = None
    instructions: str | None = Field(None, max_length=8000)
    inactivity_hours: Literal[0, 24, 48, 72] | None = None
    schedule: Literal["always", "out_of_hours"] | None = None
    hours: str | None = Field(None, max_length=11)
    days: list[int] | None = Field(None, max_length=7)


@router.put("/api/admin/ai-reply/settings")
def update_settings(req: AISettings, admin: AdminUser):
    changes = req.model_dump(exclude_none=True)
    result = ai_reply.update_settings(changes)
    audit.log(admin["id"], "settings_change", detail="IA que responde: " + ", ".join(
        f"{k}={'…' if k == 'instructions' else v}" for k, v in changes.items()))
    return result


class AITest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    instructions: str | None = Field(None, max_length=8000)  # para probar antes de guardar


@router.post("/api/admin/ai-reply/test")
def test_reply(req: AITest, _: AdminUser):
    return ai_reply.test_reply(req.message, req.instructions)


@router.get("/api/conversations/{conversation_id}/ai")
def conversation_ai(conversation_id: int, user: CurrentUser):
    return ai_reply.conversation_state(conversation_id, user)


class AIPause(BaseModel):
    paused: bool


@router.put("/api/conversations/{conversation_id}/ai")
def pause_conversation_ai(conversation_id: int, req: AIPause, user: CurrentUser):
    return ai_reply.set_paused(conversation_id, req.paused, user)


class SuggestionSend(BaseModel):
    text: str | None = Field(None, max_length=4000)  # editada; vacío = tal cual la propuso la IA


@router.post("/api/ai-replies/{reply_id}/send")
def send_suggestion(reply_id: int, req: SuggestionSend, user: CurrentUser):
    result = ai_reply.send_suggestion(reply_id, user, req.text)
    audit.log(user["id"], "message_sent", detail=f"respuesta propuesta por la IA, por {result['via']}")
    return result


@router.post("/api/ai-replies/{reply_id}/discard")
def discard_suggestion(reply_id: int, user: CurrentUser):
    ai_reply.discard_suggestion(reply_id, user)
    return {"ok": True}
