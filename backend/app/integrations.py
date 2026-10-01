"""Conexión con los canales: buzón de email (IMAP/SMTP), bot de Telegram y WhatsApp Business (Cloud API).

- Recibir: email y Telegram se sincronizan cada pocos minutos en segundo plano; WhatsApp llega por webhook.
- Enviar: desde el borrador de respuesta, por la integración del canal de la conversación.
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

from fastapi import HTTPException

from . import clients, emails, insights, search, secrets_store, settings
from .db import get_conn, rows

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
        {"key": "phone_number_id", "label": "Phone number ID", "required": True},
        {"key": "access_token", "label": "Access token", "secret": True, "required": True},
        {"key": "app_secret", "label": "App secret (para verificar el webhook)", "secret": True, "required": True},
        {"key": "verify_token", "label": "Verify token del webhook (se genera solo si lo dejas vacío)"},
    ],
}
KIND_CHANNEL = {"email": "email", "telegram": "telegram", "whatsapp": "whatsapp"}
TELEGRAM_API = "https://api.telegram.org"
GRAPH_API = "https://graph.facebook.com/v21.0"
MAX_DOWNLOAD = 20 * 1024 * 1024

# Puntos de conexión sustituibles en las pruebas.
IMAP_CLASS = imaplib.IMAP4_SSL
SMTP_SSL_CLASS = smtplib.SMTP_SSL
SMTP_CLASS = smtplib.SMTP

_locks: defaultdict[int, threading.Lock] = defaultdict(threading.Lock)


class IntegrationError(Exception):
    pass


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
        detail = e.read()[:500].decode(errors="replace")
        raise IntegrationError(f"El servicio respondió {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise IntegrationError(f"No se pudo conectar: {e.reason}") from e
    if len(content) > MAX_DOWNLOAD:
        raise IntegrationError("Archivo demasiado grande.")
    return content if raw else json.loads(content or b"null")


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
            raise HTTPException(400, f"Falta «{f['label']}».")
        cfg[f["key"]] = value
    if kind == "whatsapp" and not cfg.get("verify_token"):
        cfg["verify_token"] = secrets.token_urlsafe(24)
    if kind == "email":
        for k in ("imap_port", "smtp_port", "sync_minutes", "first_sync_days"):
            if not cfg[k].isdigit():
                raise HTTPException(400, f"«{next(f['label'] for f in FIELDS['email'] if f['key'] == k)}» debe ser un número.")
    return cfg


def list_integrations() -> list[dict]:
    with get_conn() as conn:
        found = rows(conn.execute(
            """SELECT i.id, i.kind, i.name, i.owner_user_id, u.name AS owner, i.config, i.enabled,
                      i.last_sync_at, i.last_error, i.created_at
                 FROM integrations i JOIN users u ON u.id = i.owner_user_id ORDER BY i.id"""))
    for i in found:
        i["config"] = _mask(i["kind"], secrets_store.decrypt(i["config"]))
    return found


def get(integration_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Integración no encontrada")
    data = dict(row)
    data["config"] = secrets_store.decrypt(data["config"])
    data["state"] = json.loads(data["state"])
    return data


def create(kind: str, name: str, owner_user_id: int, config: dict) -> int:
    cfg = _clean_config(kind, config)
    with get_conn() as conn:
        return conn.execute("INSERT INTO integrations (kind, name, owner_user_id, config) VALUES (?, ?, ?, ?) RETURNING id",
                            (kind, name.strip() or kind, owner_user_id, secrets_store.encrypt(cfg))).lastrowid


def update(integration_id: int, name: str | None, owner_user_id: int | None, enabled: bool | None,
           config: dict | None) -> None:
    current = get(integration_id)
    sets, args = [], []
    if name is not None:
        sets.append("name = ?")
        args.append(name.strip() or current["kind"])
    if owner_user_id is not None:
        sets.append("owner_user_id = ?")
        args.append(owner_user_id)
    if enabled is not None:
        sets.append("enabled = ?")
        args.append(int(enabled))
    if config is not None:
        sets.append("config = ?")
        args.append(secrets_store.encrypt(_clean_config(current["kind"], config, current["config"])))
    if sets:
        with get_conn() as conn:
            conn.execute(f"UPDATE integrations SET {', '.join(sets)} WHERE id = ?", [*args, integration_id])


def delete(integration_id: int) -> None:
    get(integration_id)
    with get_conn() as conn:
        conn.execute("DELETE FROM integrations WHERE id = ?", (integration_id,))


def _save_state(integration_id: int, state: dict, error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE integrations SET state = ?, last_sync_at = localtimestamp(0), last_error = ? WHERE id = ?",
                     (json.dumps(state), error, integration_id))


# ---------------------------------------------------------------- Guardar mensajes recibidos o enviados

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _existing_handle(channel: str, handle: str) -> str:
    """Para WhatsApp, reutiliza el identificador ya guardado aunque esté escrito distinto (+34 600 11 12 22)."""
    if channel != "whatsapp":
        return handle
    tail = _digits(handle)[-9:]
    with get_conn() as conn:
        for r in conn.execute("SELECT handle FROM client_identities WHERE channel IN ('whatsapp', 'phone')"):
            if tail and _digits(r["handle"])[-9:] == tail:
                return r["handle"]
    return handle


def ingest(integ: dict, *, handle: str, client_name: str, direction: str, sender: str, body: str,
           sent_at: str, external_id: str | None, subject: str | None = None,
           attachments: list | None = None) -> dict:
    channel = KIND_CHANNEL[integ["kind"]]
    result = search.import_conversation({
        "owner_user_id": integ["owner_user_id"], "channel": channel,
        "handle": _existing_handle(channel, handle), "client_name": client_name, "subject": subject,
        "messages": [{"direction": direction, "sender": sender, "body": body, "sent_at": sent_at,
                      "external_id": external_id, "attachments": attachments or []}],
    })
    # Mensaje nuevo del cliente: la IA pone al día ficha, tareas, prioridad y estado (unos minutos después).
    if result["messages"] and direction == "in":
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


def _whatsapp_media(integ: dict, media_id: str, filename: str, mime: str | None) -> dict | None:
    auth = {"Authorization": f"Bearer {integ['config']['access_token']}"}
    info = http_request("GET", f"{GRAPH_API}/{media_id}", headers=auth)
    if not info or not info.get("url"):
        return None
    return {"filename": filename, "mime": mime or info.get("mime_type"),
            "data": http_request("GET", info["url"], headers=auth, raw=True)}


def receive_whatsapp(integ: dict, payload: dict) -> int:
    imported = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                wa_id = m.get("from", "")
                name = names.get(wa_id) or f"+{wa_id}"
                kind = m.get("type")
                files, body = [], ""
                if kind == "text":
                    body = m["text"]["body"]
                elif kind in ("image", "document", "audio", "video"):
                    media = m[kind]
                    ext = {"image": "jpg", "audio": "ogg", "video": "mp4"}.get(kind, "bin")
                    fname = media.get("filename") or f"{kind}_{m['id'][-8:]}.{ext}"
                    f = _whatsapp_media(integ, media["id"], fname, media.get("mime_type"))
                    files += [f] if f else []
                    body = media.get("caption") or f"📎 {fname}"
                else:
                    body = f"[{kind}]"
                sent = datetime.fromtimestamp(int(m.get("timestamp", time.time())), tz=timezone.utc).astimezone()
                res = ingest(integ, handle=f"+{wa_id}", client_name=name, direction="in", sender=name, body=body,
                             sent_at=sent.strftime("%Y-%m-%dT%H:%M:%S"), external_id=f"wa:{m['id']}", attachments=files)
                imported += res["messages"]
    return imported


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

def sync(integration_id: int) -> dict:
    """Sincroniza una integración ahora (email y Telegram). Guarda el error si falla."""
    with _locks[integration_id]:
        integ = get(integration_id)
        try:
            if integ["kind"] == "email":
                n = sync_email(integ)
            elif integ["kind"] == "telegram":
                n = sync_telegram(integ)
            else:
                raise IntegrationError("WhatsApp no se sincroniza: los mensajes llegan solos por el webhook.")
        except (IntegrationError, OSError, imaplib.IMAP4.error, smtplib.SMTPException, KeyError, ValueError) as exc:
            _save_state(integration_id, integ["state"], error=str(exc)[:500])
            raise IntegrationError(str(exc)) from exc
        return {"imported": n}


def sender_for(conversation_id: int, user: dict) -> dict | None:
    """Integración con la que el usuario puede responder en esta conversación (o None)."""
    with get_conn() as conn:
        conv = conn.execute("SELECT channel, client_id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if not conv:
            return None
        found = conn.execute(
            """SELECT id FROM integrations WHERE kind = ? AND enabled = 1 AND (owner_user_id = ? OR ? = 'admin')
                ORDER BY owner_user_id = ? DESC, id LIMIT 1""",
            (conv["channel"], user["id"], user["role"], user["id"])).fetchone()
    return get(found["id"]) if found else None


def send_reply(conversation_id: int, user: dict, text: str) -> dict:
    integ = sender_for(conversation_id, user)
    if not integ:
        raise HTTPException(400, "No tienes una integración activa de este canal para enviar mensajes.")
    with get_conn() as conn:
        conv = conn.execute(
            "SELECT id, channel, subject, client_id, owner_user_id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        idents = [r["handle"] for r in conn.execute(
            "SELECT handle FROM client_identities WHERE client_id = ? AND channel = ? ORDER BY id",
            (conv["client_id"], conv["channel"]))]
        last_in = conn.execute(
            """SELECT external_id FROM messages WHERE conversation_id = ? AND direction = 'in'
                AND external_id IS NOT NULL ORDER BY sent_at DESC, id DESC LIMIT 1""", (conversation_id,)).fetchone()
    if not idents:
        raise HTTPException(400, "El cliente no tiene identificador en este canal.")
    try:
        if conv["channel"] == "email":
            ext = send_email(integ, idents[0], text, conv["subject"], last_in["external_id"] if last_in else None)
        elif conv["channel"] == "telegram":
            handle = next((h for h in idents if h.startswith("user")), idents[0])
            ext = send_telegram(integ, handle, text)
        else:
            ext = send_whatsapp(integ, idents[0], text)
    except (IntegrationError, OSError, smtplib.SMTPException) as exc:
        raise HTTPException(502, f"No se pudo enviar: {exc}")
    # El mensaje enviado se guarda en la conversación (como enviado por quien lo escribió).
    with get_conn() as conn:
        message_id = conn.execute(
            """INSERT INTO messages (conversation_id, direction, sender, body, sent_at, external_id)
               VALUES (?, 'out', ?, ?, ?, ?) RETURNING id""", (conversation_id, user["name"], text, _now_local(), ext)).lastrowid
    return {"message_id": message_id, "via": integ["name"]}


# ---------------------------------------------------------------- Programador en segundo plano

def _due(integ_row: dict) -> bool:
    if not integ_row["last_sync_at"]:
        return True
    minutes = 1
    if integ_row["kind"] == "email":
        try:
            minutes = max(1, int(secrets_store.decrypt(integ_row["config"]).get("sync_minutes") or 5))
        except Exception:  # noqa: BLE001
            minutes = 5
    last = datetime.fromisoformat(integ_row["last_sync_at"]).replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last >= timedelta(minutes=minutes)


def run_due_syncs() -> None:
    with get_conn() as conn:
        due = [dict(r) for r in conn.execute(
            "SELECT id, kind, config, last_sync_at FROM integrations WHERE enabled = 1 AND kind IN ('email', 'telegram')")]
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
