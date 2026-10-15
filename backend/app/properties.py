"""Propiedades de contacto: campos de la ficha que define un administrador (texto, número, fecha o lista de opciones)
y el valor de cada cliente. Un valor vacío borra el valor."""
import json
import re
from datetime import date

from .db import get_conn
from .errors import Conflict, InvalidInput, NotFound
from .repositories import properties as repo

KINDS = {"text": "Texto", "number": "Número", "date": "Fecha", "select": "Lista de opciones"}
MAX_VALUE = 500
MAX_OPTIONS = 50


def _public(p: dict) -> dict:
    return {**p, "options": json.loads(p["options"] or "[]")}


def list_properties() -> list[dict]:
    with get_conn() as conn:
        return [_public(p) for p in repo.list_all(conn)]


def _clean_options(kind: str, options: list[str] | None) -> str:
    if kind != "select":
        return "[]"
    clean = list(dict.fromkeys(o.strip()[:100] for o in options or [] if o.strip()))
    if not clean:
        raise InvalidInput("Una lista de opciones necesita al menos una opción.")
    if len(clean) > MAX_OPTIONS:
        raise InvalidInput(f"Como mucho {MAX_OPTIONS} opciones.")
    return json.dumps(clean, ensure_ascii=False)


def _clean_label(label: str) -> str:
    label = " ".join(label.split())
    if not label:
        raise InvalidInput("Ponle un nombre a la propiedad.")
    return label[:60]


def create_property(label: str, kind: str, options: list[str] | None = None) -> dict:
    if kind not in KINDS:
        raise InvalidInput("Tipo de propiedad no válido.")
    label = _clean_label(label)
    with get_conn() as conn:
        if repo.label_taken(conn, label):
            raise Conflict(f"Ya existe la propiedad «{label}».")
        property_id = repo.insert(conn, label, kind, _clean_options(kind, options))
        return _public(repo.get(conn, property_id))


def update_property(property_id: int, label: str, options: list[str] | None = None) -> dict:
    """Cambia el nombre (y las opciones de una lista). El tipo no se cambia: los valores guardados dejarían de
    tener sentido."""
    label = _clean_label(label)
    with get_conn() as conn:
        current = repo.get(conn, property_id)
        if not current:
            raise NotFound("Propiedad no encontrada.")
        if repo.label_taken(conn, label, property_id):
            raise Conflict(f"Ya existe la propiedad «{label}».")
        repo.update(conn, property_id, label, _clean_options(current["kind"], options))
        return _public(repo.get(conn, property_id))


def delete_property(property_id: int) -> None:
    with get_conn() as conn:
        if not repo.delete(conn, property_id):
            raise NotFound("Propiedad no encontrada.")


def reorder(ordered_ids: list[int]) -> list[dict]:
    with get_conn() as conn:
        known = {p["id"] for p in repo.list_all(conn)}
        if set(ordered_ids) != known:
            raise InvalidInput("El orden debe incluir todas las propiedades.")
        repo.set_positions(conn, ordered_ids)
    return list_properties()


def _clean_value(prop: dict, value: str) -> str:
    value = value.strip()
    if len(value) > MAX_VALUE:
        raise InvalidInput(f"«{prop['label']}»: como mucho {MAX_VALUE} caracteres.")
    if prop["kind"] == "number":
        normalized = value.replace(",", ".")
        if not re.fullmatch(r"-?\d+(\.\d+)?", normalized):
            raise InvalidInput(f"«{prop['label']}» debe ser un número.")
        return normalized
    if prop["kind"] == "date":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise InvalidInput(f"«{prop['label']}» debe ser una fecha (AAAA-MM-DD).")
    if prop["kind"] == "select" and value not in json.loads(prop["options"]):
        raise InvalidInput(f"«{value}» no es una opción de «{prop['label']}».")
    return value


def values_of(client_id: int) -> dict[int, str]:
    with get_conn() as conn:
        return repo.values_of(conn, client_id)


def set_values(client_id: int, values: dict[int, str], user_id: int) -> dict[int, str]:
    """Guarda los valores indicados (los demás no se tocan). Vacío = sin valor."""
    with get_conn() as conn:
        known = {p["id"]: p for p in repo.list_all(conn)}
        for property_id, value in values.items():
            prop = known.get(property_id)
            if not prop:
                raise InvalidInput("Propiedad no encontrada.")
            if not (value or "").strip():
                repo.delete_value(conn, client_id, property_id)
            else:
                repo.put_value(conn, client_id, property_id, _clean_value(prop, value), user_id)
        return repo.values_of(conn, client_id)
