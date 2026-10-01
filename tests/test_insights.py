"""Prueba del análisis con IA usando una respuesta simulada de Claude (sin llamar a la API)."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

SCRATCH = Path(__file__).resolve().parent / ".tmp"
SCRATCH.mkdir(exist_ok=True)
import testdb  # noqa: F401,E402  (base de datos de pruebas; antes que la app)

from app import agent, insights, seed  # noqa: E402
from app.db import get_conn  # noqa: E402

seed.seed(reset=True, basico=True)
ok = True


def check(label, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label + (f"  -> {extra}" if extra and not cond else ""))


prompts = []
fake_result = {}


def fake_create(**params):
    prompts.append(params)
    return SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=json.dumps(fake_result))])


agent._create = fake_create

with get_conn() as conn:
    laura_msgs = {r["body"][:25]: r["id"] for r in conn.execute(
        """SELECT m.id, m.body FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE c.client_id = 1""")}
addr_msg = next(v for k, v in laura_msgs.items() if k.startswith("Genial. La dirección"))
cif_msg = next(v for k, v in laura_msgs.items() if k.startswith("Buenos días Carlos"))
nov_msg = next(v for k, v in laura_msgs.items() if k.startswith("Gracias. Para el próximo"))
repo_msg = next(v for k, v in laura_msgs.items() if k.startswith("Lo siento mucho"))

fake_result = {
    "summary": "Cliente habitual de cajas con logo. Pedido entregado con 3 defectuosas; reposición prometida.",
    "facts": [
        {"label": "Dirección de envío", "value": "Calle Mayor 45, local 2, 28013 Madrid", "message_id": addr_msg},
        {"label": "CIF", "value": "B12345678", "message_id": cif_msg},
        {"label": "Inventado", "value": "x", "message_id": 999999},
    ],
    "new_tasks": [
        {"title": "Enviar 3 cajas de reposición a Laura", "due_date": "2026-09-05", "owner": "", "message_id": repo_msg},
        {"title": "Preguntar a Laura por el pedido de 350 unidades", "due_date": "2026-11-01", "owner": "Carlos",
         "message_id": nov_msg},
        {"title": "Tarea con fecha rara", "due_date": "el viernes", "owner": "", "message_id": 0},
    ],
    "completed_task_ids": [],
    "priority": "alta",
    "priority_reason": "  Espera la reposición de 3 cajas defectuosas ",
    "mood": "molesto",
}
changes = insights.analyze_client(1)
check("cambios devueltos", changes == {"facts": 3, "new_tasks": 3, "completed_tasks": 0}, changes)
p = prompts[-1]
check("usa salida estructurada", p["output_config"]["format"]["type"] == "json_schema")
check("el prompt incluye los mensajes con su id", f"[{addr_msg}]" in p["messages"][0]["content"])

prof = insights.profile(1)
check("resumen guardado", prof["summary"].startswith("Cliente habitual"))
check("prioridad y tono guardados", (prof["priority"], prof["mood"], prof["priority_reason"])
      == ("alta", "molesto", "Espera la reposición de 3 cajas defectuosas"), prof)
check("el esquema pide prioridad y tono", {"priority", "mood"} <= set(p["output_config"]["format"]["schema"]["required"]))
from app import search  # noqa: E402
laura_inbox = [i for i in search.unanswered(0, "team") if i["client_id"] == 1]
check("la bandeja muestra la prioridad del cliente", laura_inbox and all(i["priority"] == "alta" and i["mood"] == "molesto"
                                                                     for i in laura_inbox), laura_inbox)
check("sin mensajes nuevos tras analizar", prof["new_messages_since_analysis"] == 0)
check("datos con su mensaje de origen", {f["label"]: f["source_message_id"] for f in prof["facts"]}
      == {"CIF": cif_msg, "Dirección de envío": addr_msg, "Inventado": None}, prof["facts"])
tasks = insights.list_tasks(client_id=1)
by_title = {t["title"]: t for t in tasks}
repo = by_title["Enviar 3 cajas de reposición a Laura"]
check("tarea asignada a quien llevaba la conversación (Marta)", repo["assignee"] == "Marta López", repo)
check("tarea asignada a la persona nombrada (Carlos)",
      by_title["Preguntar a Laura por el pedido de 350 unidades"]["assignee"] == "Carlos Pérez")
check("fecha no válida se ignora", by_title["Tarea con fecha rara"]["due_date"] is None)
check("orden: por fecha de vencimiento", [t["due_date"] for t in tasks] == ["2026-09-05", "2026-11-01", None])

# Una persona corrige un dato y descarta otro; el segundo análisis los respeta.
with get_conn() as conn:
    conn.execute("UPDATE client_facts SET origin = 'manual', value = 'B12345678 (verificado)' WHERE label = 'CIF'")
    conn.execute("UPDATE client_facts SET origin = 'dismissed' WHERE label = 'Inventado'")
fake_result = {
    "summary": "Reposición enviada.",
    "facts": [{"label": "Dirección de envío", "value": "Calle Mayor 45, local 2, 28013 Madrid", "message_id": addr_msg},
              {"label": "inventado", "value": "X", "message_id": 1},
              {"label": "Horario de entrega", "value": "Mañanas", "message_id": addr_msg}],
    "new_tasks": [],
    "completed_task_ids": [repo["id"], 424242],
}
changes = insights.analyze_client(1)
second_prompt = prompts[-1]["messages"][0]["content"]
check("el prompt pasa los datos confirmados y descartados",
      "- CIF: B12345678 (verificado)" in second_prompt and "- Inventado: x" in second_prompt)
check("el prompt pasa las tareas existentes con id", f"[{repo['id']}] (abierta)" in second_prompt)
labels = {f["label"]: f["origin"] for f in insights.profile(1)["facts"]}
check("manual se conserva, descartado no vuelve, IA se renueva",
      labels == {"CIF": "manual", "Dirección de envío": "ai", "Horario de entrega": "ai"}, labels)
check("tarea completada por la IA (e id inexistente ignorado)", changes["completed_tasks"] == 1, changes)
check("estado de la tarea", insights.get_task(repo["id"])["status"] == "done")

# Sin mensajes y respuestas problemáticas
with get_conn() as conn:
    conn.execute("INSERT INTO clients (id, name) VALUES (50, 'Vacío')")
try:
    insights.analyze_client(50)
    check("cliente sin mensajes da error", False)
except insights.AnalysisError as e:
    check(f"cliente sin mensajes: {e}", True)
agent._create = lambda **_: SimpleNamespace(stop_reason="refusal", content=[])
try:
    insights.analyze_client(1)
    check("rechazo de la IA da error", False)
except insights.AnalysisError as e:
    check(f"rechazo de la IA: {e}", True)
sys.exit(0 if ok else 1)
