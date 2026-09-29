"""Notas internas del equipo, menciones (@Nombre) y avisos."""
import re

from .db import get_conn, rows

MENTION_PREVIEW_CHARS = 120


def _active_users(conn) -> list[dict]:
    return rows(conn.execute("SELECT id, name, username FROM users WHERE active = 1"))


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
    conn.executemany(
        "INSERT INTO notifications (user_id, kind, text, client_id, actor_user_id) VALUES (?, ?, ?, ?, ?)",
        [(uid, kind, text, client_id, actor_id) for uid in user_ids if uid != actor_id],
    )


def _preview(body: str) -> str:
    body = " ".join(body.split())
    return body if len(body) <= MENTION_PREVIEW_CHARS else body[:MENTION_PREVIEW_CHARS] + "…"


# ---------------------------------------------------------------- Notas

NOTE_FIELDS = """n.id, n.client_id, n.body, n.created_at, n.updated_at, n.user_id, u.name AS author"""


def list_notes(client_id: int) -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute(
            f"""SELECT {NOTE_FIELDS} FROM client_notes n LEFT JOIN users u ON u.id = n.user_id
                WHERE n.client_id = ? ORDER BY n.id DESC""", (client_id,)))


def get_note(note_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(f"""SELECT {NOTE_FIELDS} FROM client_notes n LEFT JOIN users u ON u.id = n.user_id
                               WHERE n.id = ?""", (note_id,)).fetchone()
    return dict(row) if row else None


def add_note(client_id: int, author: dict, body: str) -> dict:
    with get_conn() as conn:
        note_id = conn.execute("INSERT INTO client_notes (client_id, user_id, body) VALUES (?, ?, ?) RETURNING id",
                               (client_id, author["id"], body)).lastrowid
        client = conn.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
        mentioned = find_mentions(body, _active_users(conn))
        notify(conn, mentioned, "mention",
               f"{author['name']} te ha mencionado en una nota sobre {client['name']}: «{_preview(body)}»",
               client_id, author["id"])
    return get_note(note_id)


def update_note(note_id: int, author: dict, body: str) -> dict:
    """Al editar, solo se avisa a quienes no estaban mencionados antes."""
    with get_conn() as conn:
        old = conn.execute("SELECT client_id, body FROM client_notes WHERE id = ?", (note_id,)).fetchone()
        conn.execute("UPDATE client_notes SET body = ?, updated_at = localtimestamp(0) WHERE id = ?", (body, note_id))
        users = _active_users(conn)
        new_mentions = find_mentions(body, users) - find_mentions(old["body"], users)
        client = conn.execute("SELECT name FROM clients WHERE id = ?", (old["client_id"],)).fetchone()
        notify(conn, new_mentions, "mention",
               f"{author['name']} te ha mencionado en una nota sobre {client['name']}: «{_preview(body)}»",
               old["client_id"], author["id"])
    return get_note(note_id)


def delete_note(note_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM client_notes WHERE id = ?", (note_id,))


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
        items = rows(conn.execute(
            """SELECT id, kind, text, client_id, created_at, read_at FROM notifications
                WHERE user_id = ? ORDER BY id DESC LIMIT ?""", (user_id, limit)))
        unread = conn.execute("SELECT count(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
                              (user_id,)).fetchone()[0]
    return {"unread": unread, "items": items}


def mark_read(user_id: int, ids: list[int] | None = None) -> None:
    with get_conn() as conn:
        if ids is None:
            conn.execute("UPDATE notifications SET read_at = localtimestamp(0) WHERE user_id = ? AND read_at IS NULL",
                         (user_id,))
        else:
            conn.executemany(
                "UPDATE notifications SET read_at = localtimestamp(0) WHERE id = ? AND user_id = ? AND read_at IS NULL",
                [(i, user_id) for i in ids])
