"""Borradores: prompt y contexto con una respuesta simulada de Claude; y la API sin clave."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

SCRATCH = Path(__file__).resolve().parent / ".tmp"
SCRATCH.mkdir(exist_ok=True)
db = SCRATCH / "drafts_test.db"
db.unlink(missing_ok=True)
os.environ["DB_PATH"] = str(db)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import agent, insights, seed  # noqa: E402
from app.db import get_conn  # noqa: E402
from apitest import Session, check, results  # noqa: E402

seed.seed()
calls = []
agent._create = lambda **p: calls.append(p) or SimpleNamespace(
    stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Hola Laura, ...")])

with get_conn() as conn:
    wa = conn.execute("SELECT id FROM conversations WHERE client_id = 1 AND channel = 'whatsapp'").fetchone()["id"]
    em = conn.execute("SELECT id FROM conversations WHERE client_id = 1 AND channel = 'email'").fetchone()["id"]
    conn.execute("INSERT INTO client_facts (client_id, label, value, origin) VALUES (1, 'CIF', 'B12345678', 'manual')")
    conn.execute("INSERT INTO tasks (client_id, title) VALUES (1, 'Enviar presupuesto de 350 cajas')")

ana = {"id": 1, "name": "Ana Ruiz"}
res = insights.draft_reply(wa, ana, "ofrece entrega el martes")
prompt = calls[-1]["messages"][0]["content"]
system = calls[-1]["system"]
check("devuelve el borrador y el canal", res == {"draft": "Hola Laura, ...", "channel": "whatsapp", "subject": None,
                                                 "client_id": 1}, res)
check("estilo WhatsApp", "WhatsApp: mensaje breve" in system)
check("no inventar datos", "[precio]" in system)
check("incluye quién escribe", "Escribe: Ana Ruiz" in prompt)
check("incluye datos clave y tareas", "- CIF: B12345678" in prompt and "Enviar presupuesto de 350 cajas" in prompt)
check("incluye otros canales como contexto", "· email ·" in prompt and "· telegram ·" in prompt)
check("incluye la conversación a responder", "Calle Mayor 45" in prompt.split("Conversación a la que hay que responder:")[1])
check("incluye las indicaciones", "ofrece entrega el martes" in prompt)
check("esfuerzo bajo", calls[-1]["output_config"] == {"effort": "low"})

insights.draft_reply(em, ana)
check("estilo email con firma y asunto", "firma" in calls[-1]["system"]
      and "asunto «Datos de facturación»" in calls[-1]["messages"][0]["content"])
check("sin indicaciones no añade la línea", "Indicaciones" not in calls[-1]["messages"][0]["content"])
try:
    insights.draft_reply(9999, ana)
    check("conversación inexistente", False)
except insights.AnalysisError:
    check("conversación inexistente da error", True)
db.unlink()

# API (instancia de pruebas, sin clave)
s = Session("ana")
st, r = s.post(f"/api/conversations/{wa}/draft", {"instructions": "x"})
check("API sin clave = 503 claro", st == 503, r)
check("API conversación inexistente = 404", s.post("/api/conversations/9999/draft", {})[0] == 404)
check("API indicaciones demasiado largas = 422", s.post(f"/api/conversations/{wa}/draft", {"instructions": "x" * 2000})[0] == 422)
sys.exit(0 if results["ok"] else 1)
