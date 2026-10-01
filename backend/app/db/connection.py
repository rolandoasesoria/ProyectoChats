"""Conexiones a PostgreSQL.

Seguridad:
- La app trabaja con un usuario que solo puede leer y escribir datos (DATABASE_URL). Crear, cambiar o borrar
  tablas lo hace aparte el usuario dueño del esquema (DATABASE_ADMIN_URL), únicamente al migrar.
- Cifrado TLS: con un servidor que no es este equipo se exige verificar su certificado (verify-full), y nunca
  se acepta una conexión sin cifrar. DB_SSLMODE / DB_SSLROOTCERT permiten fijarlo también en local.
- Tiempos límite de conexión y de consulta, para que un fallo no deje la app colgada.
- Las direcciones de conexión nunca se muestran con la contraseña (safe_url).

Compatibilidad: las consultas se escriben con `?` como marcador (se traducen a `%s`) y las fechas se
devuelven como texto ISO "AAAA-MM-DDTHH:MM:SS".
"""
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.adapt import Loader
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool

from ..config import ConfigError, DatabaseConfig, config

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
ENCRYPTED_MODES = {"require", "verify-ca", "verify-full"}
SSL_MODES = {"disable", "allow", "prefer"} | ENCRYPTED_MODES
APPLICATION_NAME = "proyectochats"


# ---------------------------------------------------------------- Parámetros de conexión

def safe_url(url: str) -> str:
    """La dirección de conexión sin contraseña, para mensajes y registros."""
    try:
        params = conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        return "(dirección de conexión no válida)"
    params.pop("password", None)
    return make_conninfo(**params)


def connection_kwargs(url: str, db: DatabaseConfig, *, statement_timeout: bool = True) -> dict:
    """Parámetros de libpq para conectarse a `url` cumpliendo la política de seguridad."""
    params = conninfo_to_dict(url)
    host = params.get("host", "")
    is_local = host in LOCAL_HOSTS
    ssl_mode = params.get("sslmode") or db.ssl_mode or ("prefer" if is_local else "verify-full")
    if ssl_mode not in SSL_MODES:
        raise ConfigError(f"DB_SSLMODE no válido: «{ssl_mode}».")
    if not is_local and ssl_mode not in ENCRYPTED_MODES:
        raise ConfigError(f"La base de datos está en otro equipo ({host}): la conexión tiene que ir cifrada. "
                          "Usa DB_SSLMODE=verify-full y DB_SSLROOTCERT con el certificado de su autoridad.")
    kwargs = {"sslmode": ssl_mode, "application_name": APPLICATION_NAME, "connect_timeout": db.connect_timeout_s}
    root_cert = params.get("sslrootcert") or db.ssl_root_cert
    if root_cert:
        if not Path(root_cert).is_file():
            raise ConfigError(f"No existe el certificado DB_SSLROOTCERT: {root_cert}")
        kwargs["sslrootcert"] = root_cert
    options = ["-c timezone=UTC"]
    if statement_timeout and db.statement_timeout_ms > 0:
        options.append(f"-c statement_timeout={db.statement_timeout_ms}")
    kwargs["options"] = " ".join(options)
    return kwargs


# ---------------------------------------------------------------- Tipos: fechas como texto ISO

class _TimestampLoader(Loader):
    """TIMESTAMP -> "AAAA-MM-DDTHH:MM:SS" (sin fracciones de segundo)."""

    def load(self, data):
        return bytes(data[:19]).decode().replace(" ", "T")


class _DateLoader(Loader):
    def load(self, data):
        return bytes(data).decode()


class Row(dict):
    """Fila accesible por nombre (row["name"]) y por posición (row[0])."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


def _configure(conn: psycopg.Connection) -> None:
    conn.adapters.register_loader("timestamp", _TimestampLoader)
    conn.adapters.register_loader("date", _DateLoader)


# ---------------------------------------------------------------- Conexiones

class Cursor:
    def __init__(self, cur):
        self._cur = cur

    def __iter__(self):
        return iter(self._cur)

    def __getattr__(self, name):
        return getattr(self._cur, name)

    @property
    def lastrowid(self):
        """Id insertado: la sentencia debe terminar en RETURNING id."""
        return self._cur.fetchone()[0]


def _sql(sql: str) -> str:
    # Marcadores "?" (estilo de la versión anterior) -> "%s"; los "%" literales se escapan.
    return sql.replace("%", "%%").replace("?", "%s")


class Conn:
    def __init__(self, raw: psycopg.Connection):
        self.raw = raw

    def execute(self, sql: str, params=None) -> Cursor:
        cur = self.raw.cursor(row_factory=_row_factory)
        if params is None or len(params) == 0:
            cur.execute(sql)
        else:
            cur.execute(_sql(sql), list(params))
        return Cursor(cur)

    def executemany(self, sql: str, seq) -> None:
        seq = [list(p) for p in seq]
        if seq:
            self.raw.cursor().executemany(_sql(sql), seq)


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            db = config.database
            _pool = ConnectionPool(db.url, min_size=1, max_size=db.pool_size, kwargs=connection_kwargs(db.url, db),
                                   configure=_configure, open=True)
    return _pool


@contextmanager
def get_conn() -> Iterator[Conn]:
    """Conexión de la app (usuario solo de datos): commit al terminar, rollback si hay error."""
    with _get_pool().connection() as raw:
        yield Conn(raw)


@contextmanager
def admin_conn() -> Iterator[psycopg.Connection]:
    """Conexión del dueño del esquema, solo para migraciones y para vaciar la base de datos de pruebas."""
    db = config.database
    with psycopg.connect(db.migration_url, **connection_kwargs(db.migration_url, db, statement_timeout=False)) as raw:
        _configure(raw)
        yield raw


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]
