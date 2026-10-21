"""Conversaciones: bandeja «Sin responder», posponer, marcar como atendida y alta desde las integraciones."""
from ..db import Conn, rows

SCOPES = ("mine", "team")


def scope_clause(scope: str, user_id: int, alias: str = "c") -> tuple[str, list]:
    """Filtro de alcance sobre la conversación `alias`: "mine" = solo las del usuario; "team" = todas.
    `alias` lo pone siempre el código (nunca el usuario)."""
    if scope not in SCOPES:
        raise ValueError(f"alcance inválido: {scope}")
    if scope == "mine":
        return f" AND {alias}.owner_user_id = ?", [user_id]
    return "", []


def unanswered(conn: Conn, user_id: int, scope: str, snoozed: bool) -> list[dict]:
    """Conversaciones cuyo último mensaje es del cliente, sin atender; las pospuestas solo con `snoozed`."""
    scope_sql, scope_args = scope_clause(scope, user_id)
    # Fragmentos fijos: cuál se usa depende solo de `snoozed`.
    is_snoozed = "(c.snoozed_until > localtimestamp AND c.snoozed_message_id >= last.id)"
    return rows(conn.execute(
        f"""
        WITH last AS (
            SELECT m.*, row_number() OVER (PARTITION BY m.conversation_id
                                           ORDER BY m.sent_at DESC, m.id DESC) AS rn
              FROM messages m
        )
        SELECT c.id AS conversation_id, c.channel, c.subject, cl.id AS client_id, cl.name AS client,
               u.name AS owner, c.owner_user_id = ? AS is_mine, cl.assignee_user_id AS assignee_id, au.name AS assignee,
               last.id AS message_id, last.sender, last.body, last.sent_at,
               CASE WHEN {is_snoozed} THEN c.snoozed_until END AS snoozed_until,
               ca.priority, ca.mood, ca.priority_reason
          FROM conversations c
          JOIN last ON last.conversation_id = c.id AND last.rn = 1
          JOIN clients cl ON cl.id = c.client_id
          JOIN users u ON u.id = c.owner_user_id
          LEFT JOIN users au ON au.id = cl.assignee_user_id
          LEFT JOIN client_analysis ca ON ca.client_id = cl.id
         WHERE last.direction = 'in'
           AND (c.dismissed_message_id IS NULL OR c.dismissed_message_id < last.id)
           AND {"" if snoozed else "NOT "}coalesce({is_snoozed}, false) {scope_sql}
         ORDER BY {"c.snoozed_until" if snoozed else "last.sent_at"} ASC
        """,
        [user_id, *scope_args],
    ))


def set_dismissed(conn: Conn, conversation_id: int, message_id: int) -> bool:
    return conn.execute("UPDATE conversations SET dismissed_message_id = ? WHERE id = ?",
                        (message_id, conversation_id)).rowcount > 0


def set_snooze(conn: Conn, conversation_id: int, until: str | None, message_id: int | None) -> bool:
    return conn.execute("UPDATE conversations SET snoozed_until = ?, snoozed_message_id = ? WHERE id = ?",
                        (until, message_id, conversation_id)).rowcount > 0


def client_id_of(conn: Conn, conversation_id: int) -> int | None:
    row = conn.execute("SELECT client_id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return row["client_id"] if row else None


def chat_list(conn: Conn, user_id: int, scope: str, like: str, unread_only: bool, limit: int) -> list[dict]:
    """Clientes con mensajes en el alcance, el más reciente primero, con su último mensaje y cuántos ha escrito el
    cliente desde la última vez que `user_id` abrió su chat (todos los recibidos si nunca lo ha abierto)."""
    scope_sql, scope_args = scope_clause(scope, user_id)
    scope2_sql, scope2_args = scope_clause(scope, user_id, alias="c2")
    unread_sql = " WHERE unread > 0" if unread_only else ""  # fragmento fijo
    return rows(conn.execute(
        f"""
        SELECT * FROM (
          SELECT cl.id, cl.name, cl.company, cl.status, cl.assignee_user_id, u.name AS assignee,
                 (SELECT string_agg(t.tag, '|') FROM client_tags t WHERE t.client_id = cl.id) AS tags,
                 (SELECT string_agg(DISTINCT c2.channel, ',') FROM conversations c2
                   WHERE c2.client_id = cl.id {scope2_sql}) AS channels,
                 l.body AS last_body, l.sent_at AS last_at, l.direction AS last_direction, l.channel AS last_channel,
                 (SELECT count(*) FROM messages m2 JOIN conversations c2 ON c2.id = m2.conversation_id
                   WHERE c2.client_id = cl.id AND m2.direction = 'in'
                     AND m2.id > coalesce(v.last_message_id, 0) {scope2_sql}) AS unread
            FROM (SELECT DISTINCT ON (c.client_id) c.client_id, m.body, m.sent_at, m.direction, c.channel
                    FROM messages m JOIN conversations c ON c.id = m.conversation_id
                   WHERE TRUE {scope_sql}
                   ORDER BY c.client_id, m.sent_at DESC, m.id DESC) l
            JOIN clients cl ON cl.id = l.client_id
            LEFT JOIN users u ON u.id = cl.assignee_user_id
            LEFT JOIN client_visits v ON v.client_id = cl.id AND v.user_id = ?
           WHERE (? = '%%' OR unaccent(cl.name) ILIKE unaccent(?) OR unaccent(cl.company) ILIKE unaccent(?)
                  OR EXISTS (SELECT 1 FROM client_identities ci WHERE ci.client_id = cl.id AND ci.handle ILIKE ?))
        ) chats{unread_sql}
         ORDER BY last_at DESC
         LIMIT ?
        """,
        (*scope2_args, *scope2_args, *scope_args, user_id, like, like, like, like, limit),
    ))


def list_for_client(conn: Conn, client_id: int) -> list[dict]:
    """Conversaciones del cliente con su dueño, número de mensajes y fechas del primero y del último."""
    return rows(conn.execute(
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


def find(conn: Conn, client_id: int, owner_user_id: int, channel: str, subject: str | None) -> int | None:
    """Conversación con el mismo cliente, dueño, canal y asunto (el asunto puede ser nulo)."""
    row = conn.execute(
        """SELECT id FROM conversations
            WHERE client_id = ? AND owner_user_id = ? AND channel = ? AND subject IS NOT DISTINCT FROM ?""",
        (client_id, owner_user_id, channel, subject),
    ).fetchone()
    return row["id"] if row else None


def insert(conn: Conn, client_id: int, owner_user_id: int, channel: str, subject: str | None) -> int:
    return conn.execute(
        "INSERT INTO conversations (client_id, owner_user_id, channel, subject) VALUES (?, ?, ?, ?) RETURNING id",
        (client_id, owner_user_id, channel, subject),
    ).lastrowid


def owned_in_channel(conn: Conn, client_id: int, owner_user_id: int, channel: str) -> list[dict]:
    """Conversaciones del cliente por ese canal que entraron por la cuenta de `owner_user_id`."""
    return rows(conn.execute(
        """SELECT id, read_receipt_upto FROM conversations WHERE client_id = ? AND owner_user_id = ? AND channel = ?""",
        (client_id, owner_user_id, channel)))


def set_read_receipt(conn: Conn, conversation_id: int, message_id: int) -> None:
    """Ya se avisó a WhatsApp de que está leído hasta `message_id` incluido."""
    conn.execute("UPDATE conversations SET read_receipt_upto = greatest(read_receipt_upto, ?) WHERE id = ?",
                 (message_id, conversation_id))
