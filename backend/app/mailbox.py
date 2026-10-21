"""Correo en bandejas, como en un programa de correo: Recibidos, Enviados y Destacados, y el correo abierto con su hilo.
Es la otra forma de ver los correos de las conversaciones de email (la de siempre: en el chat de cada cliente)."""
from . import attachments, audit, auth, integrations
from .db import get_conn
from .errors import Forbidden, NotFound
from .repositories import integrations as integrations_repo
from .repositories import mail as repo

PAGE = 50


def _check_scope(user: dict, scope: str) -> None:
    if scope == "team" and not auth.can_view_team_chats(user):
        raise Forbidden("Para ver los correos de todo el equipo hace falta que un administrador te dé permiso.")


def folder(user: dict, name: str, scope: str = "mine", query: str = "", client_id: int | None = None,
           offset: int = 0) -> dict:
    """Una página de la carpeta (`more`: hay más) y cuántos recibidos quedan sin leer."""
    _check_scope(user, scope)
    with get_conn() as conn:
        items = repo.mailbox(conn, user["id"], scope, name, query.strip(), client_id, PAGE + 1, offset)
        unread = repo.unread_count(conn, user["id"], scope)
    if any(i["owner_id"] != user["id"] for i in items):
        audit.log(user["id"], "team_messages", client_id, throttle=True)
    return {"items": items[:PAGE], "more": len(items) > PAGE, "unread": unread}


def unread_count(user: dict) -> int:
    with get_conn() as conn:
        return repo.unread_count(conn, user["id"], "mine")


def open_email(user: dict, message_id: int) -> dict:
    """El correo completo (con sus direcciones, adjuntos y el resto del hilo). Queda leído."""
    with get_conn() as conn:
        mail = repo.email(conn, user["id"], message_id)
        if not mail:
            raise NotFound("Correo no encontrado.")
        mail["thread"] = repo.thread(conn, mail["conversation_id"])
        mail["client_addresses"] = repo.client_addresses(conn, mail["client_id"])
        sender_id = integrations_repo.find_sender_id(conn, "email", mail["owner_id"], "user")
        repo.mark_read(conn, user["id"], message_id)
    mail["account"] = (integrations.get(sender_id)["config"].get("address") or None) if sender_id else None
    mail["attachments"] = attachments.by_message([message_id]).get(message_id, [])
    if mail["owner_id"] != user["id"]:
        audit.log(user["id"], "team_messages", mail["client_id"], throttle=True)
    return mail


def read_all(user: dict, scope: str = "mine") -> int:
    _check_scope(user, scope)
    with get_conn() as conn:
        return repo.mark_all_read(conn, user["id"], scope)
