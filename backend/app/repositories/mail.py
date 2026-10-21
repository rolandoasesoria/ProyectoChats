"""Correo en bandejas: los correos de las conversaciones de email, uno por fila (Recibidos, Enviados, Destacados), y
cuáles ha leído cada usuario."""
from ..db import Conn, rows
from .conversations import scope_clause

# Un correo recibido está sin leer si el usuario no lo ha abierto en la bandeja ni ha abierto el chat del cliente
# después de que llegara.
UNREAD_SQL = """(m.direction = 'in' AND m.id > coalesce(v.last_message_id, 0)
                 AND NOT EXISTS (SELECT 1 FROM mail_reads r WHERE r.message_id = m.id AND r.user_id = ?))"""
FOLDERS = {
    "inbox": " AND m.direction = 'in'",
    "sent": " AND m.direction = 'out'",
    "starred": " AND EXISTS (SELECT 1 FROM starred_messages s WHERE s.message_id = m.id AND s.user_id = ?)",
}


def _filters(user_id: int, scope: str, folder: str, query: str, client_id: int | None) -> tuple[str, list]:
    """Condiciones fijas (las elige el código) y sus valores."""
    scope_sql, args = scope_clause(scope, user_id)
    sql = scope_sql + FOLDERS[folder]
    if folder == "starred":
        args.append(user_id)
    if client_id:
        sql += " AND c.client_id = ?"
        args.append(client_id)
    if query:
        like = f"%{query}%"
        sql += """ AND (unaccent(m.body) ILIKE unaccent(?) OR unaccent(coalesce(c.subject, '')) ILIKE unaccent(?)
                        OR unaccent(m.sender) ILIKE unaccent(?) OR unaccent(cl.name) ILIKE unaccent(?))"""
        args += [like] * 4
    return sql, args


def mailbox(conn: Conn, user_id: int, scope: str, folder: str, query: str, client_id: int | None, limit: int,
            offset: int) -> list[dict]:
    """Los correos de la carpeta, el más reciente primero."""
    sql, args = _filters(user_id, scope, folder, query, client_id)
    return rows(conn.execute(
        f"""SELECT m.id, m.direction, m.sender, substr(m.body, 1, 240) AS snippet, m.sent_at,
                   c.id AS conversation_id, c.subject, c.owner_user_id AS owner_id, u.name AS owner,
                   cl.id AS client_id, cl.name AS client,
                   EXISTS (SELECT 1 FROM attachments a WHERE a.message_id = m.id) AS has_files,
                   EXISTS (SELECT 1 FROM starred_messages s WHERE s.message_id = m.id AND s.user_id = ?) AS starred,
                   {UNREAD_SQL} AS unread
              FROM messages m
              JOIN conversations c ON c.id = m.conversation_id
              JOIN clients cl ON cl.id = c.client_id
              JOIN users u ON u.id = c.owner_user_id
              LEFT JOIN client_visits v ON v.client_id = cl.id AND v.user_id = ?
             WHERE c.channel = 'email' {sql}
             ORDER BY m.sent_at DESC, m.id DESC
             LIMIT ? OFFSET ?""",
        [user_id, user_id, user_id, *args, limit, offset]))


def unread_count(conn: Conn, user_id: int, scope: str) -> int:
    scope_sql, args = scope_clause(scope, user_id)
    return conn.execute(
        f"""SELECT count(*) AS n
              FROM messages m
              JOIN conversations c ON c.id = m.conversation_id
              LEFT JOIN client_visits v ON v.client_id = c.client_id AND v.user_id = ?
             WHERE c.channel = 'email' AND {UNREAD_SQL} {scope_sql}""",
        [user_id, user_id, *args]).fetchone()["n"]


def email(conn: Conn, user_id: int, message_id: int) -> dict | None:
    """Un correo con su conversación, su cliente y si está destacado."""
    row = conn.execute(
        """SELECT m.id, m.direction, m.sender, m.body, m.sent_at, m.by_ai,
                  c.id AS conversation_id, c.subject, c.owner_user_id AS owner_id, u.name AS owner,
                  cl.id AS client_id, cl.name AS client,
                  EXISTS (SELECT 1 FROM starred_messages s WHERE s.message_id = m.id AND s.user_id = ?) AS starred
             FROM messages m
             JOIN conversations c ON c.id = m.conversation_id
             JOIN clients cl ON cl.id = c.client_id
             JOIN users u ON u.id = c.owner_user_id
            WHERE m.id = ? AND c.channel = 'email'""",
        (user_id, message_id)).fetchone()
    return dict(row) if row else None


def thread(conn: Conn, conversation_id: int) -> list[dict]:
    """Los correos del hilo (la conversación), del primero al último."""
    return rows(conn.execute(
        """SELECT id, direction, sender, substr(body, 1, 240) AS snippet, sent_at
             FROM messages WHERE conversation_id = ? ORDER BY sent_at, id""",
        (conversation_id,)))


def client_addresses(conn: Conn, client_id: int) -> list[str]:
    return [r["handle"] for r in conn.execute(
        "SELECT handle FROM client_identities WHERE client_id = ? AND channel = 'email' ORDER BY id", (client_id,))]


def mark_read(conn: Conn, user_id: int, message_id: int) -> None:
    conn.execute("INSERT INTO mail_reads (user_id, message_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (user_id, message_id))


def mark_all_read(conn: Conn, user_id: int, scope: str) -> int:
    """Marca como leídos todos los recibidos sin leer de la bandeja. Devuelve cuántos."""
    scope_sql, args = scope_clause(scope, user_id)
    return conn.execute(
        f"""INSERT INTO mail_reads (user_id, message_id)
            SELECT ?, m.id
              FROM messages m
              JOIN conversations c ON c.id = m.conversation_id
              LEFT JOIN client_visits v ON v.client_id = c.client_id AND v.user_id = ?
             WHERE c.channel = 'email' AND {UNREAD_SQL} {scope_sql}
            ON CONFLICT DO NOTHING""",
        [user_id, user_id, user_id, *args]).rowcount
