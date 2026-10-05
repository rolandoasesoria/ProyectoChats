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

from . import clients, emails, insights, notes, search, secrets_store, settings
from .config import config
from .db import get_conn
from .errors import ExternalServiceError, InvalidInput, NotFound
from .repositories import integrations as repo
from .repositories import users as users_repo

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

def http_request(method: str, url: str, *, body: dict | None = None, headers: dict | None = None,
                 raw: bool = False, timeout: int = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
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
    return found


def find_whatsapp(phone_number_id: str) -> dict | None:
    """Integración de WhatsApp de ese número (las credenciales van cifradas, así que se buscan descifrándolas)."""
    return next((i for i in _whatsapp_integrations() if i["config"].get("phone_number_id") == phone_number_id), None)


def _whatsapp_integrations() -> list[dict]:
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


def _flag_problem(integ: dict, problem: str) -> None:
    """Deja la cuenta marcada con el problema (se ve en «Mis cuentas») y, si es nuevo, avisa a su dueño en la
    campana: una sola vez, no en cada intento fallido."""
    with get_conn() as conn:
        previous = repo.lock_last_error(conn, integ["id"])
        repo.set_last_error(conn, integ["id"], problem)
        if previous != problem:
            notes.notify(conn, [integ["owner_user_id"]], "integration_error",
                         f"Tu cuenta «{integ['name']}» necesita atención: {problem}", None, None)


# ---------------------------------------------------------------- Guardar mensajes recibidos o enviados

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _existing_handle(channel: str, handle: str) -> str:
    """Para WhatsApp, reutiliza el identificador ya guardado aunque esté escrito distinto (+34 600 11 12 22)."""
    if channel != "whatsapp":
        return handle
    tail = _digits(handle)[-9:]
    with get_conn() as conn:
        known = repo.phone_handles(conn)
    for existing in known:
        if tail and _digits(existing)[-9:] == tail:
            return existing
    return handle


def ingest(integ: dict, *, handle: str, client_name: str, direction: str, sender: str, body: str,
           sent_at: str, external_id: str | None, subject: str | None = None,
           attachments: list | None = None) -> dict:
    return _store(integ, handle, client_name, [{"direction": direction, "sender": sender, "body": body,
                                                "sent_at": sent_at, "external_id": external_id,
                                                "attachments": attachments or []}], subject)


def _store(integ: dict, handle: str, client_name: str, messages: list[dict], subject: str | None = None,
           analyze: bool = True) -> dict:
    """Guarda mensajes de una conversación como de la persona dueña de la integración. analyze=False para lo antiguo
    (historial importado): ni reactiva al cliente ni lanza el análisis con IA."""
    channel = KIND_CHANNEL[integ["kind"]]
    result = search.import_conversation({
        "owner_user_id": integ["owner_user_id"], "channel": channel,
        "handle": _existing_handle(channel, handle), "client_name": client_name, "subject": subject,
        "messages": messages,
    })
    # Mensaje nuevo del cliente: la IA pone al día ficha, tareas, prioridad y estado (unos minutos después).
    if analyze and result["messages"] and any(m["direction"] == "in" for m in messages):
        clients.reactivate(result["client_id"], settings.get("inactive_days"))
        insights.schedule_analysis(result["client_id"])
    return result


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- Email (IMAP / SMTP)

def _imap_date(d: date) -> str:
    return f"{d.day:02d}-{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.month - 1]}-{d.year}"


def sync_email(integ: dict) -> int:
    cfg, state = integ["config"], integ["state"]
    address = cfg["address"].lower()
    imported = 0
    imap = IMAP_CLASS(cfg["imap_host"], int(cfg["imap_port"]))
    try:
        imap.login(cfg.get("username") or cfg["address"], cfg["password"])
        for folder, direction in (("INBOX", "in"), (cfg.get("sent_folder") or "Sent", "out")):
            status, _ = imap.select(f'"{folder}"', readonly=True)
            if status != "OK":
                continue  # p. ej. la carpeta de enviados tiene otro nombre en este servidor
            last = int(state.get(folder, 0))
            if last:
                status, data = imap.uid("SEARCH", None, f"UID {last + 1}:*")
            else:
                since = date.today() - timedelta(days=int(cfg.get("first_sync_days") or 30))
                status, data = imap.uid("SEARCH", None, f"SINCE {_imap_date(since)}")
            uids = [int(u) for u in (data[0] or b"").split() if int(u) > last]
            for uid in sorted(uids):
                status, parts = imap.uid("FETCH", str(uid), "(RFC822)")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                state[folder] = uid
                if not raw:
                    continue
                msg = emails.parse_message(email.message_from_bytes(raw, policy=default_policy))
                if not msg or msg["bulk"]:
                    continue  # boletines, notificaciones automáticas...
                if direction == "in":
                    if msg["key"] == address:
                        continue
                    handle, client_name = msg["key"], msg["name"]
                else:
                    others = [r for r in msg["recipients"] if r != address]
                    if not others:
                        continue
                    handle, client_name = others[0], others[0]
                res = ingest(integ, handle=handle, client_name=client_name, direction=direction,
                             sender=msg["name"], body=msg["body"], sent_at=msg["sent_at"],
                             external_id=msg["external_id"], subject=msg["subject"],
                             attachments=msg["attachments"])
                imported += res["messages"]
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    _save_state(integ["id"], state)
    return imported


def send_email(integ: dict, to: str, text: str, subject: str | None, in_reply_to: str | None) -> str:
    cfg = integ["config"]
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("display_name") or "", cfg["address"]))
    msg["To"] = to
    msg["Subject"] = f"Re: {subject}" if subject and subject != "(sin asunto)" else (subject or "")
    msg["Message-ID"] = make_msgid(domain=cfg["address"].split("@")[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(text)
    port = int(cfg["smtp_port"])
    server = SMTP_SSL_CLASS(cfg["smtp_host"], port, timeout=30) if port == 465 else SMTP_CLASS(cfg["smtp_host"], port, timeout=30)
    try:
        if port != 465:
            server.starttls()
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
        body = m.get("text") or m.get("caption") or ("📎 " + ", ".join(f["filename"] for f in files) if files else "")
        if not body:
            continue
        sent = datetime.fromtimestamp(m["date"], tz=timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        res = ingest(integ, handle=f"user{m['chat']['id']}", client_name=name, direction="in", sender=name,
                     body=body, sent_at=sent, external_id=f"tg:{m['chat']['id']}:{m['message_id']}", attachments=files)
        imported += res["messages"]
    _save_state(integ["id"], state)
    return imported


def send_telegram(integ: dict, handle: str, text: str) -> str:
    if not handle.startswith("user") or not handle[4:].isdigit():
        raise IntegrationError("Este cliente no ha escrito al bot: Telegram solo deja responder a quien escribió antes al bot.")
    resp = http_request("POST", f"{TELEGRAM_API}/bot{integ['config']['bot_token']}/sendMessage",
                        body={"chat_id": int(handle[4:]), "text": text})
    return f"tg:{handle[4:]}:{resp['result']['message_id']}"


# ---------------------------------------------------------------- WhatsApp Business (Cloud API)

def verify_whatsapp_signature(integ: dict, raw_body: bytes, signature: str | None) -> bool:
    expected = "sha256=" + hmac.new(integ["config"]["app_secret"].encode(), raw_body, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)


META_TOKEN_REJECTED = ("Meta no acepta el access token: ha caducado o se ha revocado. Si usaste el temporal de "
                       "«API Setup» (dura 24 h), crea uno permanente con un usuario del sistema y pégalo en «Editar».")


def _explain_meta(exc: IntegrationError, phone_lookup: bool = False) -> IntegrationError:
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
    else:
        return IntegrationError(f"Meta ha respondido con un error: {message or exc}", status=exc.status, error=exc.error)
    return IntegrationError(problem, status=exc.status, error=exc.error, needs_attention=True)


def check_whatsapp(integ: dict) -> str:
    """Pregunta a Meta por el número con estas credenciales. Comprueba a la vez el access token, el Phone number ID y
    el app secret (va como appsecret_proof, que Meta valida). Devuelve el número y su nombre verificado."""
    cfg = integ["config"]
    proof = hmac.new(cfg["app_secret"].encode(), cfg["access_token"].encode(), hashlib.sha256).hexdigest()
    query = urllib.parse.urlencode({"fields": "display_phone_number,verified_name", "appsecret_proof": proof})
    info = http_request("GET", f"{GRAPH_API}/{urllib.parse.quote(cfg['phone_number_id'], safe='')}?{query}",
                        headers={"Authorization": f"Bearer {cfg['access_token']}"}, timeout=15) or {}
    return " · ".join(filter(None, [info.get("display_phone_number"), info.get("verified_name")]))


def _whatsapp_media(integ: dict, media_id: str, filename: str, mime: str | None) -> dict | None:
    auth = {"Authorization": f"Bearer {integ['config']['access_token']}"}
    info = http_request("GET", f"{GRAPH_API}/{media_id}", headers=auth)
    if not info or not info.get("url"):
        return None
    return {"filename": filename, "mime": mime or info.get("mime_type"),
            "data": http_request("GET", info["url"], headers=auth, raw=True)}


def _download_whatsapp_media(integ: dict, media_id: str, filename: str, mime: str | None) -> dict | None:
    """Adjunto de un mensaje recibido, o None si no se puede descargar. El mensaje se guarda igualmente; si es por las
    credenciales, la cuenta queda marcada y se avisa a su dueño."""
    try:
        return _whatsapp_media(integ, media_id, filename, mime)
    except IntegrationError as exc:
        error = _explain_meta(exc)
        log.warning("No se pudo descargar un adjunto de WhatsApp (integración %s): %s", integ["id"], error)
        if error.needs_attention:
            _flag_problem(integ, str(error))
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
        imported += ingest(integ, handle=f"+{wa_id}", client_name=name, direction="in", sender=name, body=body,
                           sent_at=_wa_time(m), external_id=f"wa:{m['id']}", attachments=files)["messages"]
    return imported


def _wa_echoes(integ: dict, value: dict) -> int:
    """Coexistencia: lo que la persona envía desde la app WhatsApp Business del móvil o del ordenador."""
    sender = _owner_name(integ)
    imported = 0
    for m in value.get("message_echoes", []):
        to = m.get("to", "")
        body, files = _wa_content(integ, m)
        imported += ingest(integ, handle=f"+{to}", client_name=f"+{to}", direction="out", sender=sender, body=body,
                           sent_at=_wa_time(m), external_id=f"wa:{m['id']}", attachments=files)["messages"]
    return imported


def _wa_history(integ: dict, value: dict) -> int:
    """Coexistencia: historial de hasta 6 meses que comparte la app del móvil al conectarla, por tandas."""
    business = _digits(value.get("metadata", {}).get("display_phone_number", ""))
    sender = _owner_name(integ)
    imported = 0
    for chunk in value.get("history", []):
        if chunk.get("errors"):
            set_state_fields(integ["id"], history="rechazado en el móvil")
            continue
        for thread in chunk.get("threads", []):
            customer = _digits(thread.get("id", ""))
            messages = []
            for m in thread.get("messages", []):
                outgoing = _digits(m.get("from", "")) == business if business else _digits(m.get("from", "")) != customer
                body, _ = _wa_content(integ, m, download=False)
                messages.append({"direction": "out" if outgoing else "in", "sender": sender if outgoing else f"+{customer}",
                                 "body": body, "sent_at": _wa_time(m), "external_id": f"wa:{m['id']}",
                                 "attachments": []})
            if customer and messages:
                imported += _store(integ, f"+{customer}", f"+{customer}", messages, analyze=False)["messages"]
        progress = chunk.get("metadata", {}).get("progress")
        if progress is not None:
            set_state_fields(integ["id"], history="importado" if int(progress) >= 100 else f"importando ({progress} %)")
    return imported


def _wa_contacts(integ: dict, value: dict) -> int:
    """Coexistencia: contactos de la agenda del móvil. Solo ponen nombre a clientes que solo tenían su número (no se
    crean clientes nuevos por cada contacto de la agenda)."""
    named = 0
    for item in value.get("state_sync", []):
        contact = item.get("contact") or {}
        phone = _digits(contact.get("phone_number", ""))
        name = (contact.get("full_name") or contact.get("first_name") or "").strip()
        if item.get("type") == "contact" and item.get("action") != "remove" and phone and name:
            named += clients.name_from_contact("whatsapp", _existing_handle("whatsapp", f"+{phone}"), name)
    return named


WHATSAPP_DISCONNECTED = ("Este WhatsApp Business se ha desconectado de ProyectoChats (desde la app del móvil o desde "
                         "Meta). Para volver a recibir sus mensajes, conéctalo de nuevo en «Mis cuentas».")


def _wa_account_update(integ: dict, value: dict) -> int:
    """La empresa ha desconectado el número (p. ej. desde la app WhatsApp Business): se pausa y se avisa."""
    if value.get("event") == "PARTNER_REMOVED":
        update(integ["id"], None, None, False, None)
        _flag_problem(integ, WHATSAPP_DISCONNECTED)
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
    integrations = _whatsapp_integrations()
    by_number = {i["config"].get("phone_number_id"): i for i in integrations}
    by_account = {i["config"].get("waba_id"): i for i in integrations if i["config"].get("waba_id")}
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


def send_whatsapp(integ: dict, handle: str, text: str) -> str:
    to = _digits(handle)
    if len(to) < 8:
        raise IntegrationError("El teléfono de WhatsApp del cliente no es válido.")
    cfg = integ["config"]
    resp = http_request("POST", f"{GRAPH_API}/{cfg['phone_number_id']}/messages",
                        headers={"Authorization": f"Bearer {cfg['access_token']}"},
                        body={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}})
    return f"wa:{resp['messages'][0]['id']}"


# ---------------------------------------------------------------- Sincronización y envío

def _explain(kind: str, exc: Exception, phone_lookup: bool = False) -> IntegrationError:
    """Convierte un fallo técnico en un mensaje claro. needs_attention marca los que tiene que arreglar la persona
    (credenciales rechazadas); los demás (red, servidor caído) suelen arreglarse solos en el siguiente intento."""
    if kind == "whatsapp" and isinstance(exc, IntegrationError):
        return _explain_meta(exc, phone_lookup)
    if kind == "telegram" and isinstance(exc, IntegrationError) and exc.status in (401, 404):
        return IntegrationError("Telegram no acepta el token del bot: se ha regenerado o el bot ya no existe. Copia el "
                                "token actual de @BotFather y pégalo en «Editar».", status=exc.status,
                                needs_attention=True)
    if kind == "email" and isinstance(exc, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)) \
            and re.search(r"auth|login|credential|password", str(exc), re.IGNORECASE):
        return IntegrationError("El servidor de correo no acepta el usuario o la contraseña. Si has cambiado la "
                                "contraseña de tu cuenta (Google anula entonces las contraseñas de aplicación) o la "
                                "has revocado, crea una nueva y pégala en «Editar».", needs_attention=True)
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
                _flag_problem(integ, str(error)[:500])
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


def send_reply(conversation_id: int, user: dict, text: str) -> dict:
    integ = sender_for(conversation_id, user)
    if not integ:
        raise InvalidInput("No tienes una integración activa de este canal para enviar mensajes.")
    with get_conn() as conn:
        conv = repo.conversation(conn, conversation_id)
        idents = repo.client_handles(conn, conv["client_id"], conv["channel"])
        in_reply_to = repo.last_incoming_external_id(conn, conversation_id)
    if not idents:
        raise InvalidInput("El cliente no tiene identificador en este canal.")
    try:
        if conv["channel"] == "email":
            ext = send_email(integ, idents[0], text, conv["subject"], in_reply_to)
        elif conv["channel"] == "telegram":
            handle = next((h for h in idents if h.startswith("user")), idents[0])
            ext = send_telegram(integ, handle, text)
        else:
            ext = send_whatsapp(integ, idents[0], text)
    except (IntegrationError, OSError, smtplib.SMTPException) as exc:
        error = _explain(integ["kind"], exc)
        if error.needs_attention:
            _flag_problem(integ, str(error))
        raise ExternalServiceError(f"No se pudo enviar: {error}")
    # El mensaje enviado se guarda en la conversación (como enviado por quien lo escribió).
    with get_conn() as conn:
        message_id = repo.insert_sent_message(conn, conversation_id, user["name"], text, _now_local(), ext)
    return {"message_id": message_id, "via": integ["name"]}


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
