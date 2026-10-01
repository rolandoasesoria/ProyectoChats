"""Presencia: qué cliente tiene abierto cada persona y si está respondiendo."""
from ..db import Conn, rows


def clear(conn: Conn, user_id: int) -> None:
    conn.execute("DELETE FROM presence WHERE user_id = ?", (user_id,))


def upsert(conn: Conn, user_id: int, client_id: int, composing: bool) -> None:
    conn.execute(
        """INSERT INTO presence (user_id, client_id, composing, seen_at) VALUES (?, ?, ?, localtimestamp(0))
           ON CONFLICT (user_id) DO UPDATE SET client_id = excluded.client_id, composing = excluded.composing,
               seen_at = excluded.seen_at""", (user_id, client_id, int(composing)))


def others_on_client(conn: Conn, client_id: int, user_id: int, ttl_seconds: int) -> list[dict]:
    """Compañeros con el mismo cliente abierto que se han renovado en los últimos ttl_seconds."""
    return rows(conn.execute(
        """SELECT u.name, p.composing = 1 AS composing FROM presence p JOIN users u ON u.id = p.user_id
            WHERE p.client_id = ? AND p.user_id != ?
              AND p.seen_at > localtimestamp - make_interval(secs => ?)
            ORDER BY p.composing DESC, u.name""", (client_id, user_id, ttl_seconds)))
