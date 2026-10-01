"""Borradores de respuesta con IA."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import insights
from .deps import CurrentUser, claude_errors

router = APIRouter()


class DraftRequest(BaseModel):
    instructions: str = Field("", max_length=1000)


@router.post("/api/conversations/{conversation_id}/draft")
def draft(conversation_id: int, req: DraftRequest, user: CurrentUser):
    """Borrador de respuesta con IA para revisar, editar y copiar."""
    with claude_errors():
        return insights.draft_reply(conversation_id, user, req.instructions)


class RewriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    action: Literal["formal", "friendly", "shorter", "fix", "translate"]
    language: str = Field("", max_length=40)
    channel: Literal["email", "whatsapp", "telegram"] | None = None


@router.post("/api/drafts/rewrite")
def rewrite(req: RewriteRequest, _: CurrentUser):
    """Retoca con IA un borrador ya escrito: más formal, más cercano, más corto, corregido o traducido."""
    with claude_errors():
        return {"text": insights.rewrite_draft(req.text, req.action, req.language, req.channel)}
