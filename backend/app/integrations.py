"""Conexión con los canales: buzón de email (IMAP/SMTP), bot de Telegram y WhatsApp Business (Cloud API).

- Recibir: email y Telegram se sincronizan cada pocos minutos en segundo plano; WhatsApp llega por webhook (y cada
  pocas horas se comprueba que Meta sigue aceptando sus credenciales). Con la coexistencia (el número sigue en la app
  WhatsApp Business del móvil) llegan además los mensajes enviados desde el móvil, el historial y los contactos.
- Enviar: desde el borrador de respuesta, por la integración del canal de la conversación.
- Si un servicio rechaza las credenciales (token revocado, contraseña cambiada...), la cuenta queda marcada en «Mis
  cuentas» y su dueño recibe un aviso en la campana, una sola vez.
Los mensajes entran como conversaciones de la persona dueña de la integración. La configuración
(contraseñas, tokens) se guarda cifrada (ver secrets_store.py).
"""
import email
import hashlib
import hmac
import imaplib
import json
import logging
import re
import secrets
import smtplib
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import formataddr, make_msgid

from . import attachments, clients, conversations, emails, insights, notes, secrets_store, settings, voice
from .config import config
from .db import get_conn
from .errors import ExternalServiceError, InvalidInput, NotFound
from .repositories import chat_prefs as chat_prefs_repo
from .repositories import integrations as repo
from .repositories import messages as messages_repo

log = logging.getLogger(__name__)

# Campos de configuración de cada tipo. Los marcados como secretos nunca se devuelven al navegador.
FIELDS = {
    "email": [
        {"key": "address", "label": "Dirección de correo", "required": True},
        {"key": "display_name", "label": "Nombre del remitente"},
        {"key": "username", "label": "Usuario (si no es la dirección)"},
        {"key": "password", "label": "Contraseña (o contraseña de aplicación)", "secret": True, "required": True},
        {"key": "imap_host", "label": "Servidor IMAP", "required": True, "placeholder": "imap.gmail.com"},
        {"key": "imap_port", "label": "Puerto IMAP", "default": "993"},
        {"key": "smtp_host", "label": "Servidor SMTP", "required": True, "placeholder": "smtp.gmail.com"},
        {"key": "smtp_port", "label": "Puerto SMTP (465 SSL o 587 STARTTLS)", "default": "465"},
        {"key": "sent_folder", "label": "Carpeta de enviados", "default": "Sent", "placeholder": "Sent · [Gmail]/Enviados"},
        {"key": "sync_minutes", "label": "Revisar cada (minutos)", "default": "5"},
        {"key": "first_sync_days", "label": "La primera vez, importar los últimos (días)", "default": "30"},
    ],
    "telegram": [
        {"key": "bot_token", "label": "Token del bot (de @BotFather)", "secret": True, "required": True},
    ],
    "whatsapp": [
        {"key": "phone_number_id", "label": "Identificador del número de teléfono (Phone number ID)", "required": True},
        {"key": "access_token", "label": "Access token", "secret": True, "required": True},
        {"key": "app_secret", "label": "App secret (para verificar el webhook)", "secret": True, "required": True},
        {"key": "verify_token", "label": "Verify token del webhook (se genera solo si lo dejas vacío)"},
        {"key": "waba_id", "label": "Identificador de la cuenta de WhatsApp Business (WABA ID, para las plantillas)"},
    ],
}
KIND_CHANNEL = {"email": "email", "telegram": "telegram", "whatsapp": "whatsapp"}
# Sustituibles por variables de entorno (las pruebas los apuntan a un puerto cerrado para no salir a internet).
TELEGRAM_API = config.integrations.telegram_api
GRAPH_API = config.integrations.graph_api
MAX_DOWNLOAD = 20 * 1024 * 1024

# Puntos de conexión sustituibles en las pruebas.
IMAP_CLASS = imaplib.IMAP4_SSL
SMTP_SSL_CLASS = smtplib.SMTP_SSL
SMTP_CLASS = smtplib.SMTP

_locks: defaultdict[int, threading.Lock] = defaultdict(threading.Lock)

# Cada cuánto se comprueba que Meta sigue aceptando las credenciales de WhatsApp (que no espera a que falle un envío).
WHATSAPP_CHECK_MINUTES = 6 * 60


class IntegrationError(Exception):
    """Fallo al hablar con un servicio externo. `status` y `error` guardan su respuesta (p. ej. el error de Meta:
    {"code": 190, ...}); `needs_attention` indica que lo tiene que arreglar la persona (credenciales rechazadas), no un
    fallo pasajero de red."""

    def __init__(self, message: str, *, status: int | None = None, error: dict | None = None,
                 needs_attention: bool = False):
        super().__init__(message)
        self.status = status
        self.error = error or {}
        self.needs_attention = needs_attention


# ---------------------------------------------------------------- HTTP

def _multipart(form: dict) -> tuple[bytes, str]:
    """Cuerpo multipart/form-data. Los archivos van como (nombre, tipo MIME, bytes); el resto, como texto."""
    boundary = secrets.token_hex(16).encode()
    parts = []
    for name, value in form.items():
        if isinstance(value, tuple):
            filename, mime, content = value
            head = (f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {mime}\r\n\r\n").encode()
        else:
            head, content = f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(), str(value).encode()
        parts.append(b"--" + boundary + b"\r\n" + head + content + b"\r\n")
    return b"".join(parts) + b"--" + boundary + b"--\r\n", f"multipart/form-data; boundary={boundary.decode()}"


def http_request(method: str, url: str, *, body: dict | None = None, headers: dict | None = None,
                 raw: bool = False, timeout: int = 30, form: dict | None = None):
    """Petición HTTP con cuerpo JSON (`body`) o multipart (`form`, para subir archivos)."""
    if form is not None:
        data, content_type = _multipart(form)
    else:
        data = json.dumps(body).encode() if body is not None else None
        content_type = "application/json" if data else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**({"Content-Type": content_type} if content_type else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = r.read(MAX_DOWNLOAD + 1)
    except urllib.error.HTTPError as e:
        detail = e.read()[:2000].decode(errors="replace")
        raise IntegrationError(f"El servicio respondió {e.code}: {detail[:500]}", status=e.code,
                               error=_error_body(detail)) from e
    except urllib.error.URLError as e:
        raise IntegrationError(f"No se pudo conectar: {e.reason}") from e
    if len(content) > MAX_DOWNLOAD:
        raise IntegrationError("Archivo demasiado grande.")
    return content if raw else json.loads(content or b"null")


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def graph_request(method: str, path: str, token: str | None = None, *, body: dict | None = None, timeout: int = 30):
    """Llamada a la Graph API de Meta: `path` es relativo a la versión (p. ej. "/123/messages") y, si hay token, va
    en la cabecera Authorization."""
    return http_request(method, f"{GRAPH_API}{path}", body=body, headers=bearer(token) if token else None,
                        timeout=timeout)


def _error_body(detail: str) -> dict | None:
    """El objeto "error" de una respuesta de error en JSON (formato de la Graph API de Meta), si lo hay."""
    try:
        error = json.loads(detail).get("error")
    except (ValueError, AttributeError):
        return None
    return error if isinstance(error, dict) else None


# ---------------------------------------------------------------- Gestión

def _mask(kind: str, cfg: dict) -> dict:
    return {f["key"]: ("••••••" if f.get("secret") and cfg.get(f["key"]) else cfg.get(f["key"], ""))
            for f in FIELDS[kind]}


def _clean_config(kind: str, data: dict, old: dict | None = None) -> dict:
    cfg = {}
    for f in FIELDS[kind]:
        value = str(data.get(f["key"]) or "").strip()
        if f.get("secret") and old and value in ("", "••••••"):
            value = old.get(f["key"], "")  # al editar, un secreto vacío significa "no cambiar"
        if not value and "default" in f:
            value = f["default"]
        if f.get("required") and not value:
            raise InvalidInput(f"Falta «{f['label']}».")
        cfg[f["key"]] = value
    if kind == "whatsapp" and not cfg.get("verify_token"):
        cfg["verify_token"] = secrets.token_urlsafe(24)
    if kind == "email":
        for k in ("imap_port", "smtp_port", "sync_minutes", "first_sync_days"):
            if not cfg[k].isdigit():
                raise InvalidInput(f"«{next(f['label'] for f in FIELDS['email'] if f['key'] == k)}» debe ser un número.")
    return cfg


WEBHOOK_URL_FILE = config.data_dir / "webhook_public_url.txt"  # lo escribe scripts/webhook-publico.ps1


def webhook_base_url() -> str | None:
    """Dirección pública (HTTPS) por la que Meta llega a los webhooks, si el túnel está en marcha."""
    try:
        url = WEBHOOK_URL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return url.rstrip("/") if url.startswith("https://") else None


def list_integrations(owner_user_id: int | None = None) -> list[dict]:
    """Todas las integraciones (administración) o solo las de una persona (sus cuentas)."""
    with get_conn() as conn:
        found = repo.list_all(conn, owner_user_id)
    for i in found:
        i["config"] = _mask(i["kind"], secrets_store.decrypt(i["config"]))
        state = json.loads(i.pop("state") or "{}")
        i["coexistence"] = bool(state.get("coexistence"))
        i["history"] = state.get("history")
    _annotate_wabas(found)
    return found


def _annotate_wabas(items: list[dict]) -> None:
    """Para cada número de WhatsApp: su cuenta de WhatsApp Business de Meta (WABA), qué otros números del equipo están
    en ella (comparten las plantillas) y si está en una cuenta distinta de la principal del equipo (la que tiene más
    números; a igualdad, la del número conectado antes)."""
    if not any(i["kind"] == "whatsapp" for i in items):
        return
    with get_conn() as conn:
        team = [i for i in repo.list_all(conn, None) if i["kind"] == "whatsapp"]
    wabas: dict[str, list[dict]] = {}
    for i in team:
        waba = secrets_store.decrypt(i["config"]).get("waba_id") or ""
        if waba:
            wabas.setdefault(waba, []).append(i)
    main = max(wabas, key=lambda w: (len(wabas[w]), -min(i["id"] for i in wabas[w]))) if wabas else ""
    for item in items:
        if item["kind"] != "whatsapp":
            continue
        waba = item["config"].get("waba_id") or ""
        item["waba_id"] = waba
        item["waba_shared_with"] = [f"{i['name']} ({i['owner']})" for i in wabas.get(waba, []) if i["id"] != item["id"]]
        item["waba_main"] = main
        item["waba_other"] = bool(waba and len(wabas) > 1 and waba != main)


def find_whatsapp(phone_number_id: str) -> dict | None:
    """Integración de WhatsApp de ese número (las credenciales van cifradas, así que se buscan descifrándolas)."""
    return next((i for i in whatsapp_integrations() if i["config"].get("phone_number_id") == phone_number_id), None)


def whatsapp_integrations() -> list[dict]:
    with get_conn() as conn:
        ids = repo.ids_of_kind(conn, "whatsapp")
    return [get(i) for i in ids]


def set_state_fields(integration_id: int, **fields) -> None:
    """Cambia campos sueltos del estado (p. ej. el progreso del historial) sin tocar el resto."""
    with get_conn() as conn:
        state = json.loads(repo.lock_state(conn, integration_id) or "{}")
        state.update(fields)
        repo.set_state(conn, integration_id, json.dumps(state))


def get(integration_id: int) -> dict:
    with get_conn() as conn:
        data = repo.get(conn, integration_id)
    if not data:
        raise NotFound("Integración no encontrada")
    data["config"] = secrets_store.decrypt(data["config"])
    data["state"] = json.loads(data["state"])
    return data


def create(kind: str, name: str, owner_user_id: int, config: dict) -> int:
    cfg = _clean_config(kind, config)
    with get_conn() as conn:
        return repo.insert(conn, kind, name.strip() or kind, owner_user_id, secrets_store.encrypt(cfg))


def update(integration_id: int, name: str | None, owner_user_id: int | None, enabled: bool | None,
           config: dict | None) -> None:
    current = get(integration_id)
    fields = {}
    if name is not None:
        fields["name"] = name.strip() or current["kind"]
    if owner_user_id is not None:
        fields["owner_user_id"] = owner_user_id
    if enabled is not None:
        fields["enabled"] = int(enabled)
    if config is not None:
        fields["config"] = secrets_store.encrypt(_clean_config(current["kind"], config, current["config"]))
    if fields:
        with get_conn() as conn:
            repo.update(conn, integration_id, fields)


def delete(integration_id: int) -> None:
    get(integration_id)
    with get_conn() as conn:
        repo.delete(conn, integration_id)


def _save_state(integration_id: int, state: dict, error: str | None = None) -> None:
    with get_conn() as conn:
        repo.save_state(conn, integration_id, json.dumps(state), error)


def flag_problem(integ: dict, problem: str) -> None:
    """Deja la cuenta marcada con el problema (se ve en «Mis cuentas») y, si es nuevo, avisa a su dueño en la
    campana: una sola vez, no en cada intento fallido."""
    with get_conn() as conn:
        previous = repo.lock_last_error(conn, integ["id"])
        repo.set_last_error(conn, integ["id"], problem)
        if previous != problem:
            notes.notify(conn, [integ["owner_user_id"]], "integration_error",
                         f"Tu cuenta «{integ['name']}» necesita atención: {problem}", None, None)


# ---------------------------------------------------------------- Guardar mensajes recibidos o enviados

def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def existing_handle(channel: str, handle: str) -> str:
    """Para WhatsApp, reutiliza el identificador ya guardado aunque esté escrito distinto (+34 600 11 12 22)."""
    if channel != "whatsapp":
        return handle
    tail = digits(handle)[-9:]
    with get_conn() as conn:
        known = repo.phone_handles(conn)
    for existing in known:
        if tail and digits(existing)[-9:] == tail:
            return existing
    return handle


def ingest(integ: dict, *, handle: str, client_name: str, direction: str, sender: str, body: str,
           sent_at: str, external_id: str | None, subject: str | None = None,
           attachments: list | None = None, reply_to_external: str | None = None,
           payload: dict | None = None) -> dict:
    return store(integ, handle, client_name, [{"direction": direction, "sender": sender, "body": body,
                                                "sent_at": sent_at, "external_id": external_id,
                                                "attachments": attachments or [],
                                                "reply_to_external": reply_to_external, "payload": payload}], subject)


def store(integ: dict, handle: str, client_name: str, messages: list[dict], subject: str | None = None,
           analyze: bool = True) -> dict:
    """Guarda mensajes de una conversación como de la persona dueña de la integración. analyze=False para lo antiguo
    (historial importado): ni reactiva al cliente ni lanza el análisis con IA."""
    channel = KIND_CHANNEL[integ["kind"]]
    result = conversations.import_conversation({
        "owner_user_id": integ["owner_user_id"], "channel": channel,
        "handle": existing_handle(channel, handle), "client_name": client_name, "subject": subject,
        "messages": messages,
    })
    # Mensaje nuevo del cliente: su chat sale de archivados y la IA pone al día ficha, tareas, prioridad y estado (unos
    # minutos después).
    if analyze and result["messages"] and any(m["direction"] == "in" for m in messages):
        with get_conn() as conn:
            chat_prefs_repo.unarchive(conn, result["client_id"])
        clients.reactivate(result["client_id"], settings.get("inactive_days"))
        insights.schedule_analysis(result["client_id"])
    return result


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- Email (IMAP / SMTP)

def _imap_date(d: date) -> str:
    return f"{d.day:02d}-{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.month - 1]}-{d.year}"


def _tls() -> ssl.SSLContext:
    """Conexión cifrada que comprueba el certificado y el nombre del servidor (imaplib y smtplib, por defecto, no lo
    comprueban: cualquiera en medio podría hacerse pasar por el servidor y quedarse con la contraseña)."""
    return ssl.create_default_context()


# Nombres habituales de la carpeta de enviados, por si el servidor no la marca como tal (\Sent).
SENT_FOLDER_NAMES = ("sent", "sent items", "sent messages", "sent mail", "enviados", "elementos enviados",
                     "correo enviado", "mensajes enviados", "inbox.sent", "[gmail]/enviados", "[gmail]/sent mail")
_LIST_LINE = re.compile(r'^\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')


def _sent_folder(imap, configured: str) -> str | None:
    """La carpeta de enviados: la configurada si existe y, si no, la que el servidor marca como \\Sent o una de
    nombre habitual (cada proveedor la llama de una forma y en «Otro» es fácil no acertar)."""
    if imap.select(f'"{configured}"', readonly=True)[0] == "OK":
        return configured
    status, lines = imap.list()
    folders = []
    for raw in (lines or []) if status == "OK" else []:
        m = _LIST_LINE.match(raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw))
        if m:
            folders.append((m["flags"].lower().split(), m["name"].strip().strip('"')))
    found = next((name for flags, name in folders if "\\sent" in flags), None) \
        or next((name for _, name in folders if name.lower() in SENT_FOLDER_NAMES), None)
    if found and imap.select(f'"{found}"', readonly=True)[0] == "OK":
        return found
    return None


def _new_uids(imap, last: int, first_sync_days: int) -> list[int]:
    """UID de los correos de la carpeta abierta que aún no se han importado: los posteriores al último visto o, la
    primera vez, los de los últimos `first_sync_days` días."""
    if last:
        _, data = imap.uid("SEARCH", None, f"UID {last + 1}:*")
    else:
        since = date.today() - timedelta(days=first_sync_days)
        _, data = imap.uid("SEARCH", None, f"SINCE {_imap_date(since)}")
    return sorted(int(u) for u in (data[0] or b"").split() if int(u) > last)


def _email_counterpart(msg: dict, direction: str, address: str) -> tuple[str, str] | None:
    """Con quién es la conversación: el remitente de lo recibido o el primer destinatario de lo enviado (sin contar
    la propia dirección). None si el correo es de uno mismo a sí mismo."""
    if direction == "in":
        return None if msg["key"] == address else (msg["key"], msg["name"])
    others = [r for r in msg["recipients"] if r != address]
    return (others[0], others[0]) if others else None


def sync_email(integ: dict) -> int:
    cfg, state = integ["config"], integ["state"]
    address = cfg["address"].lower()
    imported = 0
    imap = IMAP_CLASS(cfg["imap_host"], int(cfg["imap_port"]), ssl_context=_tls())
    try:
        imap.login(cfg.get("username") or cfg["address"], cfg["password"])
        sent = _sent_folder(imap, cfg.get("sent_folder") or "Sent")
        for folder, direction in (("INBOX", "in"), (sent, "out")):
            if folder is None:
                continue  # el servidor no tiene carpeta de enviados reconocible
            status, _ = imap.select(f'"{folder}"', readonly=True)
            if status != "OK":
                continue
            for uid in _new_uids(imap, int(state.get(folder, 0)), int(cfg.get("first_sync_days") or 30)):
                _, parts = imap.uid("FETCH", str(uid), "(RFC822)")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                state[folder] = uid
                msg = emails.parse_message(email.message_from_bytes(raw, policy=default_policy)) if raw else None
                if not msg or msg["bulk"]:
                    continue  # vacío, boletines, notificaciones automáticas...
                counterpart = _email_counterpart(msg, direction, address)
                if not counterpart:
                    continue
                handle, client_name = counterpart
                imported += ingest(integ, handle=handle, client_name=client_name, direction=direction,
                                   sender=msg["name"], body=msg["body"], sent_at=msg["sent_at"],
                                   external_id=msg["external_id"], subject=msg["subject"],
                                   attachments=msg["attachments"])["messages"]
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    _save_state(integ["id"], state)
    return imported


def send_email(integ: dict, to: str, text: str, subject: str | None, in_reply_to: str | None,
               attachment: dict | None = None, reply: bool = True) -> str:
    """Envía un correo: respuesta en el hilo («Re: asunto») o, con reply=False, uno nuevo con ese asunto."""
    cfg = integ["config"]
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("display_name") or "", cfg["address"]))
    msg["To"] = to
    if reply:
        msg["Subject"] = f"Re: {subject}" if subject and subject != "(sin asunto)" else (subject or "")
    else:
        msg["Subject"] = subject or ""
    msg["Message-ID"] = make_msgid(domain=cfg["address"].split("@")[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(text)
    if attachment:
        maintype, _, subtype = (attachment["mime"] or "application/octet-stream").partition("/")
        msg.add_attachment(attachment["data"], maintype=maintype, subtype=subtype or "octet-stream",
                           filename=attachment["filename"])
    port = int(cfg["smtp_port"])
    context = _tls()
    server = SMTP_SSL_CLASS(cfg["smtp_host"], port, timeout=30, context=context) if port == 465 \
        else SMTP_CLASS(cfg["smtp_host"], port, timeout=30)
    try:
        if port != 465:
            server.starttls(context=context)
        server.login(cfg.get("username") or cfg["address"], cfg["password"])
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass
    return msg["Message-ID"]


# ---------------------------------------------------------------- Telegram (bot)

def _telegram_file(token: str, file_id: str, filename: str, mime: str | None = None) -> dict | None:
    info = http_request("GET", f"{TELEGRAM_API}/bot{token}/getFile?file_id={urllib.parse.quote(file_id)}")
    path = (info or {}).get("result", {}).get("file_path")
    if not path:
        return None
    data = http_request("GET", f"{TELEGRAM_API}/file/bot{token}/{path}", raw=True)
    return {"filename": filename, "mime": mime, "data": data}


def location_text(payload: dict) -> str:
    """«📍 Ubicación: nombre · dirección» (o las coordenadas)."""
    label = " · ".join(filter(None, [payload.get("name"), payload.get("address")]))
    if not label:
        label = f"{payload.get('latitude')}, {payload.get('longitude')}"
    return f"📍 Ubicación: {label}"


def maps_url(latitude: float, longitude: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"


def voice_text(seconds: int | None) -> str:
    """«🎤 Nota de voz (1:05)»: el texto de una nota de voz (sin la duración si no se sabe)."""
    if not seconds:
        return "🎤 Nota de voz"
    return f"🎤 Nota de voz ({seconds // 60}:{seconds % 60:02d})"


# Audios y vídeos que manda el cliente por Telegram: campo del mensaje, nombre del archivo y tipo si no lo indica.
TELEGRAM_MEDIA = (("voice", "nota-de-voz-{id}.ogg", "audio/ogg"), ("audio", "audio-{id}.mp3", "audio/mpeg"),
                  ("video", "video-{id}.mp4", "video/mp4"), ("video_note", "video-{id}.mp4", "video/mp4"))


def _telegram_extra(m: dict) -> tuple[str, dict | None]:
    """Nota de voz, ubicación (o lugar) y contacto que comparte el cliente por Telegram: texto y datos."""
    if m.get("voice"):
        seconds = m["voice"].get("duration")
        return voice_text(seconds), {"type": "voice", "seconds": seconds}
    if m.get("venue") or m.get("location"):
        venue = m.get("venue") or {}
        loc = venue.get("location") or m.get("location") or {}
        payload = {"type": "location", "latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
                   "name": venue.get("title") or "", "address": venue.get("address") or ""}
        return location_text(payload), payload
    if m.get("contact"):
        c = m["contact"]
        name = " ".join(filter(None, [c.get("first_name"), c.get("last_name")])) or c.get("phone_number") or "Contacto"
        payload = {"type": "contacts", "contacts": [{"name": name, "phones": [c.get("phone_number")] if c.get("phone_number") else [],
                                                     "emails": [], "org": ""}]}
        return f"👤 Contacto: {name}", payload
    return "", None


def sync_telegram(integ: dict) -> int:
    token, state = integ["config"]["bot_token"], integ["state"]
    offset = int(state.get("offset", 0))
    resp = http_request("GET", f"{TELEGRAM_API}/bot{token}/getUpdates?timeout=0&offset={offset}")
    imported = 0
    for upd in (resp or {}).get("result", []):
        state["offset"] = upd["update_id"] + 1
        m = upd.get("message")
        if not m or m.get("chat", {}).get("type") != "private":
            continue  # solo chats privados con el bot
        who = m.get("from", {})
        name = " ".join(filter(None, [who.get("first_name"), who.get("last_name")])) or who.get("username") or "Cliente"
        files = []
        if m.get("photo"):
            f = _telegram_file(token, m["photo"][-1]["file_id"], f"foto_{m['message_id']}.jpg", "image/jpeg")
            files += [f] if f else []
        if m.get("document"):
            d = m["document"]
            f = _telegram_file(token, d["file_id"], d.get("file_name") or "documento", d.get("mime_type"))
            files += [f] if f else []
        for field, filename, mime in TELEGRAM_MEDIA:
            if m.get(field):
                d = m[field]
                f = _telegram_file(token, d["file_id"], d.get("file_name") or filename.format(id=m["message_id"]),
                                   d.get("mime_type") or mime)
                files += [f] if f else []
        extra_body, payload = _telegram_extra(m)
        body = m.get("text") or m.get("caption") or extra_body or (
            "📎 " + ", ".join(f["filename"] for f in files) if files else "")
        if not body:
            continue
        sent = datetime.fromtimestamp(m["date"], tz=timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        quoted = (m.get("reply_to_message") or {}).get("message_id")
        res = ingest(integ, handle=f"user{m['chat']['id']}", client_name=name, direction="in", sender=name,
                     body=body, sent_at=sent, external_id=f"tg:{m['chat']['id']}:{m['message_id']}", attachments=files,
                     reply_to_external=f"tg:{m['chat']['id']}:{quoted}" if quoted else None, payload=payload)
        imported += res["messages"]
    _save_state(integ["id"], state)
    return imported


def send_telegram(integ: dict, handle: str, text: str, reply_to: int | None = None) -> str:
    if not handle.startswith("user") or not handle[4:].isdigit():
        raise IntegrationError("Este cliente no ha escrito al bot: Telegram solo deja responder a quien escribió antes al bot.")
    body = {"chat_id": int(handle[4:]), "text": text}
    if reply_to:  # citando un mensaje; si ya no existe, se envía igualmente sin cita
        body["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    resp = http_request("POST", f"{TELEGRAM_API}/bot{integ['config']['bot_token']}/sendMessage", body=body)
    return f"tg:{handle[4:]}:{resp['result']['message_id']}"


def send_telegram_file(integ: dict, handle: str, attachment: dict, caption: str, reply_to: int | None = None) -> str:
    if not handle.startswith("user") or not handle[4:].isdigit():
        raise IntegrationError("Este cliente no ha escrito al bot: Telegram solo deja responder a quien escribió antes al bot.")
    photo = attachment["mime"] in ("image/jpeg", "image/png")
    method, field = ("sendPhoto", "photo") if photo else ("sendDocument", "document")
    form = {"chat_id": handle[4:], field: (attachment["filename"], attachment["mime"], attachment["data"])}
    if caption:
        form["caption"] = caption
    if reply_to:
        form["reply_to_message_id"] = str(reply_to)
    resp = http_request("POST", f"{TELEGRAM_API}/bot{integ['config']['bot_token']}/{method}", form=form, timeout=60)
    return f"tg:{handle[4:]}:{resp['result']['message_id']}"


# ---------------------------------------------------------------- WhatsApp Business (Cloud API)

META_TOKEN_REJECTED = ("Meta no acepta el access token: ha caducado o se ha revocado. Si usaste el temporal de "
                       "«API Setup» (dura 24 h), crea uno permanente con un usuario del sistema y pégalo en «Editar».")
# Envíos que WhatsApp no permite (no son fallos de la cuenta: no se marca ni se avisa en la campana).
META_SEND_LIMITS = {
    131047: "Han pasado más de 24 h desde el último mensaje del cliente: WhatsApp solo deja escribirle con una "
            "plantilla aprobada. Si tu número está en coexistencia, respóndele desde la app del móvil; si no, espera a "
            "que vuelva a escribir.",
    131030: "Ese número no está en la lista de destinatarios permitidos del número de prueba de Meta: añádelo en "
            "WhatsApp → API Setup («Para»).",
    131026: "No se puede entregar el mensaje: ese número no tiene WhatsApp o no acepta mensajes de empresas.",
}


def explain_meta(exc: IntegrationError, phone_lookup: bool = False) -> IntegrationError:
    """Traduce un error de la Graph API de Meta a un mensaje claro y marca los de credenciales (needs_attention).
    phone_lookup: la llamada era la consulta del número, así que un "objeto no encontrado" es el Phone number ID."""
    if exc.status is None:  # ni siquiera se llegó a Meta (red, DNS, cortafuegos...)
        return IntegrationError(f"No se pudo conectar con Meta ({str(exc).removeprefix('No se pudo conectar: ')}).")
    code, message = exc.error.get("code"), str(exc.error.get("message") or "")
    if code in (190, 102) or exc.status == 401:
        problem = META_TOKEN_REJECTED
    elif "appsecret_proof" in message:
        problem = ("El app secret no corresponde a la app del access token: cópialo de tu app en Meta for Developers "
                   "(Configuración de la app → Básica).")
    elif code == 10 or (isinstance(code, int) and 200 <= code <= 299):
        problem = ("Al access token le faltan permisos: genéralo con whatsapp_business_messaging y "
                   "whatsapp_business_management.")
    elif phone_lookup and code == 100:
        problem = ("El Phone number ID no existe o el access token no tiene acceso a ese número: cópialo de "
                   "WhatsApp → API Setup en Meta for Developers.")
    elif code == 131005:
        problem = ("Meta no deja enviar con este access token (acceso denegado): genera uno nuevo con el permiso "
                   "whatsapp_business_messaging y pégalo en «Editar».")
    elif code in META_SEND_LIMITS:
        return IntegrationError(META_SEND_LIMITS[code], status=exc.status, error=exc.error)
    else:
        return IntegrationError(f"Meta ha respondido con un error: {message or exc}", status=exc.status, error=exc.error)
    return IntegrationError(problem, status=exc.status, error=exc.error, needs_attention=True)


def check_whatsapp(integ: dict) -> str:
    """Pregunta a Meta por el número con estas credenciales. Comprueba a la vez el access token, el Phone number ID y
    el app secret (va como appsecret_proof, que Meta valida). Devuelve el número y su nombre verificado."""
    cfg = integ["config"]
    proof = hmac.new(cfg["app_secret"].encode(), cfg["access_token"].encode(), hashlib.sha256).hexdigest()
    query = urllib.parse.urlencode({"fields": "display_phone_number,verified_name", "appsecret_proof": proof})
    info = graph_request("GET", f"/{urllib.parse.quote(cfg['phone_number_id'], safe='')}?{query}",
                         cfg["access_token"], timeout=15) or {}
    return " · ".join(filter(None, [info.get("display_phone_number"), info.get("verified_name")]))


def send_whatsapp(integ: dict, handle: str, text: str, reply_to: str | None = None) -> str:
    """Envía un texto; con `reply_to` (id de WhatsApp de un mensaje) lo cita, como «Responder» en el móvil."""
    to = digits(handle)
    if len(to) < 8:
        raise IntegrationError("El teléfono de WhatsApp del cliente no es válido.")
    cfg = integ["config"]
    body = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    if re.search(r"https?://", text):
        body["text"]["preview_url"] = True  # el cliente ve la vista previa del enlace
    if reply_to:
        body["context"] = {"message_id": reply_to}
    resp = graph_request("POST", f"/{cfg['phone_number_id']}/messages", cfg["access_token"], body=body)
    return f"wa:{resp['messages'][0]['id']}"


def _whatsapp_message(integ: dict, handle: str, kind: str, content) -> str:
    """Envía un mensaje de WhatsApp de tipo `kind` (location, contacts…) con su contenido."""
    to = digits(handle)
    if len(to) < 8:
        raise IntegrationError("El teléfono de WhatsApp del cliente no es válido.")
    cfg = integ["config"]
    resp = graph_request("POST", f"/{cfg['phone_number_id']}/messages", cfg["access_token"],
                         body={"messaging_product": "whatsapp", "to": to, "type": kind, kind: content})
    return f"wa:{resp['messages'][0]['id']}"


def send_whatsapp_reaction(integ: dict, handle: str, message_id: str, emoji: str) -> None:
    """Reacciona con `emoji` al mensaje de WhatsApp `message_id` («» quita la reacción)."""
    to = digits(handle)
    if len(to) < 8:
        raise IntegrationError("El teléfono de WhatsApp del cliente no es válido.")
    cfg = integ["config"]
    graph_request("POST", f"/{cfg['phone_number_id']}/messages", cfg["access_token"],
                  body={"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "reaction",
                        "reaction": {"message_id": message_id, "emoji": emoji}})


def whatsapp_mark_read(integ: dict, message_id: str) -> None:
    """Marca como leído el mensaje del cliente (y los anteriores): en su móvil aparecen los checks azules."""
    cfg = integ["config"]
    graph_request("POST", f"/{cfg['phone_number_id']}/messages", cfg["access_token"],
                  body={"messaging_product": "whatsapp", "status": "read", "message_id": message_id}, timeout=15)


# Tipo de mensaje de WhatsApp según el archivo (el resto va como documento).
WHATSAPP_MEDIA = {"image/jpeg": "image", "image/png": "image", "video/mp4": "video", "audio/mpeg": "audio",
                  "audio/ogg": "audio", "audio/aac": "audio", "audio/mp4": "audio"}


def send_whatsapp_file(integ: dict, handle: str, attachment: dict, caption: str, reply_to: str | None = None) -> str:
    """Sube el archivo a Meta y lo envía (imagen, vídeo, audio o documento) con `caption` como pie."""
    to = digits(handle)
    if len(to) < 8:
        raise IntegrationError("El teléfono de WhatsApp del cliente no es válido.")
    cfg = integ["config"]
    mime = attachment["mime"] or "application/octet-stream"
    uploaded = http_request("POST", f"{GRAPH_API}/{cfg['phone_number_id']}/media", headers=bearer(cfg["access_token"]),
                            form={"messaging_product": "whatsapp", "type": mime,
                                  "file": (attachment["filename"], mime, attachment["data"])}, timeout=60)
    kind = WHATSAPP_MEDIA.get(mime, "document")
    media = {"id": uploaded["id"]}
    if caption and kind != "audio":
        media["caption"] = caption
    if kind == "document":
        media["filename"] = attachment["filename"]
    body = {"messaging_product": "whatsapp", "to": to, "type": kind, kind: media}
    if reply_to:
        body["context"] = {"message_id": reply_to}
    resp = graph_request("POST", f"/{cfg['phone_number_id']}/messages", cfg["access_token"], body=body)
    return f"wa:{resp['messages'][0]['id']}"


def send_whatsapp_template(integ: dict, handle: str, name: str, language: str, params: list[str]) -> str:
    """Envía una plantilla aprobada (lo único que WhatsApp deja enviar pasadas 24 h del último mensaje del cliente)."""
    to = digits(handle)
    if len(to) < 8:
        raise IntegrationError("El teléfono de WhatsApp del cliente no es válido.")
    cfg = integ["config"]
    template = {"name": name, "language": {"code": language}}
    if params:
        template["components"] = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
    resp = graph_request("POST", f"/{cfg['phone_number_id']}/messages", cfg["access_token"],
                         body={"messaging_product": "whatsapp", "to": to, "type": "template", "template": template})
    return f"wa:{resp['messages'][0]['id']}"


# ---------------------------------------------------------------- Sincronización y envío

def _explain(kind: str, exc: Exception, phone_lookup: bool = False) -> IntegrationError:
    """Convierte un fallo técnico en un mensaje claro. needs_attention marca los que tiene que arreglar la persona
    (credenciales rechazadas); los demás (red, servidor caído) suelen arreglarse solos en el siguiente intento."""
    if kind == "whatsapp" and isinstance(exc, IntegrationError):
        return explain_meta(exc, phone_lookup)
    if kind == "telegram" and isinstance(exc, IntegrationError) and exc.status in (401, 404):
        return IntegrationError("Telegram no acepta el token del bot: se ha regenerado o el bot ya no existe. Copia el "
                                "token actual de @BotFather y pégalo en «Editar».", status=exc.status,
                                needs_attention=True)
    if kind == "email" and isinstance(exc, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)) \
            and re.search(r"auth|login|credential|password", str(exc), re.IGNORECASE):
        return IntegrationError("El servidor de correo no acepta el usuario o la contraseña. Si has cambiado la "
                                "contraseña de tu cuenta (Google anula entonces las contraseñas de aplicación) o la "
                                "has revocado, crea una nueva y pégala en «Editar».", needs_attention=True)
    if kind == "email" and isinstance(exc, ssl.SSLCertVerificationError):
        return IntegrationError("El certificado del servidor de correo no es válido para ese nombre (o ha caducado): "
                                "por seguridad no se envía la contraseña. Revisa el servidor IMAP/SMTP en «Editar» "
                                "(debe ser el nombre exacto que da tu proveedor).", needs_attention=True)
    return exc if isinstance(exc, IntegrationError) else IntegrationError(str(exc))


def sync(integration_id: int) -> dict:
    """Sincroniza una integración ahora: trae lo pendiente (email y Telegram) o comprueba que Meta sigue aceptando
    las credenciales (WhatsApp, que recibe por webhook). Guarda el error si falla."""
    with _locks[integration_id]:
        integ = get(integration_id)
        try:
            if integ["kind"] == "email":
                n = sync_email(integ)
            elif integ["kind"] == "telegram":
                n = sync_telegram(integ)
            else:
                detail = check_whatsapp(integ)
                _save_state(integration_id, integ["state"])
                return {"imported": 0, "detail": detail}
        except (IntegrationError, OSError, imaplib.IMAP4.error, smtplib.SMTPException, KeyError, ValueError) as exc:
            error = _explain(integ["kind"], exc, phone_lookup=True)
            if error.needs_attention:
                flag_problem(integ, str(error)[:500])
            _save_state(integration_id, integ["state"], error=str(error)[:500])
            raise error from exc
        return {"imported": n}


def check_connection(integration_id: int) -> dict:
    """Prueba la cuenta recién conectada o editada: trae lo pendiente (correo, Telegram) o consulta el número a Meta
    (WhatsApp). No lanza: devuelve el resultado o el error."""
    try:
        result = sync(integration_id)
    except IntegrationError as exc:
        return {"ok": False, "imported": 0, "error": str(exc)[:300]}
    return {"ok": True, "error": None, **result}


def sender_for(conversation_id: int, user: dict) -> dict | None:
    """Integración con la que el usuario puede responder en esta conversación (o None)."""
    with get_conn() as conn:
        conv = repo.conversation(conn, conversation_id)
        if not conv:
            return None
        found_id = repo.find_sender_id(conn, conv["channel"], user["id"], user["role"])
    return get(found_id) if found_id else None


def reply_target(conversation_id: int, user: dict) -> tuple[dict, dict, list[str]]:
    """Por dónde responde `user` en esta conversación: su integración del canal, la conversación y los
    identificadores del cliente en ese canal."""
    integ = sender_for(conversation_id, user)
    if not integ:
        raise InvalidInput("No tienes una integración activa de este canal para enviar mensajes.")
    with get_conn() as conn:
        conv = repo.conversation(conn, conversation_id)
        idents = repo.client_handles(conn, conv["client_id"], conv["channel"])
    if not idents:
        raise InvalidInput("El cliente no tiene identificador en este canal.")
    return integ, conv, idents


def attempt(integ: dict, send):
    """Ejecuta `send()` (devuelve el identificador externo). Los fallos se explican y, si son de credenciales,
    marcan la cuenta."""
    try:
        return send()
    except (IntegrationError, OSError, smtplib.SMTPException) as exc:
        error = _explain(integ["kind"], exc)
        if error.needs_attention:
            flag_problem(integ, str(error))
        raise ExternalServiceError(f"No se pudo enviar: {error}")


def deliver(integ: dict, conversation_id: int, user: dict, text: str, send, by_ai: bool = False,
            reply_to_id: int | None = None, payload: dict | None = None) -> dict:
    """Envía con `send()` y guarda `text` en la conversación como enviado por quien lo escribió (o por la IA, con
    `by_ai`), citando `reply_to_id` si lo hay. Lo de WhatsApp queda «enviado» hasta que Meta avise de la entrega."""
    ext = attempt(integ, send)
    with get_conn() as conn:
        message_id = repo.insert_sent_message(conn, conversation_id, user["name"], text, _now_local(), ext, by_ai,
                                              reply_to_id, "sent" if ext.startswith("wa:") else None, payload)
    return {"message_id": message_id, "via": integ["name"]}


def send_new_email(client_id: int, user: dict, subject: str, text: str, to: str | None = None,
                   attachment: dict | None = None) -> dict:
    """Correo nuevo (hilo nuevo, con su asunto) a una dirección del cliente, por la cuenta de correo del usuario. Se
    guarda como conversación de quien tiene esa cuenta."""
    subject = " ".join(subject.split())
    if not subject:
        raise InvalidInput("Ponle un asunto al correo.")
    if not text.strip() and not attachment:
        raise InvalidInput("Escribe el correo o adjunta un archivo.")
    with get_conn() as conn:
        integration_id = repo.find_sender_id(conn, "email", user["id"], user["role"])
        addresses = repo.client_handles(conn, client_id, "email")
    if not integration_id:
        raise InvalidInput("Conecta tu correo en «Mis cuentas» para escribir desde aquí.")
    if not addresses:
        raise InvalidInput("Este cliente no tiene ninguna dirección de correo.")
    to = to or addresses[0]
    if to not in addresses:
        raise InvalidInput("Esa dirección no es de este cliente.")
    integ = get(integration_id)
    if attachment:
        attachment = {**attachment, "mime": attachments.guess_mime(attachment["filename"], attachment.get("mime"))}
    ext = attempt(integ, lambda: send_email(integ, to, text, subject, None, attachment, reply=False))
    result = conversations.import_conversation({
        "owner_user_id": integ["owner_user_id"], "channel": "email", "handle": to, "client_id": client_id,
        "subject": subject, "messages": [{
            "direction": "out", "sender": user["name"], "sent_at": _now_local(), "external_id": ext,
            "body": text.strip() or (f"📎 {attachment['filename']}" if attachment else ""),
            "attachments": [attachment] if attachment else []}],
    })
    return {"conversation_id": result["conversation_id"], "via": integ["name"]}


def _quoted(conversation_id: int, message_id: int | None) -> dict | None:
    """El mensaje que se cita al responder (tiene que ser de la misma conversación)."""
    if message_id is None:
        return None
    with get_conn() as conn:
        quoted = messages_repo.with_conversation(conn, message_id)
    if not quoted or quoted["conversation_id"] != conversation_id:
        raise InvalidInput("Solo se puede citar un mensaje de esta conversación.")
    return quoted


def _telegram_message_id(external_id: str | None) -> int | None:
    """Número de mensaje de Telegram a partir de «tg:<chat>:<número>»."""
    parts = (external_id or "").split(":")
    return int(parts[2]) if len(parts) == 3 and parts[0] == "tg" and parts[2].isdigit() else None


def send_reply(conversation_id: int, user: dict, text: str, attachment: dict | None = None,
               reply_to_message_id: int | None = None) -> dict:
    """Responde al cliente por el canal de la conversación. Con `attachment` ({filename, mime, data}) envía el archivo
    (el texto va como pie) y lo guarda en la ficha del cliente, junto al mensaje. Con `reply_to_message_id` cita ese
    mensaje (en WhatsApp y Telegram el cliente ve la cita; en el correo queda solo en la app)."""
    integ, conv, idents = reply_target(conversation_id, user)
    quoted = _quoted(conversation_id, reply_to_message_id)
    quoted_ext = (quoted or {}).get("external_id") or ""
    if attachment:
        attachment = {**attachment, "mime": attachments.guess_mime(attachment["filename"], attachment.get("mime"))}

    def send() -> str:
        if conv["channel"] == "email":
            with get_conn() as conn:
                in_reply_to = repo.last_incoming_external_id(conn, conversation_id)
            return send_email(integ, idents[0], text, conv["subject"], in_reply_to, attachment)
        if conv["channel"] == "telegram":
            handle = next((h for h in idents if h.startswith("user")), idents[0])
            reply_to = _telegram_message_id(quoted_ext)
            return (send_telegram_file(integ, handle, attachment, text, reply_to) if attachment
                    else send_telegram(integ, handle, text, reply_to))
        reply_to = quoted_ext[3:] if quoted_ext.startswith("wa:") else None
        if attachment:
            return send_whatsapp_file(integ, idents[0], attachment, text, reply_to)
        return send_whatsapp(integ, idents[0], text, reply_to)

    stored = text or (f"📎 {attachment['filename']}" if attachment else "")
    result = deliver(integ, conversation_id, user, stored, send, reply_to_id=quoted["id"] if quoted else None)
    if attachment:
        with get_conn() as conn:
            attachments.save(conn, conv["client_id"], attachment["filename"], attachment["data"], attachment["mime"],
                             result["message_id"], user["id"])
    return result


def _telegram_handle(idents: list[str]) -> str:
    handle = next((h for h in idents if h.startswith("user")), idents[0])
    if not handle.startswith("user") or not handle[4:].isdigit():
        raise IntegrationError("Este cliente no ha escrito al bot: Telegram solo deja responder a quien escribió antes al bot.")
    return handle


def _telegram_call(integ: dict, method: str, body: dict | None = None, form: dict | None = None) -> str:
    resp = http_request("POST", f"{TELEGRAM_API}/bot{integ['config']['bot_token']}/{method}", body=body, form=form,
                        timeout=60)
    chat = (body or form)["chat_id"]
    return f"tg:{chat}:{resp['result']['message_id']}"


def _email_in_thread(integ: dict, conv: dict, idents: list[str], text: str, attachment: dict | None = None) -> str:
    with get_conn() as conn:
        in_reply_to = repo.last_incoming_external_id(conn, conv["id"])
    return send_email(integ, idents[0], text, conv["subject"], in_reply_to, attachment)


def send_location(conversation_id: int, user: dict, latitude: float, longitude: float, name: str = "",
                  address: str = "") -> dict:
    """Comparte una ubicación: en WhatsApp y Telegram como ubicación (el cliente la abre en su mapa); en el correo,
    como texto con el enlace al mapa."""
    integ, conv, idents = reply_target(conversation_id, user)
    payload = {"type": "location", "latitude": latitude, "longitude": longitude, "name": name.strip(),
               "address": address.strip()}
    text = location_text(payload)

    def send() -> str:
        if conv["channel"] == "whatsapp":
            loc = {"latitude": latitude, "longitude": longitude}
            loc.update({k: payload[k] for k in ("name", "address") if payload[k]})
            return _whatsapp_message(integ, idents[0], "location", loc)
        if conv["channel"] == "telegram":
            chat = int(_telegram_handle(idents)[4:])
            if payload["name"] and payload["address"]:
                return _telegram_call(integ, "sendVenue", {"chat_id": chat, "latitude": latitude, "longitude": longitude,
                                                           "title": payload["name"], "address": payload["address"]})
            return _telegram_call(integ, "sendLocation", {"chat_id": chat, "latitude": latitude, "longitude": longitude})
        return _email_in_thread(integ, conv, idents, f"{text}\n{maps_url(latitude, longitude)}")

    return deliver(integ, conversation_id, user, text, send, payload=payload)


def send_contact(conversation_id: int, user: dict, name: str, phone: str, email: str = "") -> dict:
    """Comparte una tarjeta de contacto (nombre, teléfono y, si se quiere, email)."""
    name, phone, email = " ".join(name.split()), phone.strip(), email.strip()
    if not name or len(digits(phone)) < 6:
        raise InvalidInput("Pon el nombre y un teléfono válido del contacto.")
    integ, conv, idents = reply_target(conversation_id, user)
    payload = {"type": "contacts", "contacts": [{"name": name, "phones": [phone], "emails": [email] if email else [],
                                                 "org": ""}]}
    text = f"👤 Contacto: {name}"
    first, _, last = name.partition(" ")

    def send() -> str:
        if conv["channel"] == "whatsapp":
            card = {"name": {"formatted_name": name, "first_name": first, **({"last_name": last} if last else {})},
                    "phones": [{"phone": phone, "type": "CELL"}]}
            if email:
                card["emails"] = [{"email": email, "type": "WORK"}]
            return _whatsapp_message(integ, idents[0], "contacts", [card])
        if conv["channel"] == "telegram":
            body = {"chat_id": int(_telegram_handle(idents)[4:]), "phone_number": phone, "first_name": first}
            if last:
                body["last_name"] = last
            return _telegram_call(integ, "sendContact", body)
        return _email_in_thread(integ, conv, idents,
                                "\n".join(filter(None, [text, f"Teléfono: {phone}", f"Email: {email}" if email else ""])))

    return deliver(integ, conversation_id, user, text, send, payload=payload)


def send_voice(conversation_id: int, user: dict, data: bytes, mime: str | None, seconds: int) -> dict:
    """Envía una nota de voz grabada en la app (WhatsApp y Telegram la muestran como nota de voz; en el correo va
    adjunta). Queda en la ficha del cliente, junto al mensaje."""
    integ, conv, idents = reply_target(conversation_id, user)
    audio, mime = voice.for_sending(data, mime)
    attachment = {"filename": f"nota-de-voz-{datetime.now():%Y%m%d-%H%M%S}.{'ogg' if mime == 'audio/ogg' else 'm4a'}",
                  "mime": mime, "data": audio}
    text = voice_text(seconds)

    def send() -> str:
        if conv["channel"] == "whatsapp":
            return send_whatsapp_file(integ, idents[0], attachment, "")
        if conv["channel"] == "telegram":
            method, field = ("sendVoice", "voice") if mime == "audio/ogg" else ("sendAudio", "audio")
            return _telegram_call(integ, method, form={"chat_id": _telegram_handle(idents)[4:], "duration": str(seconds),
                                                       field: (attachment["filename"], mime, audio)})
        return _email_in_thread(integ, conv, idents, text, attachment)

    result = deliver(integ, conversation_id, user, text, send, payload={"type": "voice", "seconds": seconds})
    with get_conn() as conn:
        attachments.save(conn, conv["client_id"], attachment["filename"], audio, mime, result["message_id"], user["id"])
    return result


# ---------------------------------------------------------------- Programador en segundo plano

def _due(integ_row: dict) -> bool:
    if not integ_row["last_sync_at"]:
        return True
    minutes = 1
    if integ_row["kind"] == "whatsapp":
        minutes = WHATSAPP_CHECK_MINUTES
    elif integ_row["kind"] == "email":
        try:
            minutes = max(1, int(secrets_store.decrypt(integ_row["config"]).get("sync_minutes") or 5))
        except Exception:  # noqa: BLE001
            minutes = 5
    last = datetime.fromisoformat(integ_row["last_sync_at"]).replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last >= timedelta(minutes=minutes)


def run_due_syncs() -> None:
    with get_conn() as conn:
        due = repo.list_syncable(conn)
    for integ_row in due:
        if _due(integ_row) and not _locks[integ_row["id"]].locked():
            try:
                sync(integ_row["id"])
            except Exception:  # noqa: BLE001 - el error queda guardado en la integración
                log.warning("Fallo al sincronizar la integración %s", integ_row["id"], exc_info=True)


def start_scheduler(interval_seconds: int = 30) -> None:
    def loop():
        while True:
            try:
                run_due_syncs()
            except Exception:  # noqa: BLE001
                log.exception("Error en el programador de integraciones")
            time.sleep(interval_seconds)
    threading.Thread(target=loop, daemon=True, name="integrations-sync").start()
