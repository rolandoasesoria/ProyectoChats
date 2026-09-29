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
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT UNIQUE,
    username      TEXT,
    password_hash TEXT,
    role          TEXT NOT NULL DEFAULT 'user',    -- user | admin
    active        INTEGER NOT NULL DEFAULT 1,
    theme         TEXT NOT NULL DEFAULT 'system',  -- system | light | dark
    tour_version  INTEGER NOT NULL DEFAULT 0       -- última versión del tutorial que ha visto
);

-- Sesiones de inicio de sesión (se guarda el hash del token, nunca el token).
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);

-- Datos clave de cada cliente. origin: ai (extraído por la IA) | manual (escrito o corregido por
-- una persona; la IA nunca lo sobrescribe) | dismissed (dato de la IA descartado; no se vuelve a proponer).
CREATE TABLE IF NOT EXISTS client_facts (
    id                 INTEGER PRIMARY KEY,
    client_id          INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    label              TEXT NOT NULL,
    value              TEXT NOT NULL,
    origin             TEXT NOT NULL DEFAULT 'manual',
    source_message_id  INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    updated_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_client_facts ON client_facts(client_id, origin);

-- Tareas y compromisos (detectados por la IA o creados a mano).
CREATE TABLE IF NOT EXISTS tasks (
    id                 INTEGER PRIMARY KEY,
    client_id          INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    title              TEXT NOT NULL,
    due_date           TEXT,                -- YYYY-MM-DD
    assignee_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status             TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    origin             TEXT NOT NULL DEFAULT 'manual',   -- ai | manual
    source_message_id  INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    created_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    done_at            TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_client ON tasks(client_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_user_id, status, due_date);

-- Último análisis con IA de cada cliente (resumen del estado y hasta qué mensaje se analizó).
CREATE TABLE IF NOT EXISTS client_analysis (
    client_id        INTEGER PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
    summary          TEXT NOT NULL,
    last_message_id  INTEGER,
    analyzed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Conexiones con los canales (buzón de email, bot de Telegram, WhatsApp Business). La configuración
-- (contraseñas, tokens) se guarda cifrada. Los mensajes entran como conversaciones de owner_user_id.
CREATE TABLE IF NOT EXISTS integrations (
    id             INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN ('email', 'telegram', 'whatsapp')),
    name           TEXT NOT NULL,
    owner_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    config         TEXT NOT NULL,          -- JSON cifrado
    state          TEXT NOT NULL DEFAULT '{}',  -- progreso de la sincronización (último UID, offset...)
    enabled        INTEGER NOT NULL DEFAULT 1,
    last_sync_at   TEXT,
    last_error     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Adjuntos de mensajes y documentos subidos a la ficha. El archivo se guarda en data/attachments/;
-- extracted_text es su contenido legible (texto del PDF o lectura con IA) y se indexa para buscar.
CREATE TABLE IF NOT EXISTS attachments (
    id              INTEGER PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    message_id      INTEGER REFERENCES messages(id) ON DELETE CASCADE,   -- NULL = subido a la ficha
    filename        TEXT NOT NULL,
    mime            TEXT NOT NULL,
    size            INTEGER NOT NULL,
    path            TEXT NOT NULL,
    extracted_text  TEXT,
    extracted_by    TEXT,          -- pdf | text | ai
    uploaded_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attachments_client ON attachments(client_id);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);

CREATE VIRTUAL TABLE IF NOT EXISTS attachments_fts USING fts5(
    filename, extracted_text, content='attachments', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS attachments_ai AFTER INSERT ON attachments BEGIN
    INSERT INTO attachments_fts(rowid, filename, extracted_text) VALUES (new.id, new.filename, new.extracted_text);
END;
CREATE TRIGGER IF NOT EXISTS attachments_ad AFTER DELETE ON attachments BEGIN
    INSERT INTO attachments_fts(attachments_fts, rowid, filename, extracted_text)
    VALUES ('delete', old.id, old.filename, old.extracted_text);
END;
CREATE TRIGGER IF NOT EXISTS attachments_au AFTER UPDATE ON attachments BEGIN
    INSERT INTO attachments_fts(attachments_fts, rowid, filename, extracted_text)
    VALUES ('delete', old.id, old.filename, old.extracted_text);
    INSERT INTO attachments_fts(rowid, filename, extracted_text) VALUES (new.id, new.filename, new.extracted_text);
END;

-- Etiquetas libres de los clientes ("mayorista", "VIP"...).
CREATE TABLE IF NOT EXISTS client_tags (
    client_id  INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    tag        TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (client_id, tag)
);

-- Notas internas del equipo sobre un cliente (el cliente nunca las ve).
CREATE TABLE IF NOT EXISTS client_notes (
    id          INTEGER PRIMARY KEY,
    client_id   INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_client_notes ON client_notes(client_id, id);

-- Avisos para cada usuario (menciones en notas, tareas asignadas...).
CREATE TABLE IF NOT EXISTS notifications (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,          -- mention | task_assigned
    text           TEXT NOT NULL,
    client_id      INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    actor_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    read_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read_at, id);

-- Última vez que cada usuario abrió cada cliente (para "novedades desde tu última visita" y no leídos).
CREATE TABLE IF NOT EXISTS client_visits (
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id        INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    visited_at       TEXT NOT NULL,
    last_message_id  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, client_id)
);

-- Registro de accesos y acciones delicadas (protección de datos). client_name se guarda aparte para
-- que el registro siga siendo legible aunque el cliente se borre.
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action       TEXT NOT NULL,
    client_id    INTEGER,
    client_name  TEXT,
    detail       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

-- Intentos fallidos de inicio de sesión, para bloquear ataques de fuerza bruta.
CREATE TABLE IF NOT EXISTS login_failures (
    id          INTEGER PRIMARY KEY,
    username    TEXT NOT NULL COLLATE NOCASE,
    ip          TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_failures_user ON login_failures(username, created_at);
CREATE INDEX IF NOT EXISTS idx_login_failures_ip ON login_failures(ip, created_at);

-- Conversaciones con los asistentes. kind = agent (datos de clientes) | help (mascota).
-- Por cada (usuario, kind, cliente) hay una conversación activa; "Nueva conversación" archiva la actual.
CREATE TABLE IF NOT EXISTS chat_sessions (
    id            TEXT PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,
    client_id     INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    archived      INTEGER NOT NULL DEFAULT 0,
    api_messages  TEXT NOT NULL DEFAULT '[]',   -- historial exacto enviado a Claude (JSON)
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner ON chat_sessions(user_id, kind, client_id, archived);

-- Lo que se muestra en pantalla de cada conversación.
CREATE TABLE IF NOT EXISTS chat_turns (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text        TEXT NOT NULL,
    tool_calls  TEXT,                            -- JSON con las búsquedas hechas
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_turns_session ON chat_turns(session_id, id);

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


# Columnas añadidas después de la primera versión: se agregan a bases de datos existentes.
ADDED_COLUMNS = {
    "users": {
        "username": "TEXT",
        "password_hash": "TEXT",
        "role": "TEXT NOT NULL DEFAULT 'user'",
        "active": "INTEGER NOT NULL DEFAULT 1",
        "theme": "TEXT NOT NULL DEFAULT 'system'",
        "tour_version": "INTEGER NOT NULL DEFAULT 0",
    },
    "conversations": {
        # Último mensaje del cliente marcado como "no necesita respuesta" (sale de la bandeja Sin responder).
        "dismissed_message_id": "INTEGER",
    },
    "messages": {
        # Identificador del mensaje en su canal (Message-ID del email, id de Telegram/WhatsApp): evita
        # duplicados al sincronizar y permite responder en el mismo hilo.
        "external_id": "TEXT",
    },
    "clients": {
        "status": "TEXT NOT NULL DEFAULT 'active'",   # lead | active | issue | inactive
        "assignee_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",  # responsable del cliente
    },
}


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for table, columns in ADDED_COLUMNS.items():
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for column, ddl in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_external ON messages(external_id)")


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]
