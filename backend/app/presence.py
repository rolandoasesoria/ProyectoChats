"""Presencia: quién tiene abierto un cliente y quién está respondiendo, para no contestar dos veces.

La interfaz avisa cada pocos segundos de qué cliente tiene abierto (y si tiene el borrador abierto). Lo que no se
renueva en TTL_SECONDS se da por cerrado (pestaña cerrada, ordenador apagado...).
"""
from .db import get_conn, rows

TTL_SECONDS = 45


def update(user_id: int, client_id: int | None, composing: bool) -> list[dict]:
    """Registra dónde está el usuario y devuelve los compañeros que están en el mismo cliente."""
    with get_conn() as conn:
        if client_id is None:
            conn.execute("DELETE FROM presence WHERE user_id = ?", (user_id,))
            return []
        conn.execute(
            """INSERT INTO presence (user_id, client_id, composing, seen_at) VALUES (?, ?, ?, localtimestamp(0))
               ON CONFLICT (user_id) DO UPDATE SET client_id = excluded.client_id, composing = excluded.composing,
                   seen_at = excluded.seen_at""", (user_id, client_id, int(composing)))
        return rows(conn.execute(
            f"""SELECT u.name, p.composing = 1 AS composing FROM presence p JOIN users u ON u.id = p.user_id
                 WHERE p.client_id = ? AND p.user_id != ?
                   AND p.seen_at > localtimestamp - interval '{TTL_SECONDS} seconds'
                 ORDER BY p.composing DESC, u.name""", (client_id, user_id)))
