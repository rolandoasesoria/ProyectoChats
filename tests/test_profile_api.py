import sys

from apitest import Session, check, results

ana, marta = Session("ana"), Session("marta")

st, p = ana.get("/api/clients/1/profile")
check("ficha vacía al principio", st == 200 and p["summary"] is None and p["facts"] == [], p)
st, p = ana.post("/api/clients/1/analyze")
check("analizar sin clave = 503 claro", st == 503, p)

st, p = ana.post("/api/clients/1/facts", {"label": "CIF", "value": "B12345678"})
check("añadir dato manual", st == 200 and p["facts"][0]["origin"] == "manual" and p["facts"][0]["updated_by"] == "Ana Ruiz", p)
fid = p["facts"][0]["id"]
st, p = marta.patch(f"/api/facts/{fid}", {"label": "CIF", "value": "B87654321"})
check("otra persona lo edita", p["facts"][0]["value"] == "B87654321" and p["facts"][0]["updated_by"] == "Marta López", p)
check("dato vacío rechazado = 422", ana.post("/api/clients/1/facts", {"label": "", "value": "x"})[0] == 422)
st, p = ana.delete(f"/api/facts/{fid}")
check("borrar dato manual", p["facts"] == [], p)
check("dato inexistente = 404", ana.delete(f"/api/facts/{fid}")[0] == 404)

st, t = ana.post("/api/clients/1/tasks", {"title": "Llamar a Laura", "due_date": "2020-01-01"})
check("crear tarea (se asigna a quien la crea)", st == 200 and t["assignee"] == "Ana Ruiz" and t["status"] == "open", t)
st, t2 = ana.post("/api/clients/2/tasks", {"title": "Enviar etiquetas", "assignee_user_id": 3})
check("crear tarea para Marta", t2["assignee"] == "Marta López", t2)
check("fecha mal formada = 422", ana.post("/api/clients/1/tasks", {"title": "x", "due_date": "mañana"})[0] == 422)

st, mine = ana.get("/api/tasks?scope=mine")
check("mis tareas (Ana)", [x["title"] for x in mine] == ["Llamar a Laura"], mine)
check("mis tareas (Marta)", [x["title"] for x in marta.get("/api/tasks?scope=mine")[1]] == ["Enviar etiquetas"])
check("tareas del cliente 1 (todas)", len(ana.get("/api/tasks?scope=all&status=all&client_id=1")[1]) == 1)

st, t = ana.patch(f"/api/tasks/{t['id']}", {"status": "done"})
check("completar tarea", t["status"] == "done" and t["done_at"], t)
check("ya no está en abiertas", ana.get("/api/tasks?scope=mine")[1] == [])
st, t = ana.patch(f"/api/tasks/{t['id']}", {"status": "open", "due_date": None, "assignee_user_id": 2})
check("reabrir, quitar fecha y reasignar", t["status"] == "open" and t["done_at"] is None and t["due_date"] is None
      and t["assignee"] == "Carlos Pérez", t)
st, t = ana.patch(f"/api/tasks/{t['id']}", {"title": "Llamar a Laura por el pedido"})
check("cambiar solo el título conserva lo demás", t["title"] == "Llamar a Laura por el pedido" and t["assignee"] == "Carlos Pérez", t)
check("borrar tarea", ana.delete(f"/api/tasks/{t['id']}")[0] == 200)
check("tarea inexistente = 404", ana.patch(f"/api/tasks/{t['id']}", {"status": "done"})[0] == 404)

st, team = ana.get("/api/team")
check("equipo visible para asignar", [u["name"] for u in team] == ["Ana Ruiz", "Carlos Pérez", "Marta López"], team)
check("sin sesión = 401", Session().get("/api/tasks")[0] == 401)
sys.exit(0 if results["ok"] else 1)
