"""Acceso a la base de datos PostgreSQL.

El esquema NO está en el código: vive en backend/database/migrations (archivos .sql versionados) y lo aplica
migrations.py. Este paquete solo abre conexiones (connection.py) y prepara la base de datos al arrancar.

Modelo de datos principal (detalle en las migraciones):
- users: miembros del equipo que usan la app.
- clients: clientes (una persona/empresa, sin importar el canal).
- client_identities: cómo se identifica el cliente en cada canal (email, WhatsApp, Telegram...).
- conversations: un hilo de un canal concreto, perteneciente a un usuario del equipo.
- messages: mensajes de cada conversación, con índice de búsqueda en español (sin tildes y por raíz:
  "entregas" encuentra "entrega").
"""
from ..config import config
from . import migrations
from .connection import Conn, Row, admin_conn, get_conn, rows, safe_url

TS_CONFIG = "es_unaccent"  # configuración de búsqueda: español + sin tildes

__all__ = ["TS_CONFIG", "Conn", "Row", "admin_conn", "get_conn", "init_db", "reset_db", "rows", "safe_url"]


def init_db() -> None:
    """Al arrancar: carpeta de archivos y esquema al día (aplica las migraciones o comprueba que lo están)."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if config.database.auto_migrate:
        migrations.upgrade()
    else:
        migrations.ensure_up_to_date()


def reset_db() -> None:
    """Borra TODAS las tablas y datos y vuelve a crear el esquema (datos de demostración y pruebas)."""
    migrations.drop_all_tables()
    init_db()
