"""Acceso a la base de datos SQLite.

Modelo de datos:
- users: miembros del equipo que usan la app.
- clients: clientes (una persona/empresa, sin importar el canal).
- client_identities: cómo se identifica el cliente en cada canal
  (email, número de WhatsApp, usuario de Telegram...).
- conversations: un hilo de un canal concreto, perteneciente a un usuario del equipo.
- messages: mensajes de cada conversación. Indexados con FTS5 para búsqueda.
"""
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", "data/proyectochats.db"))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    company     TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS client_identities (
    id          INTEGER PRIMARY KEY,
    client_id   INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    channel     TEXT NOT NULL,          -- email | whatsapp | telegram | ...
    handle      TEXT NOT NULL,          -- dirección, número, @usuario
    UNIQUE (channel, handle)
);

CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY,
    client_id     INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    channel       TEXT NOT NULL,
    subject       TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    direction        TEXT NOT NULL CHECK (direction IN ('in', 'out')),  -- in = escribió el cliente
    sender           TEXT NOT NULL,
    body             TEXT NOT NULL,
    sent_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_conv_client ON conversations(client_id, owner_user_id);

-- Índice de texto completo; remove_diacritics permite que "telefono" encuentre "teléfono".
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    body,
    content='messages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, body) VALUES (new.id, new.body);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body) VALUES ('delete', old.id, old.body);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body) VALUES ('delete', old.id, old.body);
    INSERT INTO messages_fts(rowid, body) VALUES (new.id, new.body);
END;
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Conexión por operación: hace commit al terminar (rollback si hay error) y la cierra."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]
