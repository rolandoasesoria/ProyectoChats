"""Ajustes del equipo que cambia un administrador desde la app."""
from .db import get_conn

# clave: (valor por defecto, mínimo, máximo)
DEFAULTS = {
    "sla_hours": (24, 1, 168),  # plazo para responder a un cliente; a partir de aquí cuenta como «fuera de plazo»
    "retention_months": (0, 0, 120),  # borrar los mensajes de más de N meses (0 = conservarlos siempre)
}


def get_all() -> dict:
    with get_conn() as conn:
        stored = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_settings")}
    return {k: int(stored.get(k, d[0])) for k, d in DEFAULTS.items()}


def get(key: str) -> int:
    return get_all()[key]


def update(values: dict) -> dict:
    with get_conn() as conn:
        for key, value in values.items():
            _, lo, hi = DEFAULTS[key]
            if not lo <= int(value) <= hi:
                raise ValueError(f"{key} debe estar entre {lo} y {hi}")
            conn.execute("""INSERT INTO app_settings (key, value) VALUES (?, ?)
                            ON CONFLICT (key) DO UPDATE SET value = excluded.value""", (key, str(int(value))))
    return get_all()
