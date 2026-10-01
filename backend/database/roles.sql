-- Usuarios de la base de datos con el mínimo privilegio. Lo ejecuta un superusuario con psql, una vez por base
-- de datos (scripts/postgres.ps1 asegurar lo hace solo; en un servidor gestionado, el administrador):
--
--   psql -d proyectochats -v owner=proyectochats -v app=proyectochats_app -v app_password='...' -f roles.sql
--
-- owner: dueño de la base de datos y de las tablas. Solo se usa para migrar (DATABASE_ADMIN_URL).
-- app:   el usuario con el que trabaja la app (DATABASE_URL). Lee y escribe datos, pero no puede crear, cambiar
--        ni borrar tablas, ni crear usuarios: si alguien lograra colar una consulta, no podría destruir el esquema.
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE %I', :'app') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app') \gexec
ALTER ROLE :"app" WITH LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 50;

-- Nadie más que estos dos usuarios puede conectarse ni crear objetos.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app";

-- Datos: las tablas que ya existen y las que creen las migraciones futuras.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO :"app";
