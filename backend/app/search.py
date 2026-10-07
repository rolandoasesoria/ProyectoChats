"""Consultas sobre clientes y mensajes.

Todas las funciones reciben `user_id` y `scope`:
- scope="mine": solo conversaciones cuyo dueño es el usuario actual.
- scope="team": conversaciones de cualquier miembro del equipo.
El control de alcance se aplica aquí (en el servidor), no en el modelo.
"""
import re

from . import attachments
from .db import get_conn
from .repositories import clients as clients_repo
from .repositories import conversations as conversations_repo
from .repositories import messages as messages_repo


def fts_query(text: str) -> str:
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


def find_clients(query: str = "", limit: int = 50, user_id: int | None = None, status: str | None = None,
                 tag: str | None = None, assignee_id: int | None = None) -> list[dict]:
    """Clientes que coinciden con la búsqueda y los filtros. Con `user_id`, `unread` = mensajes nuevos
    desde su última visita a ese cliente (null si nunca lo ha abierto)."""
    like = f"%{query.strip()}%"
    with get_conn() as conn:
        result = clients_repo.search(conn, like, user_id, status, tag, assignee_id, limit)
    for c in result:
        c["tags"] = sorted(c["tags"].split("|"), key=str.lower) if c["tags"] else []
    return result


def record_visit(user_id: int, client_id: int) -> dict:
    """Registra que el usuario abre el cliente. Devuelve lo que ha llegado desde la visita anterior."""
    with get_conn() as conn:
        prev = clients_repo.get_visit(conn, user_id, client_id)
        stats = messages_repo.client_stats_since(conn, client_id, prev["last_message_id"] if prev else 0)
        clients_repo.save_visit(conn, user_id, client_id, stats["max_id"])
    return {
        "previous_visit_at": prev["visited_at"] if prev else None,
        "since_message_id": prev["last_message_id"] if prev else None,
        "new_messages": stats["new"] if prev else 0,
    }


def messages_since(client_id: int, since_message_id: int, limit: int = 300) -> list[dict]:
    with get_conn() as conn:
        return messages_repo.since_for_client(conn, client_id, since_message_id, limit)


def client_overview(client_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        client = clients_repo.get_overview(conn, client_id)
        if not client:
            return None
        identities = clients_repo.identities_of(conn, client_id)
        tags = clients_repo.tags_of(conn, client_id)
        conversations = conversations_repo.list_for_client(conn, client_id)
    for conv in conversations:
        conv["is_mine"] = conv["owner_id"] == user_id
    return {**client, "tags": tags, "identities": identities, "conversations": conversations}


def timeline(client_id: int, user_id: int, scope: str = "mine",
             channel: str | None = None, limit: int = 500) -> list[dict]:
    """Todos los mensajes de un cliente, de todos los canales, en orden cronológico."""
    with get_conn() as conn:
        result = messages_repo.timeline(conn, client_id, user_id, scope, channel, limit)
    files = attachments.by_message([m["id"] for m in result])
    for m in result:
        m["attachments"] = files.get(m["id"], [])
    return result


def search_messages(query: str, user_id: int, scope: str = "mine",
                    client_id: int | None = None, channels: list[str] | None = None,
                    date_from: str | None = None, date_to: str | None = None,
                    limit: int = 20, markers: tuple[str, str] = ("[", "]")) -> list[dict]:
    """Búsqueda de texto completo. `markers` rodean los términos encontrados en el fragmento."""
    fts = fts_query(query)
    if not fts:
        return []
    with get_conn() as conn:
        result = messages_repo.search(conn, fts, user_id, scope, client_id, channels, date_from, date_to,
                                      min(limit, 50))
    for r in result:
        r["snippet"] = _markers(r["snippet"], markers)
    return result


def message_context(message_id: int, user_id: int, scope: str = "mine",
                    window: int = 8) -> dict | None:
    """Mensajes alrededor de uno dado, dentro de su misma conversación."""
    with get_conn() as conn:
        target = messages_repo.locate(conn, message_id, user_id, scope)
        if not target:
            return None
        window = max(1, min(window, 25))
        before = messages_repo.before(conn, target["conversation_id"], target["sent_at"], target["id"], window)
        after = messages_repo.from_onwards(conn, target["conversation_id"], target["sent_at"], target["id"],
                                           window + 1)
    return {
        "conversation_id": target["conversation_id"],
        "channel": target["channel"],
        "client": target["client"],
        "owner": target["owner"],
        "messages": list(reversed(before)) + after,
    }
