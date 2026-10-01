"""Cifras del panel comparadas con las calculadas a mano sobre los datos de ejemplo (julio-septiembre de 2026).

Se usa el periodo de 1 año para que la prueba no dependa del día en que se ejecute (válida hasta mediados de 2027).
"""
import sys
from datetime import date, timedelta

from apitest import Session, check, results

from app.db import get_conn

ana, carlos = Session("ana"), Session("carlos")

st, d = ana.get("/api/dashboard?days=365")
t = d["totals"]
check("1 año: 13 recibidos y 8 enviados", (t["received"], t["sent"]) == (13, 8), t)
check("3 clientes con actividad", t["active_clients"] == 3)
check("mediana de primera respuesta = 15 min", abs(t["median_response_hours"] - 0.25) < 1e-6, t["median_response_hours"])
check("semanas completas del periodo, en orden", len(d["weekly"]) in (53, 54) and d["weekly"][0]["week"] < d["weekly"][-1]["week"])
check("la suma semanal cuadra con el total", sum(w["email"] + w["telegram"] + w["whatsapp"] for w in d["weekly"]) == 13)
check("clientes por estado", d["clients_by_status"] == {"lead": 0, "active": 3, "issue": 0, "inactive": 0})
people = {p["name"]: p for p in d["people"]}
check("Ana: mediana 3 min con 3 respuestas", abs(people["Ana Ruiz"]["median_response_hours"] - 0.05) < 1e-6
      and people["Ana Ruiz"]["responses"] == 3, people["Ana Ruiz"])
check("Carlos: mediana 21 min", abs(people["Carlos Pérez"]["median_response_hours"] - 0.35) < 1e-6)
check("esperando respuesta por persona", (people["Ana Ruiz"]["waiting"], people["Carlos Pérez"]["waiting"],
                                           people["Marta López"]["waiting"]) == (2, 1, 2), people)

# 30 días: se compara con una consulta directa a la base de datos, sea cual sea la fecha de hoy.
since = (date.today() - timedelta(days=29)).isoformat()
with get_conn() as conn:
    expected = conn.execute("SELECT count(*) FROM messages WHERE direction = 'in' AND sent_at >= ?", (since,)).fetchone()[0]
check("30 días: solo los mensajes del periodo", ana.get("/api/dashboard?days=30")[1]["totals"]["received"] == expected)

ana.post("/api/clients/1/tasks", {"title": "vencida", "due_date": (date.today() - timedelta(days=10)).isoformat()})
ana.post("/api/clients/1/tasks", {"title": "futura", "due_date": (date.today() + timedelta(days=30)).isoformat()})
t = ana.get("/api/dashboard")[1]["totals"]
check("tareas abiertas y vencidas", (t["open_tasks"], t["overdue_tasks"]) == (2, 1), t)

st, d = carlos.get("/api/dashboard?days=90")
check("quien no es administrador no ve el desglose por persona", st == 200 and "people" not in d)
check("periodo no permitido = 422", ana.get("/api/dashboard?days=12")[0] == 422)
sys.exit(0 if results["ok"] else 1)
