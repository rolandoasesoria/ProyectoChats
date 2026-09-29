"""Lectura de exportaciones de chats y correos.

Formatos admitidos:
- WhatsApp: el .txt de "Exportar chat" (formatos de Android e iPhone).
- Telegram: el result.json de Telegram Desktop ("Exportar historial del chat" en formato JSON).
- WhatsApp "con archivos": el .zip tal cual; las fotos y documentos quedan enlazados a su mensaje.
- Email: archivos .eml (un correo) y .mbox (buzón completo; Gmail/Google Takeout, Thunderbird), con sus adjuntos.

`parse()` devuelve los mensajes y los participantes detectados. Después, `build_conversations()`
se queda con los mensajes del participante elegido como cliente y les pone la dirección
(in = lo escribió el cliente, out = lo escribió alguien del equipo).
"""
import email
import html
import io
import json
import mailbox
import os
import re
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from email.policy import default as default_policy
from email.utils import getaddresses, parsedate_to_datetime

from fastapi import HTTPException

MAX_BYTES = 25 * 1024 * 1024
MAX_ZIP_BYTES = 50 * 1024 * 1024  # un .zip de WhatsApp con fotos pesa más


class ImportFormatError(HTTPException):
    def __init__(self, message: str):
        super().__init__(400, message)


def _iso(dt: datetime) -> str:
    """Fecha en hora local sin zona, como el resto de mensajes guardados."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- WhatsApp

_WA_DATE = r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([ap]\.?\s?m\.?)?"
_WA_IOS = re.compile(r"^\[" + _WA_DATE + r"\]\s(.+?):\s(.*)$", re.IGNORECASE)
_WA_ANDROID = re.compile(r"^" + _WA_DATE + r"\s[-–]\s(.+?):\s(.*)$", re.IGNORECASE)
_WA_SYSTEM = re.compile(r"^\[?" + _WA_DATE + r"\]?\s*[-–]?\s", re.IGNORECASE)


def _wa_datetime(d, mo, y, h, mi, s, ampm) -> datetime:
    year = int(y) + 2000 if len(y) == 2 else int(y)
    hour = int(h)
    if ampm:
        pm = ampm.lower().startswith("p")
        hour = hour % 12 + (12 if pm else 0)
    # Las exportaciones en español usan día/mes. Si el "mes" pasa de 12, el formato es mes/día.
    day, month = int(d), int(mo)
    if month > 12:
        day, month = month, day
    return datetime(year, month, day, hour, int(mi), int(s or 0))


def _parse_whatsapp(text: str) -> list[dict]:
    messages: list[dict] = []
    for raw in text.splitlines():
        line = raw.replace("‎", "").replace("‏", "").replace(" ", " ").replace("\xa0", " ")
        m = _WA_IOS.match(line) or _WA_ANDROID.match(line)
        if m:
            *date_parts, sender, body = m.groups()
            messages.append({
                "key": sender.strip(), "name": sender.strip(), "recipients": [],
                "body": body.strip(), "sent_at": _iso(_wa_datetime(*date_parts)), "subject": None,
                "attachments": [],
            })
        elif _WA_SYSTEM.match(line):
            continue  # aviso del sistema ("Los mensajes están cifrados...", "X añadió a Y")
        elif messages and line.strip():
            messages[-1]["body"] += "\n" + line.rstrip()  # continuación de un mensaje de varias líneas
    return messages


# ---------------------------------------------------------------- Telegram

def _telegram_text(value) -> str:
    if isinstance(value, str):
        return value
    return "".join(part if isinstance(part, str) else part.get("text", "") for part in value or [])


def _parse_telegram(data: dict) -> list[dict]:
    messages = []
    for m in data.get("messages", []):
        if m.get("type") != "message":
            continue
        body = _telegram_text(m.get("text")).strip()
        if not body:
            body = f"[{m.get('media_type') or 'archivo adjunto'}]" if (m.get("media_type") or m.get("file")) else ""
        if not body:
            continue
        name = m.get("from") or "Desconocido"
        messages.append({
            "key": m.get("from_id") or name, "name": name, "recipients": [],
            "body": body, "sent_at": _iso(datetime.fromisoformat(m["date"])), "subject": None,
            "attachments": [],
        })
    return messages


# ---------------------------------------------------------------- Email

_RE_PREFIX = re.compile(r"^\s*((re|rv|fw|fwd|reenv)\s*:\s*)+", re.IGNORECASE)


def _email_body(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        content = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", content, flags=re.S | re.I)
        content = re.sub(r"<br\s*/?>|</p>|</div>", "\n", content, flags=re.I)
        content = html.unescape(re.sub(r"<[^>]+>", "", content))
        content = re.sub(r"[ \t]+", " ", content)
    # Quita el texto citado de correos anteriores ("> ..." y "El ... escribió:") para no duplicar.
    lines = []
    for line in content.splitlines():
        if line.startswith(">") or re.match(r"^(El|On) .{5,120} (escribió|wrote):\s*$", line.strip()):
            break
        lines.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _email_message(msg) -> dict | None:
    from_list = getaddresses([str(msg.get("from", ""))])
    if not from_list or not from_list[0][1]:
        return None
    name, addr = from_list[0]
    recipients = [a.lower() for _, a in getaddresses([str(msg.get(h, "")) for h in ("to", "cc")]) if a]
    try:
        sent = parsedate_to_datetime(str(msg.get("date")))
    except (TypeError, ValueError):
        sent = datetime.now(timezone.utc)
    body = _email_body(msg)
    files = []
    for part in msg.iter_attachments():
        data = part.get_payload(decode=True)
        if data:
            files.append({"filename": part.get_filename() or "adjunto", "mime": part.get_content_type(), "data": data})
    if not body and files:
        body = "📎 " + ", ".join(f["filename"] for f in files)
    if not body:
        return None
    subject = _RE_PREFIX.sub("", str(msg.get("subject") or "")).strip() or "(sin asunto)"
    return {"key": addr.lower(), "name": name or addr, "recipients": recipients,
            "body": body, "sent_at": _iso(sent), "subject": subject, "attachments": files,
            "external_id": str(msg.get("message-id") or "").strip() or None,
            "bulk": bool(msg.get("list-unsubscribe") or str(msg.get("precedence", "")).lower() in ("bulk", "list", "junk")
                         or str(msg.get("auto-submitted", "no")).lower() != "no")}


def _parse_eml(data: bytes) -> list[dict]:
    m = _email_message(email.message_from_bytes(data, policy=default_policy))
    return [m] if m else []


def _parse_mbox(data: bytes) -> list[dict]:
    # mailbox necesita un archivo en disco.
    fd, path = tempfile.mkstemp(suffix=".mbox")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        box = mailbox.mbox(path, factory=lambda f: email.message_from_binary_file(f, policy=default_policy),
                           create=False)
        result = [m for m in (_email_message(msg) for msg in box) if m]
        box.close()
        return result
    finally:
        os.unlink(path)


# Marcas de adjunto en el texto exportado por WhatsApp (español e inglés, Android e iPhone).
_WA_ATTACHED = re.compile(r"<(?:adjunto|attached):\s*([^>]+)>|(\S+\.\w{2,5})\s*\((?:archivo adjunto|file attached)\)",
                          re.IGNORECASE)


def _parse_whatsapp_zip(data: bytes) -> tuple[list[dict], str | None]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportFormatError("El .zip está dañado.")
    names = [n for n in zf.namelist() if not n.endswith("/")]
    chats = [n for n in names if n.lower().endswith(".txt")]
    if not chats:
        raise ImportFormatError("El .zip no contiene el chat (.txt). ¿Es una exportación de WhatsApp?")
    chat_name = next((n for n in chats if "chat" in n.lower()), chats[0])
    messages = _parse_whatsapp(zf.read(chat_name).decode("utf-8-sig", errors="replace"))
    media = {os.path.basename(n): n for n in names if n != chat_name}
    for m in messages:
        def attach(match):
            fname = (match.group(1) or match.group(2)).strip()
            if fname in media:
                m["attachments"].append({"filename": fname, "mime": None, "data": zf.read(media[fname])})
                return f"📎 {fname}"
            return match.group(0)
        m["body"] = _WA_ATTACHED.sub(attach, m["body"])
    title = re.search(r"(?:con|with)\s+(.+?)\.(?:zip|txt)$", chat_name, re.IGNORECASE)
    return messages, title.group(1) if title else None


# ---------------------------------------------------------------- API del módulo

def parse(filename: str, data: bytes) -> dict:
    name = filename.lower()
    if len(data) > (MAX_ZIP_BYTES if name.endswith(".zip") else MAX_BYTES):
        raise ImportFormatError("El archivo es demasiado grande (máximo 25 MB, o 50 MB si es un .zip de WhatsApp).")
    if name.endswith(".zip"):
        fmt, channel = "whatsapp", "whatsapp"
        messages, title = _parse_whatsapp_zip(data)
        m = re.search(r"(?:con|with)\s+(.+?)\.zip$", filename, re.IGNORECASE)
        title = (m.group(1) if m else None) or title
    elif name.endswith(".json"):
        try:
            parsed = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ImportFormatError("El JSON no es válido.")
        if not isinstance(parsed, dict) or "messages" not in parsed:
            raise ImportFormatError("No parece una exportación de Telegram (falta la lista de mensajes).")
        fmt, channel, messages, title = "telegram", "telegram", _parse_telegram(parsed), parsed.get("name")
    elif name.endswith(".eml"):
        fmt, channel, messages, title = "eml", "email", _parse_eml(data), None
    elif name.endswith(".mbox") or data.startswith(b"From "):
        fmt, channel, messages, title = "mbox", "email", _parse_mbox(data), None
    elif name.endswith(".txt"):
        fmt, channel = "whatsapp", "whatsapp"
        messages = _parse_whatsapp(data.decode("utf-8-sig", errors="replace"))
        # "Chat de WhatsApp con Laura Gómez.txt" / "WhatsApp Chat with Laura.txt"
        m = re.search(r"(?:con|with)\s+(.+?)\.txt$", filename, re.IGNORECASE)
        title = m.group(1) if m else None
    else:
        raise ImportFormatError("Formato no reconocido. Usa .txt o .zip (WhatsApp), .json (Telegram), .eml o .mbox.")
    if not messages:
        raise ImportFormatError("No se encontró ningún mensaje en el archivo. ¿Es la exportación correcta?")

    counts = Counter(m["key"] for m in messages)
    names = {m["key"]: m["name"] for m in messages}
    if channel == "email":  # en email también cuentan los destinatarios
        for m in messages:
            for r in m["recipients"]:
                counts[r] += 1
                names.setdefault(r, r)
    participants = [{"key": k, "name": names[k], "count": c} for k, c in counts.most_common()]
    dates = sorted(m["sent_at"] for m in messages)
    return {"format": fmt, "channel": channel, "title": title, "messages": messages,
            "participants": participants, "first": dates[0], "last": dates[-1]}


def build_conversations(parsed: dict, client_key: str) -> list[dict]:
    """Conversaciones a importar para el cliente elegido: una por chat, o una por asunto en email."""
    if client_key not in {p["key"] for p in parsed["participants"]}:
        raise ImportFormatError("El participante elegido no aparece en el archivo.")
    groups: dict[str | None, list[dict]] = {}
    for m in parsed["messages"]:
        if parsed["channel"] == "email" and client_key not in (m["key"], *m["recipients"]):
            continue  # correo en el que no participa este cliente
        groups.setdefault(m["subject"], []).append({
            "direction": "in" if m["key"] == client_key else "out",
            "sender": m["name"], "body": m["body"], "sent_at": m["sent_at"],
            "attachments": m.get("attachments", []), "external_id": m.get("external_id"),
        })
    return [{"subject": subject, "messages": sorted(msgs, key=lambda x: x["sent_at"])}
            for subject, msgs in groups.items()]
