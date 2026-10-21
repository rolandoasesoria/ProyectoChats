"""Inicio y cierre de sesión, perfil propio y contraseña."""
import base64
import binascii
from typing import Literal

from fastapi import APIRouter, Cookie, Request, Response
from pydantic import BaseModel, Field

from .. import auth, avatars
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
    name: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=200)  # «» lo quita
    theme: Literal["system", "light", "dark"] | None = None
    tour_version: int | None = None


@router.patch("/api/me")
def update_me(req: ProfileUpdate, user: CurrentUser):
    return auth.update_profile(user["id"], name=req.name, email=req.email, theme=req.theme,
                               tour_version=req.tour_version)


class AvatarUpload(BaseModel):
    data: str = Field(max_length=400_000)  # imagen en base64 (hasta 256 KB)


@router.put("/api/me/avatar")
def put_avatar(req: AvatarUpload, user: CurrentUser):
    try:
        data = base64.b64decode(req.data, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidInput("No se pudo leer la imagen.")
    return avatars.set_avatar(user["id"], data)


@router.delete("/api/me/avatar")
def delete_avatar(user: CurrentUser):
    return avatars.delete_avatar(user["id"])


@router.get("/api/users/{user_id}/avatar")
def get_avatar(user_id: int, _: CurrentUser):
    mime, data = avatars.avatar(user_id)
    # La URL lleva la huella de la foto (?v=…): al cambiarla cambia la URL, así que se puede guardar en caché.
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable",
                                                    "X-Content-Type-Options": "nosniff"})


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/api/me/password")
def change_password(req: PasswordChange, user: CurrentUser, pc_session: str | None = Cookie(None)):
    auth.change_password(user["id"], req.current_password, req.new_password, keep_token=pc_session)
    return {"ok": True}
