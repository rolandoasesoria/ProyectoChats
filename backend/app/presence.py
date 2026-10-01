"""Presencia: quién tiene abierto un cliente y quién está respondiendo, para no contestar dos veces.

La interfaz avisa cada pocos segundos de qué cliente tiene abierto (y si tiene el borrador abierto). Lo que no se
renueva en TTL_SECONDS se da por cerrado (pestaña cerrada, ordenador apagado...).
"""
from .db import get_conn
from .repositories import presence as repo

TTL_SECONDS = 45


def update(user_id: int, client_id: int | None, composing: bool) -> list[dict]:
    """Registra dónde está el usuario y devuelve los compañeros que están en el mismo cliente."""
    with get_conn() as conn:
        if client_id is None:
            repo.clear(conn, user_id)
            return []
        repo.upsert(conn, user_id, client_id, composing)
        return repo.others_on_client(conn, client_id, user_id, TTL_SECONDS)
