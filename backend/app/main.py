"""API HTTP + servidor del frontend estático."""
import base64
import binascii
import hmac
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import anthropic
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (agent, attachments, audit, auth, chats, clients, followups, insights, integrations, metrics, notes,
               presence, privacy, replies, search, settings, smartsearch)
from .db import get_conn, init_db, rows

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

# FORCE_HTTPS=true: redirige HTTP a HTTPS y activa HSTS. Detrás de un proxy (Caddy, Nginx)
# arranca con `python -m app.serve`, que confía en las cabeceras X-Forwarded-* del proxy.
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false").lower() == "true"
# La documentación interactiva de la API (/docs) solo se publica si se pide expresamente.
ENABLE_DOCS = os.getenv("ENABLE_DOCS", "false").lower() == "true"

app = FastAPI(
    title="ProyectoChats",
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)
init_db()
# Sincronización periódica de los buzones y bots conectados (DISABLE_SYNC=true la desactiva, p. ej. en pruebas).
if os.getenv("DISABLE_SYNC", "false").lower() != "true":
    integrations.start_scheduler()
    privacy.start_daily_jobs()  # retención de mensajes y clientes inactivos, una vez al día

SECURITY_HEADERS = {
    # Solo se ejecutan scripts y estilos servidos por la propia app; la página no se puede incrustar en otra web.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FILE_ROUTE = re.compile(r"^/api/attachments/\d+/file$")


@app.middleware("http")
async def security(request: Request, call_next):
    if FORCE_HTTPS and request.url.scheme != "https":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)

    # Protección CSRF adicional a la cookie SameSite: las peticiones que modifican datos
    # deben venir de la propia app (mismo origen).
    if request.method in UNSAFE_METHODS:
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlsplit(origin).netloc != request.url.netloc:
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)

    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if FILE_ROUTE.match(request.url.path):
        # Los archivos adjuntos se abren en su propia pestaña (visor de PDF o imagen del navegador), que la
        # CSP de la app bloquearía. Solo se sirven en línea PDF e imágenes; lo demás se descarga.
        del response.headers["Content-Security-Policy"]
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        # HTML, JS y CSS: el navegador puede guardarlos, pero debe preguntar siempre si han cambiado (responde
        # 304 si no). Sin esto, tras una actualización podía mezclar archivos viejos y nuevos y la app fallaba.
        response.headers["Cache-Control"] = "no-cache"
    return response

CurrentUser = Annotated[dict, Depends(auth.current_user)]


def admin_user(user: CurrentUser) -> dict:
    return auth.require_admin(user)


AdminUser = Annotated[dict, Depends(admin_user)]


# ---------------------------------------------------------------- Autenticación

class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=auth.MAX_PASSWORD_LENGTH)


@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "desconocida"
    token, user = auth.login(req.username, req.password, ip)
    response.set_cookie(
        auth.COOKIE_NAME, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
        secure=auth.COOKIE_SECURE or request.url.scheme == "https",
    )
    return user


@app.post("/api/auth/logout")
def logout(response: Response, pc_session: str | None = Cookie(None)):
    auth.logout(pc_session)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


# ---------------------------------------------------------------- Perfil propio

@app.get("/api/me")
def me(user: CurrentUser):
    return user


class ProfileUpdate(BaseModel):
    theme: Literal["system", "light", "dark"] | None = None
    tour_version: int | None = None


@app.patch("/api/me")
def update_me(req: ProfileUpdate, user: CurrentUser):
    return auth.update_user(user["id"], theme=req.theme, tour_version=req.tour_version)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/me/password")
def change_password(req: PasswordChange, user: CurrentUser, pc_session: str | None = Cookie(None)):
    with get_conn() as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not auth.verify_password(req.current_password, stored["password_hash"]):
        raise HTTPException(400, "La contraseña actual no es correcta.")
    # Cierra las demás sesiones abiertas del usuario, pero no la actual.
    auth.update_user(user["id"], password=req.new_password, keep_token=pc_session)
    return {"ok": True}


# ---------------------------------------------------------------- Administración de usuarios

@app.get("/api/admin/users")
def admin_list_users(_: AdminUser):
    return auth.list_users()


class NewUser(BaseModel):
    username: str
    name: str
    password: str
    email: str | None = None
    role: Literal["user", "admin"] = "user"


@app.post("/api/admin/users")
def admin_create_user(req: NewUser, admin: AdminUser):
    user = auth.create_user(req.username, req.name, req.password, req.email, req.role)
    audit.log(admin["id"], "user_create", detail=f"{user['username']} ({user['role']})")
    return user


class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    role: Literal["user", "admin"] | None = None
    active: bool | None = None
    password: str | None = None


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, req: UserUpdate, admin: AdminUser):
    if user_id == admin["id"] and (req.active is False or req.role == "user"):
        raise HTTPException(400, "No puedes desactivarte ni quitarte el rol de administrador a ti mismo.")
    changes = req.model_dump(exclude_none=True)
    user = auth.update_user(user_id, **changes)
    described = ", ".join("contraseña restablecida" if k == "password" else f"{k}={v}" for k, v in changes.items())
    audit.log(admin["id"], "user_update", detail=f"{user['username']}: {described}")
    return user


# ---------------------------------------------------------------- Ajustes del equipo

@app.get("/api/settings")
def get_settings(_: CurrentUser):
    return settings.get_all()


class SettingsUpdate(BaseModel):
    sla_hours: int | None = Field(None, ge=1, le=168)
    retention_months: int | None = Field(None, ge=0, le=120)
    inactive_days: int | None = Field(None, ge=0, le=730)


@app.patch("/api/admin/settings")
def update_settings(req: SettingsUpdate, admin: AdminUser):
    changes = req.model_dump(exclude_none=True)
    result = settings.update(changes)
    if changes:
        audit.log(admin["id"], "settings_change", detail=", ".join(f"{k}={v}" for k, v in changes.items()))
    return result


# ---------------------------------------------------------------- Integraciones con los canales

@app.get("/api/admin/integrations")
def admin_integrations(_: AdminUser):
    return {"fields": integrations.FIELDS, "items": integrations.list_integrations()}


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


@app.post("/api/admin/integrations")
def admin_create_integration(req: IntegrationIn, admin: AdminUser):
    integration_id = integrations.create(req.kind, req.name, req.owner_user_id, req.config)
    audit.log(admin["id"], "integration_change", detail=f"creó «{req.name}» ({req.kind})")
    return {"id": integration_id}


@app.patch("/api/admin/integrations/{integration_id}")
def admin_update_integration(integration_id: int, req: IntegrationUpdate, admin: AdminUser):
    integrations.update(integration_id, req.name, req.owner_user_id, req.enabled, req.config)
    changed = ", ".join(k for k in req.model_fields_set) or "nada"
    audit.log(admin["id"], "integration_change", detail=f"modificó la integración {integration_id}: {changed}")
    return {"ok": True}


@app.delete("/api/admin/integrations/{integration_id}")
def admin_delete_integration(integration_id: int, admin: AdminUser):
    integrations.delete(integration_id)
    audit.log(admin["id"], "integration_change", detail=f"borró la integración {integration_id}")
    return {"ok": True}


@app.post("/api/admin/integrations/{integration_id}/sync")
def admin_sync_integration(integration_id: int, _: AdminUser):
    try:
        return integrations.sync(integration_id)
    except integrations.IntegrationError as exc:
        raise HTTPException(502, f"No se pudo sincronizar: {exc}")


@app.get("/api/webhooks/whatsapp/{integration_id}")
def whatsapp_verify(integration_id: int, request: Request):
    """Verificación del webhook que hace Meta al configurarlo."""
    integ = integrations.get(integration_id)
    p = request.query_params
    if integ["kind"] != "whatsapp" or p.get("hub.mode") != "subscribe" \
            or not hmac.compare_digest(p.get("hub.verify_token", ""), integ["config"]["verify_token"]):
        raise HTTPException(403, "Token de verificación incorrecto")
    return PlainTextResponse(p.get("hub.challenge", ""))


@app.post("/api/webhooks/whatsapp/{integration_id}")
async def whatsapp_webhook(integration_id: int, request: Request):
    """Mensajes entrantes de WhatsApp Business. Solo se aceptan si la firma de Meta es válida."""
    integ = integrations.get(integration_id)
    raw = await request.body()
    if integ["kind"] != "whatsapp" or not integ["enabled"] \
            or not integrations.verify_whatsapp_signature(integ, raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "Firma no válida")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "JSON no válido")
    n = await run_in_threadpool(integrations.receive_whatsapp, integ, payload)
    return {"ok": True, "imported": n}


def _last_message_id(conversation_id: int) -> int:
    with get_conn() as conn:
        return conn.execute("SELECT coalesce(max(id), 0) FROM messages WHERE conversation_id = ?",
                            (conversation_id,)).fetchone()[0]


@app.get("/api/conversations/{conversation_id}/sender")
def conversation_sender(conversation_id: int, user: CurrentUser):
    """¿Puede el usuario enviar la respuesta desde la app en esta conversación? Incluye el último mensaje, para
    avisar después si llega otro (del cliente o de un compañero) mientras se escribe la respuesta."""
    integ = integrations.sender_for(conversation_id, user)
    return {"can_send": bool(integ), "via": integ["name"] if integ else None,
            "last_message_id": _last_message_id(conversation_id)}


class SendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    after_message_id: int | None = None  # último mensaje que se veía al empezar a escribir
    force: bool = False                  # enviar aunque haya llegado algo nuevo


@app.post("/api/conversations/{conversation_id}/send")
def send_message(conversation_id: int, req: SendRequest, user: CurrentUser):
    if req.after_message_id is not None and not req.force:
        with get_conn() as conn:
            newer = rows(conn.execute(
                """SELECT direction, sender FROM messages WHERE conversation_id = ? AND id > ? ORDER BY id""",
                (conversation_id, req.after_message_id)))
        if newer:
            who = "un compañero ha respondido" if any(m["direction"] == "out" for m in newer) else "el cliente ha escrito"
            raise HTTPException(409, f"Mientras escribías, {who} en esta conversación. Revisa la conversación antes de enviar.")
    result = integrations.send_reply(conversation_id, user, req.text.strip())
    with get_conn() as conn:
        client_id = conn.execute("SELECT client_id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()[0]
    audit.log(user["id"], "message_sent", client_id, detail=f"por {result['via']}")
    return result


# ---------------------------------------------------------------- Presencia (evitar responder dos veces)

class PresenceRequest(BaseModel):
    client_id: int | None = None   # None: no tiene ningún cliente abierto
    composing: bool = False        # tiene el borrador de respuesta abierto


@app.post("/api/presence")
def update_presence(req: PresenceRequest, user: CurrentUser):
    """Latido de la interfaz: devuelve qué compañeros tienen abierto el mismo cliente y si están respondiendo."""
    if req.client_id is not None:
        _client_or_404(req.client_id)
    return presence.update(user["id"], req.client_id, req.composing)


# ---------------------------------------------------------------- Panel de actividad

@app.get("/api/dashboard")
def dashboard(user: CurrentUser, days: int = 30):
    """Métricas del equipo. El desglose por persona solo lo ven los administradores."""
    if days not in (7, 30, 90, 365):
        raise HTTPException(422, "Periodo no válido: 7, 30, 90 o 365 días.")
    return metrics.dashboard(days, include_people=user["role"] == "admin")


# ---------------------------------------------------------------- Protección de datos (solo administradores)

@app.get("/api/admin/audit")
def audit_log(_: AdminUser, user_id: int | None = None, action: str | None = None):
    return {"actions": audit.ACTIONS, "entries": audit.entries(user_id=user_id, action=action)}


@app.get("/api/clients/{client_id}/export")
def export_client(client_id: int, admin: AdminUser):
    """Todos los datos de un cliente en JSON (derecho de acceso y portabilidad)."""
    data = audit.export_client(client_id)
    if not data:
        raise HTTPException(404, "Cliente no encontrado")
    audit.log(admin["id"], "client_export", client_id)
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="cliente-{client_id}.json"'})


@app.get("/api/clients/{client_id}/sensitive")
def sensitive_messages(client_id: int, _: AdminUser):
    """Mensajes del cliente con IBAN, DNI/NIE o números de tarjeta, para ocultarlos."""
    _client_or_404(client_id)
    return privacy.sensitive_messages(client_id)


class RedactRequest(BaseModel):
    text: str | None = Field(None, min_length=3, max_length=200)  # sin texto: todos los datos sensibles del mensaje


@app.post("/api/messages/{message_id}/redact")
def redact_message(message_id: int, req: RedactRequest, admin: AdminUser):
    """Oculta datos sensibles de un mensaje. No se puede deshacer: el texto original no se guarda."""
    result = privacy.redact_message(message_id, req.text)
    if result is None:
        raise HTTPException(404, "Mensaje no encontrado")
    if result["hidden"]:
        audit.log(admin["id"], "message_redact", result["client_id"],
                  detail=f"mensaje {message_id}: {', '.join(result['hidden'])}")
    return {"body": result["body"], "hidden": result["hidden"]}


@app.get("/api/admin/retention")
def retention_preview(_: AdminUser, months: int):
    """Cuántos mensajes se borrarían con ese plazo (sin borrar nada)."""
    if not 1 <= months <= 120:
        raise HTTPException(422, "Plazo no válido: de 1 a 120 meses.")
    return privacy.retention_preview(months)


@app.post("/api/admin/retention/apply")
def retention_apply(admin: AdminUser):
    """Aplica ya el plazo de retención guardado en Ajustes."""
    result = privacy.apply_retention()
    if result["messages"]:
        audit.log(admin["id"], "retention_apply",
                  detail=f"{result['messages']} mensajes de más de {result['months']} meses")
    return result


@app.delete("/api/clients/{client_id}")
def delete_client(client_id: int, admin: AdminUser, confirm: str = ""):
    """Borra el cliente y todos sus datos (derecho de supresión). `confirm` debe ser el nombre del cliente."""
    client = _client_or_404(client_id)
    if confirm.strip().lower() != client["name"].strip().lower():
        raise HTTPException(400, "Para confirmar, escribe exactamente el nombre del cliente.")
    audit.log(admin["id"], "client_delete", client_id)  # antes de borrar, para guardar el nombre
    return audit.delete_client(client_id)


# ---------------------------------------------------------------- Clientes y mensajes

@app.get("/api/clients")
def list_clients(user: CurrentUser, q: str = "", status: Literal["lead", "active", "issue", "inactive"] | None = None,
                 tag: str | None = None, mine: bool = False):
    # La lista de la interfaz muestra hasta 500 clientes (el buscador y los filtros acotan el resto).
    return search.find_clients(q, limit=500, user_id=user["id"], status=status, tag=tag or None,
                               assignee_id=user["id"] if mine else None)


class NewClient(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(None, max_length=200)


@app.post("/api/clients")
def create_client(req: NewClient, user: CurrentUser):
    """Cliente creado a mano (p. ej. tras una llamada). Queda asignado a quien lo crea."""
    return {"id": clients.create_client(req.name, req.company, user["id"])}


class ClientUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    company: str | None = Field(None, max_length=200)
    status: Literal["lead", "active", "issue", "inactive"] | None = None
    status_auto: bool | None = None  # true: que el estado lo vuelva a decidir la IA
    assignee_user_id: int | None = None


@app.patch("/api/clients/{client_id}")
def update_client(client_id: int, req: ClientUpdate, user: CurrentUser):
    before = search.client_overview(client_id, user["id"])
    if not before:
        raise HTTPException(404, "Cliente no encontrado")
    fields = {k: getattr(req, k) for k in req.model_fields_set}
    if "company" in fields:
        fields["company"] = (fields["company"] or "").strip() or None
    if fields.pop("status_auto", None):
        clients.release_status(client_id)
    clients.update_client(client_id, fields, user["id"])
    new_assignee = fields.get("assignee_user_id")
    if new_assignee and new_assignee != before["assignee_user_id"]:
        with get_conn() as conn:
            notes.notify(conn, [new_assignee], "client_assigned",
                         f"{user['name']} te ha hecho responsable de {before['name']}", client_id, user["id"])
    return search.client_overview(client_id, user["id"])


class TagsIn(BaseModel):
    tags: list[Annotated[str, Field(max_length=40)]] = Field(max_length=20)


@app.put("/api/clients/{client_id}/tags")
def set_tags(client_id: int, req: TagsIn, _: CurrentUser):
    _client_or_404(client_id)
    return {"tags": clients.set_tags(client_id, req.tags)}


@app.get("/api/tags")
def tags(_: CurrentUser):
    return clients.all_tags()


class IdentityIn(BaseModel):
    channel: Literal["email", "whatsapp", "telegram", "phone", "other"]
    handle: str = Field(min_length=1, max_length=200)


@app.post("/api/clients/{client_id}/identities")
def add_identity(client_id: int, req: IdentityIn, _: CurrentUser):
    _client_or_404(client_id)
    return clients.add_identity(client_id, req.channel, req.handle)


@app.delete("/api/identities/{identity_id}")
def delete_identity(identity_id: int, _: CurrentUser):
    clients.delete_identity(identity_id)
    return {"ok": True}


@app.get("/api/clients/{client_id}/duplicates")
def duplicates(client_id: int, _: CurrentUser):
    _client_or_404(client_id)
    return clients.possible_duplicates(client_id)


class MergeRequest(BaseModel):
    into_client_id: int


@app.post("/api/clients/{client_id}/merge")
def merge(client_id: int, req: MergeRequest, user: CurrentUser):
    """Une este cliente con otro: todo pasa a `into_client_id` y este se borra."""
    source = _client_or_404(client_id)
    result = clients.merge_clients(client_id, req.into_client_id)
    audit.log(user["id"], "client_merge", req.into_client_id, detail=f"«{source['name']}» (id {client_id}) unido a este cliente")
    return result


@app.post("/api/clients/{client_id}/visit")
def visit_client(client_id: int, user: CurrentUser):
    """El usuario abre la ficha: devuelve cuántos mensajes han llegado desde su visita anterior."""
    _client_or_404(client_id)
    return search.record_visit(user["id"], client_id)


class WhatsNewRequest(BaseModel):
    since_message_id: int


@app.post("/api/clients/{client_id}/whats-new")
def whats_new(client_id: int, req: WhatsNewRequest, _: CurrentUser):
    """Resumen con IA de los mensajes llegados desde un punto (la visita anterior)."""
    client = _client_or_404(client_id)
    messages = search.messages_since(client_id, req.since_message_id)
    if not messages:
        return {"summary": "No hay mensajes nuevos."}
    with claude_errors():
        try:
            return {"summary": insights.summarize_new_messages(client["name"], messages)}
        except insights.AnalysisError as exc:
            raise HTTPException(400, str(exc))


class DraftRequest(BaseModel):
    instructions: str = Field("", max_length=1000)


@app.post("/api/conversations/{conversation_id}/draft")
def draft(conversation_id: int, req: DraftRequest, user: CurrentUser):
    """Borrador de respuesta con IA para revisar, editar y copiar."""
    with claude_errors():
        try:
            return insights.draft_reply(conversation_id, user, req.instructions)
        except insights.AnalysisError as exc:
            raise HTTPException(404 if "no encontrada" in str(exc) else 400, str(exc))


class RewriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    action: Literal["formal", "friendly", "shorter", "fix", "translate"]
    language: str = Field("", max_length=40)
    channel: Literal["email", "whatsapp", "telegram"] | None = None


@app.post("/api/drafts/rewrite")
def rewrite(req: RewriteRequest, _: CurrentUser):
    """Retoca con IA un borrador ya escrito: más formal, más cercano, más corto, corregido o traducido."""
    with claude_errors():
        try:
            return {"text": insights.rewrite_draft(req.text, req.action, req.language, req.channel)}
        except insights.AnalysisError as exc:
            raise HTTPException(400, str(exc))


# ---------------------------------------------------------------- Respuestas guardadas y macros

class ReplyIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    shortcut: str | None = Field(None, max_length=31)
    body: str = Field(min_length=1, max_length=5000)
    set_status: Literal["lead", "active", "issue", "inactive"] | None = None
    add_tag: str | None = Field(None, max_length=40)
    mark_done: bool = False


class ReplyUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=100)
    shortcut: str | None = Field(None, max_length=31)
    body: str | None = Field(None, min_length=1, max_length=5000)
    set_status: Literal["lead", "active", "issue", "inactive"] | None = None
    add_tag: str | None = Field(None, max_length=40)
    mark_done: bool | None = None


@app.get("/api/replies")
def list_replies(_: CurrentUser):
    return replies.list_replies()


@app.post("/api/replies")
def create_reply(req: ReplyIn, user: CurrentUser):
    return replies.create(req.model_dump(), user["id"])


@app.patch("/api/replies/{reply_id}")
def update_reply(reply_id: int, req: ReplyUpdate, user: CurrentUser):
    # Solo los campos enviados: así se puede quitar el atajo, el estado o la etiqueta enviando null.
    return replies.update(reply_id, {k: getattr(req, k) for k in req.model_fields_set}, user)


@app.delete("/api/replies/{reply_id}")
def delete_reply(reply_id: int, user: CurrentUser):
    replies.delete(reply_id, user)
    return {"ok": True}


class UseReplyRequest(BaseModel):
    client_id: int
    conversation_id: int | None = None


@app.post("/api/replies/{reply_id}/use")
def use_reply(reply_id: int, req: UseReplyRequest, user: CurrentUser):
    """Texto con las variables rellenas para el borrador; si es una macro, aplica sus acciones."""
    return replies.use(reply_id, req.client_id, req.conversation_id, user)


@app.get("/api/inbox/counts")
def inbox_counts(user: CurrentUser):
    """Cuántas conversaciones esperan respuesta: mías y de todo el equipo (solo números, sin contenido)."""
    return {"mine": len(search.unanswered(user["id"], "mine")), "team": len(search.unanswered(user["id"], "team"))}


@app.get("/api/inbox")
def inbox(user: CurrentUser, scope: Literal["mine", "team"] = "mine", snoozed: bool = False):
    """Bandeja "Sin responder": conversaciones cuyo último mensaje es del cliente (o las pospuestas)."""
    if scope == "team":
        audit.log(user["id"], "team_inbox", throttle=True)
    return search.unanswered(user["id"], scope, snoozed)


class SnoozeRequest(BaseModel):
    until: datetime
    message_id: int


@app.post("/api/conversations/{conversation_id}/snooze")
def snooze(conversation_id: int, req: SnoozeRequest, _: CurrentUser):
    """Pospone la conversación: vuelve a la bandeja en esa fecha, o antes si el cliente escribe."""
    until = req.until.astimezone(timezone.utc).replace(tzinfo=None) if req.until.tzinfo else req.until
    if until <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(400, "La fecha tiene que ser futura.")
    if not search.snooze(conversation_id, until.isoformat(timespec="seconds"), req.message_id):
        raise HTTPException(404, "Conversación no encontrada")
    return {"ok": True}


@app.delete("/api/conversations/{conversation_id}/snooze")
def unsnooze(conversation_id: int, _: CurrentUser):
    if not search.snooze(conversation_id, None):
        raise HTTPException(404, "Conversación no encontrada")
    return {"ok": True}


class FollowUpRequest(BaseModel):
    days: int = Field(ge=1, le=60)


@app.post("/api/conversations/{conversation_id}/follow-up")
def create_follow_up(conversation_id: int, req: FollowUpRequest, user: CurrentUser):
    """«Avísame si no contesta en X días»."""
    return followups.create(conversation_id, user["id"], req.days)


@app.get("/api/follow-ups")
def due_follow_ups(user: CurrentUser):
    """Seguimientos vencidos: clientes que no han contestado en el plazo."""
    return followups.due(user["id"])


@app.delete("/api/follow-ups/{follow_up_id}")
def delete_follow_up(follow_up_id: int, user: CurrentUser):
    followups.delete(follow_up_id, user["id"])
    return {"ok": True}


class DismissRequest(BaseModel):
    message_id: int


@app.post("/api/conversations/{conversation_id}/dismiss")
def dismiss(conversation_id: int, req: DismissRequest, _: CurrentUser):
    """Marca como atendido (no necesita respuesta). Si el cliente vuelve a escribir, reaparece."""
    if not search.dismiss_unanswered(conversation_id, req.message_id):
        raise HTTPException(404, "Conversación no encontrada")
    return {"ok": True}


@app.get("/api/clients/{client_id}")
def client_detail(client_id: int, user: CurrentUser):
    data = search.client_overview(client_id, user["id"])
    if not data:
        raise HTTPException(404, "Cliente no encontrado")
    return data


@app.get("/api/clients/{client_id}/timeline")
def client_timeline(client_id: int, user: CurrentUser, scope: Literal["mine", "team"] = "mine",
                    channel: str | None = None):
    messages = search.timeline(client_id, user["id"], scope, channel)
    # Solo cuenta como acceso al equipo si de verdad se muestran conversaciones de compañeros.
    if scope == "team" and any(m["owner_id"] != user["id"] for m in messages):
        audit.log(user["id"], "team_messages", client_id, throttle=True)
    return messages


@app.get("/api/search")
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


@app.post("/api/smart-search")
def smart_search_endpoint(req: SmartSearchRequest, user: CurrentUser):
    """Búsqueda por significado en mensajes y documentos (Claude amplía la pregunta y ordena los resultados)."""
    if req.client_id is not None:
        _client_or_404(req.client_id)
    if req.scope == "team":
        audit.log(user["id"], "team_search", req.client_id, detail=f"por significado: {req.question}"[:200])
    with claude_errors():
        try:
            return smartsearch.smart_search(req.question, user["id"], req.scope, req.client_id)
        except smartsearch.SmartSearchError as exc:
            raise HTTPException(400, str(exc))


# ---------------------------------------------------------------- Documentos y adjuntos

class FileUpload(BaseModel):
    filename: str = Field(max_length=255)
    data: str  # contenido del archivo en base64


@app.get("/api/clients/{client_id}/documents")
def list_documents(client_id: int, _: CurrentUser):
    _client_or_404(client_id)
    return attachments.list_for_client(client_id)


@app.post("/api/clients/{client_id}/documents")
def upload_document(client_id: int, req: FileUpload, user: CurrentUser):
    """Sube un documento a la ficha del cliente (presupuesto firmado, factura, foto...)."""
    _client_or_404(client_id)
    try:
        data = base64.b64decode(req.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "No se pudo leer el archivo.")
    with get_conn() as conn:
        att_id = attachments.save(conn, client_id, req.filename, data, uploaded_by=user["id"])
    return attachments.get(att_id) | {"path": None, "extracted_text": None}


def _attachment_or_404(attachment_id: int) -> dict:
    att = attachments.get(attachment_id)
    if not att:
        raise HTTPException(404, "Documento no encontrado")
    return att


@app.get("/api/attachments/{attachment_id}/file")
def attachment_file(attachment_id: int, _: CurrentUser, download: bool = False):
    att = _attachment_or_404(attachment_id)
    path = attachments.file_path(att)
    if not path.exists():
        raise HTTPException(404, "El archivo ya no está en el servidor.")
    # Imágenes y PDF se abren en el navegador; el resto se descarga. Nunca se sirve HTML "en línea".
    inline = not download and (att["mime"] in attachments.AI_IMAGE_TYPES or att["mime"] == "application/pdf")
    return FileResponse(path, media_type=att["mime"], filename=att["filename"],
                        content_disposition_type="inline" if inline else "attachment")


@app.get("/api/attachments/{attachment_id}/text")
def attachment_text(attachment_id: int, _: CurrentUser):
    att = _attachment_or_404(attachment_id)
    return {"filename": att["filename"], "extracted_by": att["extracted_by"], "text": att["extracted_text"]}


@app.post("/api/attachments/{attachment_id}/read")
def read_attachment(attachment_id: int, _: CurrentUser):
    """Lee una imagen o PDF con IA y guarda el texto para buscarlo."""
    _attachment_or_404(attachment_id)
    with claude_errors():
        att = attachments.read_with_ai(attachment_id)
    return att | {"path": None}


@app.delete("/api/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, user: CurrentUser):
    with get_conn() as conn:
        row = conn.execute("SELECT uploaded_by, message_id FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Documento no encontrado")
    if row["uploaded_by"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Solo quien lo subió (o un administrador) puede borrarlo.")
    attachments.delete(attachment_id)
    return {"ok": True}


# ---------------------------------------------------------------- Equipo

@app.get("/api/team")
def team(_: CurrentUser):
    """Miembros activos del equipo (para asignar tareas, menciones...)."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT id, name FROM users WHERE active = 1 ORDER BY name")]


# ---------------------------------------------------------------- Ficha del cliente (IA + manual)

@app.get("/api/clients/{client_id}/profile")
def client_profile(client_id: int, _: CurrentUser):
    _client_or_404(client_id)
    return insights.profile(client_id)


@app.post("/api/clients/{client_id}/analyze")
def analyze_client(client_id: int, _: CurrentUser):
    """Actualiza ficha, tareas y resumen con IA."""
    _client_or_404(client_id)
    with claude_errors():
        try:
            changes = insights.analyze_client(client_id)
        except insights.AnalysisError as exc:
            raise HTTPException(400, str(exc))
    return {"changes": changes, **insights.profile(client_id)}


class FactIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)


def _fact_or_404(fact_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT id, client_id, origin FROM client_facts WHERE id = ?", (fact_id,)).fetchone()
    if not row or row["origin"] == "dismissed":
        raise HTTPException(404, "Dato no encontrado")
    return dict(row)


@app.post("/api/clients/{client_id}/facts")
def add_fact(client_id: int, req: FactIn, user: CurrentUser):
    _client_or_404(client_id)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO client_facts (client_id, label, value, origin, updated_by) VALUES (?, ?, ?, 'manual', ?)",
            (client_id, req.label.strip(), req.value.strip(), user["id"]))
    return insights.profile(client_id)


@app.patch("/api/facts/{fact_id}")
def edit_fact(fact_id: int, req: FactIn, user: CurrentUser):
    """Editar un dato lo convierte en manual: la IA ya no lo cambiará."""
    fact = _fact_or_404(fact_id)
    with get_conn() as conn:
        conn.execute(
            """UPDATE client_facts SET label = ?, value = ?, origin = 'manual', updated_by = ?,
                   updated_at = localtimestamp(0) WHERE id = ?""",
            (req.label.strip(), req.value.strip(), user["id"], fact_id))
    return insights.profile(fact["client_id"])


@app.delete("/api/facts/{fact_id}")
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


# ---------------------------------------------------------------- Notas internas y avisos

class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


def _note_or_404(note_id: int) -> dict:
    note = notes.get_note(note_id)
    if not note:
        raise HTTPException(404, "Nota no encontrada")
    return note


@app.get("/api/clients/{client_id}/notes")
def list_notes(client_id: int, _: CurrentUser):
    _client_or_404(client_id)
    return notes.list_notes(client_id)


@app.post("/api/clients/{client_id}/notes")
def add_note(client_id: int, req: NoteIn, user: CurrentUser):
    _client_or_404(client_id)
    return notes.add_note(client_id, user, req.body.strip())


@app.patch("/api/notes/{note_id}")
def edit_note(note_id: int, req: NoteIn, user: CurrentUser):
    if _note_or_404(note_id)["user_id"] != user["id"]:
        raise HTTPException(403, "Solo quien escribió la nota puede editarla.")
    return notes.update_note(note_id, user, req.body.strip())


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user: CurrentUser):
    if _note_or_404(note_id)["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Solo quien escribió la nota (o un administrador) puede borrarla.")
    notes.delete_note(note_id)
    return {"ok": True}


@app.get("/api/notifications")
def notifications(user: CurrentUser):
    return notes.list_notifications(user["id"])


class ReadRequest(BaseModel):
    ids: list[int] | None = None  # sin ids: marcar todos como leídos


@app.post("/api/notifications/read")
def read_notifications(req: ReadRequest, user: CurrentUser):
    notes.mark_read(user["id"], req.ids)
    return notes.list_notifications(user["id"])


# ---------------------------------------------------------------- Tareas

@app.get("/api/tasks")
def tasks(user: CurrentUser, scope: Literal["mine", "all"] = "mine",
          status: Literal["open", "done", "all"] = "open", client_id: int | None = None):
    return insights.list_tasks(client_id=client_id, assignee_id=user["id"] if scope == "mine" else None,
                               status=None if status == "all" else status)


DatePattern = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_date: str | None = DatePattern
    assignee_user_id: int | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    due_date: str | None = DatePattern
    assignee_user_id: int | None = None
    status: Literal["open", "done"] | None = None


@app.post("/api/clients/{client_id}/tasks")
def add_task(client_id: int, req: TaskIn, user: CurrentUser):
    _client_or_404(client_id)
    with get_conn() as conn:
        task_id = conn.execute(
            """INSERT INTO tasks (client_id, title, due_date, assignee_user_id, origin, created_by)
               VALUES (?, ?, ?, ?, 'manual', ?) RETURNING id""",
            (client_id, req.title.strip(), req.due_date, req.assignee_user_id or user["id"], user["id"]),
        ).lastrowid
    task = insights.get_task(task_id)
    notes.notify_task_assigned(task, user)
    return task


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, req: TaskUpdate, user: CurrentUser):
    before = insights.get_task(task_id)
    if not before:
        raise HTTPException(404, "Tarea no encontrada")
    # Solo se tocan los campos enviados (así se puede quitar la fecha o el responsable enviando null).
    fields = {k: getattr(req, k) for k in req.model_fields_set}
    for required in ("title", "status"):
        if fields.get(required, "") is None:
            del fields[required]
    sets = [f"{k} = ?" for k in fields]
    if "status" in fields:
        sets.append("done_at = " + ("localtimestamp(0)" if fields["status"] == "done" else "NULL"))
    if sets:
        with get_conn() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", [*fields.values(), task_id])
    task = insights.get_task(task_id)
    if task["assignee_user_id"] != before["assignee_user_id"]:
        notes.notify_task_assigned(task, user)
    return task


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, _: CurrentUser):
    if not insights.get_task(task_id):
        raise HTTPException(404, "Tarea no encontrada")
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return {"ok": True}


# ---------------------------------------------------------------- Asistentes

@contextmanager
def claude_errors():
    """Traduce los errores de la API de Claude a respuestas HTTP con mensaje en español."""
    try:
        yield
    except anthropic.AuthenticationError:
        raise HTTPException(500, "Clave de API de Claude inválida o ausente (revisa backend/.env).")
    except anthropic.RateLimitError:
        raise HTTPException(429, "Límite de uso de la API alcanzado. Inténtalo en unos segundos.")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "No se pudo conectar con la API de Claude.")
    except anthropic.APIStatusError as exc:
        raise HTTPException(502, f"Error de la API de Claude: {exc.message}")
    except agent.MissingCredentialsError:
        raise HTTPException(503, "El asistente no está disponible: falta configurar ANTHROPIC_API_KEY en backend/.env.")


def _client_or_404(client_id: int | None) -> dict | None:
    if client_id is None:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT id, name FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cliente no encontrado")
    return dict(row)


Kind = Literal["agent", "help"]


@app.get("/api/conversations/{kind}")
def get_conversation(kind: Kind, user: CurrentUser, client_id: int | None = None):
    """Conversación activa del usuario (con un cliente, general o con la mascota) para mostrarla."""
    session = chats.active_session(user["id"], kind, client_id if kind == "agent" else None, create=False)
    return {"turns": chats.turns(session["id"]) if session else []}


@app.get("/api/conversations/agent/clients")
def clients_with_conversation(user: CurrentUser):
    return chats.clients_with_conversation(user["id"])


class ResetRequest(BaseModel):
    client_id: int | None = None


@app.post("/api/conversations/{kind}/reset")
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


@app.post("/api/chat")
def chat(req: ChatRequest, user: CurrentUser):
    """Asistente de datos. Cada conversación pertenece a un cliente (o a ninguno = general)."""
    client = _client_or_404(req.client_id)
    return _run_and_save(user, "agent", req.client_id, req.message,
                         lambda messages: agent.chat(messages, user, req.message, client))


@app.post("/api/help")
def help_chat(req: ChatRequest, user: CurrentUser):
    """Mascota de ayuda: dudas generales sobre el uso de la app."""
    return _run_and_save(user, "help", None, req.message,
                         lambda messages: agent.help_chat(messages, req.message))


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
