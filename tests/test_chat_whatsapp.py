"""Chat al estilo de WhatsApp, con Meta y Telegram simulados: estado de entrega (los checks), responder citando un
mensaje, reacciones con emoji y avisar de que está leído."""
import sys

from apitest import Session, check, receive, results

from app import integrations, message_actions, search, whatsapp
from app.db import get_conn
from app.errors import Forbidden, InvalidInput

calls = []
updates = []  # lo que devuelve getUpdates de Telegram
sent_ids = iter(range(1, 1000))  # cada envío a WhatsApp, su identificador


def fake_http(method, url, *, body=None, headers=None, raw=False, timeout=30, form=None):
    calls.append({"method": method, "url": url, "body": body, "form": form})
    if "getUpdates" in url:
        return {"ok": True, "result": updates}
    if "api.telegram" in url or "/bot" in url:
        return {"ok": True, "result": {"message_id": 900}}
    if url.endswith("/messages") and body and body.get("type") in ("text", "document", "image"):
        return {"messages": [{"id": f"wamid.ENV{next(sent_ids)}"}]}
    return {"success": True}


integrations.http_request = fake_http
CARLOS = {"id": 2, "name": "Carlos Pérez", "role": "user"}
MARTA = {"id": 3, "name": "Marta López", "role": "user"}
carlos, marta = Session("carlos"), Session("marta")
integ = integrations.get(integrations.create("whatsapp", "WhatsApp de Carlos", 2,
                                             {"phone_number_id": "888", "access_token": "EAAG", "app_secret": "s"}))
PHONE = "34611222333"


def webhook(field="messages", **value):
    whatsapp.receive_whatsapp(integ, {"entry": [{"changes": [{"field": field, "value": value}]}]})


def incoming(wamid, text, ts, **extra):
    webhook(contacts=[{"wa_id": PHONE, "profile": {"name": "Inés Prado"}}],
            messages=[{"from": PHONE, "id": wamid, "timestamp": ts, "type": "text", "text": {"body": text}, **extra}])


def row(where, arg):
    with get_conn() as conn:
        found = conn.execute(f"""SELECT id, conversation_id, external_id, reply_to_id, status, status_error, delivered_at,
                                        read_at FROM messages WHERE {where} = ?""", (arg,)).fetchone()
    return dict(found) if found else None


def reactions(message_id):
    return message_actions.reactions_by_message([message_id]).get(message_id, [])


def graph_calls():
    return [c["body"] for c in calls if c["url"].endswith("/888/messages")]


# ---------------------------------------------------------------- Responder citando
incoming("wamid.IN1", "Hola, ¿tenéis cita el lunes?", "1790000000")
first = row("external_id", "wa:wamid.IN1")
conv_id = first["conversation_id"]
with get_conn() as conn:
    client_id = conn.execute("SELECT client_id FROM conversations WHERE id = ?", (conv_id,)).fetchone()["client_id"]

calls.clear()
reply = integrations.send_reply(conv_id, CARLOS, "Sí, a las 10", reply_to_message_id=first["id"])
sent = graph_calls()[0]
check("responder citando: WhatsApp recibe la cita del mensaje",
      sent["context"] == {"message_id": "wamid.IN1"} and sent["text"] == {"body": "Sí, a las 10"}, sent)
ours = row("id", reply["message_id"])
check("y se guarda citándolo, como «enviado» (un check)", ours["reply_to_id"] == first["id"] and ours["status"] == "sent", ours)
calls.clear()
integrations.send_reply(conv_id, CARLOS, "Sin cita")
check("sin cita, no se envía contexto", "context" not in graph_calls()[0])
email_msg = receive("email", "ines@ejemplo.com", "Te escribo también por correo", client_id=client_id, owner=2)
email_id = row("conversation_id", email_msg["conversation_id"])["id"]
try:
    integrations.send_reply(conv_id, CARLOS, "x", reply_to_message_id=email_id)
    check("no se puede citar un mensaje de otra conversación", False)
except InvalidInput:
    check("no se puede citar un mensaje de otra conversación", True)

# ---------------------------------------------------------------- Estado de entrega
wamid = ours["external_id"][3:]
webhook(statuses=[{"id": wamid, "status": "delivered", "timestamp": "1790000100", "recipient_id": PHONE}])
check("Meta avisa de la entrega: dos checks", row("id", ours["id"])["status"] == "delivered")
webhook(statuses=[{"id": wamid, "status": "read", "timestamp": "1790000200", "recipient_id": PHONE}])
webhook(statuses=[{"id": wamid, "status": "delivered", "timestamp": "1790000300", "recipient_id": PHONE}])
webhook(statuses=[{"id": wamid, "status": "failed", "timestamp": "1790000400", "errors": [{"code": 131047}]}])
done = row("id", ours["id"])
check("leído (checks azules); un aviso tardío no hace retroceder", done["status"] == "read" and done["status_error"] is None, done)
check("con la hora de entrega y la de lectura", done["delivered_at"] and done["read_at"] and done["read_at"] > done["delivered_at"], done)
other = row("id", integrations.send_reply(conv_id, CARLOS, "¿Te va bien?")["message_id"])
webhook(statuses=[{"id": other["external_id"][3:], "status": "failed", "timestamp": "1790000500",
                   "errors": [{"code": 131047, "title": "Re-engagement message"}]}])
failed = row("id", other["id"])
check("no entregado: se marca y se explica por qué", failed["status"] == "failed" and "24 h" in failed["status_error"], failed)
webhook(statuses=[{"id": "wamid.desconocido", "status": "read", "timestamp": "1790000600"}])
check("un aviso de un mensaje que no está en la app se ignora", True)

# ---------------------------------------------------------------- El cliente cita y reacciona
incoming("wamid.IN2", "Perfecto, allí estaré", "1790000700", context={"from": "34600000000", "id": wamid})
second = row("external_id", "wa:wamid.IN2")
check("el cliente responde citando tu mensaje: se ve la cita", second["reply_to_id"] == ours["id"], second)
webhook(contacts=[], messages=[{"from": PHONE, "id": "wamid.R1", "timestamp": "1790000800", "type": "reaction",
                                "reaction": {"message_id": wamid, "emoji": "👍"}}])
check("el cliente reacciona: se guarda en el mensaje (no es un mensaje nuevo)",
      reactions(ours["id"]) == [{"side": "client", "emoji": "👍", "user": None}] and row("external_id", "wa:wamid.R1") is None,
      reactions(ours["id"]))
webhook(contacts=[], messages=[{"from": PHONE, "id": "wamid.R2", "timestamp": "1790000900", "type": "reaction",
                                "reaction": {"message_id": wamid, "emoji": ""}}])
check("y si la quita, desaparece", reactions(ours["id"]) == [])
webhook("smb_message_echoes", message_echoes=[{"from": "34600000000", "to": PHONE, "id": "wamid.E1", "timestamp": "1790001000",
                                               "type": "reaction", "reaction": {"message_id": "wamid.IN2", "emoji": "❤️"}}])
check("una reacción desde el móvil (coexistencia) es del equipo", reactions(second["id"]) == [{"side": "team", "emoji": "❤️", "user": None}])

# ---------------------------------------------------------------- Reaccionar desde la app
calls.clear()
now = message_actions.react(second["id"], CARLOS, "🙏")
sent = graph_calls()[0]
check("reaccionar: sale por WhatsApp al mensaje del cliente",
      sent["type"] == "reaction" and sent["reaction"] == {"message_id": "wamid.IN2", "emoji": "🙏"} and sent["to"] == PHONE, sent)
check("y sustituye a la anterior del equipo, con quién la puso", now == [{"side": "team", "emoji": "🙏", "user": "Carlos Pérez"}], now)
calls.clear()
check("quitarla", message_actions.react(second["id"], CARLOS, "") == [] and graph_calls()[0]["reaction"]["emoji"] == "")
for label, args, error in [("solo quien lleva la conversación puede reaccionar", (second["id"], MARTA, "👍"), Forbidden),
                           ("una reacción tiene que ser un emoji", (second["id"], CARLOS, "hola"), InvalidInput),
                           ("en el correo no hay reacciones", (email_id, CARLOS, "👍"), InvalidInput)]:
    try:
        message_actions.react(*args)
        check(label, False)
    except error:
        check(label, True)

# ---------------------------------------------------------------- Avisar de que está leído
calls.clear()
check("al abrir el chat, WhatsApp sabe que lo has leído", message_actions.mark_read(client_id, CARLOS) == 1
      and graph_calls() == [{"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.IN2"}], graph_calls())
calls.clear()
check("una sola vez por mensaje", message_actions.mark_read(client_id, CARLOS) == 0 and graph_calls() == [])
incoming("wamid.IN3", "¿Llevo algún documento?", "1790001100")
check("y otra vez cuando escribe de nuevo", message_actions.mark_read(client_id, CARLOS) == 1
      and graph_calls()[-1]["message_id"] == "wamid.IN3")
check("quien no lleva la conversación no marca nada", message_actions.mark_read(client_id, MARTA) == 0)

# ---------------------------------------------------------------- Lo que recibe la conversación
items = {m["id"]: m for m in search.timeline(client_id, 2)}
mine = items[ours["id"]]
check("la conversación trae la cita, el estado y las reacciones",
      mine["reply_sender"] == "Inés Prado" and mine["reply_body"].startswith("Hola, ¿tenéis cita")
      and mine["status"] == "read" and items[second["id"]]["reply_to_id"] == ours["id"]
      and items[second["id"]]["reactions"] == [] and items[failed["id"]]["status_error"], mine)

# ---------------------------------------------------------------- Telegram: también se cita
tg = integrations.get(integrations.create("telegram", "Bot de Carlos", 2, {"bot_token": "123:ABC"}))
updates[:] = [
    {"update_id": 1, "message": {"message_id": 10, "date": 1790002000, "chat": {"id": 555, "type": "private"},
                                 "from": {"first_name": "Pablo"}, "text": "Hola"}},
    {"update_id": 2, "message": {"message_id": 11, "date": 1790002100, "chat": {"id": 555, "type": "private"},
                                 "from": {"first_name": "Pablo"}, "text": "Esto que te dije", "reply_to_message": {"message_id": 10}}},
]
integrations.sync_telegram(tg)
tg_first, tg_second = row("external_id", "tg:555:10"), row("external_id", "tg:555:11")
check("Telegram: lo que cita el cliente se ve", tg_second["reply_to_id"] == tg_first["id"], tg_second)
calls.clear()
integrations.send_reply(tg_first["conversation_id"], CARLOS, "Recibido", reply_to_message_id=tg_first["id"])
tg_sent = next(c["body"] for c in calls if c["url"].endswith("/sendMessage"))
check("y al responder citando, Telegram recibe la cita", tg_sent["reply_parameters"]["message_id"] == 10, tg_sent)

# ---------------------------------------------------------------- API
check("reaccionar a un mensaje que no existe = 404", carlos.post("/api/messages/999999/reaction", {"emoji": "👍"})[0] == 404)
check("reaccionar en el correo = 400", carlos.post(f"/api/messages/{email_id}/reaction", {"emoji": "👍"})[0] == 400)
check("reaccionar en la conversación de otro = 403", marta.post(f"/api/messages/{second['id']}/reaction", {"emoji": "👍"})[0] == 403)
st, body = carlos.post(f"/api/conversations/{conv_id}/send", {"text": "x", "reply_to_message_id": email_id})
check("enviar citando un mensaje de otra conversación = 400", st == 400 and "citar" in body["detail"], body)
st, tl = carlos.get(f"/api/clients/{client_id}/timeline")
check("la API de la conversación trae estado, cita y reacciones",
      st == 200 and all(k in tl[0] for k in ("status", "reply_to_id", "reply_body", "reactions")), tl[:1])

sys.exit(0 if results["ok"] else 1)
