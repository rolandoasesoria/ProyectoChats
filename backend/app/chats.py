"""Conversaciones persistentes con los asistentes (una activa por usuario, tipo y cliente)."""
import json
import threading
import uuid
from collections import defaultdict
from contextlib import contextmanager

from .db import get_conn, rows

KINDS = ("agent", "help")

# Evita que dos peticiones simultáneas de la misma conversación se pisen el historial.
_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


@contextmanager
def locked(session_id: str):
    with _locks[session_id]:
        yield


def _client_clause(client_id: int | None) -> tuple[str, list]:
    return ("client_id IS NULL", []) if client_id is None else ("client_id = ?", [client_id])


def active_session(user_id: int, kind: str, client_id: int | None = None, create: bool = True) -> dict | None:
    """Conversación activa de (usuario, tipo, cliente). La crea si no existe y `create` es True."""
    clause, args = _client_clause(client_id)
    with get_conn() as conn:
        row = conn.execute(
            f"""SELECT id, api_messages FROM chat_sessions
                 WHERE user_id = ? AND kind = ? AND {clause} AND archived = 0
                 ORDER BY created_at DESC LIMIT 1""",
            [user_id, kind, *args],
        ).fetchone()
        if row:
            return {"id": row["id"], "api_messages": json.loads(row["api_messages"])}
        if not create:
            return None
        session_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO chat_sessions (id, user_id, kind, client_id) VALUES (?, ?, ?, ?)",
            (session_id, user_id, kind, client_id),
        )
    return {"id": session_id, "api_messages": []}


def reload_messages(session_id: str) -> list:
    """Relee el historial dentro del bloqueo, por si otra petición lo cambió mientras esperábamos."""
    with get_conn() as conn:
        row = conn.execute("SELECT api_messages FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return json.loads(row["api_messages"]) if row else []


def save_exchange(session_id: str, api_messages: list, user_text: str, reply: str,
                  tool_calls: list | None = None) -> None:
    """Guarda el historial de la API y los dos turnos visibles (pregunta y respuesta) en una transacción."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE chat_sessions SET api_messages = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(api_messages, ensure_ascii=False), session_id),
        )
        conn.executemany(
            "INSERT INTO chat_turns (session_id, role, text, tool_calls) VALUES (?, ?, ?, ?)",
            [
                (session_id, "user", user_text, None),
                (session_id, "assistant", reply, json.dumps(tool_calls or [], ensure_ascii=False)),
            ],
        )


def turns(session_id: str) -> list[dict]:
    with get_conn() as conn:
        result = rows(conn.execute(
            "SELECT role, text, tool_calls, created_at FROM chat_turns WHERE session_id = ? ORDER BY id",
            (session_id,),
        ))
    for t in result:
        t["tool_calls"] = json.loads(t["tool_calls"]) if t["tool_calls"] else []
    return result


def archive(user_id: int, kind: str, client_id: int | None = None) -> None:
    """"Nueva conversación": archiva la activa (queda guardada, pero ya no se muestra)."""
    clause, args = _client_clause(client_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE chat_sessions SET archived = 1 WHERE user_id = ? AND kind = ? AND {clause} AND archived = 0",
            [user_id, kind, *args],
        )


def clients_with_conversation(user_id: int) -> list[int]:
    """Clientes con los que el usuario tiene una conversación activa con mensajes."""
    with get_conn() as conn:
        return [r["client_id"] for r in conn.execute(
            """SELECT DISTINCT s.client_id FROM chat_sessions s
                WHERE s.user_id = ? AND s.kind = 'agent' AND s.archived = 0 AND s.client_id IS NOT NULL
                  AND EXISTS (SELECT 1 FROM chat_turns t WHERE t.session_id = s.id)""",
            (user_id,),
        )]
