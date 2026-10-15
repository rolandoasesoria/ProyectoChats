"""Adjuntar archivos al responder: WhatsApp (se sube a Meta y se envía), Telegram y correo, con servicios simulados; el
archivo queda en la ficha del cliente, junto al mensaje."""
import base64
import sys

from apitest import Session, check, receive, results

from app import attachments, integrations

carlos, marta = Session("carlos"), Session("marta")
CARLOS = {"id": 2, "name": "Carlos Pérez", "role": "user"}
PDF = {"filename": "presupuesto.pdf", "mime": None, "data": b"%PDF-1.4 presupuesto de prueba"}
calls = []


def fake_http(method, url, *, body=None, headers=None, raw=False, timeout=30, form=None):
    calls.append({"method": method, "url": url, "body": body, "form": form})
    if url.endswith("/media"):
        return {"id": "media-77"}
    if "/messages" in url:
        return {"messages": [{"id": "wamid.archivo"}]}
    return {"ok": True, "result": {"message_id": 501}}


integrations.http_request = fake_http
wa = integrations.create("whatsapp", "WhatsApp de Carlos", 2, {"phone_number_id": "777", "access_token": "EAAG", "app_secret": "s"})
tg = integrations.create("telegram", "Bot de Carlos", 2, {"bot_token": "123:ABC"})

# ---------------------------------------------------------------- WhatsApp
conv = receive("whatsapp", "+34633000111", "¿Me mandas el presupuesto?", client_name="Nuria", owner=2)
r = integrations.send_reply(conv["conversation_id"], CARLOS, "Aquí lo tienes", PDF)
upload = next(c for c in calls if c["url"].endswith("/777/media"))
check("WhatsApp: el archivo se sube a Meta con su tipo",
      upload["form"]["file"] == ("presupuesto.pdf", "application/pdf", PDF["data"])
      and upload["form"]["messaging_product"] == "whatsapp", upload["form"])
msg = next(c for c in calls if c["url"].endswith("/777/messages"))["body"]
check("y se envía como documento con su nombre y el texto de pie",
      msg["type"] == "document" and msg["document"] == {"id": "media-77", "caption": "Aquí lo tienes",
                                                        "filename": "presupuesto.pdf"}, msg)
docs = attachments.list_for_client(conv["client_id"])
check("queda en la ficha del cliente, junto al mensaje",
      any(d["filename"] == "presupuesto.pdf" and d["message_id"] == r["message_id"] for d in docs), docs)
calls.clear()
integrations.send_reply(conv["conversation_id"], CARLOS, "", {"filename": "foto.jpg", "mime": "image/jpeg", "data": b"\xff\xd8jpeg"})
msg = next(c for c in calls if c["url"].endswith("/777/messages"))["body"]
check("una foto va como imagen (sin pie si no hay texto)", msg["type"] == "image" and msg["image"] == {"id": "media-77"}, msg)
tl = carlos.get(f"/api/clients/{conv['client_id']}/timeline")[1]
check("sin texto, en el chat se ve el nombre del archivo", tl[-1]["body"] == "📎 foto.jpg", tl[-1])

# ---------------------------------------------------------------- Telegram
calls.clear()
tconv = receive("telegram", "user555", "Hola, ¿me envías la factura?", client_name="Óscar", owner=2)
integrations.send_reply(tconv["conversation_id"], CARLOS, "Te la adjunto", PDF)
check("Telegram: se envía como documento con pie", calls[-1]["url"].endswith("/bot123:ABC/sendDocument")
      and calls[-1]["form"]["chat_id"] == "555" and calls[-1]["form"]["caption"] == "Te la adjunto"
      and calls[-1]["form"]["document"][0] == "presupuesto.pdf", calls[-1])

# ---------------------------------------------------------------- Correo
sent_mail = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        sent_mail.append(message)

    def quit(self):
        pass


integrations.SMTP_SSL_CLASS = integrations.SMTP_CLASS = FakeSMTP
mail = integrations.create("email", "Correo de Carlos", 2, {
    "address": "carlos@miempresa.com", "password": "x", "imap_host": "imap.x", "smtp_host": "smtp.x"})
econv = receive("email", "lucia@cliente.es", "Necesito el contrato", client_name="Lucía", owner=2)
integrations.send_reply(econv["conversation_id"], CARLOS, "Adjunto el contrato.", PDF)
parts = list(sent_mail[-1].iter_attachments())
check("correo: va como adjunto del mensaje", len(parts) == 1 and parts[0].get_filename() == "presupuesto.pdf"
      and parts[0].get_content_type() == "application/pdf" and parts[0].get_content() == PDF["data"], parts)

# ---------------------------------------------------------------- La ruta (servidor real: valida antes de enviar)
cid = conv["conversation_id"]
check("sin texto ni archivo = 400", carlos.post(f"/api/conversations/{cid}/send", {"text": ""})[0] == 400)
check("archivo ilegible = 400", carlos.post(f"/api/conversations/{cid}/send",
                                            {"file": {"filename": "a.pdf", "data": "no es base64!"}})[0] == 400)
big = base64.b64encode(b"x" * (15 * 1024 * 1024 + 1)).decode()
check("más de 15 MB = 400", carlos.post(f"/api/conversations/{cid}/send", {"file": {"filename": "a.bin", "data": big}})[0] == 400)
check("Marta no puede enviar en la conversación de Carlos = 400",
      marta.post(f"/api/conversations/{cid}/send", {"text": "hola"})[0] == 400)
for integration_id in (wa, tg, mail):
    integrations.delete(integration_id)
sys.exit(0 if results["ok"] else 1)
