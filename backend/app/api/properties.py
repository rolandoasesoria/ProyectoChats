"""Propiedades de contacto: las define un administrador; cualquiera las rellena en la ficha."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import audit, properties
from .deps import AdminUser, CurrentUser, client_or_404

router = APIRouter()


@router.get("/api/properties")
def list_properties(_: CurrentUser):
    return properties.list_properties()


class PropertyIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    kind: Literal["text", "number", "date", "select"]
    options: list[str] = Field(default_factory=list, max_length=50)


class PropertyUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    options: list[str] = Field(default_factory=list, max_length=50)


class PropertyOrder(BaseModel):
    ids: list[int] = Field(max_length=200)


@router.post("/api/admin/properties")
def create_property(req: PropertyIn, admin: AdminUser):
    prop = properties.create_property(req.label, req.kind, req.options)
    audit.log(admin["id"], "settings_change", detail=f"creó la propiedad de contacto «{prop['label']}»")
    return prop


@router.put("/api/admin/properties/order")
def reorder_properties(req: PropertyOrder, _: AdminUser):
    return properties.reorder(req.ids)


@router.patch("/api/admin/properties/{property_id}")
def update_property(property_id: int, req: PropertyUpdate, admin: AdminUser):
    prop = properties.update_property(property_id, req.label, req.options)
    audit.log(admin["id"], "settings_change", detail=f"modificó la propiedad de contacto «{prop['label']}»")
    return prop


@router.delete("/api/admin/properties/{property_id}")
def delete_property(property_id: int, admin: AdminUser):
    properties.delete_property(property_id)
    audit.log(admin["id"], "settings_change", detail=f"borró la propiedad de contacto {property_id}")
    return {"ok": True}


@router.get("/api/clients/{client_id}/properties")
def client_properties(client_id: int, _: CurrentUser):
    client_or_404(client_id)
    return {"values": properties.values_of(client_id)}


class PropertyValues(BaseModel):
    values: dict[int, str] = Field(max_length=200)


@router.put("/api/clients/{client_id}/properties")
def set_client_properties(client_id: int, req: PropertyValues, user: CurrentUser):
    client_or_404(client_id)
    return {"values": properties.set_values(client_id, req.values, user["id"])}
