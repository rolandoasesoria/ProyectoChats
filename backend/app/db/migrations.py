"""Migraciones del esquema: los archivos .sql de backend/database/migrations, aplicados en orden y una sola vez.

Cada archivo se llama NNNN_descripcion.sql y se aplica en su propia transacción con el usuario dueño del
esquema. La tabla schema_migrations guarda cuáles están aplicadas y su huella (SHA-256): si alguien modifica
una migración ya aplicada, la app no arranca, porque la base de datos ya no correspondería al código.
"""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import BACKEND_DIR, ConfigError
from .connection import admin_conn, get_conn

MIGRATIONS_DIR = BACKEND_DIR / "database" / "migrations"
_FILE_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_LOCK_ID = 7426310  # bloqueo consultivo: dos procesos no migran a la vez

_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMP NOT NULL DEFAULT localtimestamp(0)
)"""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        # Saltos de línea normalizados: git en Windows puede convertir LF en CRLF al descargar.
        return hashlib.sha256(self.sql.replace("\r\n", "\n").encode()).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_NAME.match(path.name)
        if not match:
            raise ConfigError(f"Nombre de migración no válido: {path.name} (formato: 0001_descripcion.sql).")
        found.append(Migration(match.group(1), path.stem, path))
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise ConfigError("Hay dos migraciones con el mismo número.")
    return found


def _applied(conn) -> dict[str, str]:
    exists = conn.execute("SELECT to_regclass('schema_migrations') IS NOT NULL").fetchone()[0]
    if not exists:
        return {}
    return {r[0]: r[1] for r in conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()}


def _check_unchanged(migrations: list[Migration], applied: dict[str, str]) -> None:
    for m in migrations:
        if m.version in applied and applied[m.version] != m.checksum:
            raise ConfigError(f"La migración {m.name} ya aplicada ha cambiado. No se modifican: crea una nueva.")


def pending() -> list[Migration]:
    """Migraciones que faltan por aplicar (consultado con el usuario de la app)."""
    migrations = discover()
    with get_conn() as conn:
        applied = _applied(conn.raw)
    _check_unchanged(migrations, applied)
    return [m for m in migrations if m.version not in applied]


def upgrade() -> list[str]:
    """Aplica las migraciones pendientes. Devuelve sus nombres."""
    migrations = discover()
    done = []
    with admin_conn() as conn:
        conn.autocommit = True
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
        try:
            conn.execute(_TRACKING_TABLE)
            applied = _applied(conn)
            _check_unchanged(migrations, applied)
            for m in migrations:
                if m.version in applied:
                    continue
                with conn.transaction():
                    conn.execute(m.sql)
                    conn.execute("INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                                 (m.version, m.name, m.checksum))
                done.append(m.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_ID,))
    return done


def ensure_up_to_date() -> None:
    """Sin migración automática: la app no arranca si el esquema no corresponde al código."""
    missing = pending()
    if missing:
        names = ", ".join(m.name for m in missing)
        raise ConfigError(f"Faltan migraciones por aplicar ({names}). Ejecuta: python -m app.manage migrate")


def drop_all_tables() -> None:
    """Vacía la base de datos (datos de demostración y pruebas). Solo con el usuario dueño del esquema."""
    with admin_conn() as conn:
        conn.execute("""DO $$ DECLARE t record; BEGIN
            FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
                EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', t.tablename);
            END LOOP;
        END $$""")
