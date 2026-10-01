"""Conversaciones persistentes con los asistentes (una activa por usuario, tipo y cliente)."""
import json
import threading
import uuid
from collections import defaultdict
from contextlib import contextmanager

from .db import get_conn
from .repositories import chats as repo

KINDS = ("agent", "help")

# Evita que dos peticiones simultáneas de la misma conversación se pisen el historial.
_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


@contextmanager
def locked(session_id: str):
    with _locks[session_id]:
        yield


def active_session(user_id: int, kind: str, client_id: int | None = None, create: bool = True) -> dict | None:
    """Conversación activa de (usuario, tipo, cliente). La crea si no existe y `create` es True."""
    with get_conn() as conn:
        row = repo.find_active(conn, user_id, kind, client_id)
        if row:
            return {"id": row["id"], "api_messages": json.loads(row["api_messages"])}
        if not create:
            return None
        session_id = uuid.uuid4().hex
        repo.insert(conn, session_id, user_id, kind, client_id)
    return {"id": session_id, "api_messages": []}


def reload_messages(session_id: str) -> list:
    """Relee el historial dentro del bloqueo, por si otra petición lo cambió mientras esperábamos."""
    with get_conn() as conn:
        stored = repo.api_messages(conn, session_id)
    return json.loads(stored) if stored is not None else []


def save_exchange(session_id: str, api_messages: list, user_text: str, reply: str,
                  tool_calls: list | None = None) -> None:
    """Guarda el historial de la API y los dos turnos visibles (pregunta y respuesta) en una transacción."""
    with get_conn() as conn:
        repo.save_api_messages(conn, session_id, json.dumps(api_messages, ensure_ascii=False))
        repo.insert_turns(conn, session_id, [
            ("user", user_text, None),
            ("assistant", reply, json.dumps(tool_calls or [], ensure_ascii=False)),
        ])


def turns(session_id: str) -> list[dict]:
    with get_conn() as conn:
        result = repo.list_turns(conn, session_id)
    for t in result:
        t["tool_calls"] = json.loads(t["tool_calls"]) if t["tool_calls"] else []
    return result


def archive(user_id: int, kind: str, client_id: int | None = None) -> None:
    """"Nueva conversación": archiva la activa (queda guardada, pero ya no se muestra)."""
    with get_conn() as conn:
        repo.archive_active(conn, user_id, kind, client_id)


def clients_with_conversation(user_id: int) -> list[int]:
    """Clientes con los que el usuario tiene una conversación activa con mensajes."""
    with get_conn() as conn:
        return repo.clients_with_turns(conn, user_id)
