-- Chat al estilo de WhatsApp, fase 2: ubicaciones, tarjetas de contacto y notas de voz, y vistas previas de enlaces.

-- Lo que un mensaje lleva además del texto, en JSON:
--   {"type": "location", "latitude": …, "longitude": …, "name": "…", "address": "…"}
--   {"type": "contacts", "contacts": [{"name": "…", "phones": ["…"], "emails": ["…"], "org": "…"}]}
--   {"type": "voice", "seconds": …}
ALTER TABLE messages ADD COLUMN IF NOT EXISTS payload JSONB;

-- Vista previa de los enlaces (título, descripción, sitio y miniatura), para no volver a pedir la página cada vez.
-- ok = 0: no se pudo obtener (se reintenta pasado un día).
CREATE TABLE IF NOT EXISTS link_previews (
    url         TEXT PRIMARY KEY,
    title       TEXT,
    description TEXT,
    site        TEXT,
    image       TEXT,
    ok          SMALLINT NOT NULL DEFAULT 1,
    fetched_at  TIMESTAMP NOT NULL DEFAULT localtimestamp(0)
);
