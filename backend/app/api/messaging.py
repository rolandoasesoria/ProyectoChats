"""Enviar respuestas desde la app y presencia (evitar responder dos veces)."""
import base64
import binascii

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import audit, conversations, integrations, presence, whatsapp_templates
from ..errors import Conflict, InvalidInput
from .deps import CurrentUser, client_or_404

router = APIRouter()


@router.get("/api/conversations/{conversation_id}/sender")
def conversation_sender(conversation_id: int, user: CurrentUser):
    """¿Puede el usuario enviar la respuesta desde la app en esta conversación? Incluye el último mensaje, para
    avisar después si llega otro (del cliente o de un compañero) mientras se escribe la respuesta."""
    integ = integrations.sender_for(conversation_id, user)
    return {"can_send": bool(integ), "via": integ["name"] if integ else None,
            "last_message_id": conversations.last_message_id(conversation_id)}


MAX_SEND_FILE = 15 * 1024 * 1024  # por debajo de lo que admiten WhatsApp (16 MB vídeo/audio) y la mayoría de correos


class SendFile(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime: str | None = Field(None, max_length=100)
    data: str  # contenido del archivo en base64


class SendRequest(BaseModel):
    text: str = Field("", max_length=10000)
    file: SendFile | None = None         # adjunto opcional (el texto va como pie)
    after_message_id: int | None = None  # último mensaje que se veía al empezar a escribir
    force: bool = False                  # enviar aunque haya llegado algo nuevo


@router.post("/api/conversations/{conversation_id}/send")
def send_message(conversation_id: int, req: SendRequest, user: CurrentUser):
    if req.after_message_id is not None and not req.force:
        newer = conversations.newer_messages(conversation_id, req.after_message_id)
        if newer:
            who = "un compañero ha respondido" if any(m["direction"] == "out" for m in newer) else "el cliente ha escrito"
            raise Conflict(f"Mientras escribías, {who} en esta conversación. Revisa la conversación antes de enviar.")
    attachment = None
    if req.file:
        try:
            data = base64.b64decode(req.file.data, validate=True)
        except (binascii.Error, ValueError):
            raise InvalidInput("No se pudo leer el archivo.")
        if len(data) > MAX_SEND_FILE:
            raise InvalidInput("El archivo supera el máximo de 15 MB.")
        attachment = {"filename": req.file.filename, "mime": req.file.mime, "data": data}
    if not req.text.strip() and not attachment:
        raise InvalidInput("Escribe un mensaje o adjunta un archivo.")
    result = integrations.send_reply(conversation_id, user, req.text.strip(), attachment)
    audit.log(user["id"], "message_sent", conversations.conversation_client_id(conversation_id), detail=f"por {result['via']}")
    return result


@router.get("/api/conversations/{conversation_id}/templates")
def conversation_templates(conversation_id: int, user: CurrentUser):
    """Plantillas aprobadas que se pueden enviar en esta conversación de WhatsApp (por la cuenta del usuario)."""
    return {"items": whatsapp_templates.approved_for(conversation_id, user)}


class TemplateSend(BaseModel):
    name: str = Field(min_length=1, max_length=512)
    language: str = Field(min_length=2, max_length=10)
    params: list[str] = Field(default_factory=list, max_length=20)


@router.post("/api/conversations/{conversation_id}/send-template")
def send_template(conversation_id: int, req: TemplateSend, user: CurrentUser):
    result = whatsapp_templates.send_template(conversation_id, user, req.name, req.language, req.params)
    audit.log(user["id"], "message_sent", conversations.conversation_client_id(conversation_id),
              detail=f"plantilla «{req.name}» por {result['via']}")
    return result


class PresenceRequest(BaseModel):
    client_id: int | None = None   # None: no tiene ningún cliente abierto
    composing: bool = False        # tiene el borrador de respuesta abierto


@router.post("/api/presence")
def update_presence(req: PresenceRequest, user: CurrentUser):
    """Latido de la interfaz: devuelve qué compañeros tienen abierto el mismo cliente y si están respondiendo."""
    if req.client_id is not None:
        client_or_404(req.client_id)
    return presence.update(user["id"], req.client_id, req.composing)
