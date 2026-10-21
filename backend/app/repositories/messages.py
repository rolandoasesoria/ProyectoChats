"""Mensajes: últimos ids, novedades, línea de tiempo, búsqueda de texto completo, alta desde las integraciones,
estado de entrega y reacciones."""
from ..db import TS_CONFIG, Conn, rows
from .conversations import scope_clause


def last_id_in_conversation(conn: Conn, conversation_id: int) -> int:
    """Id del último mensaje de la conversación (0 si no tiene)."""
    return conn.execute("SELECT coalesce(max(id), 0) FROM messages WHERE conversation_id = ?",
                        (conversation_id,)).fetchone()[0]


def last_id_for_client(conn: Conn, client_id: int) -> int:
    """Id del último mensaje del cliente en cualquier conversación (0 si no tiene)."""
    return conn.execute("""SELECT coalesce(max(m.id), 0) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                            WHERE c.client_id = ?""", (client_id,)).fetchone()[0]


def newer_in_conversation(conn: Conn, conversation_id: int, after_message_id: int) -> list[dict]:
    """Quién ha escrito (direction, sender) en la conversación después de `after_message_id`."""
    return rows(conn.execute(
        """SELECT direction, sender FROM messages WHERE conversation_id = ? AND id > ? ORDER BY id""",
        (conversation_id, after_message_id)))


def client_stats_since(conn: Conn, client_id: int, after_message_id: int) -> dict:
    """Último id de mensaje del cliente (max_id) y cuántos hay después de `after_message_id` (new)."""
    return dict(conn.execute(
        """SELECT coalesce(max(m.id), 0) AS max_id, count(CASE WHEN m.id > ? THEN 1 END) AS new
             FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE c.client_id = ?""",
        (after_message_id, client_id)).fetchone())


def since_for_client(conn: Conn, client_id: int, since_message_id: int, limit: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT m.id, m.direction, m.sender, m.body, m.sent_at, c.channel, u.name AS owner
             FROM messages m JOIN conversations c ON c.id = m.conversation_id
             JOIN users u ON u.id = c.owner_user_id
            WHERE c.client_id = ? AND m.id > ? ORDER BY m.sent_at, m.id LIMIT ?""",
        (client_id, since_message_id, limit)))


def timeline(conn: Conn, client_id: int, user_id: int, scope: str, channel: str | None, limit: int) -> list[dict]:
    """Los últimos `limit` mensajes del cliente (todos los canales, o solo `channel`), en orden cronológico."""
    scope_sql, scope_args = scope_clause(scope, user_id)
    channel_sql, channel_args = (" AND c.channel = ?", [channel]) if channel else ("", [])
    return rows(conn.execute(
        f"""
        SELECT * FROM (
            SELECT m.id, m.direction, m.sender, m.body, m.sent_at, m.by_ai,
                   m.status, m.status_error, m.delivered_at, m.read_at,
                   coalesce(m.external_id LIKE 'wa:%', false) AS reactable,
                   m.reply_to_id, r.sender AS reply_sender, r.direction AS reply_direction,
                   substr(r.body, 1, 200) AS reply_body,
                   c.id AS conversation_id, c.channel, c.owner_user_id AS owner_id, u.name AS owner
              FROM messages m
              JOIN conversations c ON c.id = m.conversation_id
              JOIN users u ON u.id = c.owner_user_id
              LEFT JOIN messages r ON r.id = m.reply_to_id
             WHERE c.client_id = ? {scope_sql} {channel_sql}
             ORDER BY m.sent_at DESC, m.id DESC
             LIMIT ?
        ) ORDER BY sent_at ASC, id ASC
        """,
        [client_id, *scope_args, *channel_args, limit],
    ))


def search(conn: Conn, fts: str, user_id: int, scope: str, client_id: int | None, channels: list[str] | None,
           date_from: str | None, date_to: str | None, limit: int) -> list[dict]:
    """Búsqueda de texto completo (`fts` en formato to_tsquery). El fragmento marca las coincidencias con ⟦ ⟧."""
    scope_sql, args = scope_clause(scope, user_id)
    # TS_CONFIG es una constante del código; los filtros opcionales son fragmentos fijos con sus valores como
    # parámetros.
    sql = f"""
        SELECT m.id AS message_id, m.sent_at, m.direction, m.sender,
               ts_headline('{TS_CONFIG}', m.body, q, 'StartSel=⟦, StopSel=⟧, MaxWords=35, MinWords=12, ShortWord=2, MaxFragments=2, FragmentDelimiter=" … "') AS snippet,
               c.id AS conversation_id, c.channel, cl.id AS client_id, cl.name AS client,
               u.name AS owner
          FROM messages m
          CROSS JOIN to_tsquery('{TS_CONFIG}', ?) AS q
          JOIN conversations c ON c.id = m.conversation_id
          JOIN clients cl ON cl.id = c.client_id
          JOIN users u ON u.id = c.owner_user_id
         WHERE m.tsv @@ q {scope_sql}
    """
    args = [fts, *args]
    if client_id:
        sql += " AND c.client_id = ?"
        args.append(client_id)
    if channels:
        sql += f" AND c.channel IN ({','.join('?' * len(channels))})"
        args.extend(channels)
    if date_from:
        sql += " AND m.sent_at >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND m.sent_at <= ?"
        args.append(date_to)
    sql += " ORDER BY ts_rank(m.tsv, q) DESC, m.sent_at DESC LIMIT ?"
    args.append(limit)
    return rows(conn.execute(sql, args))


def locate(conn: Conn, message_id: int, user_id: int, scope: str) -> dict | None:
    """El mensaje con su conversación, canal, cliente y dueño, si está dentro del alcance."""
    scope_sql, scope_args = scope_clause(scope, user_id)
    row = conn.execute(
        f"""
        SELECT m.id, m.conversation_id, m.sent_at, c.channel, cl.name AS client, u.name AS owner
          FROM messages m
          JOIN conversations c ON c.id = m.conversation_id
          JOIN clients cl ON cl.id = c.client_id
          JOIN users u ON u.id = c.owner_user_id
         WHERE m.id = ? {scope_sql}
        """,
        [message_id, *scope_args],
    ).fetchone()
    return dict(row) if row else None


def before(conn: Conn, conversation_id: int, sent_at: str, message_id: int, limit: int) -> list[dict]:
    """Los `limit` mensajes anteriores a (sent_at, message_id) en la conversación, del más reciente al más antiguo."""
    return rows(conn.execute(
        """SELECT id, direction, sender, body, sent_at FROM messages
            WHERE conversation_id = ? AND (sent_at, id) < (?, ?)
            ORDER BY sent_at DESC, id DESC LIMIT ?""",
        (conversation_id, sent_at, message_id, limit),
    ))


def from_onwards(conn: Conn, conversation_id: int, sent_at: str, message_id: int, limit: int) -> list[dict]:
    """Los `limit` mensajes desde (sent_at, message_id) incluido, en orden cronológico."""
    return rows(conn.execute(
        """SELECT id, direction, sender, body, sent_at FROM messages
            WHERE conversation_id = ? AND (sent_at, id) >= (?, ?)
            ORDER BY sent_at ASC, id ASC LIMIT ?""",
        (conversation_id, sent_at, message_id, limit),
    ))


def existing_keys(conn: Conn, conversation_id: int) -> set[tuple]:
    """(sent_at, body) de los mensajes que ya tiene la conversación."""
    return {(r["sent_at"], r["body"]) for r in conn.execute(
        "SELECT sent_at, body FROM messages WHERE conversation_id = ?", (conversation_id,))}


def existing_external_ids(conn: Conn, conversation_id: int) -> set[str]:
    return {r["external_id"] for r in conn.execute(
        "SELECT external_id FROM messages WHERE conversation_id = ? AND external_id IS NOT NULL", (conversation_id,))}


def insert(conn: Conn, conversation_id: int, direction: str, sender: str, body: str, sent_at: str,
           external_id: str | None, reply_to_id: int | None = None) -> int:
    return conn.execute(
        """INSERT INTO messages (conversation_id, direction, sender, body, sent_at, external_id, reply_to_id)
           VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id""",
        (conversation_id, direction, sender, body, sent_at, external_id, reply_to_id)).lastrowid


def id_by_external(conn: Conn, conversation_id: int, external_id: str) -> int | None:
    """Id del mensaje de la conversación con ese identificador externo (el que cita una respuesta)."""
    row = conn.execute("SELECT id FROM messages WHERE conversation_id = ? AND external_id = ? ORDER BY id LIMIT 1",
                       (conversation_id, external_id)).fetchone()
    return row["id"] if row else None


def by_external(conn: Conn, external_id: str) -> dict | None:
    """El mensaje con ese identificador externo, con su estado de entrega (para los avisos de WhatsApp)."""
    row = conn.execute(
        """SELECT id, status, delivered_at, read_at FROM messages WHERE external_id = ?
            ORDER BY id DESC LIMIT 1""", (external_id,)).fetchone()
    return dict(row) if row else None


def update_status(conn: Conn, message_id: int, status: str, error: str | None, delivered_at: str | None,
                  read_at: str | None) -> None:
    conn.execute("UPDATE messages SET status = ?, status_error = ?, delivered_at = ?, read_at = ? WHERE id = ?",
                 (status, error, delivered_at, read_at, message_id))


def with_conversation(conn: Conn, message_id: int) -> dict | None:
    """El mensaje con su conversación (canal, cliente y dueño): para citarlo o reaccionar a él."""
    row = conn.execute(
        """SELECT m.id, m.direction, m.external_id, m.conversation_id, c.channel, c.client_id, c.owner_user_id
             FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE m.id = ?""",
        (message_id,)).fetchone()
    return dict(row) if row else None


def latest_incoming_external(conn: Conn, conversation_id: int, prefix: str) -> dict | None:
    """El último mensaje del cliente cuyo identificador externo empieza por `prefix` (p. ej. «wa:»)."""
    row = conn.execute(
        """SELECT id, external_id FROM messages
            WHERE conversation_id = ? AND direction = 'in' AND external_id LIKE ?
            ORDER BY sent_at DESC, id DESC LIMIT 1""",
        (conversation_id, prefix + "%")).fetchone()
    return dict(row) if row else None


def reactions_for(conn: Conn, message_ids: list[int]) -> list[dict]:
    if not message_ids:
        return []
    marks = ",".join("?" * len(message_ids))
    return rows(conn.execute(
        f"""SELECT r.message_id, r.side, r.emoji, u.name AS user FROM message_reactions r
              LEFT JOIN users u ON u.id = r.user_id
             WHERE r.message_id IN ({marks}) ORDER BY r.side""", message_ids))


def set_reaction(conn: Conn, message_id: int, side: str, emoji: str, user_id: int | None) -> None:
    """La reacción de un lado (cliente o equipo) al mensaje; sustituye a la que hubiera."""
    conn.execute(
        """INSERT INTO message_reactions (message_id, side, emoji, user_id) VALUES (?, ?, ?, ?)
           ON CONFLICT (message_id, side) DO UPDATE
              SET emoji = excluded.emoji, user_id = excluded.user_id, reacted_at = localtimestamp(0)""",
        (message_id, side, emoji, user_id))


def delete_reaction(conn: Conn, message_id: int, side: str) -> None:
    conn.execute("DELETE FROM message_reactions WHERE message_id = ? AND side = ?", (message_id, side))
