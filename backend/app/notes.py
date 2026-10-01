"""Notas internas del equipo, menciones (@Nombre) y avisos."""
import re

from .db import get_conn
from .repositories import notes as repo
from .repositories import notifications as notifications_repo
from .repositories import users as users_repo

MENTION_PREVIEW_CHARS = 120


def find_mentions(body: str, users: list[dict]) -> set[int]:
    """Usuarios mencionados como @Nombre Apellido, @Nombre o @usuario (sin distinguir mayúsculas)."""
    text = body.lower()
    mentioned = set()
    for u in users:
        candidates = {u["name"].lower(), u["name"].split()[0].lower()}
        if u["username"]:
            candidates.add(u["username"].lower())
        for c in candidates:
            # "@carlos" no debe coincidir con "@carlosa" (detrás no puede venir letra/número) ni con un
            # email como "laura@carlos.com" (delante de la @ no puede haber letra, número ni punto).
            if re.search(r"(?<![\w.])@" + re.escape(c) + r"(?![\w])", text):
                mentioned.add(u["id"])
                break
    return mentioned


def notify(conn, user_ids, kind: str, text: str, client_id: int | None, actor_id: int | None) -> None:
    """Avisa a los usuarios indicados, salvo a quien provoca el aviso. Usa la transacción de quien llama."""
    notifications_repo.insert_many(conn, [uid for uid in user_ids if uid != actor_id], kind, text, client_id,
                                   actor_id)


def _preview(body: str) -> str:
    body = " ".join(body.split())
    return body if len(body) <= MENTION_PREVIEW_CHARS else body[:MENTION_PREVIEW_CHARS] + "…"


# ---------------------------------------------------------------- Notas

def _mention_text(author: dict, client_name: str, body: str) -> str:
    return f"{author['name']} te ha mencionado en una nota sobre {client_name}: «{_preview(body)}»"


def list_notes(client_id: int) -> list[dict]:
    with get_conn() as conn:
        return repo.list_for_client(conn, client_id)


def get_note(note_id: int) -> dict | None:
    with get_conn() as conn:
        return repo.get(conn, note_id)


def add_note(client_id: int, author: dict, body: str) -> dict:
    with get_conn() as conn:
        note_id = repo.insert(conn, client_id, author["id"], body)
        client_name = repo.client_name(conn, client_id)
        mentioned = find_mentions(body, users_repo.list_active_for_mentions(conn))
        notify(conn, mentioned, "mention", _mention_text(author, client_name, body), client_id, author["id"])
    return get_note(note_id)


def update_note(note_id: int, author: dict, body: str) -> dict:
    """Al editar, solo se avisa a quienes no estaban mencionados antes."""
    with get_conn() as conn:
        old = repo.get_raw(conn, note_id)
        repo.update_body(conn, note_id, body)
        users = users_repo.list_active_for_mentions(conn)
        new_mentions = find_mentions(body, users) - find_mentions(old["body"], users)
        client_name = repo.client_name(conn, old["client_id"])
        notify(conn, new_mentions, "mention", _mention_text(author, client_name, body), old["client_id"],
               author["id"])
    return get_note(note_id)


def delete_note(note_id: int) -> None:
    with get_conn() as conn:
        repo.delete(conn, note_id)


# ---------------------------------------------------------------- Avisos

def notify_task_assigned(task: dict, actor: dict) -> None:
    if not task.get("assignee_user_id") or task["assignee_user_id"] == actor["id"]:
        return
    with get_conn() as conn:
        notify(conn, [task["assignee_user_id"]], "task_assigned",
               f"{actor['name']} te ha asignado una tarea de {task['client']}: «{_preview(task['title'])}»",
               task["client_id"], actor["id"])


def list_notifications(user_id: int, limit: int = 30) -> dict:
    with get_conn() as conn:
        items = notifications_repo.list_recent(conn, user_id, limit)
        unread = notifications_repo.count_unread(conn, user_id)
    return {"unread": unread, "items": items}


def mark_read(user_id: int, ids: list[int] | None = None) -> None:
    with get_conn() as conn:
        if ids is None:
            notifications_repo.mark_all_read(conn, user_id)
        else:
            notifications_repo.mark_read(conn, user_id, ids)
