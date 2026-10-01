"""Registro de accesos y acciones delicadas, y derechos de protección de datos (exportar y borrar un cliente)."""
from . import attachments
from .db import get_conn
from .repositories import audit as repo

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
        if throttle and repo.logged_recently(conn, user_id, action, client_id, THROTTLE_MINUTES):
            return
        name = repo.client_name(conn, client_id) if client_id is not None else None
        repo.insert(conn, user_id, action, client_id, name, detail)


def entries(limit: int = 300, user_id: int | None = None, action: str | None = None) -> list[dict]:
    with get_conn() as conn:
        result = repo.list_entries(conn, limit, user_id, action)
    for r in result:
        r["action_label"] = ACTIONS.get(r["action"], r["action"])
    return result


def export_client(client_id: int) -> dict | None:
    """Todos los datos guardados de un cliente (derecho de acceso / portabilidad)."""
    with get_conn() as conn:
        client = repo.get_client(conn, client_id)
        if not client:
            return None
        conversations = repo.client_conversations(conn, client_id)
        for conv in conversations:
            conv["messages"] = repo.conversation_messages(conn, conv["id"])
        return {
            "client": client,
            "identities": repo.client_identities(conn, client_id),
            "tags": repo.client_tags(conn, client_id),
            "facts": repo.client_facts(conn, client_id),
            "summary": repo.client_summary(conn, client_id),
            "tasks": repo.client_tasks(conn, client_id),
            "notes": repo.client_notes(conn, client_id),
            "conversations": conversations,
            "documents": repo.client_documents(conn, client_id),
        }


def delete_client(client_id: int) -> dict:
    """Borra el cliente y, en cascada, sus conversaciones, mensajes, datos, tareas, notas, avisos y
    conversaciones con el asistente (derecho de supresión)."""
    attachments.delete_files_for_client(client_id)
    with get_conn() as conn:
        counts = {
            "conversations": repo.count_conversations(conn, client_id),
            "messages": repo.count_messages(conn, client_id),
        }
        repo.delete_client(conn, client_id)
    return counts
