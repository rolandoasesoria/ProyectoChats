"""Enviar respuestas desde la app y presencia (evitar responder dos veces)."""
import base64
import binascii

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import audit, conversations, integrations, link_preview, message_actions, presence, whatsapp_templates
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


def _attachment(file: SendFile | None) -> dict | None:
    if not file:
        return None
    try:
        data = base64.b64decode(file.data, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidInput("No se pudo leer el archivo.")
    if len(data) > MAX_SEND_FILE:
        raise InvalidInput("El archivo supera el máximo de 15 MB.")
    return {"filename": file.filename, "mime": file.mime, "data": data}


class SendRequest(BaseModel):
    text: str = Field("", max_length=10000)
    file: SendFile | None = None         # adjunto opcional (el texto va como pie)
    after_message_id: int | None = None  # último mensaje que se veía al empezar a escribir
    force: bool = False                  # enviar aunque haya llegado algo nuevo
    reply_to_message_id: int | None = None  # mensaje que se cita (de la misma conversación)


@router.post("/api/conversations/{conversation_id}/send")
def send_message(conversation_id: int, req: SendRequest, user: CurrentUser):
    if req.after_message_id is not None and not req.force:
        newer = conversations.newer_messages(conversation_id, req.after_message_id)
        if newer:
            who = "un compañero ha respondido" if any(m["direction"] == "out" for m in newer) else "el cliente ha escrito"
            raise Conflict(f"Mientras escribías, {who} en esta conversación. Revisa la conversación antes de enviar.")
    attachment = _attachment(req.file)
    if not req.text.strip() and not attachment:
        raise InvalidInput("Escribe un mensaje o adjunta un archivo.")
    result = integrations.send_reply(conversation_id, user, req.text.strip(), attachment, req.reply_to_message_id)
    client_id = conversations.conversation_client_id(conversation_id)
    audit.log(user["id"], "message_sent", client_id, detail=f"por {result['via']}")
    message_actions.mark_read_later(client_id, user)  # quien responde ya ha leído lo que había
    return result


def _sent(conversation_id: int, user: dict, result: dict, what: str) -> dict:
    """Tras enviar: queda en el registro y lo del cliente, leído."""
    client_id = conversations.conversation_client_id(conversation_id)
    audit.log(user["id"], "message_sent", client_id, detail=f"{what} por {result['via']}")
    message_actions.mark_read_later(client_id, user)
    return result


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: str = Field("", max_length=200)
    address: str = Field("", max_length=300)


@router.post("/api/conversations/{conversation_id}/send-location")
def send_location(conversation_id: int, req: LocationRequest, user: CurrentUser):
    result = integrations.send_location(conversation_id, user, req.latitude, req.longitude, req.name, req.address)
    return _sent(conversation_id, user, result, "ubicación")


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=3, max_length=40)
    email: str = Field("", max_length=320)


@router.post("/api/conversations/{conversation_id}/send-contact")
def send_contact(conversation_id: int, req: ContactRequest, user: CurrentUser):
    result = integrations.send_contact(conversation_id, user, req.name, req.phone, req.email)
    return _sent(conversation_id, user, result, "contacto")


MAX_VOICE_SECONDS = 15 * 60


class VoiceRequest(BaseModel):
    data: str  # la grabación en base64
    mime: str = Field("", max_length=100)
    seconds: int = Field(ge=1, le=MAX_VOICE_SECONDS)


@router.post("/api/conversations/{conversation_id}/send-voice")
def send_voice(conversation_id: int, req: VoiceRequest, user: CurrentUser):
    try:
        data = base64.b64decode(req.data, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidInput("No se pudo leer la grabación.")
    if len(data) > MAX_SEND_FILE:
        raise InvalidInput("La nota de voz es demasiado larga.")
    result = integrations.send_voice(conversation_id, user, data, req.mime, req.seconds)
    return _sent(conversation_id, user, result, "nota de voz")


@router.get("/api/link-preview")
def get_link_preview(url: str, _: CurrentUser):
    """Vista previa de un enlace (título, descripción, sitio e imagen), o null si no la hay."""
    return {"preview": link_preview.preview(url)}


class Reaction(BaseModel):
    emoji: str = Field("", max_length=16)  # «» quita la reacción


@router.post("/api/messages/{message_id}/reaction")
def react_to_message(message_id: int, req: Reaction, user: CurrentUser):
    """Reacción del equipo a un mensaje de WhatsApp (sale por la cuenta por la que entró la conversación)."""
    return {"reactions": message_actions.react(message_id, user, req.emoji)}


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


class NewEmail(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    text: str = Field("", max_length=50000)
    to: str | None = Field(None, max_length=320)  # una dirección del cliente (por defecto, la primera)
    file: SendFile | None = None


@router.post("/api/clients/{client_id}/emails")
def send_new_email(client_id: int, req: NewEmail, user: CurrentUser):
    """Correo nuevo al cliente, con su asunto (abre un hilo nuevo)."""
    client_or_404(client_id)
    result = integrations.send_new_email(client_id, user, req.subject, req.text, req.to, _attachment(req.file))
    audit.log(user["id"], "message_sent", client_id, detail=f"correo nuevo por {result['via']}")
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
