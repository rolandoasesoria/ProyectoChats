"""Ajustes del equipo que cambia un administrador desde la app."""
from .db import get_conn
from .errors import InvalidInput
from .repositories import settings as repo

# clave: (valor por defecto, mínimo, máximo)
DEFAULTS = {
    "sla_hours": (24, 1, 168),  # plazo para responder a un cliente; a partir de aquí cuenta como «fuera de plazo»
    "retention_months": (0, 0, 120),  # borrar los mensajes de más de N meses (0 = conservarlos siempre)
    "inactive_days": (90, 0, 730),  # sin mensajes en N días, el cliente pasa a Inactivo (0 = nunca)
}


def get_all() -> dict:
    with get_conn() as conn:
        stored = repo.all_values(conn)
    return {k: int(stored.get(k, d[0])) for k, d in DEFAULTS.items()}


def get(key: str) -> int:
    return get_all()[key]


def update(values: dict) -> dict:
    for key, value in values.items():
        _, lo, hi = DEFAULTS[key]
        if not lo <= int(value) <= hi:
            raise InvalidInput(f"{key} debe estar entre {lo} y {hi}")
    with get_conn() as conn:
        for key, value in values.items():
            repo.put(conn, key, str(int(value)))
    return get_all()
