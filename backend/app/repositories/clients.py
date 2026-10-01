"""Clientes: datos, estado, etiquetas, identificadores, visitas y unión de duplicados."""
from ..db import Conn, rows

# Columnas que se pueden cambiar con update(): los nombres de columna se pegan en la consulta, así que solo
# se aceptan los de esta lista.
_UPDATABLE = {"name", "company", "status", "assignee_user_id"}

# Tablas cuyas filas pasan de un cliente a otro al unirlos (nombres fijos, nunca datos del usuario).
_MERGED_TABLES = ("client_identities", "conversations", "client_facts", "tasks", "client_notes", "notifications",
                  "attachments")


# ---------------------------------------------------------------- Datos del cliente

def insert(conn: Conn, name: str, company: str | None = None, assignee_user_id: int | None = None) -> int:
    return conn.execute("INSERT INTO clients (name, company, assignee_user_id) VALUES (?, ?, ?) RETURNING id",
                        (name, company, assignee_user_id)).lastrowid


def insert_named(conn: Conn, name: str) -> int:
    """Cliente nuevo solo con nombre (el que crean las integraciones al recibir mensajes)."""
    return conn.execute("INSERT INTO clients (name) VALUES (?) RETURNING id", (name,)).lastrowid


def get_basic(conn: Conn, client_id: int) -> dict | None:
    row = conn.execute("SELECT id, name FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def get(conn: Conn, client_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def get_overview(conn: Conn, client_id: int) -> dict | None:
    """Datos del cliente con el nombre de su responsable y de quien fijó el estado."""
    row = conn.execute(
        """SELECT cl.id, cl.name, cl.company, cl.notes, cl.status, cl.assignee_user_id, u.name AS assignee,
                  cl.status_source, cl.status_reason, cl.status_updated_at, su.name AS status_updated_by
             FROM clients cl LEFT JOIN users u ON u.id = cl.assignee_user_id
             LEFT JOIN users su ON su.id = cl.status_updated_by WHERE cl.id = ?""", (client_id,)
    ).fetchone()
    return dict(row) if row else None


def list_others(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute("SELECT id, name, company FROM clients WHERE id != ?", (client_id,)))


def update(conn: Conn, client_id: int, fields: dict, manual_status: dict | None = None) -> None:
    """Cambia las columnas de `fields`. Con `manual_status` ({"by": user_id, "last_message_id": n}) el estado
    queda además como fijado a mano."""
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"columnas no permitidas: {sorted(unknown)}")
    sets, args = [f"{k} = ?" for k in fields], list(fields.values())
    if manual_status is not None:
        sets += ["status_source = 'manual'", "status_reason = NULL", "status_updated_at = localtimestamp(0)",
                 "status_updated_by = ?", "status_last_message_id = ?"]
        args += [manual_status["by"], manual_status["last_message_id"]]
    conn.execute(f"UPDATE clients SET {', '.join(sets)} WHERE id = ?", [*args, client_id])


def delete(conn: Conn, client_id: int) -> None:
    conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))


def search(conn: Conn, like: str, user_id: int | None, status: str | None, tag: str | None,
           assignee_id: int | None, limit: int) -> list[dict]:
    """Clientes cuyo nombre, empresa, identificador o etiqueta coincide con `like` (patrón ILIKE; "%%" = todos).
    `unread` = mensajes nuevos desde la última visita de `user_id` (null si nunca lo ha abierto)."""
    # Filtros opcionales: fragmentos fijos; sus valores van como parámetros.
    filters, args = "", []
    if status:
        filters += " AND cl.status = ?"
        args.append(status)
    if tag:
        filters += " AND EXISTS (SELECT 1 FROM client_tags t WHERE t.client_id = cl.id AND t.tag = ?)"
        args.append(tag)
    if assignee_id:
        filters += " AND cl.assignee_user_id = ?"
        args.append(assignee_id)
    return rows(conn.execute(
        f"""
        SELECT cl.id, cl.name, cl.company, cl.status, cl.assignee_user_id,
               (SELECT string_agg(t.tag, '|') FROM client_tags t WHERE t.client_id = cl.id) AS tags,
               (SELECT string_agg(DISTINCT ci.channel, ',') FROM client_identities ci
                 WHERE ci.client_id = cl.id) AS channels,
               (SELECT max(m.sent_at) FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                 WHERE c.client_id = cl.id) AS last_message_at,
               CASE WHEN v.user_id IS NULL THEN NULL ELSE
                   (SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                     WHERE c.client_id = cl.id AND m.id > v.last_message_id) END AS unread
          FROM clients cl
          LEFT JOIN client_visits v ON v.client_id = cl.id AND v.user_id = ?
         WHERE (? = '%%'
                OR unaccent(cl.name) ILIKE unaccent(?) OR unaccent(cl.company) ILIKE unaccent(?)
                OR EXISTS (SELECT 1 FROM client_identities ci
                            WHERE ci.client_id = cl.id AND ci.handle ILIKE ?)
                OR EXISTS (SELECT 1 FROM client_tags t
                            WHERE t.client_id = cl.id AND unaccent(t.tag) ILIKE unaccent(?))) {filters}
         ORDER BY last_message_at DESC NULLS LAST, cl.name
         LIMIT ?
        """,
        (user_id, like, like, like, like, like, *args, limit),
    ))


# ---------------------------------------------------------------- Estado

def get_status(conn: Conn, client_id: int) -> dict | None:
    row = conn.execute("SELECT status, status_source, status_last_message_id FROM clients WHERE id = ?",
                       (client_id,)).fetchone()
    return dict(row) if row else None


def release_status(conn: Conn, client_id: int) -> None:
    conn.execute("""UPDATE clients SET status_source = 'auto', status_reason = NULL, status_updated_by = NULL
                     WHERE id = ? AND status_source = 'manual'""", (client_id,))


def set_auto_status(conn: Conn, client_id: int, status: str, reason: str | None, last_message_id: int) -> None:
    conn.execute("""UPDATE clients SET status = ?, status_source = 'auto', status_reason = ?,
                        status_updated_at = localtimestamp(0), status_updated_by = NULL, status_last_message_id = ?
                     WHERE id = ?""", (status, reason, last_message_id, client_id))


def is_inactive_with_recent_message(conn: Conn, client_id: int, days: int) -> bool:
    """¿Está Inactivo y ha escrito el cliente en los últimos `days` días?"""
    return conn.execute(
        """SELECT 1 FROM clients cl WHERE cl.id = ? AND cl.status = 'inactive'
              AND EXISTS (SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id
                           WHERE c.client_id = cl.id AND m.direction = 'in'
                             AND m.sent_at > localtimestamp - make_interval(days => ?))""",
        (client_id, days)).fetchone() is not None


def stale_ids(conn: Conn, days: int) -> list[int]:
    """Clientes no inactivos, con alguna conversación, sin mensajes en los últimos `days` días."""
    return [r["id"] for r in conn.execute(
        """SELECT cl.id FROM clients cl
            WHERE cl.status != 'inactive'
              AND NOT EXISTS (SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id
                               WHERE c.client_id = cl.id AND m.sent_at > localtimestamp - make_interval(days => ?))
              AND EXISTS (SELECT 1 FROM conversations c WHERE c.client_id = cl.id)""", (days,)).fetchall()]


# ---------------------------------------------------------------- Etiquetas

def replace_tags(conn: Conn, client_id: int, tags: list[str]) -> None:
    conn.execute("DELETE FROM client_tags WHERE client_id = ?", (client_id,))
    conn.executemany("INSERT INTO client_tags (client_id, tag) VALUES (?, ?)", [(client_id, t) for t in tags])


def tags_of(conn: Conn, client_id: int) -> list[str]:
    return [r["tag"] for r in conn.execute(
        "SELECT tag FROM client_tags WHERE client_id = ? ORDER BY lower(tag)", (client_id,))]


def all_tags(conn: Conn) -> list[dict]:
    return rows(conn.execute(
        "SELECT min(tag) AS tag, count(*) AS clients FROM client_tags GROUP BY lower(tag) ORDER BY lower(min(tag))"))


# ---------------------------------------------------------------- Identificadores

def identity_owner(conn: Conn, channel: str, handle: str) -> dict | None:
    """Cliente (id, name) que ya usa ese identificador en ese canal (sin distinguir mayúsculas)."""
    row = conn.execute(
        """SELECT cl.id, cl.name FROM client_identities ci JOIN clients cl ON cl.id = ci.client_id
            WHERE ci.channel = ? AND lower(ci.handle) = lower(?)""", (channel, handle)).fetchone()
    return dict(row) if row else None


def client_id_for_identity(conn: Conn, channel: str, handle: str) -> int | None:
    """Cliente con ese identificador exacto en ese canal."""
    row = conn.execute("SELECT client_id FROM client_identities WHERE channel = ? AND handle = ?",
                       (channel, handle)).fetchone()
    return row["client_id"] if row else None


def insert_identity(conn: Conn, client_id: int, channel: str, handle: str) -> int:
    return conn.execute("INSERT INTO client_identities (client_id, channel, handle) VALUES (?, ?, ?) RETURNING id",
                        (client_id, channel, handle)).lastrowid


def delete_identity(conn: Conn, identity_id: int) -> bool:
    return conn.execute("DELETE FROM client_identities WHERE id = ?", (identity_id,)).rowcount > 0


def identities_of(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        "SELECT id, channel, handle FROM client_identities WHERE client_id = ? ORDER BY channel, handle",
        (client_id,)))


def all_identities(conn: Conn) -> list[dict]:
    return rows(conn.execute("SELECT client_id, channel, handle FROM client_identities"))


# ---------------------------------------------------------------- Visitas

def get_visit(conn: Conn, user_id: int, client_id: int) -> dict | None:
    row = conn.execute("SELECT visited_at, last_message_id FROM client_visits WHERE user_id = ? AND client_id = ?",
                       (user_id, client_id)).fetchone()
    return dict(row) if row else None


def save_visit(conn: Conn, user_id: int, client_id: int, last_message_id: int) -> None:
    conn.execute(
        """INSERT INTO client_visits (user_id, client_id, visited_at, last_message_id)
           VALUES (?, ?, localtimestamp(0), ?)
           ON CONFLICT(user_id, client_id) DO UPDATE SET visited_at = excluded.visited_at,
               last_message_id = excluded.last_message_id""",
        (user_id, client_id, last_message_id))


# ---------------------------------------------------------------- Unión de clientes

def move_related(conn: Conn, source_id: int, target_id: int) -> dict[str, int]:
    """Pasa al cliente `target` las filas de `source` en cada tabla relacionada. Devuelve cuántas por tabla."""
    return {table: conn.execute(f"UPDATE {table} SET client_id = ? WHERE client_id = ?",
                                (target_id, source_id)).rowcount
            for table in _MERGED_TABLES}


def copy_tags(conn: Conn, source_id: int, target_id: int) -> None:
    conn.execute("INSERT INTO client_tags (client_id, tag) SELECT ?, tag FROM client_tags WHERE client_id = ? "
                 "ON CONFLICT DO NOTHING",
                 (target_id, source_id))


def merge_visits(conn: Conn, source_id: int, target_id: int) -> None:
    # Visitas: se conserva la más reciente de cada usuario.
    conn.execute(
        """INSERT INTO client_visits (user_id, client_id, visited_at, last_message_id)
           SELECT user_id, ?, visited_at, last_message_id FROM client_visits WHERE client_id = ?
           ON CONFLICT(user_id, client_id) DO UPDATE SET
               visited_at = GREATEST(client_visits.visited_at, excluded.visited_at),
               last_message_id = LEAST(client_visits.last_message_id, excluded.last_message_id)""",
        (target_id, source_id))


def archive_assistant_chats(conn: Conn, source_id: int, target_id: int) -> None:
    # Conversaciones con el asistente: las del cliente que desaparece quedan archivadas en el que se queda.
    conn.execute("UPDATE chat_sessions SET client_id = ?, archived = 1 WHERE client_id = ?", (target_id, source_id))


def reset_analysis(conn: Conn, client_id: int) -> None:
    """Pone a 0 el último mensaje analizado: el resumen de IA se da por desactualizado."""
    conn.execute("UPDATE client_analysis SET last_message_id = 0 WHERE client_id = ?", (client_id,))


def fill_missing(conn: Conn, client_id: int, company: str | None, notes: str | None,
                 assignee_user_id: int | None) -> None:
    """Completa empresa, notas y responsable solo si el cliente no los tiene."""
    conn.execute(
        """UPDATE clients SET company = coalesce(company, ?), notes = coalesce(notes, ?),
               assignee_user_id = coalesce(assignee_user_id, ?) WHERE id = ?""",
        (company, notes, assignee_user_id, client_id))
