"""Propiedades de contacto (las define un administrador) y su valor en cada cliente."""
from ..db import Conn, rows


def list_all(conn: Conn) -> list[dict]:
    return rows(conn.execute("SELECT id, label, kind, options, position FROM contact_properties ORDER BY position, id"))


def get(conn: Conn, property_id: int) -> dict | None:
    row = conn.execute("SELECT id, label, kind, options, position FROM contact_properties WHERE id = ?",
                       (property_id,)).fetchone()
    return dict(row) if row else None


def label_taken(conn: Conn, label: str, exclude_id: int | None = None) -> bool:
    return conn.execute("SELECT 1 FROM contact_properties WHERE lower(label) = lower(?) AND id IS DISTINCT FROM ?",
                        (label, exclude_id)).fetchone() is not None


def insert(conn: Conn, label: str, kind: str, options: str) -> int:
    return conn.execute(
        """INSERT INTO contact_properties (label, kind, options, position)
           VALUES (?, ?, ?, (SELECT coalesce(max(position), 0) + 1 FROM contact_properties)) RETURNING id""",
        (label, kind, options)).fetchone()[0]


def update(conn: Conn, property_id: int, label: str, options: str) -> None:
    conn.execute("UPDATE contact_properties SET label = ?, options = ? WHERE id = ?", (label, options, property_id))


def delete(conn: Conn, property_id: int) -> bool:
    return conn.execute("DELETE FROM contact_properties WHERE id = ?", (property_id,)).rowcount > 0


def set_positions(conn: Conn, ordered_ids: list[int]) -> None:
    for position, property_id in enumerate(ordered_ids, start=1):
        conn.execute("UPDATE contact_properties SET position = ? WHERE id = ?", (position, property_id))


def values_of(conn: Conn, client_id: int) -> dict[int, str]:
    return {r["property_id"]: r["value"] for r in conn.execute(
        "SELECT property_id, value FROM client_property_values WHERE client_id = ?", (client_id,))}


def values_for(conn: Conn, client_ids: list[int]) -> list[dict]:
    """Valores de varios clientes a la vez (para la tabla de contactos)."""
    if not client_ids:
        return []
    return rows(conn.execute(
        "SELECT client_id, property_id, value FROM client_property_values WHERE client_id = ANY(?)", (client_ids,)))


def put_value(conn: Conn, client_id: int, property_id: int, value: str, user_id: int) -> None:
    conn.execute(
        """INSERT INTO client_property_values (client_id, property_id, value, updated_by, updated_at)
           VALUES (?, ?, ?, ?, localtimestamp(0))
           ON CONFLICT (client_id, property_id) DO UPDATE SET
               value = excluded.value, updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
        (client_id, property_id, value, user_id))


def delete_value(conn: Conn, client_id: int, property_id: int) -> None:
    conn.execute("DELETE FROM client_property_values WHERE client_id = ? AND property_id = ?", (client_id, property_id))


def merge_values(conn: Conn, source_id: int, target_id: int) -> None:
    """Al unir clientes: el que se queda conserva sus valores y recibe los que le falten."""
    conn.execute(
        """INSERT INTO client_property_values (client_id, property_id, value, updated_by, updated_at)
           SELECT ?, property_id, value, updated_by, updated_at FROM client_property_values WHERE client_id = ?
           ON CONFLICT (client_id, property_id) DO NOTHING""",
        (target_id, source_id))
