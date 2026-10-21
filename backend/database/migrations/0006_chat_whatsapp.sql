-- Chat al estilo de WhatsApp: estado de entrega de lo enviado, respuestas citando un mensaje y reacciones.

-- Estado de lo enviado por WhatsApp, según los avisos de Meta: sent | delivered | read | failed (NULL en lo recibido
-- y en los canales que no lo informan). status_error: por qué no se entregó, ya explicado para la persona.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS status_error TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS read_at TIMESTAMP;

-- Mensaje al que responde citándolo (WhatsApp y Telegram lo indican; desde la app se elige al responder).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_id BIGINT REFERENCES messages(id) ON DELETE SET NULL;

-- Hasta qué mensaje del cliente se ha avisado a WhatsApp de que está leído (los dos checks azules que ve el cliente).
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS read_receipt_upto BIGINT NOT NULL DEFAULT 0;

-- Reacciones con emoji. Como en WhatsApp, una por lado y mensaje: la del cliente y la de la empresa (la pone alguien
-- del equipo desde la app, o el móvil en coexistencia: user_id NULL).
CREATE TABLE IF NOT EXISTS message_reactions (
    message_id  BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    side        TEXT NOT NULL CHECK (side IN ('client', 'team')),
    emoji       TEXT NOT NULL,
    user_id     BIGINT REFERENCES users(id) ON DELETE SET NULL,
    reacted_at  TIMESTAMP NOT NULL DEFAULT localtimestamp(0),
    PRIMARY KEY (message_id, side)
);
