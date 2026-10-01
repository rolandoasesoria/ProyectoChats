"""Enviar respuestas desde la app y presencia (evitar responder dos veces)."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import audit, integrations, presence, search
from ..errors import Conflict
from .deps import CurrentUser, client_or_404

router = APIRouter()


@router.get("/api/conversations/{conversation_id}/sender")
def conversation_sender(conversation_id: int, user: CurrentUser):
    """¿Puede el usuario enviar la respuesta desde la app en esta conversación? Incluye el último mensaje, para
    avisar después si llega otro (del cliente o de un compañero) mientras se escribe la respuesta."""
    integ = integrations.sender_for(conversation_id, user)
    return {"can_send": bool(integ), "via": integ["name"] if integ else None,
            "last_message_id": search.last_message_id(conversation_id)}


class SendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    after_message_id: int | None = None  # último mensaje que se veía al empezar a escribir
    force: bool = False                  # enviar aunque haya llegado algo nuevo


@router.post("/api/conversations/{conversation_id}/send")
def send_message(conversation_id: int, req: SendRequest, user: CurrentUser):
    if req.after_message_id is not None and not req.force:
        newer = search.newer_messages(conversation_id, req.after_message_id)
        if newer:
            who = "un compañero ha respondido" if any(m["direction"] == "out" for m in newer) else "el cliente ha escrito"
            raise Conflict(f"Mientras escribías, {who} en esta conversación. Revisa la conversación antes de enviar.")
    result = integrations.send_reply(conversation_id, user, req.text.strip())
    audit.log(user["id"], "message_sent", search.conversation_client_id(conversation_id), detail=f"por {result['via']}")
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
