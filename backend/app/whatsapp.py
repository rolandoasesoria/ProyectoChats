"""Recepción de WhatsApp Business (Cloud API): los avisos que Meta envía al webhook.

Mensajes de los clientes (con sus reacciones y lo que citan), el estado de entrega de lo enviado (enviado,
entregado, leído o no entregado) y, con la coexistencia (el número sigue en la app WhatsApp Business del móvil), también
lo que se envía desde el móvil, el historial, los nombres de la agenda y la desconexión. Cada aviso se guarda como
conversación de la persona dueña de la cuenta (integrations.ingest/store). El alta está en whatsapp_signup.py, las
plantillas en whatsapp_templates.py y el envío y la comprobación de credenciales en integrations.py.
"""
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone

from . import clients, integrations
from .db import get_conn
from .repositories import messages as messages_repo
from .repositories import users as users_repo

log = logging.getLogger(__name__)


def verify_whatsapp_signature(app_secret: str, raw_body: bytes, signature: str | None) -> bool:
    """¿Viene el aviso firmado por Meta con el app secret (cabecera X-Hub-Signature-256)?"""
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)


def _whatsapp_media(integ: dict, media_id: str, filename: str, mime: str | None) -> dict | None:
    token = integ["config"]["access_token"]
    info = integrations.graph_request("GET", f"/{media_id}", token)
    if not info or not info.get("url"):
        return None
    return {"filename": filename, "mime": mime or info.get("mime_type"),
            "data": integrations.http_request("GET", info["url"], headers=integrations.bearer(token), raw=True)}


def _download_whatsapp_media(integ: dict, media_id: str, filename: str, mime: str | None) -> dict | None:
    """Adjunto de un mensaje recibido, o None si no se puede descargar. El mensaje se guarda igualmente; si es por las
    credenciales, la cuenta queda marcada y se avisa a su dueño."""
    try:
        return _whatsapp_media(integ, media_id, filename, mime)
    except integrations.IntegrationError as exc:
        error = integrations.explain_meta(exc)
        log.warning("No se pudo descargar un adjunto de WhatsApp (integración %s): %s", integ["id"], error)
        if error.needs_attention:
            integrations.flag_problem(integ, str(error))
        return None


def _contact_cards(contacts: list) -> tuple[str, dict]:
    """Tarjetas de contacto compartidas: texto y datos (nombre, teléfonos, emails y empresa)."""
    cards = []
    for c in contacts or []:
        phones = [p.get("phone") or f"+{p.get('wa_id')}" for p in c.get("phones", []) if p.get("phone") or p.get("wa_id")]
        name = (c.get("name") or {}).get("formatted_name") or (phones[0] if phones else "Contacto")
        cards.append({"name": name, "phones": phones, "emails": [e["email"] for e in c.get("emails", []) if e.get("email")],
                      "org": (c.get("org") or {}).get("company") or ""})
    return "👤 Contacto: " + ", ".join(c["name"] for c in cards), {"type": "contacts", "contacts": cards}


def _wa_content(integ: dict, m: dict, download: bool = True) -> tuple[str, list, dict | None]:
    """Texto, adjuntos y datos (ubicación, contactos) de un mensaje de WhatsApp (recibido, enviado desde el móvil o
    del historial)."""
    kind = m.get("type")
    if kind == "text":
        return m.get("text", {}).get("body", ""), [], None
    if kind == "location":
        loc = m.get("location") or {}
        payload = {"type": "location", "latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
                   "name": loc.get("name") or "", "address": loc.get("address") or ""}
        return integrations.location_text(payload), [], payload
    if kind == "contacts":
        body, payload = _contact_cards(m.get("contacts"))
        return body, [], payload
    if kind == "button":  # pulsó un botón de una plantilla
        return (m.get("button") or {}).get("text") or "[botón]", [], None
    if kind == "interactive":  # eligió una opción de un mensaje con botones o lista
        reply = (m.get("interactive") or {}).get("button_reply") or (m.get("interactive") or {}).get("list_reply") or {}
        return reply.get("title") or "[respuesta]", [], None
    if kind not in ("image", "document", "audio", "video", "sticker"):
        return f"[{kind}]", [], None
    media = m.get(kind) or {}
    ext = {"image": "jpg", "audio": "ogg", "video": "mp4", "sticker": "webp"}.get(kind, "bin")
    fname = media.get("filename") or f"{kind}_{str(m.get('id', ''))[-8:]}.{ext}"
    body = media.get("caption") or f"📎 {fname}"
    if not download:  # historial: los archivos antiguos no se descargan (serían cientos)
        return body + "\n(archivo del historial, no importado)", [], None
    payload = {"type": "voice"} if kind == "audio" and media.get("voice") else None
    if payload or kind == "audio":
        body = media.get("caption") or ("🎤 Nota de voz" if media.get("voice") or "ogg" in (media.get("mime_type") or "")
                                        else "🎵 Audio")
    f = _download_whatsapp_media(integ, media["id"], fname, media.get("mime_type")) if media.get("id") else None
    if f:
        return body, [f], payload
    return body + (f"\n⚠ No se pudo descargar «{fname}». Revisa la cuenta de WhatsApp en «Mis cuentas» o pide al "
                   "cliente que lo reenvíe."), [], payload


def _wa_time(m: dict) -> str:
    sent = datetime.fromtimestamp(int(m.get("timestamp") or time.time()), tz=timezone.utc).astimezone()
    return sent.strftime("%Y-%m-%dT%H:%M:%S")


def _owner_name(integ: dict) -> str:
    with get_conn() as conn:
        owner = users_repo.get(conn, integ["owner_user_id"])
    return owner["name"] if owner else "Equipo"


def _wa_quoted(m: dict) -> str | None:
    """El mensaje que cita (al pulsar «Responder» en WhatsApp), como identificador externo."""
    quoted = (m.get("context") or {}).get("id")
    return f"wa:{quoted}" if quoted else None


def _wa_reaction(m: dict, side: str) -> None:
    """Reacción con emoji a un mensaje (del cliente, o de la empresa desde el móvil). Sin emoji, la quita. No es un
    mensaje nuevo: se guarda en el mensaje al que reacciona."""
    reaction = m.get("reaction") or {}
    with get_conn() as conn:
        target = messages_repo.by_external(conn, f"wa:{reaction.get('message_id')}")
        if not target:
            return
        if reaction.get("emoji"):
            messages_repo.set_reaction(conn, target["id"], side, reaction["emoji"], None)
        else:
            messages_repo.delete_reaction(conn, target["id"], side)


# Orden de los estados de entrega: un aviso que llega tarde (p. ej. «entregado» después de «leído») no hace retroceder.
STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}


def _status_error(status: dict) -> str:
    """Por qué no se entregó, explicado (los casos conocidos) o tal como lo da Meta."""
    err = (status.get("errors") or [{}])[0]
    return (integrations.META_SEND_LIMITS.get(err.get("code")) or (err.get("error_data") or {}).get("details")
            or err.get("title") or err.get("message") or "WhatsApp no pudo entregar el mensaje.")


def _wa_statuses(value: dict) -> None:
    """Estado de entrega de lo enviado desde la app: enviado, entregado, leído o no entregado."""
    for s in value.get("statuses", []):
        status, at = s.get("status"), _wa_time(s)
        with get_conn() as conn:
            msg = messages_repo.by_external(conn, f"wa:{s.get('id')}")
            if not msg:
                continue
            current, delivered, read = msg["status"], msg["delivered_at"], msg["read_at"]
            if status == "failed":
                if current not in ("delivered", "read"):
                    messages_repo.update_status(conn, msg["id"], "failed", _status_error(s), delivered, read)
                continue
            if status not in STATUS_RANK:
                continue
            if status in ("delivered", "read"):
                delivered = delivered or at
            if status == "read":
                read = read or at
            if current == "failed" or STATUS_RANK[status] > STATUS_RANK.get(current, 0):
                current = status
            messages_repo.update_status(conn, msg["id"], current, None, delivered, read)


def _wa_incoming(integ: dict, value: dict) -> int:
    """Mensajes que escriben los clientes (y sus reacciones), y el estado de entrega de lo enviado."""
    _wa_statuses(value)
    names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
    imported = 0
    for m in value.get("messages", []):
        if m.get("type") == "reaction":
            _wa_reaction(m, "client")
            continue
        wa_id = m.get("from", "")
        name = names.get(wa_id) or f"+{wa_id}"
        body, files, payload = _wa_content(integ, m)
        imported += integrations.ingest(integ, handle=f"+{wa_id}", client_name=name, direction="in", sender=name, body=body,
                           sent_at=_wa_time(m), external_id=f"wa:{m['id']}", attachments=files,
                           reply_to_external=_wa_quoted(m), payload=payload)["messages"]
    return imported


def _wa_echoes(integ: dict, value: dict) -> int:
    """Coexistencia: lo que la persona envía desde la app WhatsApp Business del móvil o del ordenador."""
    sender = _owner_name(integ)
    imported = 0
    for m in value.get("message_echoes", []):
        if m.get("type") == "reaction":
            _wa_reaction(m, "team")
            continue
        to = m.get("to", "")
        body, files, payload = _wa_content(integ, m)
        imported += integrations.ingest(integ, handle=f"+{to}", client_name=f"+{to}", direction="out", sender=sender, body=body,
                           sent_at=_wa_time(m), external_id=f"wa:{m['id']}", attachments=files,
                           reply_to_external=_wa_quoted(m), payload=payload)["messages"]
    return imported


def _wa_history(integ: dict, value: dict) -> int:
    """Coexistencia: historial de hasta 6 meses que comparte la app del móvil al conectarla, por tandas."""
    business = integrations.digits(value.get("metadata", {}).get("display_phone_number", ""))
    sender = _owner_name(integ)
    imported = 0
    for chunk in value.get("history", []):
        if chunk.get("errors"):
            integrations.set_state_fields(integ["id"], history="rechazado en el móvil")
            continue
        for thread in chunk.get("threads", []):
            customer = integrations.digits(thread.get("id", ""))
            messages = []
            for m in thread.get("messages", []):
                if m.get("type") == "reaction":
                    continue  # las reacciones antiguas no se importan
                outgoing = integrations.digits(m.get("from", "")) == business if business else integrations.digits(m.get("from", "")) != customer
                body, _, payload = _wa_content(integ, m, download=False)
                messages.append({"direction": "out" if outgoing else "in", "sender": sender if outgoing else f"+{customer}",
                                 "body": body, "sent_at": _wa_time(m), "external_id": f"wa:{m['id']}",
                                 "attachments": [], "reply_to_external": _wa_quoted(m), "payload": payload})
            if customer and messages:
                imported += integrations.store(integ, f"+{customer}", f"+{customer}", messages, analyze=False)["messages"]
        progress = chunk.get("metadata", {}).get("progress")
        if progress is not None:
            integrations.set_state_fields(integ["id"], history="importado" if int(progress) >= 100 else f"importando ({progress} %)")
    return imported


def _wa_contacts(integ: dict, value: dict) -> int:
    """Coexistencia: contactos de la agenda del móvil. Solo ponen nombre a clientes que solo tenían su número (no se
    crean clientes nuevos por cada contacto de la agenda)."""
    named = 0
    for item in value.get("state_sync", []):
        contact = item.get("contact") or {}
        phone = integrations.digits(contact.get("phone_number", ""))
        name = (contact.get("full_name") or contact.get("first_name") or "").strip()
        if item.get("type") == "contact" and item.get("action") != "remove" and phone and name:
            named += clients.name_from_contact("whatsapp", integrations.existing_handle("whatsapp", f"+{phone}"), name)
    return named


WHATSAPP_DISCONNECTED = ("Este WhatsApp Business se ha desconectado de Hilvana Chat (desde la app del móvil o desde "
                         "Meta). Para volver a recibir sus mensajes, conéctalo de nuevo en «Mis cuentas».")


def _wa_account_update(integ: dict, value: dict) -> int:
    """La empresa ha desconectado el número (p. ej. desde la app WhatsApp Business): se pausa y se avisa."""
    if value.get("event") == "PARTNER_REMOVED":
        integrations.update(integ["id"], None, None, False, None)
        integrations.flag_problem(integ, WHATSAPP_DISCONNECTED)
    return 0


# Tipo de aviso de Meta (campo «field» del webhook) -> qué hacer con él
WHATSAPP_HANDLERS = {"messages": _wa_incoming, "smb_message_echoes": _wa_echoes, "history": _wa_history,
                     "smb_app_state_sync": _wa_contacts, "account_update": _wa_account_update}


def receive_whatsapp(integ: dict, payload: dict) -> int:
    """Webhook de una integración concreta (/api/webhooks/whatsapp/{id})."""
    imported = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            handler = WHATSAPP_HANDLERS.get(change.get("field") or "messages")
            if handler:
                imported += handler(integ, change.get("value", {})) or 0
    return imported


def receive_whatsapp_app(payload: dict) -> int:
    """Webhook de la app de Meta (/api/webhooks/whatsapp): llegan los avisos de todos los números conectados con el
    registro insertado. Cada aviso va a su integración por el Phone number ID (o por la cuenta, en account_update)."""
    connected = integrations.whatsapp_integrations()
    by_number = {i["config"].get("phone_number_id"): i for i in connected}
    by_account = {i["config"].get("waba_id"): i for i in connected if i["config"].get("waba_id")}
    imported = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            integ = by_number.get(value.get("metadata", {}).get("phone_number_id")) or by_account.get(entry.get("id"))
            handler = WHATSAPP_HANDLERS.get(change.get("field") or "messages")
            if not integ or not handler:
                log.info("Aviso de WhatsApp sin integración que lo reciba (%s)", change.get("field"))
                continue
            if not integ["enabled"] and change.get("field") != "account_update":
                continue
            imported += handler(integ, value) or 0
    return imported


def has_history(payload: dict) -> bool:
    """¿Trae el aviso una tanda de historial? (puede ser grande: se procesa en segundo plano)."""
    return any(c.get("field") == "history" for e in payload.get("entry", []) for c in e.get("changes", []))
