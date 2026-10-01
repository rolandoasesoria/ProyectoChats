"""Avisos para los usuarios (menciones, tareas asignadas...)."""
from ..db import Conn, rows


def insert_many(conn: Conn, user_ids, kind: str, text: str, client_id: int | None,
                actor_id: int | None) -> None:
    """El mismo aviso para cada usuario de `user_ids` (si no hay ninguno, no hace nada)."""
    conn.executemany(
        "INSERT INTO notifications (user_id, kind, text, client_id, actor_user_id) VALUES (?, ?, ?, ?, ?)",
        [(uid, kind, text, client_id, actor_id) for uid in user_ids],
    )


def list_recent(conn: Conn, user_id: int, limit: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT id, kind, text, client_id, created_at, read_at FROM notifications
            WHERE user_id = ? ORDER BY id DESC LIMIT ?""", (user_id, limit)))


def count_unread(conn: Conn, user_id: int) -> int:
    return conn.execute("SELECT count(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
                        (user_id,)).fetchone()[0]


def mark_all_read(conn: Conn, user_id: int) -> None:
    conn.execute("UPDATE notifications SET read_at = localtimestamp(0) WHERE user_id = ? AND read_at IS NULL",
                 (user_id,))


def mark_read(conn: Conn, user_id: int, ids: list[int]) -> None:
    conn.executemany(
        "UPDATE notifications SET read_at = localtimestamp(0) WHERE id = ? AND user_id = ? AND read_at IS NULL",
        [(i, user_id) for i in ids])
