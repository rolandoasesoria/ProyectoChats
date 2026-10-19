"""Fotos de perfil de los usuarios.

Como el logo de la empresa: solo PNG, JPG y WebP, reconocidos por su contenido (no por lo que diga el navegador), de
hasta 256 KB. El navegador ya la recorta en cuadrado y la reduce antes de subirla."""
import base64
import hashlib

from .company import sniff_image
from .db import get_conn
from .errors import InvalidInput, NotFound
from .repositories import users as users_repo

AVATAR_MAX = 256 * 1024


def avatar(user_id: int) -> tuple[str, bytes]:
    with get_conn() as conn:
        found = users_repo.get_avatar(conn, user_id)
    if not found:
        raise NotFound("Este usuario no tiene foto.")
    return found["mime"], base64.b64decode(found["data"])


def set_avatar(user_id: int, data: bytes) -> dict:
    if not data:
        raise InvalidInput("El archivo está vacío.")
    if len(data) > AVATAR_MAX:
        raise InvalidInput("La foto supera el máximo de 256 KB.")
    mime = sniff_image(data)
    if not mime:
        raise InvalidInput("La foto tiene que ser una imagen PNG, JPG o WebP.")
    version = hashlib.sha256(data).hexdigest()[:12]
    with get_conn() as conn:
        users_repo.put_avatar(conn, user_id, mime, base64.b64encode(data).decode(), version)
        return users_repo.get(conn, user_id)


def delete_avatar(user_id: int) -> dict:
    with get_conn() as conn:
        users_repo.delete_avatar(conn, user_id)
        return users_repo.get(conn, user_id)
