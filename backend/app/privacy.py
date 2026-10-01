"""Protección de datos en los mensajes: ocultar datos sensibles y borrar los mensajes antiguos.

- Datos sensibles: IBAN, DNI/NIE y números de tarjeta. Se detectan en los mensajes de un cliente y se sustituyen
  por una marca ("[IBAN oculto]"). El texto original no se guarda en ningún sitio (tampoco en el índice de búsqueda,
  que se recalcula solo). El CIF de una empresa no se considera dato personal y no se toca.
- Retención: si un administrador fija un plazo (meses), los mensajes más antiguos se borran, junto con sus adjuntos
  y las conversaciones que queden vacías. Se aplica al arrancar y una vez al día.
"""
import logging
import re
import threading
import time

from . import attachments, settings
from .db import get_conn, rows

log = logging.getLogger(__name__)

PATTERNS = {
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]{4}){3,7}(?:[ -]?[A-Z0-9]{1,3})?\b"),
    "DNI": re.compile(r"\b(?:\d{8}|[XYZ]\d{7})[ -]?[A-HJ-NP-TV-Z]\b"),
    "tarjeta": re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
}


def _luhn(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)][::-1]
    total = sum(d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(digits))
    return total % 10 == 0


def find(text: str) -> list[tuple[str, str]]:
    """[(tipo, texto encontrado)] en el orden en que aparecen."""
    found = []
    for kind, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            if kind == "tarjeta" and not _luhn(m.group()):
                continue  # teléfonos, referencias de pedido...: no son tarjetas
            if any(m.group() in f or f in m.group() for _, f in found):
                continue  # un IBAN contiene dígitos que también parecen tarjeta
            found.append((kind, m.group()))
    return sorted(found, key=lambda kf: text.index(kf[1]))


def redact_text(text: str, only: str | None = None) -> tuple[str, list[str]]:
    """Sustituye los datos sensibles (o solo el texto `only`) por una marca. Devuelve (texto, tipos ocultados)."""
    if only:
        return (text.replace(only, "[dato oculto]"), ["dato"]) if only in text else (text, [])
    kinds = []
    for kind, value in find(text):
        text = text.replace(value, f"[{kind} oculto]")
        kinds.append(kind)
    return text, kinds


def sensitive_messages(client_id: int) -> list[dict]:
    """Mensajes del cliente con datos sensibles, con lo que se ha encontrado en cada uno."""
    with get_conn() as conn:
        msgs = rows(conn.execute(
            """SELECT m.id, m.body, m.sent_at, m.sender, c.channel FROM messages m
                 JOIN conversations c ON c.id = m.conversation_id WHERE c.client_id = ? ORDER BY m.sent_at""",
            (client_id,)))
    result = []
    for m in msgs:
        found = find(m["body"])
        if found:
            result.append({**m, "found": [{"kind": k, "text": t} for k, t in found]})
    return result


def redact_message(message_id: int, only: str | None = None) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT m.body, c.client_id FROM messages m JOIN conversations c ON c.id = m.conversation_id
                WHERE m.id = ?""", (message_id,)).fetchone()
        if not row:
            return None
        body, kinds = redact_text(row["body"], only)
        if kinds:
            conn.execute("UPDATE messages SET body = ? WHERE id = ?", (body, message_id))
    return {"body": body, "hidden": kinds, "client_id": row["client_id"]}


# ---------------------------------------------------------------- Retención

def _old_messages_sql(months: int) -> str:
    return f"sent_at < localtimestamp - interval '{int(months)} months'"


def retention_preview(months: int) -> dict:
    with get_conn() as conn:
        n = conn.execute(f"SELECT count(*) FROM messages WHERE {_old_messages_sql(months)}").fetchone()[0]
    return {"months": months, "messages": n}


def apply_retention(months: int | None = None) -> dict:
    """Borra los mensajes de más de `months` meses (por defecto, el ajuste del equipo; 0 = no borrar nada)."""
    months = settings.get("retention_months") if months is None else months
    if not months:
        return {"months": 0, "messages": 0, "conversations": 0}
    with get_conn() as conn:
        old = f"SELECT id FROM messages WHERE {_old_messages_sql(months)}"
        files = [r["path"] for r in conn.execute(f"SELECT path FROM attachments WHERE message_id IN ({old})")]
        conn.execute(f"DELETE FROM attachments WHERE message_id IN ({old})")
        deleted = conn.execute(f"DELETE FROM messages WHERE {_old_messages_sql(months)}").rowcount
        convs = conn.execute(
            "DELETE FROM conversations c WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)"
        ).rowcount
    for path in files:
        (attachments.STORAGE / path).unlink(missing_ok=True)
    return {"months": months, "messages": deleted, "conversations": convs}


def start_retention_job() -> None:
    """Aplica la retención al arrancar y luego una vez al día (si hay un plazo fijado)."""
    def loop():
        while True:
            try:
                result = apply_retention()
                if result["messages"]:
                    log.info("Retención: borrados %s mensajes de más de %s meses", result["messages"], result["months"])
            except Exception:  # noqa: BLE001 - un fallo no debe parar la app
                log.exception("Fallo al aplicar la retención de mensajes")
            time.sleep(24 * 3600)
    threading.Thread(target=loop, daemon=True, name="retencion").start()
