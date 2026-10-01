"""Conexión segura a la base de datos y migraciones (sin servidor de la app)."""
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import testdb  # noqa: F401  (configura la base de datos de pruebas)
import psycopg

from apitest import check, results
from app.config import ConfigError, config
from app.db import get_conn, migrations, safe_url
from app.db.connection import connection_kwargs

db = config.database


def raises_config_error(fn) -> bool:
    try:
        fn()
    except ConfigError:
        return True
    return False


# --- Política de cifrado
remote = "postgresql://app:secreto@bd.ejemplo.com:5432/proyectochats"
check("servidor remoto: se exige verificar su certificado", connection_kwargs(remote, replace(db, ssl_mode="", ssl_root_cert=""))["sslmode"] == "verify-full")
check("servidor remoto sin cifrar = no arranca",
      raises_config_error(lambda: connection_kwargs(remote, replace(db, ssl_mode="disable", ssl_root_cert=""))))
check("servidor remoto con 'prefer' (puede acabar sin cifrar) = no arranca",
      raises_config_error(lambda: connection_kwargs(remote + "?sslmode=prefer", replace(db, ssl_mode="", ssl_root_cert=""))))
check("modo TLS desconocido = no arranca",
      raises_config_error(lambda: connection_kwargs(remote, replace(db, ssl_mode="siempre", ssl_root_cert=""))))
check("certificado de la autoridad inexistente = no arranca",
      raises_config_error(lambda: connection_kwargs(remote, replace(db, ssl_mode="verify-full", ssl_root_cert="no-existe.crt"))))
local = connection_kwargs("postgresql://app@localhost/x", replace(db, ssl_mode="", ssl_root_cert=""))
check("en este equipo, por defecto se intenta TLS", local["sslmode"] == "prefer", local)
check("tiempo límite de consulta y zona UTC", "statement_timeout=" in local["options"] and "timezone=UTC" in local["options"])
check("la dirección se muestra sin contraseña", "secreto" not in safe_url(remote) and "bd.ejemplo.com" in safe_url(remote))

# --- La conexión real de las pruebas
with get_conn() as conn:
    info = conn.execute("""SELECT current_user AS usr, s.ssl FROM pg_stat_ssl s WHERE s.pid = pg_backend_pid()""").fetchone()
if config.database.ssl_mode == "verify-full":
    check("la app se conecta cifrada", info["ssl"] is True, info)
if config.database.admin_url and config.database.admin_url != config.database.url:
    check("la app usa un usuario distinto del dueño", info["usr"] not in config.database.admin_url.split("@")[0], info)
    for sql in ("DROP TABLE messages", "CREATE TABLE intruso (id int)", "ALTER TABLE clients ADD COLUMN x int",
                "TRUNCATE audit_log"):
        try:
            with get_conn() as conn:
                conn.execute(sql)
            denied = False
        except psycopg.errors.InsufficientPrivilege:
            denied = True
        check(f"el usuario de la app no puede: {sql}", denied)
    with get_conn() as conn:
        check("pero sí leer y escribir datos",
              conn.execute("UPDATE clients SET notes = notes WHERE id = 1").rowcount == 1)

# --- Migraciones
check("el esquema está al día", migrations.pending() == [])
names = [m.name for m in migrations.discover()]
check("las migraciones van en orden", names == sorted(names) and names[0] == "0001_esquema_inicial", names)
first = migrations.discover()[0]
check("una migración aplicada no se puede modificar",
      raises_config_error(lambda: migrations._check_unchanged([first], {first.version: "otra-huella"})))
with tempfile.TemporaryDirectory() as tmp:
    crlf = Path(tmp, first.path.name)
    crlf.write_bytes(first.sql.replace("\n", "\r\n").encode())
    check("la huella no depende de los saltos de línea de Windows",
          migrations.Migration(first.version, first.name, crlf).checksum == first.checksum)
with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, "1_mal.sql").write_text("SELECT 1")
    check("nombre de migración incorrecto = error", raises_config_error(lambda: migrations.discover(Path(tmp))))

sys.exit(0 if results["ok"] else 1)
