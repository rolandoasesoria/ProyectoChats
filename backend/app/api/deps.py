"""Dependencias comunes de las rutas: usuario autenticado, administrador y cliente existente."""
from typing import Annotated

from fastapi import Depends

from .. import auth, clients
from ..errors import NotFound

CurrentUser = Annotated[dict, Depends(auth.current_user)]


def admin_user(user: CurrentUser) -> dict:
    return auth.require_admin(user)


AdminUser = Annotated[dict, Depends(admin_user)]


def client_or_404(client_id: int | None) -> dict | None:
    if client_id is None:
        return None
    client = clients.get_basic(client_id)
    if not client:
        raise NotFound("Cliente no encontrado")
    return client
