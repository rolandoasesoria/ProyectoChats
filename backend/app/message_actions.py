"""Acciones sobre los mensajes de un chat de WhatsApp: reaccionar con un emoji y avisar de que se han leído (los dos
checks azules que ve el cliente). Las dos salen por la cuenta por la que entró la conversación, así que solo las hace
quien la lleva."""
import logging
import re
import threading

from . import integrations
from .db import get_conn
from .errors import Forbidden, InvalidInput, NotFound
from .repositories import conversations as conversations_repo
from .repositories import integrations as integrations_repo
from .repositories import messages as messages_repo

log = logging.getLogger(__name__)

EMOJI_MAX = 16  # un emoji con modificadores (tono de piel, familias…) cabe de sobra
NOT_EMOJI = re.compile(r"[\sA-Za-z0-9<>&\"'`]")


def reactions_by_message(message_ids: list[int]) -> dict[int, list[dict]]:
    """Reacciones de cada mensaje: [{side: client|team, emoji, user}]."""
    with get_conn() as conn:
        found = messages_repo.reactions_for(conn, message_ids)
    result: dict[int, list[dict]] = {}
    for r in found:
        result.setdefault(r.pop("message_id"), []).append(r)
    return result


def react(message_id: int, user: dict, emoji: str) -> list[dict]:
    """Reacción del equipo a un mensaje de WhatsApp («» la quita). Devuelve las reacciones del mensaje."""
    emoji = emoji.strip()
    if emoji and (len(emoji) > EMOJI_MAX or NOT_EMOJI.search(emoji)):
        raise InvalidInput("Esa reacción no es un emoji.")
    with get_conn() as conn:
        msg = messages_repo.with_conversation(conn, message_id)
        if not msg:
            raise NotFound("Mensaje no encontrado.")
        if msg["channel"] != "whatsapp" or not (msg["external_id"] or "").startswith("wa:"):
            raise InvalidInput("Las reacciones solo están disponibles en los mensajes de WhatsApp.")
        if msg["owner_user_id"] != user["id"]:
            raise Forbidden("Solo puede reaccionar quien lleva esta conversación (entró por su cuenta de WhatsApp).")
        integration_id = integrations_repo.find_sender_id(conn, "whatsapp", user["id"], "user")
        handles = integrations_repo.client_handles(conn, msg["client_id"], "whatsapp")
    if not integration_id:
        raise InvalidInput("Conecta tu WhatsApp en «Mis cuentas» para reaccionar.")
    if not handles:
        raise InvalidInput("El cliente no tiene teléfono de WhatsApp.")
    integ = integrations.get(integration_id)
    integrations.attempt(integ, lambda: integrations.send_whatsapp_reaction(integ, handles[0], msg["external_id"][3:],
                                                                             emoji))
    with get_conn() as conn:
        if emoji:
            messages_repo.set_reaction(conn, message_id, "team", emoji, user["id"])
        else:
            messages_repo.delete_reaction(conn, message_id, "team")
    return reactions_by_message([message_id]).get(message_id, [])


def mark_read(client_id: int, user: dict) -> int:
    """Avisa a WhatsApp de que la persona ha leído lo último que le escribió el cliente: él ve los checks azules. Solo
    en las conversaciones que entraron por su cuenta y una vez por mensaje. Devuelve en cuántas lo ha hecho."""
    with get_conn() as conn:
        pending = []
        for conv in conversations_repo.owned_in_channel(conn, client_id, user["id"], "whatsapp"):
            last = messages_repo.latest_incoming_external(conn, conv["id"], "wa:")
            if last and last["id"] > conv["read_receipt_upto"]:
                pending.append((conv["id"], last))
        integration_id = integrations_repo.find_sender_id(conn, "whatsapp", user["id"], "user") if pending else None
    if not integration_id:
        return 0
    integ = integrations.get(integration_id)
    marked = 0
    for conversation_id, last in pending:
        try:
            integrations.whatsapp_mark_read(integ, last["external_id"][3:])
        except (integrations.IntegrationError, OSError) as exc:
            log.info("No se pudo avisar a WhatsApp de que está leído (conversación %s): %s", conversation_id, exc)
            continue
        with get_conn() as conn:
            conversations_repo.set_read_receipt(conn, conversation_id, last["id"])
        marked += 1
    return marked


def mark_read_later(client_id: int, user: dict) -> None:
    """mark_read en segundo plano: abrir el chat o enviar no esperan a Meta."""
    threading.Thread(target=_mark_read_quietly, args=(client_id, dict(user)), daemon=True).start()


def _mark_read_quietly(client_id: int, user: dict) -> None:
    try:
        mark_read(client_id, user)
    except Exception:  # noqa: BLE001 — en segundo plano: que un fallo no tumbe nada, solo queda en el registro
        log.exception("Fallo al avisar a WhatsApp de que está leído (cliente %s)", client_id)
