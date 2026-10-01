"""Ajustes del equipo."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import audit, settings
from .deps import AdminUser, CurrentUser

router = APIRouter()


@router.get("/api/settings")
def get_settings(_: CurrentUser):
    return settings.get_all()


class SettingsUpdate(BaseModel):
    sla_hours: int | None = Field(None, ge=1, le=168)
    retention_months: int | None = Field(None, ge=0, le=120)
    inactive_days: int | None = Field(None, ge=0, le=730)


@router.patch("/api/admin/settings")
def update_settings(req: SettingsUpdate, admin: AdminUser):
    changes = req.model_dump(exclude_none=True)
    result = settings.update(changes)
    if changes:
        audit.log(admin["id"], "settings_change", detail=", ".join(f"{k}={v}" for k, v in changes.items()))
    return result
