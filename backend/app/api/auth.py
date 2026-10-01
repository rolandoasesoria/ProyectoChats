"""Inicio y cierre de sesión, perfil propio y contraseña."""
from typing import Literal

from fastapi import APIRouter, Cookie, Request, Response
from pydantic import BaseModel, Field

from .. import auth
from ..db import get_conn
from ..errors import InvalidInput
from .deps import CurrentUser

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=auth.MAX_PASSWORD_LENGTH)


@router.post("/api/auth/login")
def login(req: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "desconocida"
    token, user = auth.login(req.username, req.password, ip)
    response.set_cookie(
        auth.COOKIE_NAME, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
        secure=auth.COOKIE_SECURE or request.url.scheme == "https",
    )
    return user


@router.post("/api/auth/logout")
def logout(response: Response, pc_session: str | None = Cookie(None)):
    auth.logout(pc_session)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@router.get("/api/me")
def me(user: CurrentUser):
    return user


class ProfileUpdate(BaseModel):
    theme: Literal["system", "light", "dark"] | None = None
    tour_version: int | None = None


@router.patch("/api/me")
def update_me(req: ProfileUpdate, user: CurrentUser):
    return auth.update_user(user["id"], theme=req.theme, tour_version=req.tour_version)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/api/me/password")
def change_password(req: PasswordChange, user: CurrentUser, pc_session: str | None = Cookie(None)):
    with get_conn() as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not auth.verify_password(req.current_password, stored["password_hash"]):
        raise InvalidInput("La contraseña actual no es correcta.")
    # Cierra las demás sesiones abiertas del usuario, pero no la actual.
    auth.update_user(user["id"], password=req.new_password, keep_token=pc_session)
    return {"ok": True}
