import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from apitest import Session, check, results  # noqa: E402

from app.notes import find_mentions  # noqa: E402

users = [{"id": 1, "name": "Ana Ruiz", "username": "ana"}, {"id": 2, "name": "Carlos Pérez", "username": "carlos"},
         {"id": 3, "name": "Marta López", "username": "marta"}]
check("mención por nombre completo", find_mentions("Ojo @Carlos Pérez, paga tarde", users) == {2})
check("mención por nombre y usuario, sin mayúsculas", find_mentions("@marta y @ANA", users) == {1, 3})
check("no confunde @carlosa con @carlos", find_mentions("@carlosa", users) == set())
check("un email no es una mención", find_mentions("escribe a laura@ana.com", users) == set())

ana, carlos, marta = Session("ana"), Session("carlos"), Session("marta")

st, n = ana.post("/api/clients/1/notes", {"body": "Paga siempre tarde. @Carlos Pérez revisa la factura y @marta la reposición."})
check("crear nota", st == 200 and n["author"] == "Ana Ruiz", n)
st, c = carlos.get("/api/notifications")
check("Carlos recibe el aviso", c["unread"] == 1 and "Ana Ruiz te ha mencionado" in c["items"][0]["text"]
      and c["items"][0]["client_id"] == 1, c)
check("Marta también", marta.get("/api/notifications")[1]["unread"] == 1)
check("Ana no se avisa a sí misma", ana.get("/api/notifications")[1]["unread"] == 0)

st, e = carlos.patch(f"/api/notes/{n['id']}", {"body": "hack"})
check("solo el autor edita = 403", st == 403, e)
st, e = ana.patch(f"/api/notes/{n['id']}", {"body": n["body"] + " @Carlos, gracias"})
check("editar la nota", st == 200 and e["updated_at"], e)
check("editar no repite el aviso a quien ya estaba mencionado", carlos.get("/api/notifications")[1]["unread"] == 1)

st, lst = marta.get("/api/clients/1/notes")
check("todo el equipo ve las notas", len(lst) == 1 and lst[0]["body"].endswith("gracias"), lst)

st, c = carlos.post("/api/notifications/read", {"ids": [c["items"][0]["id"]]})
check("marcar un aviso como leído", c["unread"] == 0 and c["items"][0]["read_at"], c)
check("no puede marcar avisos ajenos", marta.post("/api/notifications/read", {"ids": [c["items"][0]["id"]]})[1]["unread"] == 1)
st, m = marta.post("/api/notifications/read", {})
check("marcar todo como leído", m["unread"] == 0, m)

# Tareas asignadas por otra persona
st, t = ana.post("/api/clients/2/tasks", {"title": "Llamar a Jorge", "assignee_user_id": 3})
check("aviso al asignar tarea a otro", "te ha asignado una tarea de Jorge Martín" in marta.get("/api/notifications")[1]["items"][0]["text"])
st, t2 = marta.post("/api/clients/2/tasks", {"title": "Mi tarea"})
check("sin aviso al crearse una tarea a sí mismo", marta.get("/api/notifications")[1]["unread"] == 1)
ana.patch(f"/api/tasks/{t['id']}", {"assignee_user_id": 2})
check("aviso al reasignar", carlos.get("/api/notifications")[1]["unread"] == 1)
ana.patch(f"/api/tasks/{t['id']}", {"status": "done"})
check("completar no avisa", carlos.get("/api/notifications")[1]["unread"] == 1)

check("carlos no puede borrar la nota de Ana = 403", carlos.delete(f"/api/notes/{n['id']}")[0] == 403)
check("ana (admin y autora) sí", ana.delete(f"/api/notes/{n['id']}")[0] == 200)
check("nota vacía = 422", ana.post("/api/clients/1/notes", {"body": ""})[0] == 422)
check("cliente inexistente = 404", ana.post("/api/clients/999/notes", {"body": "x"})[0] == 404)
sys.exit(0 if results["ok"] else 1)
