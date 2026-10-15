"""Registro de accesos y acciones delicadas."""
from .db import get_conn
from .repositories import audit as repo

ACTIONS = {
    "team_messages": "Vio mensajes de conversaciones del equipo",
    "team_search": "Buscó en conversaciones del equipo",
    "assistant_team_search": "El asistente buscó en conversaciones del equipo",
    "team_inbox": "Vio la bandeja «Sin responder» del equipo",
    "team_chats": "Vio los chats del equipo",
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
