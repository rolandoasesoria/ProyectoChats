"""Información de la propia conexión a la base de datos (para diagnóstico desde la consola)."""
from ..db import Conn


def connection_info(conn: Conn) -> dict:
    """Usuario de la conexión, si va cifrada (versión TLS y cifrado) y si puede crear tablas."""
    return dict(conn.execute("""SELECT current_user AS usuario, s.ssl, s.version AS tls, s.cipher,
                                       has_schema_privilege('public', 'CREATE') AS puede_crear
                                  FROM pg_stat_ssl s WHERE s.pid = pg_backend_pid()""").fetchone())
