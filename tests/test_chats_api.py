"""Sección Chats: lista de clientes con su último mensaje, no leídos, búsqueda, filtro y alcance."""
import sys

from apitest import Session, check, receive, results

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
sys.exit(0 if results["ok"] else 1)
