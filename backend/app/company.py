"""Datos de la empresa: el logo (el nombre es un ajuste más, ver settings.py).

El logo se guarda en los ajustes (app_settings) en base64 y se sirve por /api/company/logo. Solo se admiten PNG, JPG
y WebP, reconocidos por su contenido (no por lo que diga el navegador); SVG no, porque puede llevar código."""
import base64
import hashlib
import json

from .db import get_conn
from .errors import InvalidInput
from .repositories import settings as repo

LOGO_KEY = "company_logo"
LOGO_MAX = 256 * 1024


def sniff_image(data: bytes) -> str | None:
    """Tipo de imagen según sus primeros bytes, o None si no es PNG, JPG ni WebP."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _stored() -> str | None:
    with get_conn() as conn:
        return repo.all_values(conn).get(LOGO_KEY) or None


def logo() -> tuple[str, bytes] | None:
    raw = _stored()
    if not raw:
        return None
    value = json.loads(raw)
    return value["mime"], base64.b64decode(value["data"])


def logo_version() -> str:
    """Huella corta del logo guardado («» si no hay): sirve para que el navegador no use uno anterior de su caché."""
    raw = _stored()
    return hashlib.sha256(raw.encode()).hexdigest()[:12] if raw else ""


def set_logo(data: bytes) -> str:
    if not data:
        raise InvalidInput("El archivo está vacío.")
    if len(data) > LOGO_MAX:
        raise InvalidInput("El logo supera el máximo de 256 KB.")
    mime = sniff_image(data)
    if not mime:
        raise InvalidInput("El logo tiene que ser una imagen PNG, JPG o WebP.")
    with get_conn() as conn:
        repo.put(conn, LOGO_KEY, json.dumps({"mime": mime, "data": base64.b64encode(data).decode()}))
    return logo_version()


def delete_logo() -> None:
    with get_conn() as conn:
        repo.put(conn, LOGO_KEY, "")
