"""Sección Contactos: propiedades de contacto (las define un administrador), sus valores y la tabla de contactos."""
import sys
import unicodedata

from apitest import Session, check, results

ana, carlos = Session("ana"), Session("carlos")

# ---------------------------------------------------------------- Propiedades (solo administradores)
check("sin propiedades al principio", ana.get("/api/properties")[1] == [])
check("Carlos no puede crearlas = 403", carlos.post("/api/admin/properties", {"label": "DNI", "kind": "text"})[0] == 403)
st, dni = ana.post("/api/admin/properties", {"label": "DNI", "kind": "text"})
check("crear una de texto", st == 200 and dni["label"] == "DNI" and dni["kind"] == "text", dni)
st, alta = ana.post("/api/admin/properties", {"label": "Fecha de alta", "kind": "date"})
st, plantilla = ana.post("/api/admin/properties", {"label": "Empleados", "kind": "number"})
st, origen = ana.post("/api/admin/properties", {"label": "Origen", "kind": "select", "options": ["Web", "Referido", " Web "]})
check("lista de opciones sin repetidas", origen["options"] == ["Web", "Referido"], origen)
check("nombre repetido = 409", ana.post("/api/admin/properties", {"label": "dni", "kind": "text"})[0] == 409)
check("lista sin opciones = 400", ana.post("/api/admin/properties", {"label": "Zona", "kind": "select"})[0] == 400)
check("tipo no válido = 422", ana.post("/api/admin/properties", {"label": "X", "kind": "color"})[0] == 422)
st, edited = ana.patch(f"/api/admin/properties/{dni['id']}", {"label": "DNI / NIE"})
check("renombrar", st == 200 and edited["label"] == "DNI / NIE", edited)
order = [origen["id"], dni["id"], alta["id"], plantilla["id"]]
check("reordenar", [p["id"] for p in ana.call("PUT", "/api/admin/properties/order", {"ids": order})[1]] == order)
check("todos las ven (en ese orden)", [p["id"] for p in carlos.get("/api/properties")[1]] == order)

# ---------------------------------------------------------------- Valores en la ficha
values = {str(dni["id"]): "12345678Z", str(alta["id"]): "2024-03-01", str(plantilla["id"]): "12,5",
          str(origen["id"]): "Referido"}
st, r = carlos.call("PUT", "/api/clients/1/properties", {"values": values})
check("cualquiera las rellena", st == 200 and r["values"][str(plantilla["id"])] == "12.5", r)
check("se leen en la ficha", carlos.get("/api/clients/1/properties")[1]["values"][str(dni["id"])] == "12345678Z")
for label, bad in (("fecha", {str(alta["id"]): "1 de marzo"}), ("número", {str(plantilla["id"]): "doce"}),
                   ("opción", {str(origen["id"]): "Feria"}), ("propiedad", {"99999": "x"})):
    check(f"{label} no válida = 400", carlos.call("PUT", "/api/clients/1/properties", {"values": bad})[0] == 400)
st, r = carlos.call("PUT", "/api/clients/1/properties", {"values": {str(dni["id"]): "  "}})
check("vacío borra el valor y deja los demás", str(dni["id"]) not in r["values"] and str(alta["id"]) in r["values"], r)
check("cliente inexistente = 404", carlos.get("/api/clients/9999/properties")[0] == 404)

# ---------------------------------------------------------------- Tabla de contactos
st, table = ana.get("/api/contacts")
laura = next(c for c in table if c["id"] == 1)
check("la tabla trae teléfonos, emails, canales y etiquetas",
      laura["phones"] and laura["emails"] and "whatsapp" in laura["channels"] and isinstance(laura["tags"], list), laura)
check("y las propiedades", laura["properties"][str(origen["id"])] == "Referido", laura["properties"])
# Orden: por nombre por defecto (sin tener en cuenta mayúsculas ni tildes) y de otras formas
ana.post("/api/clients", {"name": "álvaro Ruiz", "company": "Zeta SL"})
ana.post("/api/clients", {"name": "Beatriz Soler"})


def names(query=""):
    return [c["name"] for c in ana.get(f"/api/contacts{query}")[1]]


def plain(text):
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()


by_name = names()
check("por defecto, ordenados por nombre (sin mirar mayúsculas ni tildes)",
      by_name == sorted(by_name, key=plain) and by_name[0] == "álvaro Ruiz", by_name)
check("y de la Z a la A", names("?sort=name&order=desc") == by_name[::-1])
activity = ana.get("/api/contacts?sort=activity")[1]
dates = [c["last_message_at"] for c in activity if c["last_message_at"]]
check("por última actividad: lo más reciente primero y los que no tienen mensajes al final",
      dates == sorted(dates, reverse=True) and not activity[-1]["last_message_at"], [c["name"] for c in activity])
companies = [c["company"] for c in ana.get("/api/contacts?sort=company")[1]]
filled = [c for c in companies if c]
check("por empresa (los que no tienen, al final)", filled == sorted(filled, key=plain) and companies[-1] in (None, ""), companies)
check("por fecha de alta: los nuevos primero", names("?sort=created")[:2] == ["Beatriz Soler", "álvaro Ruiz"])
statuses = [c["status"] for c in ana.get("/api/contacts?sort=status")[1]]
rank = {"issue": 0, "lead": 1, "active": 2, "inactive": 3}
check("por estado: incidencias, potenciales, activos e inactivos", statuses == sorted(statuses, key=rank.get), statuses)
check("un orden que no existe = 422", ana.get("/api/contacts?sort=telefono")[0] == 422)
check("y el último mensaje, como en la lista de chats (para la lista junto al contacto abierto)",
      laura["last_body"] and laura["last_direction"] in ("in", "out") and laura["last_message_at"], laura)
check("filtro por canal", all("telegram" in c["channels"] for c in ana.get("/api/contacts?channel=telegram")[1]))
check("buscar", [c["id"] for c in ana.get("/api/contacts?q=laura")[1]] == [1])

# ---------------------------------------------------------------- Al unir clientes se conservan
st, nuevo = ana.post("/api/clients", {"name": "Laura (duplicada)"})
ana.call("PUT", f"/api/clients/{nuevo['id']}/properties", {"values": {str(dni["id"]): "87654321X", str(origen["id"]): "Web"}})
check("unir", ana.post(f"/api/clients/{nuevo['id']}/merge", {"into_client_id": 1})[0] == 200)
merged = ana.get("/api/clients/1/properties")[1]["values"]
check("el que se queda recibe lo que le faltaba y conserva lo suyo",
      merged[str(dni["id"])] == "87654321X" and merged[str(origen["id"])] == "Referido", merged)

st, export = ana.get("/api/clients/1/export")
check("la exportación de datos del cliente incluye sus propiedades",
      {"label": "DNI / NIE", "value": "87654321X"}.items() <= next((p for p in export.get("properties", [])
                                                                  if p["label"] == "DNI / NIE"), {}).items(), export.get("properties"))

# ---------------------------------------------------------------- Borrar una propiedad borra sus valores
check("borrar", ana.delete(f"/api/admin/properties/{origen['id']}")[0] == 200)
check("ya no aparece en la ficha", str(origen["id"]) not in ana.get("/api/clients/1/properties")[1]["values"])
check("borrar la que no existe = 404", ana.delete(f"/api/admin/properties/{origen['id']}")[0] == 404)
sys.exit(0 if results["ok"] else 1)
