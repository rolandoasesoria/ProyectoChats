"""Registro de accesos y acciones delicadas, y derechos de protección de datos (exportar y borrar un cliente)."""
from . import attachments
from .db import get_conn, rows

ACTIONS = {
    "team_messages": "Vio mensajes de conversaciones del equipo",
    "team_search": "Buscó en conversaciones del equipo",
    "assistant_team_search": "El asistente buscó en conversaciones del equipo",
    "team_inbox": "Vio la bandeja «Sin responder» del equipo",
    "client_export": "Exportó todos los datos del cliente",
    "client_delete": "Borró el cliente y todos sus datos",
    "client_merge": "Unió dos clientes",
    "user_create": "Creó una cuenta",
    "user_update": "Modificó una cuenta",
    "integration_change": "Cambió una integración de canal",
    "message_sent": "Envió un mensaje al cliente desde la app",
    "settings_change": "Cambió los ajustes del equipo",
    "message_redact": "Ocultó datos sensibles de un mensaje",
    "retention_apply": "Borró mensajes antiguos (retención)",
}
THROTTLE_MINUTES = 10  # las consultas repetidas en poco tiempo cuentan como un solo acceso


def log(user_id: int, action: str, client_id: int | None = None, detail: str | None = None,
        throttle: bool = False) -> None:
    with get_conn() as conn:
        if throttle and conn.execute(
                f"""SELECT 1 FROM audit_log WHERE user_id = ? AND action = ? AND client_id IS NOT DISTINCT FROM ?
                     AND created_at > localtimestamp - interval '{THROTTLE_MINUTES} minutes'""",
                (user_id, action, client_id)).fetchone():
            return
        name = None
        if client_id is not None:
            row = conn.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
            name = row["name"] if row else None
        conn.execute("INSERT INTO audit_log (user_id, action, client_id, client_name, detail) VALUES (?, ?, ?, ?, ?)",
                     (user_id, action, client_id, name, detail))


def entries(limit: int = 300, user_id: int | None = None, action: str | None = None) -> list[dict]:
    sql = """SELECT a.id, a.created_at, a.action, a.client_id, a.client_name, a.detail, u.name AS user
               FROM audit_log a LEFT JOIN users u ON u.id = a.user_id WHERE 1 = 1"""
    args: list = []
    if user_id:
        sql += " AND a.user_id = ?"
        args.append(user_id)
    if action:
        sql += " AND a.action = ?"
        args.append(action)
    sql += " ORDER BY a.id DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        result = rows(conn.execute(sql, args))
    for r in result:
        r["action_label"] = ACTIONS.get(r["action"], r["action"])
    return result


def export_client(client_id: int) -> dict | None:
    """Todos los datos guardados de un cliente (derecho de acceso / portabilidad)."""
    with get_conn() as conn:
        client = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not client:
            return None
        conversations = rows(conn.execute(
            """SELECT c.id, c.channel, c.subject, c.created_at, u.name AS owner FROM conversations c
                 JOIN users u ON u.id = c.owner_user_id WHERE c.client_id = ? ORDER BY c.id""", (client_id,)))
        for conv in conversations:
            conv["messages"] = rows(conn.execute(
                "SELECT direction, sender, body, sent_at FROM messages WHERE conversation_id = ? ORDER BY sent_at, id",
                (conv["id"],)))
        analysis = conn.execute("SELECT summary, analyzed_at FROM client_analysis WHERE client_id = ?",
                                (client_id,)).fetchone()
        return {
            "client": dict(client),
            "identities": rows(conn.execute("SELECT channel, handle FROM client_identities WHERE client_id = ?", (client_id,))),
            "tags": [r["tag"] for r in conn.execute("SELECT tag FROM client_tags WHERE client_id = ?", (client_id,))],
            "facts": rows(conn.execute(
                "SELECT label, value, origin, updated_at FROM client_facts WHERE client_id = ? AND origin != 'dismissed'",
                (client_id,))),
            "summary": dict(analysis) if analysis else None,
            "tasks": rows(conn.execute(
                "SELECT title, due_date, status, created_at, done_at FROM tasks WHERE client_id = ?", (client_id,))),
            "notes": rows(conn.execute(
                """SELECT n.body, n.created_at, u.name AS author FROM client_notes n
                     LEFT JOIN users u ON u.id = n.user_id WHERE n.client_id = ?""", (client_id,))),
            "conversations": conversations,
            "documents": rows(conn.execute(
                """SELECT filename, mime, size, message_id, created_at, extracted_text FROM attachments
                    WHERE client_id = ?""", (client_id,))),
        }


def delete_client(client_id: int) -> dict:
    """Borra el cliente y, en cascada, sus conversaciones, mensajes, datos, tareas, notas, avisos y
    conversaciones con el asistente (derecho de supresión)."""
    attachments.delete_files_for_client(client_id)
    with get_conn() as conn:
        counts = {
            "conversations": conn.execute("SELECT count(*) FROM conversations WHERE client_id = ?", (client_id,)).fetchone()[0],
            "messages": conn.execute(
                """SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.client_id = ?""", (client_id,)).fetchone()[0],
        }
        conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    return counts
