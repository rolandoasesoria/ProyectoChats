"""Búsqueda de mensajes: por palabras y por significado."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import audit, search, smartsearch
from .deps import CurrentUser, claude_errors, client_or_404

router = APIRouter()


@router.get("/api/search")
def search_endpoint(q: str, user: CurrentUser, scope: Literal["mine", "team"] = "mine",
                    client_id: int | None = None):
    if scope == "team":
        audit.log(user["id"], "team_search", client_id, detail=q[:200])
    # Marcas poco habituales para que la interfaz resalte sin confundirlas con corchetes del propio texto.
    return search.search_messages(q, user["id"], scope, client_id=client_id, limit=30, markers=("⟦", "⟧"))


class SmartSearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    scope: Literal["mine", "team"] = "mine"
    client_id: int | None = None


@router.post("/api/smart-search")
def smart_search_endpoint(req: SmartSearchRequest, user: CurrentUser):
    """Búsqueda por significado en mensajes y documentos (Claude amplía la pregunta y ordena los resultados)."""
    if req.client_id is not None:
        client_or_404(req.client_id)
    if req.scope == "team":
        audit.log(user["id"], "team_search", req.client_id, detail=f"por significado: {req.question}"[:200])
    with claude_errors():
        return smartsearch.smart_search(req.question, user["id"], req.scope, req.client_id)
