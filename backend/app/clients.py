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
        return conn.execute("INSERT INTO clients (name, company, assignee_user_id) VALUES (?, ?, ?) RETURNING id",
                            (name.strip(), (company or "").strip() or None, user_id)).lastrowid


def _last_message_id(conn, client_id: int) -> int:
    return conn.execute("""SELECT coalesce(max(m.id), 0) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                            WHERE c.client_id = ?""", (client_id,)).fetchone()[0]


def update_client(client_id: int, fields: dict, user_id: int | None = None) -> None:
    """Cambia datos del cliente. Un cambio de estado hecho por una persona (user_id) queda como manual: la IA no lo
    toca hasta que lleguen mensajes nuevos."""
    allowed = {"name", "company", "status", "assignee_user_id"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if "status" in fields and fields["status"] not in STATUSES:
        raise HTTPException(400, "Estado no válido.")
    if "name" in fields and not (fields["name"] or "").strip():
        raise HTTPException(400, "El nombre es obligatorio.")
    if not fields:
        return
    with get_conn() as conn:
        sets, args = [f"{k} = ?" for k in fields], list(fields.values())
        if "status" in fields:
            current = conn.execute("SELECT status FROM clients WHERE id = ?", (client_id,)).fetchone()
            if current and current["status"] != fields["status"]:
                sets += ["status_source = 'manual'", "status_reason = NULL", "status_updated_at = localtimestamp(0)",
                         "status_updated_by = ?", "status_last_message_id = ?"]
                args += [user_id, _last_message_id(conn, client_id)]
        conn.execute(f"UPDATE clients SET {', '.join(sets)} WHERE id = ?", [*args, client_id])


def release_status(client_id: int) -> None:
    """Deshace el «fijado a mano»: el estado se queda como está hasta que lo decida la IA o la regla de inactividad."""
    with get_conn() as conn:
        conn.execute("""UPDATE clients SET status_source = 'auto', status_reason = NULL, status_updated_by = NULL
                         WHERE id = ? AND status_source = 'manual'""", (client_id,))


def set_auto_status(conn, client_id: int, status: str, reason: str) -> str | None:
    """Estado decidido por la IA o por la regla de inactividad. No pisa un cambio manual mientras no haya mensajes
    nuevos desde entonces. Devuelve el estado anterior si ha cambiado (None si no)."""
    row = conn.execute("SELECT status, status_source, status_last_message_id FROM clients WHERE id = ?",
                       (client_id,)).fetchone()
    if not row or status not in STATUSES:
        return None
    last = _last_message_id(conn, client_id)
    if row["status_source"] == "manual" and last <= (row["status_last_message_id"] or 0):
        return None
    conn.execute("""UPDATE clients SET status = ?, status_source = 'auto', status_reason = ?,
                        status_updated_at = localtimestamp(0), status_updated_by = NULL, status_last_message_id = ?
                     WHERE id = ?""", (status, reason or None, last, client_id))
    return row["status"] if row["status"] != status else None


def reactivate(client_id: int, days: int) -> bool:
    """Sin IA: un cliente inactivo que vuelve a escribir (en los últimos `days` días) pasa a Activo."""
    with get_conn() as conn:
        recent = conn.execute(
            f"""SELECT 1 FROM clients cl WHERE cl.id = ? AND cl.status = 'inactive'
                  AND EXISTS (SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id
                               WHERE c.client_id = cl.id AND m.direction = 'in'
                                 AND m.sent_at > localtimestamp - interval '{int(days or 90)} days')""",
            (client_id,)).fetchone()
        return bool(recent and set_auto_status(conn, client_id, "active", "Ha vuelto a escribir"))


def mark_inactive(days: int) -> int:
    """Regla diaria (sin IA): pasa a Inactivo a los clientes sin mensajes en `days` días. Devuelve cuántos."""
    if not days:
        return 0
    changed = 0
    with get_conn() as conn:
        stale = conn.execute(
            f"""SELECT cl.id FROM clients cl
                 WHERE cl.status != 'inactive'
                   AND NOT EXISTS (SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id
                                    WHERE c.client_id = cl.id AND m.sent_at > localtimestamp - interval '{int(days)} days')
                   AND EXISTS (SELECT 1 FROM conversations c WHERE c.client_id = cl.id)""").fetchall()
        for r in stale:
            if set_auto_status(conn, r["id"], "inactive", f"Sin mensajes en los últimos {days} días"):
                changed += 1
    return changed


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
            "SELECT min(tag) AS tag, count(*) AS clients FROM client_tags GROUP BY lower(tag) ORDER BY lower(min(tag))"))


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
                WHERE ci.channel = ? AND lower(ci.handle) = lower(?)""", (channel, handle)).fetchone()
        if other:
            if other["id"] == client_id:
                raise HTTPException(409, "Este cliente ya tiene ese identificador.")
            raise HTTPException(409, f"Ese identificador ya pertenece a «{other['name']}». "
                                     "Si es la misma persona, usa «Unir con otro cliente».")
        ident_id = conn.execute("INSERT INTO client_identities (client_id, channel, handle) VALUES (?, ?, ?) RETURNING id",
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
        conn.execute("INSERT INTO client_tags (client_id, tag) SELECT ?, tag FROM client_tags WHERE client_id = ? "
                     "ON CONFLICT DO NOTHING",
                     (target_id, source_id))
        # Visitas: se conserva la más reciente de cada usuario.
        conn.execute(
            """INSERT INTO client_visits (user_id, client_id, visited_at, last_message_id)
               SELECT user_id, ?, visited_at, last_message_id FROM client_visits WHERE client_id = ?
               ON CONFLICT(user_id, client_id) DO UPDATE SET
                   visited_at = GREATEST(client_visits.visited_at, excluded.visited_at),
                   last_message_id = LEAST(client_visits.last_message_id, excluded.last_message_id)""",
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
