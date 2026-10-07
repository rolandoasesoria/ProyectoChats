"""Recepción de WhatsApp Business (Cloud API): los avisos que Meta envía al webhook.

Mensajes de los clientes y, con la coexistencia (el número sigue en la app WhatsApp Business del móvil), también lo
que se envía desde el móvil, el historial, los nombres de la agenda y la desconexión. Cada aviso se guarda como
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


def _wa_content(integ: dict, m: dict, download: bool = True) -> tuple[str, list]:
    """Texto y adjuntos de un mensaje de WhatsApp (recibido, enviado desde el móvil o del historial)."""
    kind = m.get("type")
    if kind == "text":
        return m.get("text", {}).get("body", ""), []
    if kind not in ("image", "document", "audio", "video", "sticker"):
        return f"[{kind}]", []
    media = m.get(kind) or {}
    ext = {"image": "jpg", "audio": "ogg", "video": "mp4", "sticker": "webp"}.get(kind, "bin")
    fname = media.get("filename") or f"{kind}_{str(m.get('id', ''))[-8:]}.{ext}"
    body = media.get("caption") or f"📎 {fname}"
    if not download:  # historial: los archivos antiguos no se descargan (serían cientos)
        return body + "\n(archivo del historial, no importado)", []
    f = _download_whatsapp_media(integ, media["id"], fname, media.get("mime_type")) if media.get("id") else None
    if f:
        return body, [f]
    return body + (f"\n⚠ No se pudo descargar «{fname}». Revisa la cuenta de WhatsApp en «Mis cuentas» o pide al "
                   "cliente que lo reenvíe."), []


def _wa_time(m: dict) -> str:
    sent = datetime.fromtimestamp(int(m.get("timestamp") or time.time()), tz=timezone.utc).astimezone()
    return sent.strftime("%Y-%m-%dT%H:%M:%S")


def _owner_name(integ: dict) -> str:
    with get_conn() as conn:
        owner = users_repo.get(conn, integ["owner_user_id"])
    return owner["name"] if owner else "Equipo"


def _wa_incoming(integ: dict, value: dict) -> int:
    """Mensajes que escriben los clientes."""
    names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
    imported = 0
    for m in value.get("messages", []):
        wa_id = m.get("from", "")
        name = names.get(wa_id) or f"+{wa_id}"
        body, files = _wa_content(integ, m)
        imported += integrations.ingest(integ, handle=f"+{wa_id}", client_name=name, direction="in", sender=name, body=body,
                           sent_at=_wa_time(m), external_id=f"wa:{m['id']}", attachments=files)["messages"]
    return imported


def _wa_echoes(integ: dict, value: dict) -> int:
    """Coexistencia: lo que la persona envía desde la app WhatsApp Business del móvil o del ordenador."""
    sender = _owner_name(integ)
    imported = 0
    for m in value.get("message_echoes", []):
        to = m.get("to", "")
        body, files = _wa_content(integ, m)
        imported += integrations.ingest(integ, handle=f"+{to}", client_name=f"+{to}", direction="out", sender=sender, body=body,
                           sent_at=_wa_time(m), external_id=f"wa:{m['id']}", attachments=files)["messages"]
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
                outgoing = integrations.digits(m.get("from", "")) == business if business else integrations.digits(m.get("from", "")) != customer
                body, _ = _wa_content(integ, m, download=False)
                messages.append({"direction": "out" if outgoing else "in", "sender": sender if outgoing else f"+{customer}",
                                 "body": body, "sent_at": _wa_time(m), "external_id": f"wa:{m['id']}",
                                 "attachments": []})
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


WHATSAPP_DISCONNECTED = ("Este WhatsApp Business se ha desconectado de ProyectoChats (desde la app del móvil o desde "
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
