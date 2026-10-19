-- Foto de perfil de cada usuario (la sube él mismo desde «Mi perfil»). La imagen se guarda aparte, en base64, para
-- no cargarla con cada consulta de usuarios; en users queda su huella (avatar_version, «» sin foto), que cambia la
-- URL de la imagen al cambiar la foto.
CREATE TABLE IF NOT EXISTS user_avatars (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    mime    TEXT NOT NULL,
    data    TEXT NOT NULL
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_version TEXT NOT NULL DEFAULT '';
