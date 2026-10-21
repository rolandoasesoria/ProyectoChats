"""Vistas previas de enlaces ya pedidas (ver link_preview.py)."""
from ..db import Conn


def get(conn: Conn, url: str) -> dict | None:
    row = conn.execute("SELECT title, description, site, image, ok, fetched_at FROM link_previews WHERE url = ?",
                       (url,)).fetchone()
    return dict(row) if row else None


def put(conn: Conn, url: str, found: dict | None) -> None:
    """Guarda lo obtenido (o que no se pudo: ok = 0)."""
    found = found or {}
    conn.execute(
        """INSERT INTO link_previews (url, title, description, site, image, ok) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (url) DO UPDATE SET title = excluded.title, description = excluded.description,
               site = excluded.site, image = excluded.image, ok = excluded.ok, fetched_at = localtimestamp(0)""",
        (url, found.get("title"), found.get("description"), found.get("site"), found.get("image"), int(bool(found))))
