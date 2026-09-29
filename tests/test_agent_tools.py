"""Herramientas del asistente: alcance aplicado en el servidor, ficha ampliada y registro de accesos."""
import os
import sys
from pathlib import Path

db = Path(__file__).resolve().parent / ".tmp" / "agent_tools_test.db"
db.parent.mkdir(exist_ok=True)
db.unlink(missing_ok=True)
os.environ["DB_PATH"] = str(db)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import agent, audit, notes, seed  # noqa: E402
from app.db import get_conn  # noqa: E402
from apitest import check, results  # noqa: E402

seed.seed()
ANA = 1

mine = agent._run_tool("buscar_mensajes", {"consulta": "CIF factura", "alcance": "mias"}, ANA)
check("con alcance 'mias' Ana no ve el CIF (está en el email de Carlos)", isinstance(mine, dict) and mine["resultados"] == 0, mine)
team = agent._run_tool("buscar_mensajes", {"consulta": "CIF", "alcance": "equipo"}, ANA)
check("con alcance 'equipo' sí, indicando de quién es", team and team[0]["owner"] == "Carlos Pérez", team)
check("la búsqueda en el equipo queda registrada",
      [(e["action"], e["detail"]) for e in audit.entries()] == [("assistant_team_search", "CIF")], audit.entries())

msg_id = team[0]["message_id"]
check("leer_contexto de un mensaje ajeno con 'mias' no se permite",
      "error" in agent._run_tool("leer_contexto", {"mensaje_id": msg_id, "alcance": "mias"}, ANA))
ctx = agent._run_tool("leer_contexto", {"mensaje_id": msg_id, "alcance": "equipo"}, ANA)
check("con 'equipo' sí", ctx["owner"] == "Carlos Pérez" and len(ctx["messages"]) >= 2, ctx)
try:
    agent._run_tool("buscar_mensajes", {"consulta": "x", "alcance": "todo"}, ANA)
    check("alcance inválido da error", False)
except ValueError:
    check("alcance inválido da error", True)

with get_conn() as conn:
    conn.execute("INSERT INTO client_facts (client_id, label, value, origin) VALUES (1, 'CIF', 'B12345678', 'manual')")
    conn.execute("INSERT INTO tasks (client_id, title, due_date, assignee_user_id) VALUES (1, 'Enviar presupuesto', '2026-10-01', 1)")
notes.add_note(1, {"id": 2, "name": "Carlos Pérez"}, "Paga tarde")
ficha = agent._run_tool("resumen_cliente", {"cliente_id": 1}, ANA)
check("la ficha incluye datos clave", ficha["datos_clave"] == [{"dato": "CIF", "valor": "B12345678", "origen": "confirmado"}], ficha["datos_clave"])
check("tareas abiertas", ficha["tareas_abiertas"] == [{"tarea": "Enviar presupuesto", "vence": "2026-10-01", "responsable": "Ana Ruiz"}])
check("notas internas", ficha["notas_internas"][0]["nota"] == "Paga tarde" and ficha["notas_internas"][0]["autor"] == "Carlos Pérez")
check("estado y etiquetas", ficha["status"] == "active" and ficha["tags"] == [])
found = agent._run_tool("buscar_cliente", {"texto": "floristeria"}, ANA)
check("buscar_cliente por empresa (sin tilde)", [c["name"] for c in found] == ["Laura Gómez"], found)
db.unlink()
sys.exit(0 if results["ok"] else 1)
