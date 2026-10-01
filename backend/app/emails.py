"""Lectura de correos (los que trae la integración de email por IMAP): remitente, cuerpo sin la cita del
correo anterior, asunto sin «Re:», adjuntos y si es un envío masivo (boletines, avisos automáticos)."""
import html
import re
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime


def _iso(dt: datetime) -> str:
    """Fecha en hora local sin zona, como el resto de mensajes guardados."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


_RE_PREFIX = re.compile(r"^\s*((re|rv|fw|fwd|reenv)\s*:\s*)+", re.IGNORECASE)


def _body(msg) -> str:
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


def parse_message(msg) -> dict | None:
    """Datos de un correo (email.message) para guardarlo: remitente, destinatarios, cuerpo, adjuntos..."""
    from_list = getaddresses([str(msg.get("from", ""))])
    if not from_list or not from_list[0][1]:
        return None
    name, addr = from_list[0]
    recipients = [a.lower() for _, a in getaddresses([str(msg.get(h, "")) for h in ("to", "cc")]) if a]
    try:
        sent = parsedate_to_datetime(str(msg.get("date")))
    except (TypeError, ValueError):
        sent = datetime.now(timezone.utc)
    body = _body(msg)
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
