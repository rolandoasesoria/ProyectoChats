import sys

from apitest import Session, check, results

ana, carlos = Session("ana"), Session("carlos")

# Accesos a datos del equipo
carlos.get("/api/clients/1/timeline?scope=mine")
carlos.get("/api/clients/1/timeline?scope=team")
carlos.get("/api/clients/1/timeline?scope=team")  # repetida: no duplica el registro
carlos.get("/api/search?q=presupuesto&scope=team")
carlos.get("/api/inbox?scope=team")
st, log = ana.get("/api/admin/audit")
entries = log["entries"]
acts = [(e["user"], e["action"], e["client_name"]) for e in entries]
check("registra ver mensajes del equipo (una sola vez en 10 min)",
      acts.count(("Carlos Pérez", "team_messages", "Laura Gómez")) == 1, acts)
check("ver solo mis mensajes no se registra", len([a for a in acts if a[1] == "team_messages"]) == 1)
check("registra la búsqueda en el equipo con el texto", any(e["action"] == "team_search" and e["detail"] == "presupuesto" for e in entries))
check("registra la bandeja del equipo", ("Carlos Pérez", "team_inbox", None) in acts)
check("con descripción legible", entries[0]["action_label"].startswith("Vio") or entries[0]["action_label"].startswith("Buscó"), entries[0])
check("filtro por persona", all(e["user"] == "Carlos Pérez" for e in ana.get("/api/admin/audit?user_id=2")[1]["entries"]))
check("filtro por acción", [e["action"] for e in ana.get("/api/admin/audit?action=team_search")[1]["entries"]] == ["team_search"])
check("solo administradores ven el registro = 403", carlos.get("/api/admin/audit")[0] == 403)

# Cambios de cuentas
ana.post("/api/admin/users", {"username": "pepe", "name": "Pepe", "password": "pepe12345"})
st, users = ana.get("/api/admin/users")
pepe = next(u for u in users if u["username"] == "pepe")
ana.patch(f"/api/admin/users/{pepe['id']}", {"password": "otra12345", "role": "admin"})
entries = ana.get("/api/admin/audit?user_id=1")[1]["entries"]
check("registra alta de cuenta", any(e["action"] == "user_create" and "pepe" in e["detail"] for e in entries))
upd = next(e for e in entries if e["action"] == "user_update")
check("registra cambios de cuenta sin mostrar la contraseña", "contraseña restablecida" in upd["detail"]
      and "otra12345" not in upd["detail"] and "role=admin" in upd["detail"], upd)

# Exportar
check("exportar solo administradores = 403", carlos.get("/api/clients/1/export")[0] == 403)
st, data = ana.get("/api/clients/1/export")
check("exportar todos los datos", st == 200 and data["client"]["name"] == "Laura Gómez"
      and len(data["conversations"]) == 3 and sum(len(c["messages"]) for c in data["conversations"]) == 12
      and {i["channel"] for i in data["identities"]} == {"email", "whatsapp", "telegram"}, {k: type(v).__name__ for k, v in data.items()})
check("registra la exportación", ana.get("/api/admin/audit?action=client_export")[1]["entries"][0]["client_name"] == "Laura Gómez")

# Borrar
ana.post("/api/clients/1/notes", {"body": "nota"})
ana.post("/api/clients/1/tasks", {"title": "tarea"})
check("borrar solo administradores = 403", carlos.delete("/api/clients/1?confirm=Laura%20G%C3%B3mez")[0] == 403)
check("sin confirmar el nombre = 400", ana.delete("/api/clients/1?confirm=Laura")[0] == 400)
st, r = ana.delete("/api/clients/1?confirm=laura%20g%C3%B3mez")
check("borrar cliente", st == 200 and r == {"conversations": 3, "messages": 12}, r)
check("ya no existe", ana.get("/api/clients/1")[0] == 404)
check("sus mensajes ya no aparecen en búsquedas", ana.get("/api/search?q=Calle%20Mayor&scope=team")[1] == [])
check("sus tareas tampoco", all(t["client"] != "Laura Gómez" for t in ana.get("/api/tasks?scope=mine")[1]))
del_entry = ana.get("/api/admin/audit?action=client_delete")[1]["entries"][0]
check("el registro conserva el nombre del cliente borrado", del_entry["client_name"] == "Laura Gómez", del_entry)

from app.db import get_conn  # noqa: E402

with get_conn() as db:
    leftovers = {t: db.execute(f"SELECT count(*) FROM {t} WHERE client_id = 1").fetchone()[0]
                 for t in ("conversations", "client_identities", "client_facts", "tasks", "client_notes",
                           "chat_sessions", "client_visits", "client_tags", "notifications")}
    fts = db.execute("SELECT count(*) FROM messages WHERE tsv @@ to_tsquery('es_unaccent', 'Mayor')").fetchone()[0]
check("no queda nada del cliente en la base de datos", not any(leftovers.values()), leftovers)
check("ni en el índice de búsqueda", fts == 0, fts)
sys.exit(0 if results["ok"] else 1)
