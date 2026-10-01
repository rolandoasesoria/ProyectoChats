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
from .repositories import users as users_repo

SCOPES = conversations_repo.SCOPES


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
        return users_repo.list_contacts(conn)


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


def unanswered(user_id: int, scope: str = "mine", snoozed: bool = False) -> list[dict]:
    """Conversaciones cuyo último mensaje es del cliente (esperan respuesta), la más antigua primero.

    Se excluyen las marcadas como atendidas y las pospuestas, salvo que el cliente haya escrito algo después.
    Con snoozed=True devuelve justo las pospuestas.
    """
    with get_conn() as conn:
        return conversations_repo.unanswered(conn, user_id, scope, snoozed)


def dismiss_unanswered(conversation_id: int, message_id: int) -> bool:
    with get_conn() as conn:
        return conversations_repo.set_dismissed(conn, conversation_id, message_id)


def snooze(conversation_id: int, until: str | None, message_id: int | None = None) -> bool:
    """Pospone la conversación hasta `until` (UTC). Si el cliente escribe después de `message_id`, vuelve antes."""
    with get_conn() as conn:
        return conversations_repo.set_snooze(conn, conversation_id, until, message_id if until else None)


def last_message_id(conversation_id: int) -> int:
    """Id del último mensaje de la conversación (0 si no tiene)."""
    with get_conn() as conn:
        return messages_repo.last_id_in_conversation(conn, conversation_id)


def newer_messages(conversation_id: int, after_message_id: int) -> list[dict]:
    """Quién ha escrito (direction, sender) en la conversación después de `after_message_id`."""
    with get_conn() as conn:
        return messages_repo.newer_in_conversation(conn, conversation_id, after_message_id)


def conversation_client_id(conversation_id: int) -> int | None:
    """Cliente al que pertenece la conversación (None si no existe)."""
    with get_conn() as conn:
        return conversations_repo.client_id_of(conn, conversation_id)


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
    fts = _fts_query(query)
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


def import_conversation(payload: dict) -> dict:
    """Guarda mensajes de una conversación (los que traen las integraciones). Crea el cliente/identidad si no existen.

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
        ident_client_id = clients_repo.client_id_for_identity(conn, payload["channel"], payload["handle"])
        client_id = payload.get("client_id") or ident_client_id
        if not client_id:
            client_id = clients_repo.insert_named(conn, payload.get("client_name") or payload["handle"])
        if ident_client_id is None:
            clients_repo.insert_identity(conn, client_id, payload["channel"], payload["handle"])
        # Recibir el mismo mensaje dos veces es seguro: se reutiliza la conversación existente (mismo cliente, dueño, canal y asunto)
        # y se saltan los mensajes que ya estaban (misma fecha y mismo texto).
        conv_id = conversations_repo.find(conn, client_id, payload["owner_user_id"], payload["channel"],
                                          payload.get("subject"))
        if conv_id is None:
            conv_id = conversations_repo.insert(conn, client_id, payload["owner_user_id"], payload["channel"],
                                                payload.get("subject"))
        seen = messages_repo.existing_keys(conn, conv_id)
        seen_ext = messages_repo.existing_external_ids(conn, conv_id)
        new, files = 0, 0
        for m in payload["messages"]:
            key = (m["sent_at"], m["body"])
            ext = m.get("external_id")
            if key in seen or (ext and ext in seen_ext):
                continue
            seen.add(key)
            if ext:
                seen_ext.add(ext)
            message_id = messages_repo.insert(conn, conv_id, m["direction"], m["sender"], m["body"], m["sent_at"],
                                              ext)
            new += 1
            for f in m.get("attachments") or []:
                attachments.save(conn, client_id, f["filename"], f["data"], f.get("mime"), message_id,
                                 payload["owner_user_id"])
                files += 1
    return {"client_id": client_id, "conversation_id": conv_id, "messages": new,
            "duplicates": len(payload["messages"]) - new, "attachments": files}
