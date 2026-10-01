"""Consultas sobre clientes y mensajes.

Todas las funciones reciben `user_id` y `scope`:
- scope="mine": solo conversaciones cuyo dueño es el usuario actual.
- scope="team": conversaciones de cualquier miembro del equipo.
El control de alcance se aplica aquí (en el servidor), no en el modelo.
"""
import re

from . import attachments
from .db import TS_CONFIG, get_conn, rows

SCOPES = ("mine", "team")


def _scope_clause(scope: str, user_id: int, alias: str = "c") -> tuple[str, list]:
    if scope not in SCOPES:
        raise ValueError(f"alcance inválido: {scope}")
    if scope == "mine":
        return f" AND {alias}.owner_user_id = ?", [user_id]
    return "", []


def _fts_query(text: str) -> str:
    """Convierte texto libre en una consulta segura para to_tsquery: términos OR con prefijo.

    La configuración es_unaccent quita tildes y reduce a la raíz ("entregas" -> "entreg"), así que
    "direccion", "dirección" o "direcciones" encuentran lo mismo.
    """
    terms = [t for t in re.findall(r"[^\W_]+", text, flags=re.UNICODE) if len(t) > 1]
    if not terms:
        return ""
    return " | ".join(f"{t}:*" for t in terms)


def _markers(snippet: str | None, markers: tuple[str, str]) -> str:
    """ts_headline marca las coincidencias con ⟦ ⟧; se cambian por las marcas pedidas."""
    return (snippet or "").replace("⟦", markers[0]).replace("⟧", markers[1])


def list_users() -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute("SELECT id, name, email FROM users ORDER BY name"))


def find_clients(query: str = "", limit: int = 50, user_id: int | None = None, status: str | None = None,
                 tag: str | None = None, assignee_id: int | None = None) -> list[dict]:
    """Clientes que coinciden con la búsqueda y los filtros. Con `user_id`, `unread` = mensajes nuevos
    desde su última visita a ese cliente (null si nunca lo ha abierto)."""
    like = f"%{query.strip()}%"
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
    with get_conn() as conn:
        result = rows(conn.execute(
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
    for c in result:
        c["tags"] = sorted(c["tags"].split("|"), key=str.lower) if c["tags"] else []
    return result


def unanswered(user_id: int, scope: str = "mine", snoozed: bool = False) -> list[dict]:
    """Conversaciones cuyo último mensaje es del cliente (esperan respuesta), la más antigua primero.

    Se excluyen las marcadas como atendidas y las pospuestas, salvo que el cliente haya escrito algo después.
    Con snoozed=True devuelve justo las pospuestas.
    """
    scope_sql, scope_args = _scope_clause(scope, user_id)
    is_snoozed = "(c.snoozed_until > localtimestamp AND c.snoozed_message_id >= last.id)"
    with get_conn() as conn:
        return rows(conn.execute(
            f"""
            WITH last AS (
                SELECT m.*, row_number() OVER (PARTITION BY m.conversation_id
                                               ORDER BY m.sent_at DESC, m.id DESC) AS rn
                  FROM messages m
            )
            SELECT c.id AS conversation_id, c.channel, c.subject, cl.id AS client_id, cl.name AS client,
                   u.name AS owner, c.owner_user_id = ? AS is_mine,
                   last.id AS message_id, last.sender, last.body, last.sent_at,
                   CASE WHEN {is_snoozed} THEN c.snoozed_until END AS snoozed_until
              FROM conversations c
              JOIN last ON last.conversation_id = c.id AND last.rn = 1
              JOIN clients cl ON cl.id = c.client_id
              JOIN users u ON u.id = c.owner_user_id
             WHERE last.direction = 'in'
               AND (c.dismissed_message_id IS NULL OR c.dismissed_message_id < last.id)
               AND {"" if snoozed else "NOT "}coalesce({is_snoozed}, false) {scope_sql}
             ORDER BY {"c.snoozed_until" if snoozed else "last.sent_at"} ASC
            """,
            [user_id, *scope_args],
        ))


def dismiss_unanswered(conversation_id: int, message_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("UPDATE conversations SET dismissed_message_id = ? WHERE id = ?",
                           (message_id, conversation_id))
    return cur.rowcount > 0


def snooze(conversation_id: int, until: str | None, message_id: int | None = None) -> bool:
    """Pospone la conversación hasta `until` (UTC). Si el cliente escribe después de `message_id`, vuelve antes."""
    with get_conn() as conn:
        cur = conn.execute("UPDATE conversations SET snoozed_until = ?, snoozed_message_id = ? WHERE id = ?",
                           (until, message_id if until else None, conversation_id))
    return cur.rowcount > 0


def record_visit(user_id: int, client_id: int) -> dict:
    """Registra que el usuario abre el cliente. Devuelve lo que ha llegado desde la visita anterior."""
    with get_conn() as conn:
        prev = conn.execute(
            "SELECT visited_at, last_message_id FROM client_visits WHERE user_id = ? AND client_id = ?",
            (user_id, client_id)).fetchone()
        stats = conn.execute(
            """SELECT coalesce(max(m.id), 0) AS max_id, count(CASE WHEN m.id > ? THEN 1 END) AS new
                 FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE c.client_id = ?""",
            (prev["last_message_id"] if prev else 0, client_id)).fetchone()
        conn.execute(
            """INSERT INTO client_visits (user_id, client_id, visited_at, last_message_id)
               VALUES (?, ?, localtimestamp(0), ?)
               ON CONFLICT(user_id, client_id) DO UPDATE SET visited_at = excluded.visited_at,
                   last_message_id = excluded.last_message_id""",
            (user_id, client_id, stats["max_id"]))
    return {
        "previous_visit_at": prev["visited_at"] if prev else None,
        "since_message_id": prev["last_message_id"] if prev else None,
        "new_messages": stats["new"] if prev else 0,
    }


def messages_since(client_id: int, since_message_id: int, limit: int = 300) -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute(
            """SELECT m.id, m.direction, m.sender, m.body, m.sent_at, c.channel, u.name AS owner
                 FROM messages m JOIN conversations c ON c.id = m.conversation_id
                 JOIN users u ON u.id = c.owner_user_id
                WHERE c.client_id = ? AND m.id > ? ORDER BY m.sent_at, m.id LIMIT ?""",
            (client_id, since_message_id, limit)))


def client_overview(client_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        client = conn.execute(
            """SELECT cl.id, cl.name, cl.company, cl.notes, cl.status, cl.assignee_user_id, u.name AS assignee
                 FROM clients cl LEFT JOIN users u ON u.id = cl.assignee_user_id WHERE cl.id = ?""", (client_id,)
        ).fetchone()
        if not client:
            return None
        identities = rows(conn.execute(
            "SELECT id, channel, handle FROM client_identities WHERE client_id = ? ORDER BY channel, handle",
            (client_id,),
        ))
        tags = [r["tag"] for r in conn.execute(
            "SELECT tag FROM client_tags WHERE client_id = ? ORDER BY lower(tag)", (client_id,))]
        conversations = rows(conn.execute(
            """
            SELECT c.id, c.channel, c.subject, u.id AS owner_id, u.name AS owner,
                   count(m.id) AS messages, min(m.sent_at) AS first_at, max(m.sent_at) AS last_at
              FROM conversations c
              JOIN users u ON u.id = c.owner_user_id
              LEFT JOIN messages m ON m.conversation_id = c.id
             WHERE c.client_id = ?
             GROUP BY c.id, u.id
             ORDER BY last_at DESC
            """,
            (client_id,),
        ))
    for conv in conversations:
        conv["is_mine"] = conv["owner_id"] == user_id
    return {**dict(client), "tags": tags, "identities": identities, "conversations": conversations}


def timeline(client_id: int, user_id: int, scope: str = "mine",
             channel: str | None = None, limit: int = 500) -> list[dict]:
    """Todos los mensajes de un cliente, de todos los canales, en orden cronológico."""
    scope_sql, scope_args = _scope_clause(scope, user_id)
    channel_sql, channel_args = (" AND c.channel = ?", [channel]) if channel else ("", [])
    with get_conn() as conn:
        result = rows(conn.execute(
            f"""
            SELECT * FROM (
                SELECT m.id, m.direction, m.sender, m.body, m.sent_at,
                       c.id AS conversation_id, c.channel, c.owner_user_id AS owner_id, u.name AS owner
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  JOIN users u ON u.id = c.owner_user_id
                 WHERE c.client_id = ? {scope_sql} {channel_sql}
                 ORDER BY m.sent_at DESC, m.id DESC
                 LIMIT ?
            ) ORDER BY sent_at ASC, id ASC
            """,
            [client_id, *scope_args, *channel_args, limit],
        ))
    files = attachments.by_message([m["id"] for m in result])
    for m in result:
        m["attachments"] = files.get(m["id"], [])
    return result


def search_messages(query: str, user_id: int, scope: str = "mine",
                    client_id: int | None = None, channels: list[str] | None = None,
                    date_from: str | None = None, date_to: str | None = None,
                    limit: int = 20, markers: tuple[str, str] = ("[", "]")) -> list[dict]:
    """Búsqueda de texto completo. `markers` rodean los términos encontrados en el fragmento."""
    fts = _fts_query(query)
    if not fts:
        return []
    scope_sql, args = _scope_clause(scope, user_id)
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
    args.append(min(limit, 50))
    with get_conn() as conn:
        result = rows(conn.execute(sql, args))
    for r in result:
        r["snippet"] = _markers(r["snippet"], markers)
    return result


def message_context(message_id: int, user_id: int, scope: str = "mine",
                    window: int = 8) -> dict | None:
    """Mensajes alrededor de uno dado, dentro de su misma conversación."""
    scope_sql, scope_args = _scope_clause(scope, user_id)
    with get_conn() as conn:
        target = conn.execute(
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
        if not target:
            return None
        window = max(1, min(window, 25))
        before = rows(conn.execute(
            """SELECT id, direction, sender, body, sent_at FROM messages
                WHERE conversation_id = ? AND (sent_at, id) < (?, ?)
                ORDER BY sent_at DESC, id DESC LIMIT ?""",
            (target["conversation_id"], target["sent_at"], target["id"], window),
        ))
        after = rows(conn.execute(
            """SELECT id, direction, sender, body, sent_at FROM messages
                WHERE conversation_id = ? AND (sent_at, id) >= (?, ?)
                ORDER BY sent_at ASC, id ASC LIMIT ?""",
            (target["conversation_id"], target["sent_at"], target["id"], window + 1),
        ))
    return {
        "conversation_id": target["conversation_id"],
        "channel": target["channel"],
        "client": target["client"],
        "owner": target["owner"],
        "messages": list(reversed(before)) + after,
    }


def import_conversation(payload: dict) -> dict:
    """Importa una conversación. Crea el cliente/identidad si no existen.

    payload = {
      "owner_user_id": 1,
      "channel": "whatsapp",
      "handle": "+34600111222",
      "client_name": "Laura Gómez",     # usado si la identidad es nueva
      "client_id": null,                # opcional: forzar a qué cliente asociar
      "subject": "...",
      "messages": [{"direction": "in", "sender": "Laura", "body": "...", "sent_at": "2026-09-01T10:00:00"}]
    }
    """
    with get_conn() as conn:
        ident = conn.execute(
            "SELECT client_id FROM client_identities WHERE channel = ? AND handle = ?",
            (payload["channel"], payload["handle"]),
        ).fetchone()
        client_id = payload.get("client_id") or (ident["client_id"] if ident else None)
        if not client_id:
            client_id = conn.execute(
                "INSERT INTO clients (name) VALUES (?) RETURNING id",
                (payload.get("client_name") or payload["handle"],),
            ).lastrowid
        if not ident:
            conn.execute(
                "INSERT INTO client_identities (client_id, channel, handle) VALUES (?, ?, ?)",
                (client_id, payload["channel"], payload["handle"]),
            )
        # Reimportar es seguro: se reutiliza la conversación existente (mismo cliente, dueño, canal y asunto)
        # y se saltan los mensajes que ya estaban (misma fecha y mismo texto).
        existing = conn.execute(
            """SELECT id FROM conversations
                WHERE client_id = ? AND owner_user_id = ? AND channel = ? AND subject IS NOT DISTINCT FROM ?""",
            (client_id, payload["owner_user_id"], payload["channel"], payload.get("subject")),
        ).fetchone()
        if existing:
            conv_id = existing["id"]
        else:
            conv_id = conn.execute(
                "INSERT INTO conversations (client_id, owner_user_id, channel, subject) VALUES (?, ?, ?, ?) RETURNING id",
                (client_id, payload["owner_user_id"], payload["channel"], payload.get("subject")),
            ).lastrowid
        seen = {(r["sent_at"], r["body"]) for r in conn.execute(
            "SELECT sent_at, body FROM messages WHERE conversation_id = ?", (conv_id,))}
        seen_ext = {r["external_id"] for r in conn.execute(
            "SELECT external_id FROM messages WHERE conversation_id = ? AND external_id IS NOT NULL", (conv_id,))}
        new, files = 0, 0
        for m in payload["messages"]:
            key = (m["sent_at"], m["body"])
            ext = m.get("external_id")
            if key in seen or (ext and ext in seen_ext):
                continue
            seen.add(key)
            if ext:
                seen_ext.add(ext)
            message_id = conn.execute(
                """INSERT INTO messages (conversation_id, direction, sender, body, sent_at, external_id)
                   VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
                (conv_id, m["direction"], m["sender"], m["body"], m["sent_at"], ext)).lastrowid
            new += 1
            for f in m.get("attachments") or []:
                attachments.save(conn, client_id, f["filename"], f["data"], f.get("mime"), message_id,
                                 payload["owner_user_id"])
                files += 1
    return {"client_id": client_id, "conversation_id": conv_id, "messages": new,
            "duplicates": len(payload["messages"]) - new, "attachments": files}
