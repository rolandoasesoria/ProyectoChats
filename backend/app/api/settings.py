"""Ajustes del equipo y datos de la empresa (nombre y logo)."""
import base64
import binascii

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from .. import audit, company, settings
from ..errors import InvalidInput, NotFound
from .deps import AdminUser, CurrentUser

router = APIRouter()


@router.get("/api/settings")
def get_settings(_: CurrentUser):
    # company_logo: huella del logo («» si no hay); la imagen se pide a /api/company/logo?v=<huella>
    return {**settings.get_all(), "company_logo": company.logo_version()}


class SettingsUpdate(BaseModel):
    sla_hours: int | None = Field(None, ge=1, le=168)
    retention_months: int | None = Field(None, ge=0, le=120)
    inactive_days: int | None = Field(None, ge=0, le=730)
    auto_analysis: int | None = Field(None, ge=0, le=1)
    company_name: str | None = Field(None, max_length=80)


@router.patch("/api/admin/settings")
def update_settings(req: SettingsUpdate, admin: AdminUser):
    changes = req.model_dump(exclude_none=True)
    result = settings.update(changes)
    if changes:
        audit.log(admin["id"], "settings_change", detail=", ".join(f"{k}={v}" for k, v in changes.items()))
    return {**result, "company_logo": company.logo_version()}


@router.get("/api/company/logo")
def get_logo(_: CurrentUser):
    found = company.logo()
    if not found:
        raise NotFound("La empresa no tiene logo.")
    mime, data = found
    # La URL lleva la huella del logo (?v=…): al cambiarlo cambia la URL, así que se puede guardar en caché.
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable",
                                                    "X-Content-Type-Options": "nosniff"})


class LogoUpload(BaseModel):
    data: str = Field(max_length=400_000)  # imagen en base64 (hasta 256 KB)


@router.put("/api/admin/company/logo")
def put_logo(req: LogoUpload, admin: AdminUser):
    try:
        data = base64.b64decode(req.data, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidInput("No se pudo leer la imagen.")
    version = company.set_logo(data)
    audit.log(admin["id"], "settings_change", detail="logo de la empresa")
    return {"company_logo": version}


@router.delete("/api/admin/company/logo")
def delete_logo(admin: AdminUser):
    company.delete_logo()
    audit.log(admin["id"], "settings_change", detail="logo de la empresa quitado")
    return {"company_logo": ""}
