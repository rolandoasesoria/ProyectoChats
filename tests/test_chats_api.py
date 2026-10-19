"""Sección Chats: lista de clientes con su último mensaje, no leídos, búsqueda, filtro y alcance."""
import sys

from apitest import Session, check, receive, results

from app.db import get_conn

ana = Session("ana")

st, mine = ana.get("/api/chats")
check("Ana ve sus chats", st == 200 and len(mine) >= 2, mine)
check("el más reciente primero", [c["last_at"] for c in mine] == sorted((c["last_at"] for c in mine), reverse=True))
check("con su último mensaje, canales y etiquetas",
      all(c["last_body"] and c["last_channel"] in c["channels"] and isinstance(c["tags"], list) for c in mine), mine)
st, team = ana.get("/api/chats?scope=team")
check("el equipo incluye todos los suyos", {c["id"] for c in mine} <= {c["id"] for c in team})
check("ver los del equipo queda en el registro de accesos",
      ana.get("/api/admin/audit?action=team_chats")[1]["entries"][0]["action"] == "team_chats")

# Llega un mensaje nuevo de Laura (cliente 1) por WhatsApp a Ana
ana.post("/api/clients/1/visit")
receive("whatsapp", "+34600111222", "¿Me confirmas el envío de mañana?", client_name="Laura Gómez", owner=1)
st, mine = ana.get("/api/chats")
laura = mine[0]
check("sube arriba del todo con el mensaje nuevo", laura["id"] == 1 and laura["last_body"] == "¿Me confirmas el envío de mañana?"
      and laura["last_direction"] == "in" and laura["last_channel"] == "whatsapp", laura)
check("y cuenta como no leído", laura["unread"] == 1, laura)
check("filtro «No leídos»", 1 in {c["id"] for c in ana.get("/api/chats?unread=true")[1]})
ana.post("/api/clients/1/visit")
check("al abrirlo deja de estar sin leer", next(c for c in ana.get("/api/chats")[1] if c["id"] == 1)["unread"] == 0)
check("y desaparece de «No leídos»", 1 not in {c["id"] for c in ana.get("/api/chats?unread=true")[1]})
check("buscar por nombre", [c["id"] for c in ana.get("/api/chats?q=laura")[1]] == [1])
check("buscar por teléfono", [c["id"] for c in ana.get("/api/chats?q=600111222")[1]] == [1])
check("alcance no válido = 422", ana.get("/api/chats?scope=todos")[0] == 422)

# «Todo el equipo»: los administradores siempre; los demás, con el permiso que les da un administrador
carlos = Session("carlos")
st, res = carlos.get("/api/chats?scope=team")
check("sin permiso, un usuario no ve los chats del equipo = 403", st == 403 and "permiso" in res["detail"], res)
check("pero sí los suyos", carlos.get("/api/chats")[0] == 200)
check("solo un administrador da el permiso = 403", carlos.patch("/api/admin/users/2", {"can_view_team_chats": True})[0] == 403)
st, user = ana.patch("/api/admin/users/2", {"can_view_team_chats": True})
check("un administrador se lo da", st == 200 and user["can_view_team_chats"] == 1, user)
check("y ya puede verlos", carlos.get("/api/chats?scope=team")[0] == 200)
check("su sesión lo sabe (para mostrarle el selector)", carlos.get("/api/me")[1]["can_view_team_chats"] == 1)
check("el cambio queda en el registro de accesos",
      "can_view_team_chats=True" in ana.get("/api/admin/audit?action=user_update")[1]["entries"][0]["detail"])
ana.patch("/api/admin/users/2", {"can_view_team_chats": False})
check("y se le puede quitar", carlos.get("/api/chats?scope=team")[0] == 403)
st, user = ana.post("/api/admin/users", {"username": "permiso.prueba", "name": "Prueba Permiso", "password": "demo12345",
                                         "can_view_team_chats": True})
check("también se da al crear el usuario", st == 200 and user["can_view_team_chats"] == 1, user)
with get_conn() as conn:
    conn.execute("DELETE FROM users WHERE username = 'permiso.prueba'")
sys.exit(0 if results["ok"] else 1)
