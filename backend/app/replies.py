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

from . import clients, search
from .clients import STATUSES, _norm_name
from .db import Conn, get_conn
from .errors import Forbidden, InvalidInput, NotFound
from .repositories import replies as repo

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
            raise InvalidInput("El atajo solo puede tener letras sin tildes, números, guiones y _ (máx. 30).")
        out["shortcut"] = sc
    if out.get("set_status") and out["set_status"] not in STATUSES:
        raise InvalidInput("Estado no válido.")
    if "mark_done" in out:
        out["mark_done"] = int(bool(out["mark_done"]))
    for required in ("title", "body"):
        if required in out and not out[required]:
            raise InvalidInput("El título y el texto son obligatorios.")
    return out


def _check_shortcut(conn: Conn, shortcut: str | None, reply_id: int | None = None) -> None:
    if shortcut and repo.shortcut_taken(conn, shortcut, reply_id):
        raise InvalidInput(f"Ya hay otra respuesta con el atajo /{shortcut}.")


def list_replies() -> list[dict]:
    with get_conn() as conn:
        return repo.list_all(conn)


def get_reply(reply_id: int) -> dict:
    reply = next((r for r in list_replies() if r["id"] == reply_id), None)
    if not reply:
        raise NotFound("Respuesta guardada no encontrada")
    return reply


def create(fields: dict, user_id: int) -> dict:
    data = _clean(fields)
    if not data.get("title") or not data.get("body"):
        raise InvalidInput("El título y el texto son obligatorios.")
    with get_conn() as conn:
        _check_shortcut(conn, data.get("shortcut"))
        reply_id = repo.insert(conn, data, user_id)
    return get_reply(reply_id)


def _can_edit(reply: dict, user: dict) -> None:
    if reply["created_by"] != user["id"] and user["role"] != "admin":
        raise Forbidden("Solo quien la creó (o un administrador) puede cambiarla.")


def update(reply_id: int, fields: dict, user: dict) -> dict:
    _can_edit(get_reply(reply_id), user)
    data = _clean(fields)
    if data:
        with get_conn() as conn:
            _check_shortcut(conn, data.get("shortcut"), reply_id)
            repo.update(conn, reply_id, data)
    return get_reply(reply_id)


def delete(reply_id: int, user: dict) -> None:
    _can_edit(get_reply(reply_id), user)
    with get_conn() as conn:
        repo.delete(conn, reply_id)


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
        client = repo.client(conn, client_id)
        if not client:
            raise NotFound("Cliente no encontrado")
        facts = repo.client_facts(conn, client_id)
        tags = repo.client_tags(conn, client_id)
    applied = []
    if reply["set_status"]:
        clients.update_client(client_id, {"status": reply["set_status"]}, user["id"])
        applied.append(f"estado: {STATUSES[reply['set_status']]}")
    if reply["add_tag"] and reply["add_tag"].lower() not in {t.lower() for t in tags}:
        clients.set_tags(client_id, [*tags, reply["add_tag"]])
        applied.append(f"etiqueta «{reply['add_tag']}»")
    if reply["mark_done"] and conversation_id:
        with get_conn() as conn:
            last_in_id = repo.last_incoming_message_id(conn, conversation_id, client_id)
        if last_in_id and search.dismiss_unanswered(conversation_id, last_in_id):
            applied.append("conversación marcada como atendida")
    return {"text": fill(reply["body"], client, facts, user), "applied": applied}
