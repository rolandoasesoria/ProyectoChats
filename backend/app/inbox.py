"""Bandeja «Sin responder»: conversaciones que esperan respuesta, posponerlas y marcarlas como atendidas."""
from .db import get_conn
from .repositories import conversations as conversations_repo


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
