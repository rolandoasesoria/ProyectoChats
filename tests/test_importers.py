import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import importers  # noqa: E402

ok = True


def check(label, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label + (f"  -> {extra}" if extra and not cond else ""))


android = """03/10/26, 9:15 - Los mensajes y las llamadas están cifrados de extremo a extremo.
03/10/26, 9:15 - Pedro Sanz: Hola, ¿tenéis cajas de 40x30?
03/10/26, 9:20 - Ana Ruiz: Sí, desde 100 unidades
03/10/26, 9:21 - Pedro Sanz: Perfecto, mi dirección es:
Av. Libertad 12
46002 Valencia
04/10/26, 18:05 - Pedro Sanz: <Multimedia omitido>
"""
p = importers.parse("Chat de WhatsApp con Pedro Sanz.txt", android.encode())
check("WhatsApp Android: 4 mensajes (sin avisos del sistema)", len(p["messages"]) == 4, p["messages"])
check("WhatsApp: título del archivo", p["title"] == "Pedro Sanz", p["title"])
check("WhatsApp: mensaje de varias líneas", "46002 Valencia" in p["messages"][2]["body"])
check("WhatsApp: fecha día/mes", p["messages"][0]["sent_at"] == "2026-10-03T09:15:00", p["messages"][0]["sent_at"])
convs = importers.build_conversations(p, "Pedro Sanz")
check("WhatsApp: direcciones in/out", [m["direction"] for m in convs[0]["messages"]] == ["in", "out", "in", "in"])

ios = "\u200e[3/10/26, 9:15:02 p. m.] Pedro Sanz: Hola\n[3/10/26, 9:16:40\u202fp. m.] Ana Ruiz: Buenas\n"
p = importers.parse("_chat.txt", ios.encode())
check("WhatsApp iPhone con p. m.", [m["sent_at"] for m in p["messages"]] == ["2026-10-03T21:15:02", "2026-10-03T21:16:40"],
      p["messages"])

tg = {"name": "Sofía Navarro", "type": "personal_chat", "messages": [
    {"id": 1, "type": "service", "date": "2026-09-15T12:00:00", "action": "phone_call"},
    {"id": 2, "type": "message", "date": "2026-09-15T13:00:00", "from": "Sofía", "from_id": "user555",
     "text": ["Mira ", {"type": "bold", "text": "esto"}]},
    {"id": 3, "type": "message", "date": "2026-09-15T13:05:00", "from": "Marta", "from_id": "user1", "text": "Vale"},
    {"id": 4, "type": "message", "date": "2026-09-15T13:06:00", "from": "Sofía", "from_id": "user555",
     "text": "", "media_type": "voice_message"},
]}
p = importers.parse("result.json", json.dumps(tg).encode())
check("Telegram: 3 mensajes, texto con formato unido", [m["body"] for m in p["messages"]] == ["Mira esto", "Vale", "[voice_message]"],
      p["messages"])
check("Telegram: participante por id", p["participants"][0]["key"] == "user555")

eml1 = b"""From: Jorge Martin <jorge@talleresmartin.com>
To: ana@miempresa.com
Subject: Re: Pedido etiquetas
Date: Tue, 22 Sep 2026 09:05:00 +0200
Content-Type: text/plain; charset=utf-8

Confirmo el pedido de 5.000 etiquetas.

El lun, 21 sept 2026 a las 11:00, Ana <ana@miempresa.com> escribi\xc3\xb3:
> Te paso el precio
"""
p = importers.parse("pedido.eml", eml1)
check("EML: cuerpo sin la cita anterior", p["messages"][0]["body"] == "Confirmo el pedido de 5.000 etiquetas.",
      p["messages"][0]["body"])
check("EML: asunto sin 'Re:'", p["messages"][0]["subject"] == "Pedido etiquetas")

mbox = (b"From jorge@talleresmartin.com Tue Sep 22 09:05:00 2026\n" + eml1 + b"\n"
        b"From otro@x.com Tue Sep 22 10:00:00 2026\nFrom: Otro <otro@x.com>\nTo: ana@miempresa.com\n"
        b"Subject: Oferta\nDate: Tue, 22 Sep 2026 10:00:00 +0200\n"
        b"Content-Type: text/html; charset=utf-8\n\n<p>Hola <b>Ana</b></p><p>Adios</p>\n\n"
        b"From ana@miempresa.com Tue Sep 22 11:00:00 2026\nFrom: Ana <ana@miempresa.com>\nTo: jorge@talleresmartin.com\n"
        b"Subject: RE: Pedido etiquetas\nDate: Tue, 22 Sep 2026 11:00:00 +0200\n\nPerfecto, gracias Jorge\n")
p = importers.parse("buzon.mbox", mbox)
check("MBOX: 3 correos", len(p["messages"]) == 3, len(p["messages"]))
check("MBOX: HTML convertido a texto", "Hola Ana" in p["messages"][1]["body"] and "<" not in p["messages"][1]["body"],
      p["messages"][1]["body"])
convs = importers.build_conversations(p, "jorge@talleresmartin.com")
check("MBOX: solo los correos de Jorge, en un hilo", len(convs) == 1 and len(convs[0]["messages"]) == 2, convs)
check("MBOX: direcciones", [m["direction"] for m in convs[0]["messages"]] == ["in", "out"])

for bad, name in ((b"hola que tal", "notas.txt"), (b"{}", "x.json"), (b"x", "foto.png")):
    try:
        importers.parse(name, bad)
        check(f"rechaza {name}", False)
    except importers.ImportFormatError as e:
        check(f"rechaza {name}: {e.detail}", True)

sys.exit(0 if ok else 1)
