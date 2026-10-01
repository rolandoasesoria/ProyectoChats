"""Respuestas guardadas y macros del equipo.

Una respuesta guardada es un texto con variables que se rellenan con los datos del cliente:
  {nombre}  nombre de pila del cliente      {cliente}  nombre completo
  {empresa} empresa del cliente             {yo}       quien responde
  {dato:CIF} cualquier dato clave de la ficha (por su nombre, sin distinguir mayúsculas ni tildes)
Lo que no se conoce queda entre corchetes ([empresa], [CIF]) para rellenarlo a mano.

Si además tiene acciones (cambiar el estado, añadir una etiqueta, marcar como atendida) es una macro:
al usarla se aplican al cliente y a la conversación.
"""
import re

from fastapi import HTTPException

from . import clients, search
from .clients import STATUSES, _norm_name
from .db import get_conn, rows

VARIABLE = re.compile(r"\{(nombre|cliente|empresa|yo|dato:([^{}]{1,100}))\}", re.IGNORECASE)
SHORTCUT = re.compile(r"^[a-z0-9_-]{1,30}$")
FIELDS = ("title", "shortcut", "body", "set_status", "add_tag", "mark_done")


def _clean(fields: dict) -> dict:
    out = {k: v for k, v in fields.items() if k in FIELDS}
    for k in ("title", "body", "add_tag"):
        if k in out and isinstance(out[k], str):
            out[k] = out[k].strip() or None
    if "shortcut" in out:
        sc = (out["shortcut"] or "").strip().lstrip("/").lower() or None
        if sc and not SHORTCUT.match(sc):
            raise HTTPException(400, "El atajo solo puede tener letras sin tildes, números, guiones y _ (máx. 30).")
        out["shortcut"] = sc
    if out.get("set_status") and out["set_status"] not in STATUSES:
        raise HTTPException(400, "Estado no válido.")
    if "mark_done" in out:
        out["mark_done"] = int(bool(out["mark_done"]))
    for required in ("title", "body"):
        if required in out and not out[required]:
            raise HTTPException(400, "El título y el texto son obligatorios.")
    return out


def _check_shortcut(conn, shortcut: str | None, reply_id: int | None = None) -> None:
    if shortcut and conn.execute("SELECT 1 FROM saved_replies WHERE lower(shortcut) = ? AND id IS DISTINCT FROM ?",
                                 (shortcut, reply_id)).fetchone():
        raise HTTPException(400, f"Ya hay otra respuesta con el atajo /{shortcut}.")


def list_replies() -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute(
            """SELECT r.id, r.title, r.shortcut, r.body, r.set_status, r.add_tag, r.mark_done = 1 AS mark_done,
                      r.created_by, u.name AS author
                 FROM saved_replies r LEFT JOIN users u ON u.id = r.created_by
                ORDER BY lower(r.title)"""))


def get_reply(reply_id: int) -> dict:
    reply = next((r for r in list_replies() if r["id"] == reply_id), None)
    if not reply:
        raise HTTPException(404, "Respuesta guardada no encontrada")
    return reply


def create(fields: dict, user_id: int) -> dict:
    data = _clean(fields)
    if not data.get("title") or not data.get("body"):
        raise HTTPException(400, "El título y el texto son obligatorios.")
    with get_conn() as conn:
        _check_shortcut(conn, data.get("shortcut"))
        reply_id = conn.execute(
            f"INSERT INTO saved_replies ({', '.join(data)}, created_by) VALUES ({', '.join('?' * len(data))}, ?) RETURNING id",
            [*data.values(), user_id]).lastrowid
    return get_reply(reply_id)


def _can_edit(reply: dict, user: dict) -> None:
    if reply["created_by"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Solo quien la creó (o un administrador) puede cambiarla.")


def update(reply_id: int, fields: dict, user: dict) -> dict:
    _can_edit(get_reply(reply_id), user)
    data = _clean(fields)
    if data:
        with get_conn() as conn:
            _check_shortcut(conn, data.get("shortcut"), reply_id)
            conn.execute(f"UPDATE saved_replies SET {', '.join(f'{k} = ?' for k in data)}, updated_at = localtimestamp(0) "
                         "WHERE id = ?", [*data.values(), reply_id])
    return get_reply(reply_id)


def delete(reply_id: int, user: dict) -> None:
    _can_edit(get_reply(reply_id), user)
    with get_conn() as conn:
        conn.execute("DELETE FROM saved_replies WHERE id = ?", (reply_id,))


def fill(body: str, client: dict, facts: list[dict], author: dict) -> str:
    """Sustituye las variables por los datos del cliente; lo desconocido queda como [hueco]."""
    by_label = {_norm_name(f["label"]): f["value"] for f in facts}

    def value(m: re.Match) -> str:
        key = m.group(1).lower()
        if key == "nombre":
            return (client["name"] or "").split()[0] if client["name"] else "[nombre]"
        if key == "cliente":
            return client["name"] or "[cliente]"
        if key == "empresa":
            return client.get("company") or "[empresa]"
        if key == "yo":
            return author["name"]
        label = m.group(2).strip()
        return by_label.get(_norm_name(label)) or f"[{label}]"

    return VARIABLE.sub(value, body)


def use(reply_id: int, client_id: int, conversation_id: int | None, user: dict) -> dict:
    """Texto listo para el borrador y, si es una macro, aplica sus acciones. Devuelve qué se ha hecho."""
    reply = get_reply(reply_id)
    with get_conn() as conn:
        client = conn.execute("SELECT id, name, company FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not client:
            raise HTTPException(404, "Cliente no encontrado")
        facts = rows(conn.execute(
            "SELECT label, value FROM client_facts WHERE client_id = ? AND origin != 'dismissed'", (client_id,)))
        tags = [r["tag"] for r in conn.execute("SELECT tag FROM client_tags WHERE client_id = ?", (client_id,))]
    applied = []
    if reply["set_status"]:
        clients.update_client(client_id, {"status": reply["set_status"]}, user["id"])
        applied.append(f"estado: {STATUSES[reply['set_status']]}")
    if reply["add_tag"] and reply["add_tag"].lower() not in {t.lower() for t in tags}:
        clients.set_tags(client_id, [*tags, reply["add_tag"]])
        applied.append(f"etiqueta «{reply['add_tag']}»")
    if reply["mark_done"] and conversation_id:
        with get_conn() as conn:
            last_in = conn.execute(
                """SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.id = ? AND c.client_id = ? AND m.direction = 'in' ORDER BY m.sent_at DESC, m.id DESC LIMIT 1""",
                (conversation_id, client_id)).fetchone()
        if last_in and search.dismiss_unanswered(conversation_id, last_in["id"]):
            applied.append("conversación marcada como atendida")
    return {"text": fill(reply["body"], dict(client), facts, user), "applied": applied}
