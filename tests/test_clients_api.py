import base64
import sys

from apitest import Session, check, results

ana, carlos = Session("ana"), Session("carlos")

# Crear y editar
st, r = ana.post("/api/clients", {"name": "Laura G.", "company": ""})
check("crear cliente a mano", st == 200 and r["id"], r)
dup = r["id"]
st, c = ana.get(f"/api/clients/{dup}")
check("responsable = quien lo crea, estado activo", c["assignee"] == "Ana Ruiz" and c["status"] == "active" and c["company"] is None, c)
st, c = ana.patch(f"/api/clients/{dup}", {"status": "lead", "assignee_user_id": 2, "company": "  Floristería  "})
check("editar estado, responsable y empresa", c["status"] == "lead" and c["assignee"] == "Carlos Pérez" and c["company"] == "Floristería", c)
check("aviso al nuevo responsable", "te ha hecho responsable de Laura G." in carlos.get("/api/notifications")[1]["items"][0]["text"])
check("estado no válido = 422", ana.patch(f"/api/clients/{dup}", {"status": "raro"})[0] == 422)
check("nombre vacío = 422", ana.patch(f"/api/clients/{dup}", {"name": ""})[0] == 422)

# Etiquetas
st, r = ana.call("PUT", f"/api/clients/{dup}/tags", {"tags": ["VIP", " vip ", "mayorista", ""]})
check("etiquetas sin duplicados ni vacías", r["tags"] == ["VIP", "mayorista"], r)
ana.call("PUT", "/api/clients/2/tags", {"tags": ["mayorista"]})
st, tags = ana.get("/api/tags")
check("lista de etiquetas con recuento", {t["tag"].lower(): t["clients"] for t in tags} == {"mayorista": 2, "vip": 1}, tags)

# Filtros de la lista
names = lambda path: sorted(c["name"] for c in ana.get(path)[1])  # noqa: E731
check("filtro por estado", names("/api/clients?status=lead") == ["Laura G."])
check("filtro por etiqueta", names("/api/clients?tag=mayorista") == ["Jorge Martín", "Laura G."])
check("filtro 'míos' (de Carlos)", names("/api/clients?mine=true") == [] and
      sorted(c["name"] for c in carlos.get("/api/clients?mine=true")[1]) == ["Laura G."])
check("la búsqueda encuentra por etiqueta", names("/api/clients?q=VIP") == ["Laura G."])
check("la lista trae estado y etiquetas", next(c for c in ana.get("/api/clients")[1] if c["id"] == dup)["tags"] == ["mayorista", "VIP"])

# Identificadores
st, r = ana.post(f"/api/clients/{dup}/identities", {"channel": "phone", "handle": "600 111 222"})
check("añadir teléfono", st == 200, r)
st, r = ana.post(f"/api/clients/{dup}/identities", {"channel": "email", "handle": "LAURA@floristeriagomez.es"})
check("un email de otro cliente = 409 con sugerencia de unir", st == 409 and "Unir con otro cliente" in r["detail"], r)
st, r = ana.post(f"/api/clients/{dup}/identities", {"channel": "fax", "handle": "x"})
check("canal no válido = 422", st == 422)

# Duplicados
st, d = ana.get(f"/api/clients/{dup}/duplicates")
check("detecta a Laura Gómez por el teléfono", [(x["name"], x["reasons"]) for x in d] == [("Laura Gómez", ["mismo teléfono"])], d)
st, d = ana.get("/api/clients/1/duplicates")
check("y al revés", [x["id"] for x in d] == [dup], d)

# Contenido del duplicado antes de unir
chat = "10/09/26, 10:00 - Laura: Soy Laura otra vez, desde el móvil nuevo\n"
ana.post("/api/import/file", {"filename": "c.txt", "data": base64.b64encode(chat.encode()).decode(),
                              "client_key": "Laura", "client_id": dup, "handle": "+34 699 000 000"})
ana.post(f"/api/clients/{dup}/facts", {"label": "Móvil nuevo", "value": "699 000 000"})
ana.post(f"/api/clients/{dup}/tasks", {"title": "Actualizar teléfono"})
ana.post(f"/api/clients/{dup}/notes", {"body": "Cambió de móvil"})
ana.post(f"/api/clients/{dup}/visit")
ana.post("/api/clients/1/visit")

# Unir: todo pasa a Laura Gómez (1) y el duplicado desaparece
st, m = ana.post(f"/api/clients/{dup}/merge", {"into_client_id": 1})
check("unir clientes", st == 200 and m["client_id"] == 1 and m["moved_conversations"] == 1, m)
check("el duplicado ya no existe", ana.get(f"/api/clients/{dup}")[0] == 404)
st, c = ana.get("/api/clients/1")
check("identificadores movidos", {"600 111 222", "+34 699 000 000"} <= {i["handle"] for i in c["identities"]}, c["identities"])
check("etiquetas movidas", c["tags"] == ["mayorista", "VIP"], c["tags"])
check("conversación movida", any(x["channel"] == "whatsapp" and x["messages"] == 1 for x in c["conversations"]), c["conversations"])
check("dato movido", any(f["label"] == "Móvil nuevo" for f in ana.get("/api/clients/1/profile")[1]["facts"]))
check("tarea movida", any(t["title"] == "Actualizar teléfono" for t in ana.get("/api/tasks?scope=all&status=all&client_id=1")[1]))
check("nota movida", any(n["body"] == "Cambió de móvil" for n in ana.get("/api/clients/1/notes")[1]))
check("el mensaje es buscable en el cliente que queda", any(r["client_id"] == 1 for r in ana.get("/api/search?q=m%C3%B3vil%20nuevo")[1]))
check("unir consigo mismo = 400", ana.post("/api/clients/1/merge", {"into_client_id": 1})[0] == 400)
check("unir con inexistente = 404", ana.post("/api/clients/1/merge", {"into_client_id": 999})[0] == 404)

st, c = ana.get("/api/clients/1")
ident = next(i for i in c["identities"] if i["handle"] == "600 111 222")
check("quitar identificador", ana.delete(f"/api/identities/{ident['id']}")[0] == 200)
check("identificador inexistente = 404", ana.delete(f"/api/identities/{ident['id']}")[0] == 404)
sys.exit(0 if results["ok"] else 1)
