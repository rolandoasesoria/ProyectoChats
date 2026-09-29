"""Consultas sobre clientes y mensajes.

Todas las funciones reciben `user_id` y `scope`:
- scope="mine": solo conversaciones cuyo dueño es el usuario actual.
- scope="team": conversaciones de cualquier miembro del equipo.
El control de alcance se aplica aquí (en el servidor), no en el modelo.
"""
import re

from .db import get_conn, rows

SCOPES = ("mine", "team")


def _scope_clause(scope: str, user_id: int, alias: str = "c") -> tuple[str, list]:
    if scope not in SCOPES:
        raise ValueError(f"alcance inválido: {scope}")
    if scope == "mine":
        return f" AND {alias}.owner_user_id = ?", [user_id]
    return "", []


def _fts_query(text: str) -> str:
    """Convierte texto libre en una consulta FTS5 segura: términos OR con prefijo."""
    terms = [t for t in re.findall(r"\w+", text, flags=re.UNICODE) if len(t) > 1]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"*' for t in terms)


def list_users() -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute("SELECT id, name, email FROM users ORDER BY name"))


def find_clients(query: str = "", limit: int = 50) -> list[dict]:
    like = f"%{query.strip()}%"
    with get_conn() as conn:
        return rows(conn.execute(
            """
            SELECT cl.id, cl.name, cl.company,
                   (SELECT group_concat(DISTINCT ci.channel) FROM client_identities ci
                     WHERE ci.client_id = cl.id) AS channels,
                   (SELECT max(m.sent_at) FROM messages m
                      JOIN conversations c ON c.id = m.conversation_id
                     WHERE c.client_id = cl.id) AS last_message_at
              FROM clients cl
             WHERE ? = '%%'
                OR cl.name LIKE ? OR cl.company LIKE ?
                OR EXISTS (SELECT 1 FROM client_identities ci
                            WHERE ci.client_id = cl.id AND ci.handle LIKE ?)
             ORDER BY last_message_at DESC NULLS LAST, cl.name
             LIMIT ?
            """,
            (like, like, like, like, limit),
        ))


def client_overview(client_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        client = conn.execute(
            "SELECT id, name, company, notes FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if not client:
            return None
        identities = rows(conn.execute(
            "SELECT channel, handle FROM client_identities WHERE client_id = ? ORDER BY channel",
            (client_id,),
        ))
        conversations = rows(conn.execute(
            """
            SELECT c.id, c.channel, c.subject, u.id AS owner_id, u.name AS owner,
                   count(m.id) AS messages, min(m.sent_at) AS first_at, max(m.sent_at) AS last_at
              FROM conversations c
              JOIN users u ON u.id = c.owner_user_id
              LEFT JOIN messages m ON m.conversation_id = c.id
             WHERE c.client_id = ?
             GROUP BY c.id
             ORDER BY last_at DESC
            """,
            (client_id,),
        ))
    for conv in conversations:
        conv["is_mine"] = conv["owner_id"] == user_id
    return {**dict(client), "identities": identities, "conversations": conversations}


def timeline(client_id: int, user_id: int, scope: str = "mine",
             channel: str | None = None, limit: int = 500) -> list[dict]:
    """Todos los mensajes de un cliente, de todos los canales, en orden cronológico."""
    scope_sql, scope_args = _scope_clause(scope, user_id)
    channel_sql, channel_args = (" AND c.channel = ?", [channel]) if channel else ("", [])
    with get_conn() as conn:
        return rows(conn.execute(
            f"""
            SELECT * FROM (
                SELECT m.id, m.direction, m.sender, m.body, m.sent_at,
                       c.id AS conversation_id, c.channel, u.name AS owner
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  JOIN users u ON u.id = c.owner_user_id
                 WHERE c.client_id = ? {scope_sql} {channel_sql}
                 ORDER BY m.sent_at DESC
                 LIMIT ?
            ) ORDER BY sent_at ASC
            """,
            [client_id, *scope_args, *channel_args, limit],
        ))


def search_messages(query: str, user_id: int, scope: str = "mine",
                    client_id: int | None = None, channels: list[str] | None = None,
                    date_from: str | None = None, date_to: str | None = None,
                    limit: int = 20) -> list[dict]:
    fts = _fts_query(query)
    if not fts:
        return []
    scope_sql, args = _scope_clause(scope, user_id)
    sql = f"""
        SELECT m.id AS message_id, m.sent_at, m.direction, m.sender,
               snippet(messages_fts, 0, '[', ']', '…', 24) AS snippet,
               c.id AS conversation_id, c.channel, cl.id AS client_id, cl.name AS client,
               u.name AS owner
          FROM messages_fts
          JOIN messages m ON m.id = messages_fts.rowid
          JOIN conversations c ON c.id = m.conversation_id
          JOIN clients cl ON cl.id = c.client_id
          JOIN users u ON u.id = c.owner_user_id
         WHERE messages_fts MATCH ? {scope_sql}
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
    sql += " ORDER BY bm25(messages_fts) LIMIT ?"
    args.append(min(limit, 50))
    with get_conn() as conn:
        return rows(conn.execute(sql, args))


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
                "INSERT INTO clients (name) VALUES (?)",
                (payload.get("client_name") or payload["handle"],),
            ).lastrowid
        if not ident:
            conn.execute(
                "INSERT INTO client_identities (client_id, channel, handle) VALUES (?, ?, ?)",
                (client_id, payload["channel"], payload["handle"]),
            )
        conv_id = conn.execute(
            "INSERT INTO conversations (client_id, owner_user_id, channel, subject) VALUES (?, ?, ?, ?)",
            (client_id, payload["owner_user_id"], payload["channel"], payload.get("subject")),
        ).lastrowid
        conn.executemany(
            "INSERT INTO messages (conversation_id, direction, sender, body, sent_at) VALUES (?, ?, ?, ?, ?)",
            [(conv_id, m["direction"], m["sender"], m["body"], m["sent_at"]) for m in payload["messages"]],
        )
    return {"client_id": client_id, "conversation_id": conv_id, "messages": len(payload["messages"])}
