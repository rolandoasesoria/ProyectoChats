"""Cuentas del equipo (administración) y lista del equipo."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from .. import audit, auth
from ..db import get_conn
from ..errors import InvalidInput
from .deps import AdminUser, CurrentUser

router = APIRouter()


@router.get("/api/admin/users")
def admin_list_users(_: AdminUser):
    return auth.list_users()


class NewUser(BaseModel):
    username: str
    name: str
    password: str
    email: str | None = None
    role: Literal["user", "admin"] = "user"


@router.post("/api/admin/users")
def admin_create_user(req: NewUser, admin: AdminUser):
    user = auth.create_user(req.username, req.name, req.password, req.email, req.role)
    audit.log(admin["id"], "user_create", detail=f"{user['username']} ({user['role']})")
    return user


class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    role: Literal["user", "admin"] | None = None
    active: bool | None = None
    password: str | None = None


@router.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, req: UserUpdate, admin: AdminUser):
    if user_id == admin["id"] and (req.active is False or req.role == "user"):
        raise InvalidInput("No puedes desactivarte ni quitarte el rol de administrador a ti mismo.")
    changes = req.model_dump(exclude_none=True)
    user = auth.update_user(user_id, **changes)
    described = ", ".join("contraseña restablecida" if k == "password" else f"{k}={v}" for k, v in changes.items())
    audit.log(admin["id"], "user_update", detail=f"{user['username']}: {described}")
    return user


@router.get("/api/team")
def team(_: CurrentUser):
    """Miembros activos del equipo (para asignar tareas, menciones...)."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT id, name FROM users WHERE active = 1 ORDER BY name")]
