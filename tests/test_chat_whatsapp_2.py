"""Chat al estilo de WhatsApp, fase 2, con Meta, Telegram y el correo simulados: ubicaciones y tarjetas de contacto
(recibir y enviar), notas de voz (de WebM a Ogg/Opus sin recodificar) y vistas previas de enlaces (sin salir a
internet y sin poder pedir direcciones internas)."""
import base64
import os
import struct
import sys
import urllib.error
import urllib.request

from apitest import Session, check, receive, results

from app import attachments, integrations, link_preview, voice, whatsapp
from app.db import get_conn
from app.errors import InvalidInput

calls, updates, sent_mail = [], [], []
ids = iter(range(1, 1000))


def fake_http(method, url, *, body=None, headers=None, raw=False, timeout=30, form=None):
    calls.append({"url": url, "body": body, "form": form})
    if "getUpdates" in url:
        return {"ok": True, "result": updates}
    if url.endswith("/media"):
        return {"id": "media-9"}
    if url.endswith("/messages"):
        return {"messages": [{"id": f"wamid.F2{next(ids)}"}]}
    return {"ok": True, "result": {"message_id": 700 + next(ids)}}


class FakeSMTP:
    def __init__(self, *args, **kwargs):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        sent_mail.append(message)

    def quit(self):
        pass


integrations.http_request = fake_http
integrations.SMTP_SSL_CLASS = integrations.SMTP_CLASS = FakeSMTP
CARLOS = {"id": 2, "name": "Carlos Pérez", "role": "user"}
carlos = Session("carlos")
wa = integrations.get(integrations.create("whatsapp", "WhatsApp de Carlos", 2,
                                          {"phone_number_id": "888", "access_token": "EAAG", "app_secret": "s"}))
tg = integrations.get(integrations.create("telegram", "Bot de Carlos", 2, {"bot_token": "123:ABC"}))
integrations.create("email", "Correo de Carlos", 2, {"address": "carlos@miempresa.com", "password": "x",
                                                     "imap_host": "imap.x", "smtp_host": "smtp.x"})
PHONE = "34611222444"


def webhook(*messages):
    whatsapp.receive_whatsapp(wa, {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": PHONE, "profile": {"name": "Rosa Gil"}}], "messages": list(messages)}}]}]})


def row(ext):
    with get_conn() as conn:
        found = conn.execute("SELECT id, conversation_id, body, payload FROM messages WHERE external_id = ?", (ext,)).fetchone()
    return dict(found) if found else None


def wa_bodies():
    return [c["body"] for c in calls if c["url"].endswith("/888/messages")]


# ---------------------------------------------------------------- Recibir ubicación, contactos y botones
webhook({"from": PHONE, "id": "wamid.L1", "timestamp": "1790000000", "type": "location",
         "location": {"latitude": 40.4168, "longitude": -3.7038, "name": "Oficina", "address": "Gran Vía 1, Madrid"}},
        {"from": PHONE, "id": "wamid.C1", "timestamp": "1790000010", "type": "contacts",
         "contacts": [{"name": {"formatted_name": "Pedro Gil"}, "phones": [{"phone": "+34 600 111 333", "wa_id": "34600111333"}],
                       "emails": [{"email": "pedro@gil.es"}], "org": {"company": "Gil SL"}}]},
        {"from": PHONE, "id": "wamid.B1", "timestamp": "1790000020", "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": "si", "title": "Sí, confirmo"}}})
loc = row("wa:wamid.L1")
check("ubicación recibida: texto y datos para el mapa",
      loc["body"] == "📍 Ubicación: Oficina · Gran Vía 1, Madrid"
      and loc["payload"] == {"type": "location", "latitude": 40.4168, "longitude": -3.7038, "name": "Oficina",
                             "address": "Gran Vía 1, Madrid"}, loc)
card = row("wa:wamid.C1")
check("tarjeta de contacto recibida: nombre, teléfono, email y empresa",
      card["body"] == "👤 Contacto: Pedro Gil" and card["payload"]["contacts"] == [
          {"name": "Pedro Gil", "phones": ["+34 600 111 333"], "emails": ["pedro@gil.es"], "org": "Gil SL"}], card)
check("la respuesta a un botón llega como su texto", row("wa:wamid.B1")["body"] == "Sí, confirmo")
conv_id = loc["conversation_id"]

# ---------------------------------------------------------------- Enviar ubicación y contacto
calls.clear()
r = integrations.send_location(conv_id, CARLOS, 41.3874, 2.1686, "Asesoría", "Pl. Catalunya 1, Barcelona")
check("enviar ubicación por WhatsApp", wa_bodies()[-1] == {
    "messaging_product": "whatsapp", "to": PHONE, "type": "location",
    "location": {"latitude": 41.3874, "longitude": 2.1686, "name": "Asesoría", "address": "Pl. Catalunya 1, Barcelona"}},
    wa_bodies())
with get_conn() as conn:
    sent = dict(conn.execute("SELECT body, payload, status FROM messages WHERE id = ?", (r["message_id"],)).fetchone())
check("y queda en la conversación con sus datos", sent["body"].startswith("📍 Ubicación: Asesoría")
      and sent["payload"]["latitude"] == 41.3874 and sent["status"] == "sent", sent)
integrations.send_contact(conv_id, CARLOS, "Lucía Martín Ruiz", "+34 600 222 444", "lucia@asesoria.es")
check("enviar tarjeta de contacto por WhatsApp", wa_bodies()[-1]["contacts"] == [{
    "name": {"formatted_name": "Lucía Martín Ruiz", "first_name": "Lucía", "last_name": "Martín Ruiz"},
    "phones": [{"phone": "+34 600 222 444", "type": "CELL"}], "emails": [{"email": "lucia@asesoria.es", "type": "WORK"}]}],
    wa_bodies()[-1])
try:
    integrations.send_contact(conv_id, CARLOS, "Sin teléfono", "12")
    check("un contacto necesita nombre y teléfono", False)
except InvalidInput:
    check("un contacto necesita nombre y teléfono", True)

updates[:] = [{"update_id": 1, "message": {"message_id": 5, "date": 1790001000, "chat": {"id": 555, "type": "private"},
                                           "from": {"first_name": "Pablo"},
                                           "venue": {"location": {"latitude": 39.47, "longitude": -0.37},
                                                     "title": "Mercado", "address": "Valencia"}}},
              {"update_id": 2, "message": {"message_id": 6, "date": 1790001010, "chat": {"id": 555, "type": "private"},
                                           "from": {"first_name": "Pablo"},
                                           "contact": {"phone_number": "+34611000999", "first_name": "Eva", "last_name": "Sanz"}}}]
integrations.sync_telegram(tg)
check("Telegram: lugar y contacto recibidos",
      row("tg:555:5")["payload"]["name"] == "Mercado" and row("tg:555:6")["body"] == "👤 Contacto: Eva Sanz")
tg_conv = row("tg:555:5")["conversation_id"]
calls.clear()
integrations.send_location(tg_conv, CARLOS, 40.0, -3.0, "Oficina", "Calle Mayor 2")
integrations.send_location(tg_conv, CARLOS, 40.0, -3.0)
integrations.send_contact(tg_conv, CARLOS, "Lucía Martín", "+34600222444")
tg_calls = [(c["url"].rsplit("/", 1)[1], c["body"]) for c in calls]
check("Telegram: lugar (con nombre y dirección), ubicación y contacto",
      [m for m, _ in tg_calls] == ["sendVenue", "sendLocation", "sendContact"]
      and tg_calls[2][1] == {"chat_id": 555, "phone_number": "+34600222444", "first_name": "Lucía", "last_name": "Martín"},
      tg_calls)
econv = receive("email", "rosa@cliente.es", "¿Dónde estáis?", client_name="Rosa Gil", owner=2)
integrations.send_location(econv["conversation_id"], CARLOS, 40.4168, -3.7038, "Oficina")
check("correo: la ubicación va como texto con el enlace al mapa",
      "https://www.google.com/maps/search/?api=1&query=40.4168,-3.7038" in sent_mail[-1].get_content(), sent_mail[-1].get_content())

# ---------------------------------------------------------------- Notas de voz: de WebM a Ogg/Opus


def ebml(el_id, body, unknown=False):
    size = b"\x01\xff\xff\xff\xff\xff\xff\xff" if unknown else (0x10000000 | len(body)).to_bytes(4, "big")
    return el_id.to_bytes((el_id.bit_length() + 7) // 8, "big") + size + body


head = struct.pack("<8sBBHIhB", b"OpusHead", 1, 1, 312, 48000, 0, 0)
packets = [bytes([0xF8]) + os.urandom(n) for n in (60, 300, 80)] * 40  # tramas de 20 ms (960 muestras), una de 300 bytes
track = ebml(0xAE, ebml(0xD7, b"\x01") + ebml(0x86, b"A_OPUS") + ebml(0x63A2, head))
blocks = b"".join(ebml(0xA3, b"\x81" + struct.pack(">h", i * 20) + b"\x80" + p) for i, p in enumerate(packets))
webm = ebml(0x1A45DFA3, ebml(0x4282, b"webm")) + ebml(
    0x18538067, ebml(0x1549A966, b"") + ebml(0x1654AE6B, track) + ebml(0x1F43B675, ebml(0xE7, b"\x00") + blocks, unknown=True),
    unknown=True)


def ogg_pages(data):
    pages, pos = [], 0
    while pos < len(data):
        nseg = data[pos + 26]
        lacing = data[pos + 27:pos + 27 + nseg]
        page = data[pos:pos + 27 + nseg + sum(lacing)]
        crc = struct.unpack("<I", page[22:26])[0]
        pages.append({"magic": page[:4], "type": page[5], "granule": struct.unpack("<q", page[6:14])[0],
                      "seq": struct.unpack("<I", page[18:22])[0], "lacing": lacing, "body": page[27 + nseg:],
                      "crc_ok": voice._ogg_crc(page[:22] + b"\0\0\0\0" + page[26:]) == crc})
        pos += len(page)
    return pages


def ogg_packets(pages):
    out, current = [], b""
    for p in pages:
        offset = 0
        for value in p["lacing"]:
            current += p["body"][offset:offset + value]
            offset += value
            if value < 255:
                out.append(current)
                current = b""
    return out


check("CRC de Ogg (valor de comprobación conocido)", voice._ogg_crc(b"123456789") == 0x89A1897F)
ogg = voice.webm_to_ogg(webm)
pages = ogg_pages(ogg)
check("Ogg: cabecera Opus (inicio de flujo), etiquetas y fin de flujo en la última página",
      pages[0]["type"] == 2 and pages[0]["body"] == head and pages[1]["body"].startswith(b"OpusTags")
      and pages[-1]["type"] == 4 and all(p["magic"] == b"OggS" for p in pages))
check("Ogg: todas las páginas con su CRC y en orden", all(p["crc_ok"] for p in pages)
      and [p["seq"] for p in pages] == list(range(len(pages))))
check("Ogg: los mismos paquetes Opus, sin recodificar (también uno de más de 255 bytes)", ogg_packets(pages[2:]) == packets)
check("Ogg: la posición final cuenta todas las muestras", pages[-1]["granule"] == len(packets) * 960, pages[-1]["granule"])
check("Firefox (Ogg) y Safari (MP4) se envían tal cual",
      voice.for_sending(ogg, "audio/ogg;codecs=opus") == (ogg, "audio/ogg")
      and voice.for_sending(b"....ftypM4A", "audio/mp4") == (b"....ftypM4A", "audio/mp4"))
try:
    voice.for_sending(b"RIFF....WAVE", "audio/wav")
    check("otros formatos no se aceptan", False)
except InvalidInput:
    check("otros formatos no se aceptan", True)

calls.clear()
r = integrations.send_voice(conv_id, CARLOS, webm, "audio/webm;codecs=opus", 72)
upload = next(c for c in calls if c["url"].endswith("/888/media"))
check("nota de voz por WhatsApp: se sube como Ogg/Opus y se envía como audio",
      upload["form"]["type"] == "audio/ogg" and upload["form"]["file"][2][:4] == b"OggS"
      and wa_bodies()[-1]["type"] == "audio" and "caption" not in wa_bodies()[-1]["audio"], wa_bodies()[-1])
with get_conn() as conn:
    note = dict(conn.execute("SELECT body, payload FROM messages WHERE id = ?", (r["message_id"],)).fetchone())
files = attachments.by_message([r["message_id"]])[r["message_id"]]
check("queda en la conversación (1:12) con su audio en la ficha",
      note["body"] == "🎤 Nota de voz (1:12)" and note["payload"] == {"type": "voice", "seconds": 72}
      and files[0]["mime"] == "audio/ogg", (note, files))
calls.clear()
integrations.send_voice(tg_conv, CARLOS, webm, "audio/webm", 5)
check("Telegram: como nota de voz (sendVoice)", calls[-1]["url"].endswith("/sendVoice")
      and calls[-1]["form"]["voice"][1] == "audio/ogg" and calls[-1]["form"]["duration"] == "5", calls[-1]["url"])

# ---------------------------------------------------------------- Vistas previas de enlaces
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PAGE = ('<html><head><meta charset="utf-8"><title>Otro título</title>'
        '<meta property="og:title" content="Nueva ley de autónomos">'
        '<meta property="og:description" content="Lo que cambia en 2027 &amp; cómo afecta">'
        '<meta property="og:site_name" content="Diario Asesor"><meta property="og:image" content="/foto.png">'
        '</head><body>…</body></html>').encode()
web = {"https://ejemplo.es/articulo": (PAGE, "text/html", "https://ejemplo.es/articulo", "utf-8"),
       "https://ejemplo.es/foto.png": (PNG, "image/png", "https://ejemplo.es/foto.png", "")}
fetched = []


def fake_get(url, accept, limit):
    fetched.append(url)
    if url not in web:
        raise urllib.error.URLError("no existe")
    return web[url]


link_preview._get = fake_get
link_preview.ENABLED = True
p = link_preview.preview("https://ejemplo.es/articulo")
check("vista previa: título, descripción, sitio y miniatura",
      p["title"] == "Nueva ley de autónomos" and p["description"] == "Lo que cambia en 2027 & cómo afecta"
      and p["site"] == "Diario Asesor" and p["image"].startswith("data:image/png;base64,"), p)
fetched.clear()
check("la segunda vez sale de lo guardado (no se vuelve a pedir)",
      link_preview.preview("https://ejemplo.es/articulo") == p and fetched == [])
check("una página que no existe no tiene vista previa", link_preview.preview("https://ejemplo.es/no-existe") is None)
fetched.clear()
check("y tampoco se vuelve a pedir enseguida", link_preview.preview("https://ejemplo.es/no-existe") is None and fetched == [])
blocked = []
for url in ("http://127.0.0.1/admin", "http://localhost/", "http://10.0.0.5/", "http://192.168.1.10/",
            "http://169.254.169.254/latest/meta-data", "http://[::1]/", "ftp://ejemplo.es/", "file:///etc/passwd",
            "http://ejemplo.es:8080/", "http://usuario:clave@ejemplo.es/"):
    try:
        link_preview.check_url(url)
    except link_preview.Blocked:
        blocked.append(url)
check("nunca se piden direcciones internas, otros protocolos o puertos, ni con usuario y contraseña", len(blocked) == 10, blocked)
try:
    link_preview._SafeRedirect().redirect_request(urllib.request.Request("https://ejemplo.es/"), None, 302, "Found", {},
                                                   "http://127.0.0.1/admin")
    check("una redirección a una dirección interna se corta", False)
except link_preview.Blocked:
    check("una redirección a una dirección interna se corta", True)
calls.clear()
integrations.send_reply(conv_id, CARLOS, "Mira esto: https://ejemplo.es/articulo")
check("lo que envías por WhatsApp con un enlace lleva su vista previa", wa_bodies()[-1]["text"]["preview_url"] is True)

# ---------------------------------------------------------------- API
st, body = carlos.get("/api/link-preview?url=https%3A%2F%2Fejemplo.es%2Farticulo")
check("API: la vista previa guardada", st == 200 and body["preview"]["title"] == "Nueva ley de autónomos", body)
check("API: sin vista previa (en las pruebas no se sale a internet)",
      carlos.get("/api/link-preview?url=https%3A%2F%2Fotra.es%2F")[1] == {"preview": None})
check("API: sin sesión = 401", Session().get("/api/link-preview?url=https%3A%2F%2Fotra.es%2F")[0] == 401)
check("API: latitud imposible = 422", carlos.post(f"/api/conversations/{conv_id}/send-location",
                                                  {"latitude": 100, "longitude": 0})[0] == 422)
check("API: contacto sin teléfono = 422", carlos.post(f"/api/conversations/{conv_id}/send-contact",
                                                      {"name": "Eva", "phone": ""})[0] == 422)
check("API: grabación ilegible = 400", carlos.post(f"/api/conversations/{conv_id}/send-voice",
                                                   {"data": "###", "mime": "audio/webm", "seconds": 3})[0] == 400)
st, tl = carlos.get(f"/api/clients/{econv['client_id']}/timeline?scope=team")
check("API: la conversación trae los datos de cada mensaje", st == 200 and any(m.get("payload") for m in tl), tl[-1:])

sys.exit(0 if results["ok"] else 1)
