"""IA que responde por WhatsApp: configuración, modo supervisado y automático, pasar a una persona, pausar un chat,
inactividad del equipo, ventana de 24 h y horario (Claude y Meta simulados)."""
import json
import sys
from datetime import datetime, timedelta

from apitest import Session, check, claude_reply, receive, results

from app import agent, ai_reply, integrations
from app.db import get_conn

ana, carlos, marta = Session("ana"), Session("carlos"), Session("marta")
CARLOS = {"id": 2, "name": "Carlos Pérez", "role": "user"}

# ---------------------------------------------------------------- Configuración (solo administradores)
check("por defecto, desactivada y supervisada",
      {k: carlos.get("/api/ai-reply/settings")[1][k] for k in ("enabled", "mode")} == {"enabled": False, "mode": "supervised"})
check("Carlos no puede cambiarla = 403", carlos.call("PUT", "/api/admin/ai-reply/settings", {"enabled": True})[0] == 403)
check("no se activa sin instrucciones = 400", ana.call("PUT", "/api/admin/ai-reply/settings", {"enabled": True})[0] == 400)
check("horario mal escrito = 400", ana.call("PUT", "/api/admin/ai-reply/settings", {"hours": "18:00-09:00"})[0] == 400)
check("horas de inactividad no válidas = 422", ana.call("PUT", "/api/admin/ai-reply/settings", {"inactivity_hours": 5})[0] == 422)
st, cfg = ana.call("PUT", "/api/admin/ai-reply/settings", {
    "enabled": True, "instructions": "Somos una floristería. Abrimos de 9 a 18 h. Envíos en Madrid en 24 h."})
check("activar con instrucciones (modo supervisado)", st == 200 and cfg["enabled"] and cfg["mode"] == "supervised", cfg)
check("probar la IA sin clave de Claude = 503", ana.post("/api/admin/ai-reply/test", {"message": "Hola"})[0] == 503)
check("probar la IA es de administradores = 403", carlos.post("/api/admin/ai-reply/test", {"message": "Hola"})[0] == 403)

# ---------------------------------------------------------------- Con Claude y Meta simulados (en este proceso)
decision = {"action": "reply", "message": "¡Hola! Sí, enviamos en 24 h.", "reason": ""}
prompts, sent = [], []
agent.credentials_configured = lambda: True
agent._create = lambda **p: prompts.append(p) or claude_reply(json.dumps(decision))


def meta(method, url, *, body=None, headers=None, raw=False, timeout=30):
    sent.append(body)
    return {"messages": [{"id": f"wamid.ia{len(sent)}"}]}


integrations.http_request = meta
wa = integrations.create("whatsapp", "WhatsApp de Carlos", 2,
                         {"phone_number_id": "777", "access_token": "EAAG", "app_secret": "s", "waba_id": "w"})
conv = receive("whatsapp", "+34611000111", "¿Hacéis envíos a Madrid?", client_name="Inés", owner=2)["conversation_id"]

check("supervisado: deja una propuesta", ai_reply.run_once() == {"pending": 1})
check("con las instrucciones del negocio en el prompt", "floristería" in prompts[-1]["system"]
      and "¿Hacéis envíos a Madrid?" in prompts[-1]["messages"][0]["content"])
check("y no se trata dos veces el mismo mensaje", ai_reply.run_once() == {})
st, state = carlos.get(f"/api/conversations/{conv}/ai")
check("Carlos ve la propuesta en el chat", st == 200 and state["pending"]["text"] == decision["message"], state)
check("Marta no decide en la conversación de Carlos = 403", marta.get(f"/api/conversations/{conv}/ai")[0] == 403)
counts = carlos.get("/api/me/counts")[1]
check("la barra lateral cuenta la propuesta pendiente de Carlos (y no la de Marta)",
      counts["ai_pending"] == 1 and counts["ai_enabled"] is True and isinstance(counts["unread_chats"], int)
      and marta.get("/api/me/counts")[1]["ai_pending"] == 0, counts)
with get_conn() as conn:
    avisos = conn.execute("SELECT count(*) FROM notifications WHERE user_id = 2 AND kind = 'ai_suggestion'").fetchone()[0]
check("y le llega un aviso", avisos == 1)
ai_reply.send_suggestion(state["pending"]["id"], CARLOS, "¡Hola Inés! Sí, enviamos en 24 h.")
check("al aprobarla (editada) se envía por WhatsApp", sent[-1]["text"]["body"] == "¡Hola Inés! Sí, enviamos en 24 h.")
tl = carlos.get(f"/api/clients/{receive('whatsapp', '+34611000111', 'Genial, gracias', owner=2)['client_id']}/timeline")[1]
check("y queda en el chat marcada como de la IA", any(m["by_ai"] and m["body"].startswith("¡Hola Inés") for m in tl), tl[-3:])
check("una propuesta ya enviada no se envía otra vez",
      carlos.post(f"/api/ai-replies/{state['pending']['id']}/send", {})[0] == 400)

# Modo automático: responde sola, por la cuenta de quien lleva la conversación
ana.call("PUT", "/api/admin/ai-reply/settings", {"mode": "auto"})
check("automático: responde sola", ai_reply.run_once() == {"sent": 1})
check("enviada al cliente", sent[-1]["to"] == "34611000111" and sent[-1]["text"]["body"] == decision["message"])

# Pasar a una persona
decision = {"action": "handoff", "message": "", "reason": "Pide hablar con una persona"}
receive("whatsapp", "+34611000111", "Quiero hablar con alguien, por favor", owner=2)
check("si pide una persona, no responde", ai_reply.run_once() == {"handoff": 1})
with get_conn() as conn:
    texto = conn.execute("SELECT text FROM notifications WHERE user_id = 2 AND kind = 'ai_handoff' ORDER BY id DESC").fetchone()[0]
check("y avisa con el motivo", "Pide hablar con una persona" in texto, texto)

# Pausar la IA en un chat
decision = {"action": "reply", "message": "Te contesto enseguida.", "reason": ""}
check("pausar la IA en este chat", carlos.call("PUT", f"/api/conversations/{conv}/ai", {"paused": True})[1]["paused"])
receive("whatsapp", "+34611000111", "¿Sigues ahí?", owner=2)
check("con la IA pausada no responde", ai_reply.run_once() == {})
carlos.call("PUT", f"/api/conversations/{conv}/ai", {"paused": False})

# Si una persona del equipo ha escrito hace poco, la IA no se mete
ana.call("PUT", "/api/admin/ai-reply/settings", {"inactivity_hours": 24})
receive("whatsapp", "+34611000111", "Te escribo yo, Inés", owner=2, direction="out", sender="Carlos Pérez")
receive("whatsapp", "+34611000111", "Vale, gracias", owner=2)
check("con un compañero activo en el chat, no entra", ai_reply.run_once() == {})
ana.call("PUT", "/api/admin/ai-reply/settings", {"inactivity_hours": 0})
check("con 0 horas de inactividad, entra siempre", ai_reply.run_once() == {"sent": 1})

# Fuera de la ventana de 24 h de WhatsApp no responde
old = (datetime.now() - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%S")
receive("whatsapp", "+34622000222", "Mensaje de ayer", client_name="Rosa", owner=2, sent_at=old)
check("pasadas 24 h del último mensaje del cliente no responde", ai_reply.run_once() == {})

# Horario: solo fuera del horario de oficina
cfg = {**ai_reply.get_settings(), "schedule": "out_of_hours", "hours": "09:00-18:00", "days": [1, 2, 3, 4, 5]}
check("en horario de oficina (lunes 10:00) no responde", not ai_reply.in_schedule(cfg, datetime(2026, 10, 19, 10, 0)))
check("fuera de horario (lunes 20:00) sí", ai_reply.in_schedule(cfg, datetime(2026, 10, 19, 20, 0)))
check("en fin de semana (sábado 10:00) sí", ai_reply.in_schedule(cfg, datetime(2026, 10, 24, 10, 0)))

# Desactivada no hace nada
ana.call("PUT", "/api/admin/ai-reply/settings", {"enabled": False})
receive("whatsapp", "+34611000111", "¿Hola?", owner=2)
check("desactivada no responde", ai_reply.run_once() == {})
integrations.delete(wa)
sys.exit(0 if results["ok"] else 1)
