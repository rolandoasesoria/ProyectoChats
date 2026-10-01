"""Conversaciones persistentes con los asistentes (chat_sessions) y sus turnos visibles (chat_turns)."""
from ..db import Conn, rows


def _client_clause(client_id: int | None) -> tuple[str, list]:
    # Fragmento fijo del código: «IS NULL» no se puede expresar con un parámetro.
    return ("client_id IS NULL", []) if client_id is None else ("client_id = ?", [client_id])


def find_active(conn: Conn, user_id: int, kind: str, client_id: int | None) -> dict | None:
    """Conversación activa más reciente (id y api_messages en JSON) de (usuario, tipo, cliente)."""
    clause, args = _client_clause(client_id)
    row = conn.execute(
        f"""SELECT id, api_messages FROM chat_sessions
             WHERE user_id = ? AND kind = ? AND {clause} AND archived = 0
             ORDER BY created_at DESC LIMIT 1""",
        [user_id, kind, *args],
    ).fetchone()
    return dict(row) if row else None


def insert(conn: Conn, session_id: str, user_id: int, kind: str, client_id: int | None) -> None:
    conn.execute(
        "INSERT INTO chat_sessions (id, user_id, kind, client_id) VALUES (?, ?, ?, ?)",
        (session_id, user_id, kind, client_id),
    )


def api_messages(conn: Conn, session_id: str) -> str | None:
    """Historial de la API guardado (JSON), o None si la conversación no existe."""
    row = conn.execute("SELECT api_messages FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return row["api_messages"] if row else None


def save_api_messages(conn: Conn, session_id: str, api_messages_json: str) -> None:
    conn.execute(
        "UPDATE chat_sessions SET api_messages = ?, updated_at = localtimestamp(0) WHERE id = ?",
        (api_messages_json, session_id),
    )


def insert_turns(conn: Conn, session_id: str, turns: list[tuple[str, str, str | None]]) -> None:
    """Añade turnos visibles: cada uno es (rol, texto, tool_calls en JSON o None)."""
    conn.executemany(
        "INSERT INTO chat_turns (session_id, role, text, tool_calls) VALUES (?, ?, ?, ?)",
        [(session_id, role, text, tool_calls) for role, text, tool_calls in turns],
    )


def list_turns(conn: Conn, session_id: str) -> list[dict]:
    return rows(conn.execute(
        "SELECT role, text, tool_calls, created_at FROM chat_turns WHERE session_id = ? ORDER BY id",
        (session_id,),
    ))


def archive_active(conn: Conn, user_id: int, kind: str, client_id: int | None) -> None:
    clause, args = _client_clause(client_id)
    conn.execute(
        f"UPDATE chat_sessions SET archived = 1 WHERE user_id = ? AND kind = ? AND {clause} AND archived = 0",
        [user_id, kind, *args],
    )


def clients_with_turns(conn: Conn, user_id: int) -> list[int]:
    """Clientes con los que el usuario tiene una conversación activa del asistente de datos con mensajes."""
    return [r["client_id"] for r in conn.execute(
        """SELECT DISTINCT s.client_id FROM chat_sessions s
            WHERE s.user_id = ? AND s.kind = 'agent' AND s.archived = 0 AND s.client_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM chat_turns t WHERE t.session_id = s.id)""",
        (user_id,),
    )]
