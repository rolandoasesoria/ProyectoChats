"""Cuentas conectadas (correo, Telegram, WhatsApp) y webhook de WhatsApp."""
import hashlib
import hmac
import json
import threading
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import audit, integrations, whatsapp_signup
from ..config import config
from ..errors import ExternalServiceError, Forbidden, InvalidInput, NotFound
from .deps import AdminUser, CurrentUser

router = APIRouter()


@router.get("/api/admin/integrations")
def admin_integrations(_: AdminUser):
    return {"fields": integrations.FIELDS, "items": integrations.list_integrations(),
            "webhook_base": integrations.webhook_base_url()}


class IntegrationIn(BaseModel):
    kind: Literal["email", "telegram", "whatsapp"]
    name: str = Field(min_length=1, max_length=100)
    owner_user_id: int
    config: dict[str, str]


class IntegrationUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    owner_user_id: int | None = None
    enabled: bool | None = None
    config: dict[str, str] | None = None


@router.post("/api/admin/integrations")
def admin_create_integration(req: IntegrationIn, admin: AdminUser):
    """Conecta una cuenta para alguien del equipo y la prueba al momento, como «Mis cuentas»."""
    integration_id = integrations.create(req.kind, req.name, req.owner_user_id, req.config)
    audit.log(admin["id"], "integration_change", detail=f"creó «{req.name}» ({req.kind})")
    return {"id": integration_id, "test": integrations.check_connection(integration_id)}


@router.patch("/api/admin/integrations/{integration_id}")
def admin_update_integration(integration_id: int, req: IntegrationUpdate, admin: AdminUser):
    integrations.update(integration_id, req.name, req.owner_user_id, req.enabled, req.config)
    changed = ", ".join(k for k in req.model_fields_set) or "nada"
    audit.log(admin["id"], "integration_change", detail=f"modificó la integración {integration_id}: {changed}")
    test = integrations.check_connection(integration_id) if req.config is not None else None
    return {"ok": True, "test": test}


@router.delete("/api/admin/integrations/{integration_id}")
def admin_delete_integration(integration_id: int, admin: AdminUser):
    integrations.delete(integration_id)
    audit.log(admin["id"], "integration_change", detail=f"borró la integración {integration_id}")
    return {"ok": True}


def _sync(integ: dict) -> dict:
    """«↻ Revisar ahora» (correo, Telegram) o «↻ Comprobar ahora» (WhatsApp)."""
    try:
        return integrations.sync(integ["id"])
    except integrations.IntegrationError as exc:
        action = "comprobar" if integ["kind"] == "whatsapp" else "sincronizar"
        raise ExternalServiceError(f"No se pudo {action}: {exc}")


@router.post("/api/admin/integrations/{integration_id}/sync")
def admin_sync_integration(integration_id: int, _: AdminUser):
    return _sync(integrations.get(integration_id))


# Cada persona conecta sus propias cuentas (correo, bot de Telegram, WhatsApp Business): los mensajes entran como
# conversaciones suyas y puede responder desde la app.

class MyIntegrationIn(BaseModel):
    kind: Literal["email", "telegram", "whatsapp"]
    name: str = Field(min_length=1, max_length=100)
    config: dict[str, str]


class MyIntegrationUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    enabled: bool | None = None
    config: dict[str, str] | None = None


def _my_integration(integration_id: int, user: dict) -> dict:
    integ = integrations.get(integration_id)
    if integ["owner_user_id"] != user["id"]:
        raise NotFound("Integración no encontrada")
    return integ


@router.get("/api/me/integrations")
def my_integrations(user: CurrentUser):
    return {"fields": integrations.FIELDS, "items": integrations.list_integrations(user["id"]),
            "webhook_base": integrations.webhook_base_url()}


@router.post("/api/me/integrations")
def create_my_integration(req: MyIntegrationIn, user: CurrentUser):
    """Conecta una cuenta y la prueba al momento (trae lo pendiente o devuelve el error)."""
    integration_id = integrations.create(req.kind, req.name, user["id"], req.config)
    audit.log(user["id"], "integration_change", detail=f"conectó su cuenta «{req.name}» ({req.kind})")
    return {"id": integration_id, "test": integrations.check_connection(integration_id)}


@router.patch("/api/me/integrations/{integration_id}")
def update_my_integration(integration_id: int, req: MyIntegrationUpdate, user: CurrentUser):
    _my_integration(integration_id, user)
    integrations.update(integration_id, req.name, None, req.enabled, req.config)
    test = integrations.check_connection(integration_id) if req.config is not None else None
    return {"ok": True, "test": test}


@router.delete("/api/me/integrations/{integration_id}")
def delete_my_integration(integration_id: int, user: CurrentUser):
    integ = _my_integration(integration_id, user)
    integrations.delete(integration_id)
    audit.log(user["id"], "integration_change", detail=f"desconectó su cuenta «{integ['name']}»")
    return {"ok": True}


@router.post("/api/me/integrations/{integration_id}/sync")
def sync_my_integration(integration_id: int, user: CurrentUser):
    return _sync(_my_integration(integration_id, user))


# Coexistencia: cada persona conecta el WhatsApp Business de su móvil con el registro insertado de Meta.

@router.get("/api/meta/whatsapp-signup")
def whatsapp_signup_settings(user: CurrentUser):
    return whatsapp_signup.settings_for(user)


class CoexistenceIn(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    waba_id: str = Field("", max_length=40)
    phone_number_id: str = Field("", max_length=40)
    name: str = Field("", max_length=100)


@router.post("/api/me/integrations/whatsapp-coexistence")
def connect_whatsapp_coexistence(req: CoexistenceIn, user: CurrentUser):
    """Alta del WhatsApp Business del móvil (sigue funcionando en la app y además entra en ProyectoChats)."""
    result = whatsapp_signup.connect(user, req.code, req.waba_id, req.phone_number_id, req.name)
    audit.log(user["id"], "integration_change",
              detail=f"conectó su WhatsApp Business {result['number'].get('display_phone_number', '')} (coexistencia)")
    return result


@router.get("/api/webhooks/whatsapp")
def whatsapp_app_verify(request: Request):
    """Verificación del webhook de la app de Meta (se configura una vez para todos los números)."""
    p = request.query_params
    expected = config.meta.webhook_verify_token
    if not expected or p.get("hub.mode") != "subscribe" or not hmac.compare_digest(p.get("hub.verify_token", ""), expected):
        raise Forbidden("Token de verificación incorrecto")
    return PlainTextResponse(p.get("hub.challenge", ""))


@router.post("/api/webhooks/whatsapp")
async def whatsapp_app_webhook(request: Request):
    """Avisos de todos los números conectados con el registro insertado. Solo se aceptan con la firma de la app."""
    raw = await request.body()
    secret = config.meta.app_secret
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest() if secret else ""
    if not secret or not hmac.compare_digest(expected, request.headers.get("x-hub-signature-256", "")):
        raise Forbidden("Firma no válida")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise InvalidInput("JSON no válido")
    if integrations.has_history(payload):
        # El historial puede traer miles de mensajes: se guarda en segundo plano y se contesta a Meta al momento.
        threading.Thread(target=integrations.receive_whatsapp_app, args=(payload,), daemon=True,
                         name="whatsapp-history").start()
        return {"ok": True, "queued": True}
    return {"ok": True, "imported": await run_in_threadpool(integrations.receive_whatsapp_app, payload)}


@router.get("/api/webhooks/whatsapp/{integration_id}")
def whatsapp_verify(integration_id: int, request: Request):
    """Verificación del webhook que hace Meta al configurarlo."""
    integ = integrations.get(integration_id)
    p = request.query_params
    if integ["kind"] != "whatsapp" or p.get("hub.mode") != "subscribe" \
            or not hmac.compare_digest(p.get("hub.verify_token", ""), integ["config"]["verify_token"]):
        raise Forbidden("Token de verificación incorrecto")
    return PlainTextResponse(p.get("hub.challenge", ""))


@router.post("/api/webhooks/whatsapp/{integration_id}")
async def whatsapp_webhook(integration_id: int, request: Request):
    """Mensajes entrantes de WhatsApp Business. Solo se aceptan si la firma de Meta es válida."""
    integ = integrations.get(integration_id)
    raw = await request.body()
    if integ["kind"] != "whatsapp" or not integ["enabled"] \
            or not integrations.verify_whatsapp_signature(integ, raw, request.headers.get("x-hub-signature-256")):
        raise Forbidden("Firma no válida")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise InvalidInput("JSON no válido")
    n = await run_in_threadpool(integrations.receive_whatsapp, integ, payload)
    return {"ok": True, "imported": n}
