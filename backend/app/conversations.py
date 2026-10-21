"""Conversaciones: guardar los mensajes que llegan (integraciones, importación, datos de ejemplo) y consultar su
estado (último mensaje, lo nuevo desde que se empezó a escribir, a qué cliente pertenece)."""
from . import attachments
from .db import get_conn
from .repositories import clients as clients_repo
from .repositories import conversations as conversations_repo
from .repositories import messages as messages_repo


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


def import_conversation(payload: dict) -> dict:
    """Guarda mensajes de una conversación (los que traen las integraciones). Crea el cliente/identidad si no existen.

    payload = {
      "owner_user_id": 1,
      "channel": "whatsapp",
      "handle": "+34600111222",
      "client_name": "Laura Gómez",     # usado si la identidad es nueva
      "client_id": null,                # opcional: forzar a qué cliente asociar
      "subject": "...",
      "messages": [{"direction": "in", "sender": "Laura", "body": "...", "sent_at": "2026-09-01T10:00:00",
                    "reply_to_external": "wa:..."}]   # opcional: el mensaje que cita (su identificador externo)
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
            quoted = m.get("reply_to_external")
            reply_to_id = messages_repo.id_by_external(conn, conv_id, quoted) if quoted else None
            message_id = messages_repo.insert(conn, conv_id, m["direction"], m["sender"], m["body"], m["sent_at"],
                                              ext, reply_to_id)
            new += 1
            for f in m.get("attachments") or []:
                attachments.save(conn, client_id, f["filename"], f["data"], f.get("mime"), message_id,
                                 payload["owner_user_id"])
                files += 1
    return {"client_id": client_id, "conversation_id": conv_id, "messages": new,
            "duplicates": len(payload["messages"]) - new, "attachments": files}
