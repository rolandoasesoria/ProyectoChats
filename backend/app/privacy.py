"""Protección de datos en los mensajes: ocultar datos sensibles y borrar los mensajes antiguos.

- Datos sensibles: IBAN, DNI/NIE y números de tarjeta. Se detectan en los mensajes de un cliente y se sustituyen
  por una marca ("[IBAN oculto]"). El texto original no se guarda en ningún sitio (tampoco en el índice de búsqueda,
  que se recalcula solo). El CIF de una empresa no se considera dato personal y no se toca.
- Retención: si un administrador fija un plazo (meses), los mensajes más antiguos se borran, junto con sus adjuntos
  y las conversaciones que queden vacías. Se aplica al arrancar y una vez al día, junto con la regla que pasa a
  Inactivo a los clientes sin actividad (clients.mark_inactive).
"""
import logging
import re
import threading
import time

from . import attachments, clients, settings
from .db import get_conn
from .repositories import privacy as repo

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
        msgs = repo.client_messages(conn, client_id)
    result = []
    for m in msgs:
        found = find(m["body"])
        if found:
            result.append({**m, "found": [{"kind": k, "text": t} for k, t in found]})
    return result


def redact_message(message_id: int, only: str | None = None) -> dict | None:
    with get_conn() as conn:
        row = repo.message_with_client(conn, message_id)
        if not row:
            return None
        body, kinds = redact_text(row["body"], only)
        if kinds:
            repo.set_message_body(conn, message_id, body)
    return {"body": body, "hidden": kinds, "client_id": row["client_id"]}


# ---------------------------------------------------------------- Retención

def retention_preview(months: int) -> dict:
    with get_conn() as conn:
        n = repo.count_old_messages(conn, int(months))
    return {"months": months, "messages": n}


def apply_retention(months: int | None = None) -> dict:
    """Borra los mensajes de más de `months` meses (por defecto, el ajuste del equipo; 0 = no borrar nada)."""
    months = settings.get("retention_months") if months is None else months
    if not months:
        return {"months": 0, "messages": 0, "conversations": 0}
    with get_conn() as conn:
        # Primero los adjuntos de los mensajes antiguos (para borrar también sus archivos), luego los mensajes
        # y, al final, las conversaciones que se han quedado vacías.
        files = repo.old_attachment_paths(conn, int(months))
        repo.delete_old_attachments(conn, int(months))
        deleted = repo.delete_old_messages(conn, int(months))
        convs = repo.delete_empty_conversations(conn)
    for path in files:
        (attachments.STORAGE / path).unlink(missing_ok=True)
    return {"months": months, "messages": deleted, "conversations": convs}


def start_daily_jobs() -> None:
    """Al arrancar y luego una vez al día: retención de mensajes (si hay plazo) y clientes inactivos."""
    def loop():
        while True:
            try:
                result = apply_retention()
                if result["messages"]:
                    log.info("Retención: borrados %s mensajes de más de %s meses", result["messages"], result["months"])
                inactive = clients.mark_inactive(settings.get("inactive_days"))
                if inactive:
                    log.info("%s clientes pasan a Inactivo por falta de actividad", inactive)
            except Exception:  # noqa: BLE001 - un fallo no debe parar la app
                log.exception("Fallo en las tareas diarias")
            time.sleep(24 * 3600)
    threading.Thread(target=loop, daemon=True, name="tareas-diarias").start()
