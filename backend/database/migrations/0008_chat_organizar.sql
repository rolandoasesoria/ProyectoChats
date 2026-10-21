-- Organizar los chats como en WhatsApp. Cada usuario organiza su propia lista: fijar arriba (hasta 3), archivar
-- (el chat vuelve a la lista si el cliente escribe), silenciar hasta una fecha (9999-12-31 = siempre) y marcar como no
-- leído (se quita al abrirlo).
CREATE TABLE IF NOT EXISTS chat_prefs (
    user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id      BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    pinned_at      TIMESTAMP,
    archived_at    TIMESTAMP,
    muted_until    TIMESTAMP,
    marked_unread  SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, client_id)
);

-- Mensajes destacados (★) de cada usuario.
CREATE TABLE IF NOT EXISTS starred_messages (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id  BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    created_at  TIMESTAMP NOT NULL DEFAULT localtimestamp(0),
    PRIMARY KEY (user_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_starred_user ON starred_messages (user_id, created_at DESC);
