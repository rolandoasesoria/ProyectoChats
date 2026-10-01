"""Datos clave de la ficha del cliente (los propone la IA o los escribe una persona)."""
from ..db import Conn, rows


def list_confirmed_and_dismissed(conn: Conn, client_id: int) -> list[dict]:
    """Los que la IA no debe tocar: escritos o corregidos por una persona, y los descartados."""
    return rows(conn.execute(
        "SELECT label, value, origin FROM client_facts WHERE client_id = ? AND origin IN ('manual', 'dismissed')",
        (client_id,),
    ))


def list_visible(conn: Conn, client_id: int) -> list[dict]:
    return rows(conn.execute(
        """SELECT f.id, f.label, f.value, f.origin, f.source_message_id, f.updated_at, u.name AS updated_by
             FROM client_facts f LEFT JOIN users u ON u.id = f.updated_by
            WHERE f.client_id = ? AND f.origin != 'dismissed' ORDER BY lower(f.label)""",
        (client_id,),
    ))


def get(conn: Conn, fact_id: int) -> dict | None:
    row = conn.execute("SELECT id, client_id, origin FROM client_facts WHERE id = ?", (fact_id,)).fetchone()
    return dict(row) if row else None


def replace_ai(conn: Conn, client_id: int, facts: list[dict]) -> None:
    """Sustituye los datos de la IA del cliente. Cada dato: label, value, source_message_id."""
    conn.execute("DELETE FROM client_facts WHERE client_id = ? AND origin = 'ai'", (client_id,))
    conn.executemany(
        """INSERT INTO client_facts (client_id, label, value, origin, source_message_id)
           VALUES (?, ?, ?, 'ai', ?)""",
        [(client_id, f["label"], f["value"], f["source_message_id"]) for f in facts],
    )


def insert_manual(conn: Conn, client_id: int, label: str, value: str, user_id: int) -> None:
    conn.execute(
        "INSERT INTO client_facts (client_id, label, value, origin, updated_by) VALUES (?, ?, ?, 'manual', ?)",
        (client_id, label, value, user_id))


def update_manual(conn: Conn, fact_id: int, label: str, value: str, user_id: int) -> None:
    conn.execute(
        """UPDATE client_facts SET label = ?, value = ?, origin = 'manual', updated_by = ?,
               updated_at = localtimestamp(0) WHERE id = ?""",
        (label, value, user_id, fact_id))


def dismiss(conn: Conn, fact_id: int, user_id: int) -> None:
    conn.execute("UPDATE client_facts SET origin = 'dismissed', updated_by = ? WHERE id = ?", (user_id, fact_id))


def delete(conn: Conn, fact_id: int) -> None:
    conn.execute("DELETE FROM client_facts WHERE id = ?", (fact_id,))
