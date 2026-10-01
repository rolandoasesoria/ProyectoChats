"""Ficha del cliente: análisis con IA y datos clave."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import insights
from ..db import get_conn
from ..errors import NotFound
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


def _fact_or_404(fact_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT id, client_id, origin FROM client_facts WHERE id = ?", (fact_id,)).fetchone()
    if not row or row["origin"] == "dismissed":
        raise NotFound("Dato no encontrado")
    return dict(row)


@router.post("/api/clients/{client_id}/facts")
def add_fact(client_id: int, req: FactIn, user: CurrentUser):
    client_or_404(client_id)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO client_facts (client_id, label, value, origin, updated_by) VALUES (?, ?, ?, 'manual', ?)",
            (client_id, req.label.strip(), req.value.strip(), user["id"]))
    return insights.profile(client_id)


@router.patch("/api/facts/{fact_id}")
def edit_fact(fact_id: int, req: FactIn, user: CurrentUser):
    """Editar un dato lo convierte en manual: la IA ya no lo cambiará."""
    fact = _fact_or_404(fact_id)
    with get_conn() as conn:
        conn.execute(
            """UPDATE client_facts SET label = ?, value = ?, origin = 'manual', updated_by = ?,
                   updated_at = localtimestamp(0) WHERE id = ?""",
            (req.label.strip(), req.value.strip(), user["id"], fact_id))
    return insights.profile(fact["client_id"])


@router.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int, user: CurrentUser):
    """Un dato de la IA queda descartado (no se vuelve a proponer); uno manual se borra."""
    fact = _fact_or_404(fact_id)
    with get_conn() as conn:
        if fact["origin"] == "ai":
            conn.execute("UPDATE client_facts SET origin = 'dismissed', updated_by = ? WHERE id = ?",
                         (user["id"], fact_id))
        else:
            conn.execute("DELETE FROM client_facts WHERE id = ?", (fact_id,))
    return insights.profile(fact["client_id"])
