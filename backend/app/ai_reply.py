"""IA que responde a los clientes por WhatsApp, con las instrucciones del negocio.

Cada minuto se buscan las conversaciones de WhatsApp cuyo último mensaje es del cliente y que la IA no ha tratado.
Solo entra si está activada, en el horario elegido, si nadie del equipo ha escrito en ese chat en las últimas
`inactivity_hours` horas (0 = siempre), si no se ha pausado en ese chat y dentro de las 24 h en las que WhatsApp
deja responder con texto libre. Con cada mensaje, Claude decide:

- responder: en modo supervisado deja una propuesta que una persona envía (tal cual o editada) o descarta; en modo
  automático la envía por la cuenta de quien lleva la conversación, marcada como de la IA.
- pasar a una persona (handoff): si el cliente lo pide, se queja, está molesto o pregunta algo que no está en las
  instrucciones; no responde y avisa al responsable.

Un mensaje del cliente se trata una sola vez y hay un máximo de respuestas de la IA por conversación y día.
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta

from . import agent, insights, integrations, notes
from .db import get_conn
from .errors import AppError, Forbidden, InvalidInput, NotFound
from .repositories import ai_replies as repo
from .repositories import analysis as analysis_repo
from .repositories import settings as settings_repo
from .repositories import users as users_repo

log = logging.getLogger(__name__)

MODES = ("supervised", "auto")
INACTIVITY_HOURS = (0, 24, 48, 72)
WINDOW_HOURS = 24                 # WhatsApp: texto libre solo hasta 24 h después del último mensaje del cliente
MAX_REPLIES_PER_DAY = 5           # por conversación: evita bucles con otro bot o un cliente insistente
SCAN_SECONDS = 60
MAX_INSTRUCTIONS = 8000
AI_SENDER = "IA"
DEFAULTS = {"enabled": False, "mode": "supervised", "instructions": "", "inactivity_hours": 0,
            "schedule": "always", "hours": "09:00-18:00", "days": [1, 2, 3, 4, 5]}
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["reply", "handoff"]},
        "message": {"type": "string", "description": "El mensaje para el cliente (vacío si action=handoff)."},
        "reason": {"type": "string", "description": "Por qué se pasa a una persona (vacío si action=reply)."},
    },
    "required": ["action", "message", "reason"],
    "additionalProperties": False,
}


class AIReplyError(AppError):
    """La IA no ha podido decidir qué responder."""


# ---------------------------------------------------------------- Configuración (Administración → IA)

def get_settings() -> dict:
    with get_conn() as conn:
        stored = settings_repo.all_values(conn)
    raw = stored.get("ai_reply")
    return {**DEFAULTS, **(json.loads(raw) if raw else {})}


def _parse_hours(hours: str) -> tuple[str, str]:
    try:
        start, end = (datetime.strptime(h.strip(), "%H:%M").strftime("%H:%M") for h in hours.split("-"))
    except ValueError:
        raise InvalidInput("El horario debe ser «HH:MM-HH:MM», p. ej. 09:00-18:00.")
    if start >= end:
        raise InvalidInput("En el horario, la hora de inicio debe ser anterior a la de fin.")
    return start, end


def update_settings(values: dict) -> dict:
    current = get_settings()
    new = {**current, **{k: v for k, v in values.items() if k in DEFAULTS and v is not None}}
    if new["mode"] not in MODES:
        raise InvalidInput("Modo no válido.")
    if new["inactivity_hours"] not in INACTIVITY_HOURS:
        raise InvalidInput("Las horas de inactividad deben ser 0, 24, 48 o 72.")
    if new["schedule"] not in ("always", "out_of_hours"):
        raise InvalidInput("Horario no válido.")
    new["hours"] = "-".join(_parse_hours(new["hours"]))
    new["days"] = sorted({int(d) for d in new["days"] if 1 <= int(d) <= 7})
    new["instructions"] = new["instructions"].strip()[:MAX_INSTRUCTIONS]
    if new["enabled"] and not new["instructions"]:
        raise InvalidInput("Escribe las instrucciones antes de activar la IA: es lo que sabrá de tu negocio.")
    with get_conn() as conn:
        settings_repo.put(conn, "ai_reply", json.dumps(new, ensure_ascii=False))
    return new


def in_schedule(cfg: dict, now: datetime) -> bool:
    """¿Puede responder ahora? «always» siempre; «out_of_hours» solo fuera del horario de oficina."""
    if cfg["schedule"] == "always":
        return True
    start, end = _parse_hours(cfg["hours"])
    office = now.isoweekday() in cfg["days"] and start <= now.strftime("%H:%M") < end
    return not office


# ---------------------------------------------------------------- Decidir con Claude

def _system(instructions: str) -> str:
    return (
        "Eres el asistente que atiende por WhatsApp a los clientes de esta empresa en nombre del equipo. Respondes al "
        "último mensaje del cliente teniendo en cuenta la conversación.\n\n"
        "Reglas:\n"
        "- Usa solo la información de las instrucciones del negocio y del contexto. No inventes precios, plazos, "
        "disponibilidad ni datos.\n"
        "- Pasa la conversación a una persona (action=handoff, sin mensaje) si el cliente pide hablar con alguien, se "
        "queja o está molesto, plantea algo delicado (pagos, reclamaciones, datos personales) o pregunta algo que las "
        "instrucciones no cubren. Explica el motivo en una frase en reason.\n"
        "- Mensajes breves y cercanos, como en WhatsApp, en el idioma del cliente. Sin firma.\n"
        "- No prometas acciones del equipo; como mucho, que un compañero le contestará.\n\n"
        f"Instrucciones del negocio:\n{instructions or '(sin instrucciones)'}"
    )


def decide(instructions: str, thread: list[dict], client_name: str, profile: dict | None = None) -> dict:
    """Qué haría la IA con el último mensaje del cliente: {"action", "message", "reason"}."""
    lines = [f"Fecha y hora: {datetime.now():%Y-%m-%d %H:%M}", f"Cliente: {client_name}"]
    if profile and profile.get("summary"):
        lines += ["Resumen del cliente:", profile["summary"]]
    if profile and profile.get("facts"):
        lines += ["Datos del cliente:", *[f"- {f['label']}: {f['value']}" for f in profile["facts"]]]
    lines += ["", "Conversación (la más reciente al final):", *[insights.message_line(m) for m in thread]]
    response = agent._create(
        system=_system(instructions),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        return {"action": "handoff", "message": "", "reason": "La IA no ha querido responder a este mensaje."}
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        decision = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIReplyError("La respuesta de la IA no tiene el formato esperado.") from exc
    if decision.get("action") == "reply" and not (decision.get("message") or "").strip():
        decision = {"action": "handoff", "message": "", "reason": "La IA no ha sabido qué responder."}
    return {"action": decision.get("action", "handoff"), "message": (decision.get("message") or "").strip(),
            "reason": (decision.get("reason") or "").strip()}


def test_reply(message: str, instructions: str | None = None) -> dict:
    """«Probar la IA»: qué respondería a este mensaje (no envía nada ni guarda nada)."""
    instructions = get_settings()["instructions"] if instructions is None else instructions
    thread = [{"direction": "in", "sender": "Cliente", "body": message.strip(),
               "sent_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}]
    return decide(instructions, thread, "Cliente de prueba")


# ---------------------------------------------------------------- El motor (cada minuto)

def _notify_people(conn, conversation_id: int, kind: str, text: str) -> None:
    """Avisa a quien lleva la conversación y al responsable del cliente."""
    conv = repo.conversation(conn, conversation_id)
    people = {conv["owner_user_id"], *([conv["assignee_user_id"]] if conv["assignee_user_id"] else [])}
    notes.notify(conn, sorted(people), kind, text, conv["client_id"], None)


def _send(conversation_id: int, owner_id: int, text: str) -> dict:
    """Envía por la cuenta de WhatsApp de quien lleva la conversación, marcado como mensaje de la IA."""
    with get_conn() as conn:
        owner = users_repo.get(conn, owner_id)
    integ, _, idents = integrations.reply_target(conversation_id, owner)
    return integrations.deliver(integ, conversation_id, {"name": AI_SENDER}, text,
                                lambda: integrations.send_whatsapp(integ, idents[0], text), by_ai=True)


def handle(candidate: dict, cfg: dict) -> str:
    """Trata un mensaje del cliente. Devuelve lo que se ha hecho: pending, sent, handoff o failed."""
    conv_id, message_id = candidate["conversation_id"], candidate["message_id"]
    with get_conn() as conn:
        conversation = analysis_repo.conversation(conn, conv_id)
        thread = analysis_repo.conversation_thread(conn, conv_id)
    try:
        decision = decide(cfg["instructions"], thread, conversation["client"], insights.profile(candidate["client_id"]))
    except Exception as exc:  # noqa: BLE001 - sin IA no se responde, pero el resto sigue funcionando
        log.warning("La IA no ha podido decidir en la conversación %s: %s", conv_id, exc)
        with get_conn() as conn:
            repo.insert(conn, conv_id, message_id, "failed", reason=str(exc)[:500])
        return "failed"
    who = conversation["client"]
    if decision["action"] == "handoff":
        with get_conn() as conn:
            if repo.insert(conn, conv_id, message_id, "handoff", reason=decision["reason"]) is not None:
                _notify_people(conn, conv_id, "ai_handoff",
                               f"La IA no ha respondido a {who}: {decision['reason'] or 'necesita a una persona'}")
        return "handoff"
    if cfg["mode"] == "supervised":
        with get_conn() as conn:
            reply_id = repo.insert(conn, conv_id, message_id, "pending", text=decision["message"])
            if reply_id is not None:
                repo.discard_stale(conn, conv_id, reply_id)
                _notify_people(conn, conv_id, "ai_suggestion", f"La IA propone una respuesta para {who}: revísala en Chats")
        return "pending"
    with get_conn() as conn:
        reply_id = repo.insert(conn, conv_id, message_id, "sent", text=decision["message"])
    if reply_id is None:
        return "sent"  # ya lo había tratado otro proceso
    try:
        _send(conv_id, candidate["owner_user_id"], decision["message"])
    except Exception as exc:  # noqa: BLE001 - la cuenta puede estar desconectada o caducada
        with get_conn() as conn:
            repo.set_status(conn, reply_id, "failed")
            _notify_people(conn, conv_id, "ai_handoff", f"La IA no ha podido enviar su respuesta a {who}: {exc}")
        return "failed"
    return "sent"


def run_once(now: datetime | None = None) -> dict[str, int]:
    """Una pasada del motor. Devuelve cuántos mensajes ha tratado de cada forma."""
    cfg = get_settings()
    now = now or datetime.now()
    done: dict[str, int] = {}
    if not cfg["enabled"] or not cfg["instructions"] or not agent.credentials_configured() or not in_schedule(cfg, now):
        return done
    fmt = "%Y-%m-%dT%H:%M:%S"
    window_from = (now - timedelta(hours=WINDOW_HOURS)).strftime(fmt)
    human_from = (now - timedelta(hours=cfg["inactivity_hours"])).strftime(fmt) if cfg["inactivity_hours"] else None
    with get_conn() as conn:
        found = repo.candidates(conn, window_from, human_from, (now - timedelta(days=1)).strftime(fmt),
                                MAX_REPLIES_PER_DAY)
    for candidate in found:
        result = handle(candidate, cfg)
        done[result] = done.get(result, 0) + 1
    return done


def start_scheduler() -> None:
    def loop():
        while True:
            try:
                run_once()
            except Exception:  # noqa: BLE001
                log.exception("Error en la IA que responde")
            time.sleep(SCAN_SECONDS)
    threading.Thread(target=loop, daemon=True, name="ai-reply").start()


# ---------------------------------------------------------------- En el chat: estado, pausar, enviar y descartar

def _own_conversation(conn, conversation_id: int, user: dict) -> dict:
    conv = repo.conversation(conn, conversation_id)
    if not conv:
        raise NotFound("Conversación no encontrada.")
    if conv["owner_user_id"] != user["id"] and user["role"] != "admin":
        raise Forbidden("Solo quien lleva la conversación (o un administrador) decide sobre la IA en ella.")
    return conv


def conversation_state(conversation_id: int, user: dict) -> dict:
    cfg = get_settings()
    with get_conn() as conn:
        conv = _own_conversation(conn, conversation_id, user)
        pending = repo.pending_for(conn, conversation_id)
        paused = repo.is_paused(conn, conversation_id)
    return {"available": conv["channel"] == "whatsapp", "enabled": cfg["enabled"], "mode": cfg["mode"],
            "paused": paused, "pending": {"id": pending["id"], "text": pending["text"]} if pending else None}


def set_paused(conversation_id: int, paused: bool, user: dict) -> dict:
    with get_conn() as conn:
        _own_conversation(conn, conversation_id, user)
        repo.set_paused(conn, conversation_id, paused, user["id"])
    return conversation_state(conversation_id, user)


def send_suggestion(reply_id: int, user: dict, text: str | None = None) -> dict:
    """Envía la propuesta (tal cual o editada) por la cuenta de quien la aprueba."""
    with get_conn() as conn:
        reply = repo.get(conn, reply_id)
        if not reply:
            raise NotFound("Propuesta no encontrada.")
        _own_conversation(conn, reply["conversation_id"], user)
    text = (text or reply["text"]).strip()
    if not text:
        raise InvalidInput("El mensaje está vacío.")
    with get_conn() as conn:
        if not repo.lock_pending(conn, reply_id):
            raise InvalidInput("Esta propuesta ya se ha enviado o descartado.")
        integ, _, idents = integrations.reply_target(reply["conversation_id"], user)
        result = integrations.deliver(integ, reply["conversation_id"], user, text,
                                      lambda: integrations.send_whatsapp(integ, idents[0], text), by_ai=True)
        repo.set_status(conn, reply_id, "sent", user["id"], text)
    return result


def discard_suggestion(reply_id: int, user: dict) -> None:
    with get_conn() as conn:
        reply = repo.get(conn, reply_id)
        if not reply:
            raise NotFound("Propuesta no encontrada.")
        _own_conversation(conn, reply["conversation_id"], user)
        if not repo.lock_pending(conn, reply_id):
            raise InvalidInput("Esta propuesta ya se ha enviado o descartado.")
        repo.set_status(conn, reply_id, "discarded", user["id"])
