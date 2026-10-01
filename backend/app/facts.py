"""Datos clave de la ficha del cliente, editados a mano.

Lo que escribe o corrige una persona queda como manual y la IA ya no lo cambia (ver insights.py).
"""
from .db import get_conn
from .errors import NotFound
from .repositories import facts as repo


def _fact_or_404(conn, fact_id: int) -> dict:
    fact = repo.get(conn, fact_id)
    if not fact or fact["origin"] == "dismissed":
        raise NotFound("Dato no encontrado")
    return fact


def add_fact(client_id: int, label: str, value: str, user_id: int) -> None:
    with get_conn() as conn:
        repo.insert_manual(conn, client_id, label.strip(), value.strip(), user_id)


def edit_fact(fact_id: int, label: str, value: str, user_id: int) -> int:
    """Editar un dato lo convierte en manual: la IA ya no lo cambiará. Devuelve el id del cliente."""
    with get_conn() as conn:
        fact = _fact_or_404(conn, fact_id)
        repo.update_manual(conn, fact_id, label.strip(), value.strip(), user_id)
    return fact["client_id"]


def delete_fact(fact_id: int, user_id: int) -> int:
    """Un dato de la IA queda descartado (no se vuelve a proponer); uno manual se borra. Devuelve el id del cliente."""
    with get_conn() as conn:
        fact = _fact_or_404(conn, fact_id)
        if fact["origin"] == "ai":
            repo.dismiss(conn, fact_id, user_id)
        else:
            repo.delete(conn, fact_id)
    return fact["client_id"]
