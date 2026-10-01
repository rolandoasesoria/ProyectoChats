"""Ficha del cliente: análisis con IA y datos clave."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import facts, insights
from .deps import CurrentUser, claude_errors, client_or_404

router = APIRouter()


@router.get("/api/clients/{client_id}/profile")
def client_profile(client_id: int, _: CurrentUser):
    client_or_404(client_id)
    return insights.profile(client_id)


@router.post("/api/clients/{client_id}/analyze")
def analyze_client(client_id: int, _: CurrentUser):
    """Actualiza ficha, tareas y resumen con IA."""
    client_or_404(client_id)
    with claude_errors():
        changes = insights.analyze_client(client_id)
    return {"changes": changes, **insights.profile(client_id)}


class FactIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)


@router.post("/api/clients/{client_id}/facts")
def add_fact(client_id: int, req: FactIn, user: CurrentUser):
    client_or_404(client_id)
    facts.add_fact(client_id, req.label, req.value, user["id"])
    return insights.profile(client_id)


@router.patch("/api/facts/{fact_id}")
def edit_fact(fact_id: int, req: FactIn, user: CurrentUser):
    """Editar un dato lo convierte en manual: la IA ya no lo cambiará."""
    return insights.profile(facts.edit_fact(fact_id, req.label, req.value, user["id"]))


@router.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int, user: CurrentUser):
    """Un dato de la IA queda descartado (no se vuelve a proponer); uno manual se borra."""
    return insights.profile(facts.delete_fact(fact_id, user["id"]))
