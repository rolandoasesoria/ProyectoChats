"""Gestión de clientes: datos básicos, estado, responsable, etiquetas, identificadores y unión de duplicados."""
import re
import unicodedata

from fastapi import HTTPException

from .db import get_conn, rows

STATUSES = {"lead": "Potencial", "active": "Activo", "issue": "Incidencia", "inactive": "Inactivo"}
CHANNELS = ("email", "whatsapp", "telegram", "phone", "other")


def _norm_name(name: str) -> str:
    text = unicodedata.normalize("NFD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _digits(handle: str) -> str:
    """Últimos 9 dígitos de un teléfono (ignora prefijo de país, espacios y guiones)."""
    d = re.sub(r"\D", "", handle or "")
    return d[-9:] if len(d) >= 9 else ""


def create_client(name: str, company: str | None, user_id: int) -> int:
    with get_conn() as conn:
        return conn.execute("INSERT INTO clients (name, company, assignee_user_id) VALUES (?, ?, ?)",
                            (name.strip(), (company or "").strip() or None, user_id)).lastrowid


def update_client(client_id: int, fields: dict) -> None:
    allowed = {"name", "company", "status", "assignee_user_id"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if "status" in fields and fields["status"] not in STATUSES:
        raise HTTPException(400, "Estado no válido.")
    if "name" in fields and not (fields["name"] or "").strip():
        raise HTTPException(400, "El nombre es obligatorio.")
    if not fields:
        return
    with get_conn() as conn:
        conn.execute(f"UPDATE clients SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                     [*fields.values(), client_id])


def set_tags(client_id: int, tags: list[str]) -> list[str]:
    clean = []
    for t in tags:
        t = " ".join(t.split())[:40]
        if t and t.lower() not in {c.lower() for c in clean}:
            clean.append(t)
    with get_conn() as conn:
        conn.execute("DELETE FROM client_tags WHERE client_id = ?", (client_id,))
        conn.executemany("INSERT INTO client_tags (client_id, tag) VALUES (?, ?)", [(client_id, t) for t in clean[:20]])
    return clean[:20]


def all_tags() -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute(
            "SELECT tag, count(*) AS clients FROM client_tags GROUP BY tag COLLATE NOCASE ORDER BY tag COLLATE NOCASE"))


def add_identity(client_id: int, channel: str, handle: str) -> dict:
    handle = handle.strip()
    if channel not in CHANNELS:
        raise HTTPException(400, "Canal no válido.")
    if not handle:
        raise HTTPException(400, "El identificador es obligatorio.")
    if channel == "email":
        handle = handle.lower()
    with get_conn() as conn:
        other = conn.execute(
            """SELECT cl.id, cl.name FROM client_identities ci JOIN clients cl ON cl.id = ci.client_id
                WHERE ci.channel = ? AND ci.handle = ? COLLATE NOCASE""", (channel, handle)).fetchone()
        if other:
            if other["id"] == client_id:
                raise HTTPException(409, "Este cliente ya tiene ese identificador.")
            raise HTTPException(409, f"Ese identificador ya pertenece a «{other['name']}». "
                                     "Si es la misma persona, usa «Unir con otro cliente».")
        ident_id = conn.execute("INSERT INTO client_identities (client_id, channel, handle) VALUES (?, ?, ?)",
                                (client_id, channel, handle)).lastrowid
    return {"id": ident_id, "channel": channel, "handle": handle}


def delete_identity(identity_id: int) -> None:
    with get_conn() as conn:
        if not conn.execute("DELETE FROM client_identities WHERE id = ?", (identity_id,)).rowcount:
            raise HTTPException(404, "Identificador no encontrado.")


def possible_duplicates(client_id: int) -> list[dict]:
    """Otros clientes que probablemente son la misma persona: mismo nombre, mismo email o mismo teléfono."""
    with get_conn() as conn:
        me = conn.execute("SELECT id, name FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not me:
            return []
        all_clients = rows(conn.execute("SELECT id, name, company FROM clients WHERE id != ?", (client_id,)))
        idents = rows(conn.execute("SELECT client_id, channel, handle FROM client_identities"))
    mine = [i for i in idents if i["client_id"] == client_id]
    my_emails = {i["handle"].lower() for i in mine if "@" in i["handle"] and not i["handle"].startswith("@")}
    my_phones = {_digits(i["handle"]) for i in mine} - {""}
    my_name = _norm_name(me["name"])
    result = []
    for c in all_clients:
        theirs = [i for i in idents if i["client_id"] == c["id"]]
        reasons = []
        if my_name and _norm_name(c["name"]) == my_name:
            reasons.append("mismo nombre")
        if my_emails & {i["handle"].lower() for i in theirs}:
            reasons.append("mismo email")
        if my_phones & ({_digits(i["handle"]) for i in theirs} - {""}):
            reasons.append("mismo teléfono")
        if reasons:
            result.append({**c, "reasons": reasons})
    return result


def merge_clients(source_id: int, target_id: int) -> dict:
    """Mueve todo lo del cliente `source` al `target` y borra `source`. No se puede deshacer."""
    if source_id == target_id:
        raise HTTPException(400, "No se puede unir un cliente consigo mismo.")
    with get_conn() as conn:
        src = conn.execute("SELECT * FROM clients WHERE id = ?", (source_id,)).fetchone()
        dst = conn.execute("SELECT * FROM clients WHERE id = ?", (target_id,)).fetchone()
        if not src or not dst:
            raise HTTPException(404, "Cliente no encontrado.")
        moved = {}
        for table in ("client_identities", "conversations", "client_facts", "tasks", "client_notes", "notifications",
                      "attachments"):
            moved[table] = conn.execute(f"UPDATE {table} SET client_id = ? WHERE client_id = ?",
                                        (target_id, source_id)).rowcount
        conn.execute("INSERT OR IGNORE INTO client_tags (client_id, tag) SELECT ?, tag FROM client_tags WHERE client_id = ?",
                     (target_id, source_id))
        # Visitas: se conserva la más reciente de cada usuario.
        conn.execute(
            """INSERT INTO client_visits (user_id, client_id, visited_at, last_message_id)
               SELECT user_id, ?, visited_at, last_message_id FROM client_visits WHERE client_id = ?
               ON CONFLICT(user_id, client_id) DO UPDATE SET
                   visited_at = max(visited_at, excluded.visited_at),
                   last_message_id = min(last_message_id, excluded.last_message_id)""",
            (target_id, source_id))
        # Conversaciones con el asistente: las del cliente que desaparece quedan archivadas en el que se queda.
        conn.execute("UPDATE chat_sessions SET client_id = ?, archived = 1 WHERE client_id = ?", (target_id, source_id))
        # El resumen de IA del que se queda deja de estar al día: se fuerza a mostrar mensajes nuevos.
        conn.execute("UPDATE client_analysis SET last_message_id = 0 WHERE client_id = ?", (target_id,))
        conn.execute(
            """UPDATE clients SET company = coalesce(company, ?), notes = coalesce(notes, ?),
                   assignee_user_id = coalesce(assignee_user_id, ?) WHERE id = ?""",
            (src["company"], src["notes"], src["assignee_user_id"], target_id))
        conn.execute("DELETE FROM clients WHERE id = ?", (source_id,))
    return {"client_id": target_id, "moved_conversations": moved["conversations"],
            "moved_identities": moved["client_identities"]}
