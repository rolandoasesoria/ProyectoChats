"""Organizar los chats como en WhatsApp: fijar (hasta 3), archivar, silenciar, marcar como no leído, destacar mensajes
(★) y ver lo compartido en cada chat (fotos y vídeos, documentos y enlaces). Cada usuario organiza su propia lista."""
import re
from datetime import datetime, timedelta

from . import message_actions, search
from .db import get_conn
from .errors import Conflict, NotFound
from .repositories import chat_prefs as repo
from .repositories import messages as messages_repo

MAX_PINNED = 3
MUTE_FOREVER = datetime(9999, 12, 31)
MUTE_FOR = {"8h": timedelta(hours=8), "week": timedelta(days=7)}
SHARED_LIMIT = 300
EMAIL_PHOTO_MIN = 40 * 1024  # en el correo, las imágenes más pequeñas son logos de firmas (como en la conversación)
URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _flags(prefs: dict) -> dict:
    muted_until = prefs["muted_until"]
    muted = bool(muted_until) and datetime.fromisoformat(str(muted_until)) > _now()
    return {"pinned": bool(prefs["pinned_at"]), "archived": bool(prefs["archived_at"]), "muted": muted,
            "muted_until": muted_until if muted else None, "marked_unread": bool(prefs["marked_unread"])}


def update(user: dict, client_id: int, *, pinned: bool | None = None, archived: bool | None = None,
           mute: str | None = None, unread: bool | None = None) -> dict:
    """Cambia cómo ve `user` el chat del cliente. mute: «8h», «week», «always» u «off»."""
    values = {}
    with get_conn() as conn:
        current = repo.get(conn, user["id"], client_id)
        if pinned and not current["pinned_at"]:
            if repo.pinned_count(conn, user["id"]) >= MAX_PINNED:
                raise Conflict(f"Solo se pueden fijar {MAX_PINNED} chats: desfija otro antes.")
            values.update(pinned_at=_now(), archived_at=None)  # fijar lo saca de archivados
        elif pinned is False:
            values["pinned_at"] = None
        if archived:
            values.update(archived_at=_now(), pinned_at=None)  # archivar lo desfija
        elif archived is False:
            values["archived_at"] = None
        if mute:
            values["muted_until"] = None if mute == "off" else MUTE_FOREVER if mute == "always" else _now() + MUTE_FOR[mute]
        if unread is not None:
            values["marked_unread"] = int(unread)
        if values:
            repo.save(conn, user["id"], client_id, values)
        prefs = repo.get(conn, user["id"], client_id)
    if unread is False:
        # «Marcar como leído»: como abrirlo (lo del cliente queda leído y, en WhatsApp, él ve los checks azules)
        search.record_visit(user["id"], client_id)
        message_actions.mark_read_later(client_id, user)
    return _flags(prefs)


# ---------------------------------------------------------------- Mensajes destacados

def star(user_id: int, message_id: int, on: bool) -> dict:
    with get_conn() as conn:
        if not messages_repo.with_conversation(conn, message_id):
            raise NotFound("Mensaje no encontrado.")
        repo.set_star(conn, user_id, message_id, on)
    return {"starred": on}


def starred(user_id: int, client_id: int | None = None) -> list[dict]:
    with get_conn() as conn:
        return repo.starred(conn, user_id, client_id, SHARED_LIMIT)


# ---------------------------------------------------------------- Fotos, documentos y enlaces del chat

def _links(text: str) -> list[str]:
    return list(dict.fromkeys(u.rstrip(".,;:!?)]") for u in URL_RE.findall(text)))


def shared(client_id: int, user_id: int, scope: str) -> dict:
    """Lo compartido en las conversaciones del cliente: fotos y vídeos, documentos (y audios aparte) y enlaces."""
    with get_conn() as conn:
        files = repo.shared_files(conn, client_id, user_id, scope, SHARED_LIMIT)
        with_links = repo.messages_with_links(conn, client_id, user_id, scope, SHARED_LIMIT)
    media = [f for f in files if f["mime"].startswith("video/") or (
        f["mime"].startswith("image/") and (f["channel"] != "email" or f["size"] >= EMAIL_PHOTO_MIN))]
    docs = [f for f in files if not f["mime"].startswith(("image/", "video/", "audio/"))]
    links = [{"url": url, "message_id": m["id"], "sent_at": m["sent_at"], "sender": m["sender"],
              "direction": m["direction"], "channel": m["channel"]}
             for m in with_links for url in _links(m["body"])]
    return {"media": media, "docs": docs, "links": links[:SHARED_LIMIT]}
