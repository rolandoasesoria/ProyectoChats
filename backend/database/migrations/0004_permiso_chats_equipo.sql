-- Permiso para ver en Mis Chats los chats de todo el equipo (los administradores pueden siempre).
-- Lo concede un administrador al crear el usuario o después.
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_view_team_chats SMALLINT NOT NULL DEFAULT 0;
