"""Adjuntos y documentos de los clientes (la fila; el archivo está en disco)."""
from ..db import TS_CONFIG, Conn, rows

FIELDS = """a.id, a.client_id, a.message_id, a.filename, a.mime, a.size, a.extracted_by,
            length(a.extracted_text) AS text_length, a.created_at, u.name AS uploaded_by"""


def insert(conn: Conn, client_id: int, message_id: int | None, filename: str, mime: str, size: int, path: str,
           extracted_text: str | None, extracted_by: str | None, uploaded_by: int | None) -> int:
    return conn.execute(
        """INSERT INTO attachments (client_id, message_id, filename, mime, size, path, extracted_text,
                                    extracted_by, uploaded_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           RETURNING id""",
        (client_id, message_id, filename, mime, size, path, extracted_text, extracted_by, uploaded_by)).lastrowid


def get(conn: Conn, attachment_id: int) -> dict | None:
    row = conn.execute(f"""SELECT {FIELDS}, a.path, a.extracted_text FROM attachments a
                           LEFT JOIN users u ON u.id = a.uploaded_by WHERE a.id = ?""", (attachment_id,)).fetchone()
    return dict(row) if row else None


def owner(conn: Conn, attachment_id: int) -> dict | None:
    """Quién lo subió y de qué mensaje viene (para comprobar si se puede borrar)."""
    row = conn.execute("SELECT uploaded_by, message_id FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    return dict(row) if row else None


def list_for_client(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        f"""SELECT {FIELDS}, m.sent_at AS message_sent_at, c.channel
              FROM attachments a LEFT JOIN users u ON u.id = a.uploaded_by
              LEFT JOIN messages m ON m.id = a.message_id
              LEFT JOIN conversations c ON c.id = m.conversation_id
             WHERE a.client_id = ? ORDER BY coalesce(m.sent_at, a.created_at) DESC""", (client_id,)))


def list_for_messages(conn: Conn, message_ids: list[int]) -> list[dict]:
    # Un marcador "?" por id: solo se pega en la consulta el número de marcadores, nunca los valores.
    marks = ",".join("?" * len(message_ids))
    return rows(conn.execute(
        f"SELECT id, message_id, filename, mime, size FROM attachments WHERE message_id IN ({marks})", message_ids))


def delete(conn: Conn, attachment_id: int) -> None:
    conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))


def paths_for_client(conn: Conn, client_id: int) -> list[str]:
    return [r["path"] for r in conn.execute("SELECT path FROM attachments WHERE client_id = ?", (client_id,))]


def set_ai_text(conn: Conn, attachment_id: int, text: str) -> None:
    conn.execute("UPDATE attachments SET extracted_text = ?, extracted_by = 'ai' WHERE id = ?", (text, attachment_id))


def search(conn: Conn, query_fts: str, user_id: int, only_mine: bool, client_id: int | None, limit: int) -> list[dict]:
    """Documentos que casan con la consulta de texto completo, de más a menos relevante.

    Con `only_mine`, los adjuntos de mensajes solo de conversaciones de `user_id` (los subidos a la ficha, siempre).
    TS_CONFIG es una constante de la app (configuración de idioma), no un valor del usuario.
    """
    sql = f"""SELECT a.id AS documento_id, a.filename, a.client_id, cl.name AS client, a.extracted_by,
                    ts_headline('{TS_CONFIG}', coalesce(a.extracted_text, a.filename), q, 'StartSel=⟦, StopSel=⟧, MaxWords=35, MinWords=12, ShortWord=2, MaxFragments=2, FragmentDelimiter=" … "') AS snippet,
                    coalesce(m.sent_at, a.created_at) AS fecha, c.channel, u.name AS owner
               FROM attachments a
               CROSS JOIN to_tsquery('{TS_CONFIG}', ?) AS q
               JOIN clients cl ON cl.id = a.client_id
               LEFT JOIN messages m ON m.id = a.message_id
               LEFT JOIN conversations c ON c.id = m.conversation_id
               LEFT JOIN users u ON u.id = c.owner_user_id
              WHERE a.tsv @@ q"""
    args: list = [query_fts]
    if only_mine:
        sql += " AND (a.message_id IS NULL OR c.owner_user_id = ?)"
        args.append(user_id)
    if client_id:
        sql += " AND a.client_id = ?"
        args.append(client_id)
    sql += " ORDER BY ts_rank(a.tsv, q) DESC LIMIT ?"
    args.append(limit)
    return rows(conn.execute(sql, args))


def texts_for_client(conn: Conn, client_id: int, max_chars: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT a.filename, a.message_id, substr(a.extracted_text, 1, ?) AS text FROM attachments a
            WHERE a.client_id = ? AND a.extracted_text IS NOT NULL ORDER BY a.id DESC LIMIT 20""",
        (max_chars, client_id)))
