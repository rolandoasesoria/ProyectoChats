"""Documentos y adjuntos: subida, extracción de texto, archivos, .eml con adjunto, .zip de WhatsApp,
búsqueda del asistente, lectura con IA (simulada), permisos y borrado de archivos del disco."""
import base64
import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from apitest import BASE, Session, check, results  # noqa: E402


def make_pdf(text: str) -> bytes:
    """PDF mínimo válido de una página con una línea de texto."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
b64 = lambda data: base64.b64encode(data).decode()  # noqa: E731
ana, carlos = Session("ana"), Session("carlos")
STORAGE = Path(os.environ["DB_PATH"]).parent / "attachments"

# Subir documentos a la ficha
st, pdf = ana.post("/api/clients/1/documents", {"filename": "Factura 2026-117.pdf", "data": b64(make_pdf("Factura 2026-117 Importe total 1250 EUR"))})
check("subir PDF: se lee el texto al momento", st == 200 and pdf["extracted_by"] == "pdf" and pdf["text_length"] > 20, pdf)
st, img = ana.post("/api/clients/1/documents", {"filename": "albaran.png", "data": b64(PNG)})
check("subir imagen: sin texto hasta leerla con IA", img["mime"] == "image/png" and img["extracted_by"] is None, img)
st, docs = ana.get("/api/clients/1/documents")
check("lista de documentos", [d["filename"] for d in docs][:2] == ["albaran.png", "Factura 2026-117.pdf"] or len(docs) == 2, docs)
st, txt = ana.get(f"/api/attachments/{pdf['id']}/text")
check("ver texto del PDF", "Importe total 1250" in txt["text"], txt)
check("leer con IA sin clave = 503", ana.post(f"/api/attachments/{img['id']}/read")[0] == 503)
too_big = b64(b"x" * (20 * 1024 * 1024 + 1))
check("más de 20 MB = 400", ana.post("/api/clients/1/documents", {"filename": "grande.bin", "data": too_big})[0] == 400)

# Servir archivos
def raw(path):
    req = urllib.request.Request(BASE + path)
    with ana.opener.open(req) as r:
        return r.headers, r.read()
h, body = raw(f"/api/attachments/{pdf['id']}/file")
check("PDF en línea con su tipo", h["Content-Type"] == "application/pdf" and h["Content-Disposition"].startswith("inline")
      and body.startswith(b"%PDF"), dict(h))
check("sin CSP en archivos (visor de PDF) pero con nosniff", "Content-Security-Policy" not in h and h["X-Content-Type-Options"] == "nosniff")
h, _ = raw(f"/api/attachments/{pdf['id']}/file?download=true")
check("descargar fuerza attachment", h["Content-Disposition"].startswith("attachment"))
st, up = ana.post("/api/clients/1/documents", {"filename": "pagina.html", "data": b64(b"<script>alert(1)</script>")})
h, _ = raw(f"/api/attachments/{up['id']}/file")
check("un HTML subido nunca se sirve en línea", h["Content-Disposition"].startswith("attachment"), dict(h))
check("el resto de la app sigue con CSP", "Content-Security-Policy" in raw("/api/me")[0])

# Email con adjunto
eml = (b"From: Jorge Martin <jorge@talleresmartin.com>\nTo: ana@miempresa.com\nSubject: Presupuesto firmado\n"
       b"Date: Tue, 22 Sep 2026 09:05:00 +0200\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=XX\n\n"
       b"--XX\nContent-Type: text/plain; charset=utf-8\n\nTe adjunto el presupuesto firmado.\n"
       b"--XX\nContent-Type: application/pdf; name=\"presupuesto.pdf\"\nContent-Disposition: attachment; filename=\"presupuesto.pdf\"\n"
       b"Content-Transfer-Encoding: base64\n\n" + base64.encodebytes(make_pdf("Presupuesto etiquetas vinilo 0,12 EUR unidad")) + b"--XX--\n")
st, res = ana.post("/api/import/file", {"filename": "p.eml", "data": b64(eml), "client_key": "jorge@talleresmartin.com", "client_id": 2})
check("importar .eml con adjunto", res["messages"] == 1 and res["attachments"] == 1, res)
tl = ana.get("/api/clients/2/timeline?scope=mine")[1]
msg = next(m for m in tl if "presupuesto firmado" in m["body"])
check("el adjunto aparece bajo su mensaje", [a["filename"] for a in msg["attachments"]] == ["presupuesto.pdf"], msg)

# WhatsApp con archivos (.zip)
zbuf = io.BytesIO()
with zipfile.ZipFile(zbuf, "w") as z:
    z.writestr("Chat de WhatsApp con Sofía Navarro.txt",
               "03/10/26, 9:15 - Sofía Navarro: Te mando foto del modelo\n"
               "03/10/26, 9:16 - Sofía Navarro: IMG-20261003-WA0001.jpg (archivo adjunto)\n"
               "03/10/26, 9:17 - Marta López: ¡Recibido!\n")
    z.writestr("IMG-20261003-WA0001.jpg", PNG)
st, prev = ana.post("/api/import/preview", {"filename": "Chat de WhatsApp con Sofía Navarro.zip", "data": b64(zbuf.getvalue())})
check("vista previa del .zip", st == 200 and prev["total"] == 3 and prev["title"] == "Sofía Navarro", prev)
st, res = ana.post("/api/import/file", {"filename": "Chat de WhatsApp con Sofía Navarro.zip", "data": b64(zbuf.getvalue()),
                                        "client_key": "Sofía Navarro", "client_id": 3})
check("importar .zip: 3 mensajes y 1 foto", (res["messages"], res["attachments"]) == (3, 1), res)
tl = ana.get("/api/clients/3/timeline?scope=mine")[1]
photo_msg = next(m for m in tl if m["attachments"])
check("la marca del adjunto se sustituye por 📎", photo_msg["body"] == "📎 IMG-20261003-WA0001.jpg", photo_msg["body"])
st, bad = ana.post("/api/import/preview", {"filename": "x.zip", "data": b64(b"no es un zip")})
check("zip dañado = 400", st == 400, bad)

# Búsqueda del asistente en documentos (mismo proceso, misma base de datos)
from app import agent, attachments  # noqa: E402

found = agent._run_tool("buscar_documentos", {"consulta": "importe factura", "alcance": "mias"}, 1)
check("el asistente encuentra la factura por su contenido", found and found[0]["filename"] == "Factura 2026-117.pdf", found)
found = agent._run_tool("buscar_documentos", {"consulta": "vinilo", "alcance": "mias"}, 3)
check("un adjunto de conversación ajena no se ve con 'mias'", isinstance(found, dict) and found["resultados"] == 0, found)
found = agent._run_tool("buscar_documentos", {"consulta": "vinilo", "alcance": "equipo"}, 3)
check("con 'equipo' sí", found and found[0]["filename"] == "presupuesto.pdf", found)

# Lectura con IA (respuesta simulada)
calls = []
agent._create = lambda **p: calls.append(p) or SimpleNamespace(
    stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Albarán nº 5541 · 350 cajas entregadas")])
att = attachments.read_with_ai(img["id"])
block = calls[-1]["messages"][0]["content"][0]
check("la imagen se envía como bloque de imagen", block["type"] == "image" and block["source"]["media_type"] == "image/png")
check("texto leído guardado", att["extracted_by"] == "ai")
check("y buscable", agent._run_tool("buscar_documentos", {"consulta": "albarán 5541", "alcance": "mias"}, 1)[0]["filename"] == "albaran.png")
attachments.read_with_ai(pdf["id"])
check("un PDF se envía como bloque de documento", calls[-1]["messages"][0]["content"][0]["type"] == "document")

# Permisos y borrado de archivos
check("Carlos no puede borrar un documento de Ana = 403", carlos.delete(f"/api/attachments/{img['id']}")[0] == 403)
stored = STORAGE / attachments.get(img["id"])["path"]
check("el archivo existe en disco", stored.exists())
check("Ana lo borra", ana.delete(f"/api/attachments/{img['id']}")[0] == 200)
check("y desaparece del disco", not stored.exists())
files_before = len(list(STORAGE.iterdir()))
ana.delete("/api/clients/3?confirm=Sof%C3%ADa%20Navarro")
check("al borrar un cliente se borran sus archivos", len(list(STORAGE.iterdir())) == files_before - 1)
st, data = ana.get("/api/clients/2/export")
check("la exportación incluye los documentos con su texto", data["documents"][0]["filename"] == "presupuesto.pdf"
      and "vinilo" in data["documents"][0]["extracted_text"], data["documents"])
sys.exit(0 if results["ok"] else 1)
