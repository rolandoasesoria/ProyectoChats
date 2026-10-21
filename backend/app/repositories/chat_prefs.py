"""Cómo organiza cada usuario su lista de chats (fijar, archivar, silenciar y marcar como no leído), sus mensajes
destacados (★) y lo que se ha compartido en cada chat (fotos, vídeos, documentos y enlaces)."""
from ..db import Conn, rows
from .conversations import scope_clause

PREF_COLUMNS = ("pinned_at", "archived_at", "muted_until", "marked_unread")
EMPTY = {"pinned_at": None, "archived_at": None, "muted_until": None, "marked_unread": 0}


def get(conn: Conn, user_id: int, client_id: int) -> dict:
    row = conn.execute("""SELECT pinned_at, archived_at, muted_until, marked_unread FROM chat_prefs
                           WHERE user_id = ? AND client_id = ?""", (user_id, client_id)).fetchone()
    return dict(row) if row else dict(EMPTY)


def save(conn: Conn, user_id: int, client_id: int, values: dict) -> None:
    """Guarda las columnas de `values` (solo las de PREF_COLUMNS: los nombres de columna los pone el código)."""
    cols = [c for c in PREF_COLUMNS if c in values]
    conn.execute(
        f"""INSERT INTO chat_prefs (user_id, client_id, {", ".join(cols)}) VALUES (?, ?, {", ".join("?" * len(cols))})
            ON CONFLICT (user_id, client_id) DO UPDATE SET {", ".join(f"{c} = excluded.{c}" for c in cols)}""",
        (user_id, client_id, *[values[c] for c in cols]))


def pinned_count(conn: Conn, user_id: int) -> int:
    return conn.execute("SELECT count(*) AS n FROM chat_prefs WHERE user_id = ? AND pinned_at IS NOT NULL",
                        (user_id,)).fetchone()["n"]


def clear_unread(conn: Conn, user_id: int, client_id: int) -> None:
    """Al abrir el chat deja de estar «marcado como no leído»."""
    conn.execute("UPDATE chat_prefs SET marked_unread = 0 WHERE user_id = ? AND client_id = ? AND marked_unread = 1",
                 (user_id, client_id))


def unarchive(conn: Conn, client_id: int) -> None:
    """El cliente ha escrito: su chat vuelve a la lista de quien lo tenía archivado (como en WhatsApp)."""
    conn.execute("UPDATE chat_prefs SET archived_at = NULL WHERE client_id = ? AND archived_at IS NOT NULL", (client_id,))


def merge(conn: Conn, source_id: int, target_id: int) -> None:
    """Al unir dos clientes, cada usuario conserva cómo tenía el chat que se queda y suma lo del otro: fijado,
    silenciado o marcado como no leído (si el que se queda estaba a la vista, no pasa a archivados)."""
    conn.execute(
        """INSERT INTO chat_prefs (user_id, client_id, pinned_at, archived_at, muted_until, marked_unread)
           SELECT user_id, ?, pinned_at, archived_at, muted_until, marked_unread FROM chat_prefs WHERE client_id = ?
           ON CONFLICT (user_id, client_id) DO UPDATE SET
               pinned_at = coalesce(chat_prefs.pinned_at, excluded.pinned_at),
               muted_until = coalesce(chat_prefs.muted_until, excluded.muted_until),
               marked_unread = greatest(chat_prefs.marked_unread, excluded.marked_unread)""",
        (target_id, source_id))


# ---------------------------------------------------------------- Mensajes destacados

def set_star(conn: Conn, user_id: int, message_id: int, on: bool) -> None:
    if on:
        conn.execute("INSERT INTO starred_messages (user_id, message_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                     (user_id, message_id))
    else:
        conn.execute("DELETE FROM starred_messages WHERE user_id = ? AND message_id = ?", (user_id, message_id))


def starred(conn: Conn, user_id: int, client_id: int | None, limit: int) -> list[dict]:
    """Los mensajes que destacó el usuario (de un cliente o de todos), el último destacado primero."""
    client_sql, client_args = (" AND c.client_id = ?", [client_id]) if client_id else ("", [])
    return rows(conn.execute(
        f"""SELECT m.id, m.direction, m.sender, m.body, m.sent_at, s.created_at AS starred_at,
                   c.id AS conversation_id, c.channel, cl.id AS client_id, cl.name AS client
              FROM starred_messages s
              JOIN messages m ON m.id = s.message_id
              JOIN conversations c ON c.id = m.conversation_id
              JOIN clients cl ON cl.id = c.client_id
             WHERE s.user_id = ? {client_sql}
             ORDER BY s.created_at DESC, m.id DESC
             LIMIT ?""",
        [user_id, *client_args, limit]))


# ---------------------------------------------------------------- Lo compartido en el chat

def shared_files(conn: Conn, client_id: int, user_id: int, scope: str, limit: int) -> list[dict]:
    """Archivos enviados y recibidos en las conversaciones del cliente (en el alcance), el más reciente primero."""
    scope_sql, scope_args = scope_clause(scope, user_id)
    return rows(conn.execute(
        f"""SELECT a.id, a.filename, a.mime, a.size, m.id AS message_id, m.sent_at, m.direction, m.sender, c.channel
              FROM attachments a
              JOIN messages m ON m.id = a.message_id
              JOIN conversations c ON c.id = m.conversation_id
             WHERE c.client_id = ? {scope_sql}
             ORDER BY m.sent_at DESC, a.id DESC
             LIMIT ?""",
        [client_id, *scope_args, limit]))


def messages_with_links(conn: Conn, client_id: int, user_id: int, scope: str, limit: int) -> list[dict]:
    """Mensajes de WhatsApp y Telegram con algún enlace (los correos traen muchos de firmas y bajas: no se cuentan)."""
    scope_sql, scope_args = scope_clause(scope, user_id)
    return rows(conn.execute(
        f"""SELECT m.id, m.body, m.sent_at, m.direction, m.sender, c.channel
              FROM messages m
              JOIN conversations c ON c.id = m.conversation_id
             WHERE c.client_id = ? AND c.channel <> 'email' AND m.body ~* 'https{{0,1}}://' {scope_sql}
             ORDER BY m.sent_at DESC, m.id DESC
             LIMIT ?""",
        [client_id, *scope_args, limit]))
