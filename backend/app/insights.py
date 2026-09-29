"""Análisis de clientes con IA: datos clave (ficha), compromisos (tareas) y resumen del estado.

Una sola llamada a Claude por análisis, con salida estructurada (JSON validado por la API).
Lo que ha escrito o corregido una persona nunca se sobrescribe: se le pasa a la IA como ya confirmado.
"""
import json
import logging
import threading
from collections import defaultdict
from datetime import date

from . import agent, attachments
from .db import get_conn, rows

log = logging.getLogger(__name__)

MAX_MESSAGES = 1500        # mensajes más recientes que se analizan
MAX_MESSAGE_CHARS = 2000   # recorte por mensaje (firmas y textos pegados muy largos)

_locks: defaultdict[int, threading.Lock] = defaultdict(threading.Lock)

SYSTEM = """Analizas el historial de conversaciones (email, WhatsApp, Telegram...) entre un equipo \
y uno de sus clientes, para mantener su ficha al día. Devuelve:

1. summary: el estado actual de la relación en 2-4 frases (qué quiere el cliente, en qué punto está, \
qué queda pendiente). Concreto, sin relleno.
2. facts: datos útiles y estables del cliente: contacto (teléfonos, emails, direcciones de envío y \
facturación), datos fiscales (razón social, CIF/NIF), preferencias (horarios, forma de pago, canal preferido), \
condiciones acordadas (precios, descuentos, plazos), productos habituales. Una etiqueta corta en español \
("Dirección de envío", "CIF", "Forma de pago") y el valor exacto. Si un dato cambió, da solo el más reciente. \
message_id = id del mensaje donde aparece. No incluyas datos que ya estén en "Datos confirmados" ni los \
de "Datos descartados".
3. new_tasks: compromisos pendientes que requieren acción del equipo: lo que alguien del equipo prometió \
("te mando el presupuesto"), y seguimientos de lo que prometió el cliente ("confirmará en noviembre"). \
Título en imperativo y concreto ("Enviar presupuesto de 350 cajas a Laura"). due_date en formato AAAA-MM-DD \
si se deduce una fecha (interpreta "mañana", "el viernes"... respecto a la fecha del mensaje); si no, "". \
owner: nombre de la persona del equipo responsable si está claro; si no, "". \
No repitas tareas que ya estén en "Tareas existentes" (abiertas o hechas), aunque estén redactadas distinto. \
No crees tareas de cosas ya resueltas en la conversación.
4. completed_task_ids: ids de "Tareas existentes" abiertas que la conversación demuestra ya cumplidas.

Si no hay nada para un apartado, devuelve una lista vacía."""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "facts": {"type": "array", "items": {
            "type": "object",
            "properties": {"label": {"type": "string"}, "value": {"type": "string"},
                           "message_id": {"type": "integer"}},
            "required": ["label", "value", "message_id"], "additionalProperties": False,
        }},
        "new_tasks": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "due_date": {"type": "string"},
                           "owner": {"type": "string"}, "message_id": {"type": "integer"}},
            "required": ["title", "due_date", "owner", "message_id"], "additionalProperties": False,
        }},
        "completed_task_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["summary", "facts", "new_tasks", "completed_task_ids"],
    "additionalProperties": False,
}


class AnalysisError(Exception):
    pass


def _load_context(client_id: int) -> dict | None:
    with get_conn() as conn:
        client = conn.execute("SELECT id, name, company FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not client:
            return None
        messages = rows(conn.execute(
            """SELECT * FROM (
                   SELECT m.id, m.direction, m.sender, m.body, m.sent_at, c.channel, c.owner_user_id, u.name AS owner
                     FROM messages m JOIN conversations c ON c.id = m.conversation_id
                     JOIN users u ON u.id = c.owner_user_id
                    WHERE c.client_id = ? ORDER BY m.sent_at DESC, m.id DESC LIMIT ?
               ) ORDER BY sent_at, id""",
            (client_id, MAX_MESSAGES),
        ))
        facts = rows(conn.execute(
            "SELECT label, value, origin FROM client_facts WHERE client_id = ? AND origin IN ('manual', 'dismissed')",
            (client_id,),
        ))
        tasks = rows(conn.execute(
            "SELECT id, title, status, due_date FROM tasks WHERE client_id = ? ORDER BY id", (client_id,)))
        users = rows(conn.execute("SELECT id, name FROM users WHERE active = 1"))
    return {"client": dict(client), "messages": messages, "facts": facts, "tasks": tasks, "users": users}


def _prompt(ctx: dict) -> str:
    client = ctx["client"]
    lines = [f"Fecha de hoy: {date.today().isoformat()}",
             f"Cliente: {client['name']}" + (f" ({client['company']})" if client["company"] else ""),
             "Equipo: " + ", ".join(u["name"] for u in ctx["users"]), ""]
    confirmed = [f"- {f['label']}: {f['value']}" for f in ctx["facts"] if f["origin"] == "manual"]
    dismissed = [f"- {f['label']}: {f['value']}" for f in ctx["facts"] if f["origin"] == "dismissed"]
    lines += ["Datos confirmados:", *(confirmed or ["(ninguno)"]), "",
              "Datos descartados:", *(dismissed or ["(ninguno)"]), "",
              "Tareas existentes:"]
    lines += [f"- [{t['id']}] ({'hecha' if t['status'] == 'done' else 'abierta'}) {t['title']}"
              + (f" · vence {t['due_date']}" if t["due_date"] else "") for t in ctx["tasks"]] or ["(ninguna)"]
    docs = attachments.texts_for_client(ctx["client"]["id"])
    if docs:
        lines += ["", "Documentos y adjuntos del cliente (contenido extraído):"]
        for d in docs:
            origin = f"adjunto del mensaje [{d['message_id']}]" if d["message_id"] else "subido a la ficha"
            lines.append(f"--- {d['filename']} ({origin}):\n{d['text']}")
    lines += ["", "Mensajes (id · fecha · canal · quién escribe):"]
    for m in ctx["messages"]:
        who = f"{m['sender']} (cliente)" if m["direction"] == "in" else f"{m['sender']} (equipo; conversación de {m['owner']})"
        body = m["body"][:MAX_MESSAGE_CHARS] + ("…" if len(m["body"]) > MAX_MESSAGE_CHARS else "")
        lines.append(f"[{m['id']}] {m['sent_at'][:16].replace('T', ' ')} · {m['channel']} · {who}: {body}")
    return "\n".join(lines)


def _call_claude(prompt: str) -> dict:
    response = agent._create(
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if response.stop_reason == "refusal":
        raise AnalysisError("La IA no ha podido analizar estas conversaciones.")
    if response.stop_reason == "max_tokens":
        raise AnalysisError("El análisis ha salido demasiado largo; inténtalo de nuevo.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisError("La respuesta de la IA no tiene el formato esperado.") from exc


def _resolve_assignee(owner_hint: str, message: dict | None, users: list[dict]) -> int | None:
    """Responsable de una tarea: la persona nombrada por la IA o, si no, la dueña de esa conversación."""
    hint = owner_hint.strip().lower()
    if hint:
        for u in users:
            if hint in u["name"].lower() or u["name"].lower().split()[0] == hint.split()[0]:
                return u["id"]
    return message["owner_user_id"] if message else None


def _valid_date(value: str) -> str | None:
    try:
        return date.fromisoformat(value.strip()).isoformat() if value.strip() else None
    except ValueError:
        return None


def analyze_client(client_id: int) -> dict:
    """Analiza el cliente y guarda ficha, tareas nuevas y resumen. Devuelve lo que ha cambiado."""
    with _locks[client_id]:
        ctx = _load_context(client_id)
        if ctx is None:
            raise AnalysisError("Cliente no encontrado.")
        if not ctx["messages"]:
            raise AnalysisError("Este cliente todavía no tiene mensajes que analizar.")
        result = _call_claude(_prompt(ctx))

        by_id = {m["id"]: m for m in ctx["messages"]}
        known = {(f["label"].strip().lower(), f["value"].strip().lower()) for f in ctx["facts"]}
        open_ids = {t["id"] for t in ctx["tasks"] if t["status"] == "open"}
        facts = [f for f in result["facts"]
                 if f["label"].strip() and f["value"].strip()
                 and (f["label"].strip().lower(), f["value"].strip().lower()) not in known]
        new_tasks = [t for t in result["new_tasks"] if t["title"].strip()]
        completed = [i for i in result["completed_task_ids"] if i in open_ids]

        with get_conn() as conn:
            # Los datos de la IA se sustituyen enteros en cada análisis; los manuales y descartados se conservan.
            conn.execute("DELETE FROM client_facts WHERE client_id = ? AND origin = 'ai'", (client_id,))
            conn.executemany(
                """INSERT INTO client_facts (client_id, label, value, origin, source_message_id)
                   VALUES (?, ?, ?, 'ai', ?)""",
                [(client_id, f["label"].strip(), f["value"].strip(),
                  f["message_id"] if f["message_id"] in by_id else None) for f in facts],
            )
            conn.executemany(
                """INSERT INTO tasks (client_id, title, due_date, assignee_user_id, origin, source_message_id)
                   VALUES (?, ?, ?, ?, 'ai', ?)""",
                [(client_id, t["title"].strip(), _valid_date(t["due_date"]),
                  _resolve_assignee(t["owner"], by_id.get(t["message_id"]), ctx["users"]),
                  t["message_id"] if t["message_id"] in by_id else None) for t in new_tasks],
            )
            conn.executemany(
                "UPDATE tasks SET status = 'done', done_at = datetime('now') WHERE id = ? AND status = 'open'",
                [(i,) for i in completed],
            )
            conn.execute(
                """INSERT INTO client_analysis (client_id, summary, last_message_id, analyzed_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(client_id) DO UPDATE SET summary = excluded.summary,
                       last_message_id = excluded.last_message_id, analyzed_at = excluded.analyzed_at""",
                (client_id, result["summary"].strip(), max(by_id)),
            )
        return {"facts": len(facts), "new_tasks": len(new_tasks), "completed_tasks": len(completed)}


def analyze_in_background(client_id: int) -> None:
    """Tras una importación: analiza sin hacer esperar al usuario. Si no hay clave de API, no hace nada."""
    def run():
        try:
            analyze_client(client_id)
        except agent.MissingCredentialsError:
            pass
        except Exception:  # noqa: BLE001 - un fallo aquí no debe afectar a la importación
            log.exception("Fallo al analizar el cliente %s en segundo plano", client_id)
    threading.Thread(target=run, daemon=True).start()


def summarize_new_messages(client_name: str, messages: list[dict]) -> str:
    """Resumen breve de los mensajes llegados desde la última visita (no se guarda)."""
    lines = [f"Cliente: {client_name}", "Mensajes nuevos (fecha · canal · quién escribe):"]
    for m in messages:
        who = f"{m['sender']} (cliente)" if m["direction"] == "in" else f"{m['sender']} (equipo)"
        body = m["body"][:MAX_MESSAGE_CHARS]
        lines.append(f"{m['sent_at'][:16].replace('T', ' ')} · {m['channel']} · {who}: {body}")
    response = agent._create(
        system="Resume en español, en 1 a 4 viñetas cortas, qué ha pasado en estos mensajes nuevos entre el "
               "equipo y el cliente: peticiones, cambios, acuerdos y lo que queda pendiente de responder. "
               "Sin introducción ni despedida.",
        messages=[{"role": "user", "content": "\n".join(lines)}],
        output_config={"effort": "low"},
    )
    if response.stop_reason == "refusal":
        raise AnalysisError("La IA no ha podido resumir estos mensajes.")
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


CHANNEL_STYLE = {
    "whatsapp": "WhatsApp: mensaje breve y cercano, frases cortas, sin asunto ni firma formal. Emojis solo si el cliente los usa.",
    "telegram": "Telegram: mensaje breve y cercano, sin asunto ni firma formal.",
    "email": "Email: saludo, cuerpo claro en párrafos cortos, despedida y firma con el nombre de quien escribe. Sin línea de asunto.",
}


def draft_reply(conversation_id: int, author: dict, instructions: str = "") -> dict:
    """Borrador de respuesta para una conversación, con el contexto del cliente en todos los canales."""
    with get_conn() as conn:
        conv = conn.execute(
            """SELECT c.id, c.channel, c.subject, c.client_id, cl.name AS client, u.name AS owner
                 FROM conversations c JOIN clients cl ON cl.id = c.client_id
                 JOIN users u ON u.id = c.owner_user_id WHERE c.id = ?""", (conversation_id,)).fetchone()
        if not conv:
            raise AnalysisError("Conversación no encontrada.")
        thread = rows(conn.execute(
            """SELECT * FROM (SELECT direction, sender, body, sent_at FROM messages WHERE conversation_id = ?
                               ORDER BY sent_at DESC, id DESC LIMIT 40) ORDER BY sent_at""", (conversation_id,)))
        other = rows(conn.execute(
            """SELECT * FROM (SELECT m.direction, m.sender, m.body, m.sent_at, c.channel FROM messages m
                               JOIN conversations c ON c.id = m.conversation_id
                              WHERE c.client_id = ? AND c.id != ? ORDER BY m.sent_at DESC LIMIT 20)
               ORDER BY sent_at""", (conv["client_id"], conversation_id)))
    if not thread:
        raise AnalysisError("La conversación está vacía.")
    ficha = profile(conv["client_id"])
    open_tasks = list_tasks(client_id=conv["client_id"], status="open")

    def fmt(m, channel=None):
        who = f"{m['sender']} (cliente)" if m["direction"] == "in" else f"{m['sender']} (equipo)"
        return f"{m['sent_at'][:16].replace('T', ' ')}{' · ' + channel if channel else ''} · {who}: {m['body'][:MAX_MESSAGE_CHARS]}"

    lines = [f"Fecha de hoy: {date.today().isoformat()}",
             f"Escribe: {author['name']} (del equipo)",
             f"Cliente: {conv['client']}",
             f"Canal: {conv['channel']}" + (f" · asunto «{conv['subject']}»" if conv["subject"] else ""),
             ""]
    if ficha["summary"]:
        lines += ["Resumen del cliente:", ficha["summary"], ""]
    if ficha["facts"]:
        lines += ["Datos clave:", *[f"- {f['label']}: {f['value']}" for f in ficha["facts"]], ""]
    if open_tasks:
        lines += ["Tareas pendientes con este cliente:", *[f"- {t['title']}" + (f" (vence {t['due_date']})" if t["due_date"] else "")
                                                           for t in open_tasks], ""]
    if other:
        lines += ["Mensajes recientes por otros canales (contexto):", *[fmt(m, m["channel"]) for m in other], ""]
    lines += ["Conversación a la que hay que responder:", *[fmt(m) for m in thread], ""]
    if instructions.strip():
        lines += [f"Indicaciones de {author['name']} para esta respuesta: {instructions.strip()}"]

    response = agent._create(
        system="Redactas borradores de respuesta para que una persona del equipo los revise y los envíe al cliente. "
               "Responde a lo último que ha escrito el cliente teniendo en cuenta todo el contexto. Escribe en el idioma "
               "del cliente y con el tono que ya se usa en la conversación. No inventes datos (precios, fechas, "
               "disponibilidad) que no aparezcan en el contexto: si hacen falta, deja un hueco entre corchetes, "
               "p. ej. [precio]. Devuelve solo el texto del mensaje, listo para copiar, sin comentarios.\n\n"
               + CHANNEL_STYLE.get(conv["channel"], "Mensaje claro y breve."),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        output_config={"effort": "low"},
    )
    if response.stop_reason == "refusal":
        raise AnalysisError("La IA no ha podido redactar esta respuesta.")
    draft = "\n".join(b.text for b in response.content if b.type == "text").strip()
    return {"draft": draft, "channel": conv["channel"], "subject": conv["subject"], "client_id": conv["client_id"]}


# ---------------------------------------------------------------- Consultas y edición manual

def profile(client_id: int) -> dict:
    with get_conn() as conn:
        analysis = conn.execute(
            "SELECT summary, analyzed_at, last_message_id FROM client_analysis WHERE client_id = ?", (client_id,)
        ).fetchone()
        new_since = conn.execute(
            """SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                WHERE c.client_id = ? AND m.id > ?""",
            (client_id, analysis["last_message_id"] if analysis else 0),
        ).fetchone()[0]
        facts = rows(conn.execute(
            """SELECT f.id, f.label, f.value, f.origin, f.source_message_id, f.updated_at, u.name AS updated_by
                 FROM client_facts f LEFT JOIN users u ON u.id = f.updated_by
                WHERE f.client_id = ? AND f.origin != 'dismissed' ORDER BY f.label COLLATE NOCASE""",
            (client_id,),
        ))
    return {
        "summary": analysis["summary"] if analysis else None,
        "analyzed_at": analysis["analyzed_at"] if analysis else None,
        "new_messages_since_analysis": new_since,
        "facts": facts,
    }


TASK_FIELDS = """t.id, t.client_id, cl.name AS client, t.title, t.due_date, t.status, t.origin,
                 t.source_message_id, t.assignee_user_id, u.name AS assignee, t.created_at, t.done_at"""


def list_tasks(client_id: int | None = None, assignee_id: int | None = None,
               status: str | None = None) -> list[dict]:
    sql = f"""SELECT {TASK_FIELDS} FROM tasks t JOIN clients cl ON cl.id = t.client_id
              LEFT JOIN users u ON u.id = t.assignee_user_id WHERE 1 = 1"""
    args: list = []
    if client_id is not None:
        sql += " AND t.client_id = ?"
        args.append(client_id)
    if assignee_id is not None:
        sql += " AND t.assignee_user_id = ?"
        args.append(assignee_id)
    if status:
        sql += " AND t.status = ?"
        args.append(status)
    # Primero las abiertas; dentro, las que vencen antes (las que no tienen fecha, al final).
    sql += " ORDER BY t.status = 'done', t.due_date IS NULL, t.due_date, t.id DESC"
    with get_conn() as conn:
        return rows(conn.execute(sql, args))


def get_task(task_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            f"""SELECT {TASK_FIELDS} FROM tasks t JOIN clients cl ON cl.id = t.client_id
                LEFT JOIN users u ON u.id = t.assignee_user_id WHERE t.id = ?""", (task_id,)).fetchone()
    return dict(row) if row else None
