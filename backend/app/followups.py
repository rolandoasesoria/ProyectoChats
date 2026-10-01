"""Seguimientos: «avísame si el cliente no contesta en X días».

Se crean al responder (enviando desde la app o copiando el borrador). Cuando vence el plazo y el cliente no ha
escrito nada nuevo en esa conversación, aparece en la bandeja «Sin responder» de quien lo pidió. Si el cliente
contesta antes, el seguimiento se resuelve solo.
"""
from .db import get_conn
from .errors import NotFound
from .repositories import followups as repo


def create(conversation_id: int, user_id: int, days: int) -> dict:
    with get_conn() as conn:
        last = repo.last_message_id(conn, conversation_id)
        if last is None:
            raise NotFound("Conversación no encontrada o vacía")
        # Un seguimiento por persona y conversación: el nuevo sustituye al anterior.
        repo.delete_for_user(conn, conversation_id, user_id)
        return repo.insert(conn, conversation_id, user_id, last, days)


def due(user_id: int) -> list[dict]:
    """Seguimientos vencidos del usuario cuyo cliente sigue sin contestar. Borra los ya resueltos."""
    with get_conn() as conn:
        repo.delete_answered(conn, user_id)
        return repo.list_due(conn, user_id)


def delete(follow_up_id: int, user_id: int) -> None:
    with get_conn() as conn:
        if not repo.delete(conn, follow_up_id, user_id):
            raise NotFound("Seguimiento no encontrado")
