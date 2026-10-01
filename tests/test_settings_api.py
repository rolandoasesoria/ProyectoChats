"""Ajustes del equipo (plazo de respuesta) y su efecto en el panel."""
import sys
from datetime import date, timedelta

from apitest import Session, check, results
from app import metrics
from app.db import get_conn

ana, carlos = Session("ana"), Session("carlos")

check("ajustes por defecto", carlos.get("/api/settings")[1] == {"sla_hours": 24, "retention_months": 0, "inactive_days": 90})
check("solo administradores lo cambian = 403", carlos.patch("/api/admin/settings", {"sla_hours": 4})[0] == 403)
check("fuera de rango = 422", ana.patch("/api/admin/settings", {"sla_hours": 0})[0] == 422
      and ana.patch("/api/admin/settings", {"sla_hours": 500})[0] == 422)
st, r = ana.patch("/api/admin/settings", {"sla_hours": 1})
check("cambiar el plazo", st == 200 and r["sla_hours"] == 1 and carlos.get("/api/settings")[1]["sla_hours"] == 1, r)
check("queda en el registro de accesos",
      ana.get("/api/admin/audit?action=settings_change")[1]["entries"][0]["detail"] == "sla_hours=1")

since = (date.today() - timedelta(days=364)).isoformat()
with get_conn() as conn:
    hours = [t["hours"] for t in metrics.response_times(since, conn)]
expected = round(100 * sum(1 for h in hours if h <= 1) / len(hours))
d = ana.get("/api/dashboard?days=365")[1]
check("el panel calcula el % respondido en plazo", d["totals"]["within_sla_pct"] == expected
      and d["totals"]["sla_hours"] == 1, (d["totals"], expected))
check("y por persona", all("within_sla_pct" in p for p in d["people"]))
ana.patch("/api/admin/settings", {"sla_hours": 168})
check("con un plazo amplio, todo en plazo", ana.get("/api/dashboard?days=365")[1]["totals"]["within_sla_pct"] == 100)
sys.exit(0 if results["ok"] else 1)
