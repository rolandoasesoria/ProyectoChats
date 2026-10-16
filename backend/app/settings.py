"""Ajustes del equipo que cambia un administrador desde la app."""
from .db import get_conn
from .errors import InvalidInput
from .repositories import settings as repo

# clave: (valor por defecto, mínimo, máximo)
DEFAULTS = {
    "sla_hours": (24, 1, 168),  # plazo para responder a un cliente; a partir de aquí cuenta como «fuera de plazo»
    "retention_months": (0, 0, 120),  # borrar los mensajes de más de N meses (0 = conservarlos siempre)
    "inactive_days": (90, 0, 730),  # sin mensajes en N días, el cliente pasa a Inactivo (0 = nunca)
    "auto_analysis": (1, 0, 1),  # 1: la IA analiza al cliente cuando le llegan mensajes; 0: solo al pedirlo
}
# Ajustes de texto: clave: (valor por defecto, longitud máxima)
TEXT_DEFAULTS = {
    "company_name": ("", 80),  # nombre de la empresa: encabeza la ruta de navegación de la app
}


def get_all() -> dict:
    with get_conn() as conn:
        stored = repo.all_values(conn)
    return {**{k: int(stored.get(k, d[0])) for k, d in DEFAULTS.items()},
            **{k: stored.get(k, d[0]) for k, d in TEXT_DEFAULTS.items()}}


def get(key: str) -> int | str:
    return get_all()[key]


def update(values: dict) -> dict:
    clean = {}
    for key, value in values.items():
        if key in TEXT_DEFAULTS:
            value = " ".join(str(value).split())  # sin espacios de sobra ni saltos de línea
            if len(value) > TEXT_DEFAULTS[key][1]:
                raise InvalidInput(f"{key}: máximo {TEXT_DEFAULTS[key][1]} caracteres")
            clean[key] = value
            continue
        _, lo, hi = DEFAULTS[key]
        if not lo <= int(value) <= hi:
            raise InvalidInput(f"{key} debe estar entre {lo} y {hi}")
        clean[key] = str(int(value))
    with get_conn() as conn:
        for key, value in clean.items():
            repo.put(conn, key, value)
    return get_all()
