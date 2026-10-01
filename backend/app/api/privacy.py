"""Protección de datos: registro de accesos, exportación, datos sensibles, retención y borrado."""
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import audit, privacy
from ..errors import InvalidInput, NotFound
from .deps import AdminUser, client_or_404

router = APIRouter()


@router.get("/api/admin/audit")
def audit_log(_: AdminUser, user_id: int | None = None, action: str | None = None):
    return {"actions": audit.ACTIONS, "entries": audit.entries(user_id=user_id, action=action)}


@router.get("/api/clients/{client_id}/export")
def export_client(client_id: int, admin: AdminUser):
    """Todos los datos de un cliente en JSON (derecho de acceso y portabilidad)."""
    data = audit.export_client(client_id)
    if not data:
        raise NotFound("Cliente no encontrado")
    audit.log(admin["id"], "client_export", client_id)
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="cliente-{client_id}.json"'})


@router.get("/api/clients/{client_id}/sensitive")
def sensitive_messages(client_id: int, _: AdminUser):
    """Mensajes del cliente con IBAN, DNI/NIE o números de tarjeta, para ocultarlos."""
    client_or_404(client_id)
    return privacy.sensitive_messages(client_id)


class RedactRequest(BaseModel):
    text: str | None = Field(None, min_length=3, max_length=200)  # sin texto: todos los datos sensibles del mensaje


@router.post("/api/messages/{message_id}/redact")
def redact_message(message_id: int, req: RedactRequest, admin: AdminUser):
    """Oculta datos sensibles de un mensaje. No se puede deshacer: el texto original no se guarda."""
    result = privacy.redact_message(message_id, req.text)
    if result is None:
        raise NotFound("Mensaje no encontrado")
    if result["hidden"]:
        audit.log(admin["id"], "message_redact", result["client_id"],
                  detail=f"mensaje {message_id}: {', '.join(result['hidden'])}")
    return {"body": result["body"], "hidden": result["hidden"]}


@router.get("/api/admin/retention")
def retention_preview(_: AdminUser, months: Annotated[int, Query(ge=1, le=120)]):
    """Cuántos mensajes se borrarían con ese plazo (sin borrar nada)."""
    return privacy.retention_preview(months)


@router.post("/api/admin/retention/apply")
def retention_apply(admin: AdminUser):
    """Aplica ya el plazo de retención guardado en Ajustes."""
    result = privacy.apply_retention()
    if result["messages"]:
        audit.log(admin["id"], "retention_apply",
                  detail=f"{result['messages']} mensajes de más de {result['months']} meses")
    return result


@router.delete("/api/clients/{client_id}")
def delete_client(client_id: int, admin: AdminUser, confirm: str = ""):
    """Borra el cliente y todos sus datos (derecho de supresión). `confirm` debe ser el nombre del cliente."""
    client = client_or_404(client_id)
    if confirm.strip().lower() != client["name"].strip().lower():
        raise InvalidInput("Para confirmar, escribe exactamente el nombre del cliente.")
    audit.log(admin["id"], "client_delete", client_id)  # antes de borrar, para guardar el nombre
    return audit.delete_client(client_id)
