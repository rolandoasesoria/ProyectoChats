"""Respuestas guardadas y macros: CRUD, permisos, variables y acciones."""
import sys

from apitest import Session, check, results

ana, carlos = Session("ana"), Session("carlos")

st, items = carlos.get("/api/replies")
check("lista de respuestas de ejemplo", st == 200 and {r["shortcut"] for r in items} >= {"facturacion", "envio", "gracias"}, items)

st, r = carlos.post("/api/replies", {"title": "Horario", "shortcut": "/Horario", "body": "Hola {nombre}, abrimos de 9 a 14. {yo}"})
check("crear respuesta (el atajo se guarda sin / y en minúsculas)", st == 200 and r["shortcut"] == "horario" and r["author"] == "Carlos Pérez", r)
hid = r["id"]
check("atajo repetido = 400", carlos.post("/api/replies", {"title": "Otra", "shortcut": "horario", "body": "x"})[0] == 400)
check("atajo con espacios = 400", carlos.post("/api/replies", {"title": "Otra", "shortcut": "dos palabras", "body": "x"})[0] == 400)
check("sin texto = 422", carlos.post("/api/replies", {"title": "Vacía", "body": ""})[0] == 422)
check("otro usuario no puede editarla = 403", Session("marta").patch(f"/api/replies/{hid}", {"title": "X"})[0] == 403)
st, r = ana.patch(f"/api/replies/{hid}", {"title": "Horario de verano", "shortcut": None})
check("un administrador sí, y se puede quitar el atajo", st == 200 and r["title"] == "Horario de verano" and r["shortcut"] is None, r)

# Variables: Laura Gómez (cliente 1), con empresa y un dato clave
ana.post("/api/clients/1/facts", {"label": "Dirección de envío", "value": "Calle Mayor 45, Madrid"})
st, used = carlos.post(f"/api/replies/{hid}/use", {"client_id": 1})
check("rellena {nombre} y {yo}", used["text"] == "Hola Laura, abrimos de 9 a 14. Carlos Pérez", used)
envio = next(r for r in items if r["shortcut"] == "envio")
st, used = carlos.post(f"/api/replies/{envio['id']}/use", {"client_id": 1})
check("rellena {dato:...} sin distinguir mayúsculas ni tildes",
      used["text"].endswith("va a Calle Mayor 45, Madrid?") and used["applied"] == [], used)
st, used = carlos.post(f"/api/replies/{envio['id']}/use", {"client_id": 2})
check("dato desconocido queda como [hueco]", "[Dirección de envío]" in used["text"], used)
st, r = carlos.post("/api/replies", {"title": "Empresa", "body": "{empresa} / {cliente} / {desconocida}"})
st, used = carlos.post(f"/api/replies/{r['id']}/use", {"client_id": 3})
check("empresa desconocida y variables no reconocidas", used["text"] == "[empresa] / Sofía Navarro / {desconocida}", used)
check("cliente inexistente = 404", carlos.post(f"/api/replies/{hid}/use", {"client_id": 999})[0] == 404)

# Macro: estado + etiqueta
presupuesto = next(r for r in items if r["shortcut"] == "presupuesto")
st, used = carlos.post(f"/api/replies/{presupuesto['id']}/use", {"client_id": 2})
client = carlos.get("/api/clients/2")[1]
check("macro: cambia el estado y añade la etiqueta", client["status"] == "lead" and "presupuesto enviado" in client["tags"]
      and used["applied"] == ["estado: Potencial", "etiqueta «presupuesto enviado»"], (used, client["status"], client["tags"]))
st, used = carlos.post(f"/api/replies/{presupuesto['id']}/use", {"client_id": 2})
check("la etiqueta no se duplica", used["applied"] == ["estado: Potencial"], used)

# Macro: marcar atendida
inbox = ana.get("/api/inbox?scope=mine")[1]
item = inbox[0]
gracias = next(r for r in items if r["shortcut"] == "gracias")
st, used = ana.post(f"/api/replies/{gracias['id']}/use", {"client_id": item["client_id"], "conversation_id": item["conversation_id"]})
check("macro: marca la conversación como atendida", "conversación marcada como atendida" in used["applied"]
      and all(i["conversation_id"] != item["conversation_id"] for i in ana.get("/api/inbox?scope=mine")[1]), used)

check("borrar ajena = 403", Session("marta").delete(f"/api/replies/{hid}")[0] == 403)
check("borrar propia", carlos.delete(f"/api/replies/{hid}")[0] == 200
      and all(r["id"] != hid for r in carlos.get("/api/replies")[1]))
check("sin sesión = 401", Session().get("/api/replies")[0] == 401)
sys.exit(0 if results["ok"] else 1)
