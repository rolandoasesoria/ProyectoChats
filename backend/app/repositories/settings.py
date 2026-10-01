"""Ajustes del equipo (clave-valor)."""
from ..db import Conn


def all_values(conn: Conn) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_settings")}


def put(conn: Conn, key: str, value: str) -> None:
    conn.execute("""INSERT INTO app_settings (key, value) VALUES (?, ?)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value""", (key, value))
