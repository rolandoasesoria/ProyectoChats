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
               u.name AS owner, c.owner_user_id = ? AS is_mine,
               last.id AS message_id, last.sender, last.body, last.sent_at,
               CASE WHEN {is_snoozed} THEN c.snoozed_until END AS snoozed_until,
               ca.priority, ca.mood, ca.priority_reason
          FROM conversations c
          JOIN last ON last.conversation_id = c.id AND last.rn = 1
          JOIN clients cl ON cl.id = c.client_id
          JOIN users u ON u.id = c.owner_user_id
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
