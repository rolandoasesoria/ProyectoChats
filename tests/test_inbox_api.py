import sys

from apitest import Session, check, receive, results

ana, marta = Session("ana"), Session("marta")

st, mine = ana.get("/api/inbox?scope=mine")
check("bandeja de Ana: Jorge (email) y Laura (WhatsApp), la más antigua primero",
      [(i["client"], i["channel"]) for i in mine] == [("Jorge Martín", "email"), ("Laura Gómez", "whatsapp")], mine)
check("todas son suyas", all(i["is_mine"] for i in mine))
st, team = ana.get("/api/inbox?scope=team")
check("bandeja del equipo: 5 conversaciones", len(team) == 5, [(i["client"], i["owner"]) for i in team])
check("Jorge por WhatsApp no está (el último mensaje es del equipo)",
      not any(i["client"] == "Jorge Martín" and i["channel"] == "whatsapp" for i in team))

laura = next(i for i in mine if i["client"] == "Laura Gómez")
check("atendido", ana.post(f"/api/conversations/{laura['conversation_id']}/dismiss",
                           {"message_id": laura["message_id"]})[0] == 200)
check("desaparece de la bandeja", len(ana.get("/api/inbox?scope=mine")[1]) == 1)
check("conversación inexistente = 404", ana.post("/api/conversations/9999/dismiss", {"message_id": 1})[0] == 404)

# Primera visita: no hay "novedades"; en la lista no hay contador hasta haberlo visitado
st, clients = ana.get("/api/clients")
check("sin visitas, sin contador de no leídos", all(c["unread"] is None for c in clients), clients)
st, v = ana.post("/api/clients/1/visit")
check("primera visita", v == {"previous_visit_at": None, "since_message_id": None, "new_messages": 0}, v)
st, clients = ana.get("/api/clients")
check("tras visitar: 0 no leídos", next(c for c in clients if c["id"] == 1)["unread"] == 0)

# Llega un mensaje nuevo de Laura por WhatsApp (conversación de Ana)
res = receive("whatsapp", "+34600111222", "Hola Ana, ¿al final podéis entregar el martes?", client_name="Laura Gómez",
              sent_at="2026-08-06T09:00:00")
check("entra el mensaje nuevo en la ficha de Laura", res["messages"] == 1 and res["client_id"] == 1, res)
st, clients = ana.get("/api/clients")
check("no leídos: 1", next(c for c in clients if c["id"] == 1)["unread"] == 1)
check("para Marta (nunca lo abrió) sigue sin contador",
      next(c for c in marta.get("/api/clients")[1] if c["id"] == 1)["unread"] is None)
check("Laura vuelve a la bandeja al escribir de nuevo",
      any(i["client"] == "Laura Gómez" for i in ana.get("/api/inbox?scope=mine")[1]))

st, v = ana.post("/api/clients/1/visit")
check("segunda visita: 1 mensaje nuevo desde la anterior", v["new_messages"] == 1 and v["previous_visit_at"], v)
st, r = ana.post("/api/clients/1/whats-new", {"since_message_id": v["since_message_id"]})
check("resumir novedades sin clave = 503 claro", st == 503, r)
st, r = ana.post("/api/clients/1/whats-new", {"since_message_id": 10**9})
check("sin mensajes nuevos no llama a la IA", r == {"summary": "No hay mensajes nuevos."}, r)
st, v = ana.post("/api/clients/1/visit")
check("tercera visita: nada nuevo", v["new_messages"] == 0, v)
sys.exit(0 if results["ok"] else 1)
