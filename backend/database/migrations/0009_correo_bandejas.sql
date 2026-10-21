-- Correo en bandejas: qué correos recibidos ha abierto cada usuario en la bandeja (los demás cuentan como leídos si
-- abrió el chat del cliente después de que llegaran).
CREATE TABLE IF NOT EXISTS mail_reads (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id  BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    read_at     TIMESTAMP NOT NULL DEFAULT localtimestamp(0),
    PRIMARY KEY (user_id, message_id)
);
