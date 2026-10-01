"""Lectura de correos de la integración de email: cuerpo sin citas, asunto, HTML, adjuntos y envíos masivos."""
import email
import sys
from email.policy import default as default_policy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import emails  # noqa: E402

ok = True


def check(label, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label + (f"  -> {extra}" if extra and not cond else ""))


def parse(raw: bytes) -> dict | None:
    return emails.parse_message(email.message_from_bytes(raw, policy=default_policy))


m = parse(b"""From: Jorge Martin <jorge@talleresmartin.com>
To: ana@miempresa.com
Subject: Re: Pedido etiquetas
Date: Tue, 22 Sep 2026 09:05:00 +0200
Message-ID: <abc@talleresmartin.com>
Content-Type: text/plain; charset=utf-8

Confirmo el pedido de 5.000 etiquetas.

El lun, 21 sept 2026 a las 11:00, Ana <ana@miempresa.com> escribi\xc3\xb3:
> Te paso el precio
""")
check("cuerpo sin la cita del correo anterior", m["body"] == "Confirmo el pedido de 5.000 etiquetas.", m["body"])
check("asunto sin «Re:»", m["subject"] == "Pedido etiquetas")
check("remitente, destinatarios e id", (m["key"], m["name"], m["recipients"], m["external_id"])
      == ("jorge@talleresmartin.com", "Jorge Martin", ["ana@miempresa.com"], "<abc@talleresmartin.com>"), m)
check("no es un envío masivo", m["bulk"] is False)

m = parse(b"From: Otro <otro@x.com>\nTo: ana@miempresa.com\nSubject: Oferta\nDate: Tue, 22 Sep 2026 10:00:00 +0200\n"
          b"Content-Type: text/html; charset=utf-8\n\n<p>Hola <b>Ana</b></p><style>p{}</style><p>Adios</p>\n")
check("HTML convertido a texto", "Hola Ana" in m["body"] and "<" not in m["body"] and "p{}" not in m["body"], m["body"])

m = parse(b"From: Tienda <news@tienda.com>\nTo: ana@miempresa.com\nSubject: Ofertas\nList-Unsubscribe: <mailto:x>\n\nRebajas\n")
check("boletín marcado como envío masivo", m["bulk"] is True)

m = parse(b"From: Jorge <jorge@talleresmartin.com>\nTo: ana@miempresa.com\nSubject: Factura\nMIME-Version: 1.0\n"
          b"Content-Type: multipart/mixed; boundary=XX\n\n--XX\nContent-Type: application/pdf; name=\"f.pdf\"\n"
          b"Content-Disposition: attachment; filename=\"f.pdf\"\nContent-Transfer-Encoding: base64\n\nJVBERi0=\n--XX--\n")
check("solo adjunto: el cuerpo lo nombra y el archivo se conserva",
      m["body"] == "📎 f.pdf" and [(a["filename"], a["mime"]) for a in m["attachments"]] == [("f.pdf", "application/pdf")], m)
check("sin remitente se ignora", parse(b"Subject: x\n\nhola\n") is None)
sys.exit(0 if ok else 1)
