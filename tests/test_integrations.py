"""Integraciones con servidores simulados: IMAP/SMTP falsos, API de Telegram simulada y webhook de WhatsApp firmado."""
import hashlib
import hmac
import imaplib
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from apitest import BASE, Session, check, results  # noqa: E402

from app import integrations  # noqa: E402
from app.db import get_conn  # noqa: E402

ana, carlos = Session("ana"), Session("carlos")


def notices(user_id=1):
    """Avisos de «tu cuenta necesita atención» que ha recibido la persona."""
    with get_conn() as conn:
        return conn.execute("SELECT count(*) FROM notifications WHERE user_id = ? AND kind = 'integration_error'",
                            (user_id,)).fetchone()[0]


# ---------------------------------------------------------------- Administración (API)
st, r = ana.post("/api/admin/integrations", {"kind": "email", "name": "Buzón de Ana", "owner_user_id": 1, "config": {
    "address": "ana@miempresa.com", "password": "secreta123", "imap_host": "imap.falso", "smtp_host": "smtp.falso"}})
check("crear integración de email", st == 200, r)
email_id = r["id"]
st, lst = ana.get("/api/admin/integrations")
item = next(i for i in lst["items"] if i["id"] == email_id)
check("la contraseña nunca se devuelve", item["config"]["password"] == "••••••" and "secreta123" not in json.dumps(lst))
check("valores por defecto (puertos, carpeta)", item["config"]["imap_port"] == "993" and item["config"]["sent_folder"] == "Sent")
with get_conn() as conn:
    stored = conn.execute("SELECT config FROM integrations WHERE id = ?", (email_id,)).fetchone()[0]
check("guardada cifrada en la base de datos", "secreta123" not in stored and "ana@miempresa.com" not in stored)
ana.patch(f"/api/admin/integrations/{email_id}", {"config": {**item["config"], "password": "••••••", "sync_minutes": "10"}})
cfg = integrations.get(email_id)["config"]
check("editar sin tocar la contraseña la conserva", cfg["password"] == "secreta123" and cfg["sync_minutes"] == "10")
check("falta un campo obligatorio = 400", ana.post("/api/admin/integrations", {"kind": "telegram", "name": "x", "owner_user_id": 1,
                                                                             "config": {}})[0] == 400)
check("solo administradores = 403", carlos.get("/api/admin/integrations")[0] == 403)

# ---------------------------------------------------------------- Email: IMAP falso
def mail(frm, to, subject, body, msgid, extra=""):
    return (f"From: {frm}\nTo: {to}\nSubject: {subject}\nDate: Mon, 28 Sep 2026 10:00:00 +0200\n"
            f"Message-ID: {msgid}\n{extra}Content-Type: text/plain; charset=utf-8\n\n{body}\n").encode()


MAILBOX = {
    "INBOX": {1: mail("Pedro Sanz <pedro@nuevo.com>", "ana@miempresa.com", "Presupuesto cajas", "Hola, quiero 500 cajas", "<p1@nuevo.com>"),
              2: mail("Ofertas <news@tienda.com>", "ana@miempresa.com", "Rebajas", "50% dto", "<n1@tienda.com>",
                      "List-Unsubscribe: <mailto:baja@tienda.com>\n"),
              3: mail("Laura Gómez <laura@floristeriagomez.es>", "ana@miempresa.com", "Pedido noviembre", "Confirmo 350 cajas", "<l1@flor.es>")},
    "Sent": {7: mail("Ana <ana@miempresa.com>", "pedro@nuevo.com", "Re: Presupuesto cajas", "Te lo preparo hoy", "<s1@miempresa.com>")},
}
log = []


class FakeIMAP:
    def __init__(self, host, port):
        log.append(("connect", host, port))
        self.folder = None

    def login(self, user, password):
        log.append(("login", user, password))

    def select(self, folder, readonly=False):
        self.folder = folder.strip('"')
        return ("OK", [b"1"]) if self.folder in MAILBOX else ("NO", [b"no existe"])

    def uid(self, cmd, *args):
        box = MAILBOX[self.folder]
        if cmd == "SEARCH":
            crit = args[-1]
            log.append(("search", self.folder, crit))
            uids = sorted(box)
            if crit.startswith("UID "):
                start = int(crit.split()[1].split(":")[0])
                uids = [u for u in uids if u >= start] or [max(box)]  # como IMAP real: "n:*" devuelve al menos el último
            return "OK", [" ".join(map(str, uids)).encode()]
        return "OK", [(f"{args[0]} (RFC822 {{}}".encode(), box[int(args[0])]), b")"]

    def logout(self):
        pass


integrations.IMAP_CLASS = FakeIMAP
r = integrations.sync(email_id)
check("sincronizar: importa 3 (el boletín se descarta)", r == {"imported": 3}, r)
check("usa la contraseña descifrada", ("login", "ana@miempresa.com", "secreta123") in log)
check("primera vez: busca desde hace N días", any(e[0] == "search" and e[2].startswith("SINCE") for e in log))
clients = {c["name"]: c for c in ana.get("/api/clients")[1]}
check("crea el cliente nuevo", "Pedro Sanz" in clients and "Ofertas" not in clients, list(clients))
check("el correo de Laura va a su ficha", any(m["body"] == "Confirmo 350 cajas" for m in ana.get("/api/clients/1/timeline?scope=mine")[1]))
pedro_tl = ana.get(f"/api/clients/{clients['Pedro Sanz']['id']}/timeline?scope=mine")[1]
check("recibido y enviado en el mismo hilo", [m["direction"] for m in pedro_tl] == ["in", "out"], pedro_tl)
check("sin errores guardados", integrations.get(email_id)["last_error"] is None)

log.clear()
MAILBOX["INBOX"][4] = mail("Pedro Sanz <pedro@nuevo.com>", "ana@miempresa.com", "Re: Presupuesto cajas", "¿Y el precio?", "<p2@nuevo.com>")
r = integrations.sync(email_id)
check("segunda sincronización: solo lo nuevo, desde el último UID", r == {"imported": 1}
      and any(e[0] == "search" and e[2] == "UID 4:*" for e in log), (r, log))
check("tercera: nada nuevo (sin duplicados)", integrations.sync(email_id) == {"imported": 0})

class Broken(FakeIMAP):
    def login(self, user, password):
        raise OSError("Autenticación fallida")
integrations.IMAP_CLASS = Broken
try:
    integrations.sync(email_id)
    check("error de conexión", False)
except integrations.IntegrationError:
    check("un error de conexión se guarda en la integración", "Autenticación fallida" in integrations.get(email_id)["last_error"])
check("un fallo de red no avisa en la campana (suele ser pasajero)", notices() == 0)


class Rejected(FakeIMAP):
    def login(self, user, password):
        raise imaplib.IMAP4.error("b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'")


integrations.IMAP_CLASS = Rejected
for _ in range(2):
    try:
        integrations.sync(email_id)
    except integrations.IntegrationError:
        pass
check("contraseña de correo rechazada: lo explica en la cuenta",
      "no acepta el usuario o la contraseña" in integrations.get(email_id)["last_error"])
check("y avisa a su dueña una sola vez, aunque falle en cada revisión", notices() == 1)
integrations.IMAP_CLASS = FakeIMAP
integrations.sync(email_id)
check("cuando vuelve a funcionar se quita la marca", integrations.get(email_id)["last_error"] is None)

# ---------------------------------------------------------------- Email: envío por SMTP falso
sent = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def login(self, user, pw):
        sent.append(("login", user, pw))

    def send_message(self, msg):
        sent.append(msg)

    def starttls(self):
        sent.append("starttls")

    def quit(self):
        pass


integrations.SMTP_SSL_CLASS = FakeSMTP
integrations.SMTP_CLASS = FakeSMTP
with get_conn() as conn:
    conv = conn.execute("SELECT id FROM conversations WHERE client_id = ? AND channel = 'email'", (clients["Pedro Sanz"]["id"],)).fetchone()[0]
sender = Session("ana").get(f"/api/conversations/{conv}/sender")[1]
check("Ana puede enviar en esa conversación", sender["can_send"] and sender["via"] == "Buzón de Ana", sender)
check("Carlos no tiene integración de email", carlos.get(f"/api/conversations/{conv}/sender")[1]["can_send"] is False)
res = integrations.send_reply(conv, {"id": 1, "name": "Ana Ruiz", "role": "admin"}, "Son 0,40 € por caja.")
msg = next(m for m in sent if not isinstance(m, (tuple, str)))
check("envía al cliente, respondiendo en el hilo", msg["To"] == "pedro@nuevo.com" and msg["In-Reply-To"] == "<p2@nuevo.com>"
      and msg["Subject"] == "Re: Presupuesto cajas" and "0,40" in msg.get_content(), dict(msg))
tl = ana.get(f"/api/clients/{clients['Pedro Sanz']['id']}/timeline?scope=mine")[1]
check("el enviado queda en la conversación", tl[-1]["body"] == "Son 0,40 € por caja." and tl[-1]["direction"] == "out")
check("no se vuelve a importar al sincronizar enviados",
      (MAILBOX["Sent"].__setitem__(8, mail("Ana <ana@miempresa.com>", "pedro@nuevo.com", "Re: Presupuesto cajas",
                                          "Son 0,40 € por caja.", msg["Message-ID"])), integrations.sync(email_id))[1] == {"imported": 0})

# ---------------------------------------------------------------- Telegram: API simulada
st, r = ana.post("/api/admin/integrations", {"kind": "telegram", "name": "Bot de la empresa", "owner_user_id": 3,
                                             "config": {"bot_token": "123:ABC"}})
tg_id = r["id"]
calls = []
PHOTO = b"\x89PNG\r\n\x1a\nfalsa"


def fake_http(method, url, *, body=None, headers=None, raw=False, timeout=30):
    calls.append((method, url, body))
    if "/getUpdates" in url:
        if "offset=0" not in url:
            return {"ok": True, "result": []}
        return {"ok": True, "result": [
            {"update_id": 500, "message": {"message_id": 1, "date": 1790000000, "chat": {"id": 777, "type": "private"},
                                           "from": {"first_name": "Sofía", "last_name": "Navarro", "username": "sofianavarro"},
                                           "text": "Hola, ¿tenéis bolsas kraft?"}},
            {"update_id": 501, "message": {"message_id": 2, "date": 1790000060, "chat": {"id": -100, "type": "group"},
                                           "from": {"first_name": "X"}, "text": "mensaje de grupo"}},
            {"update_id": 502, "message": {"message_id": 3, "date": 1790000120, "chat": {"id": 777, "type": "private"},
                                           "from": {"first_name": "Sofía"}, "photo": [{"file_id": "small"}, {"file_id": "big"}],
                                           "caption": "Este modelo"}}]}
    if "/getFile" in url:
        return {"ok": True, "result": {"file_path": "photos/file_1.jpg"}}
    if "/file/bot" in url:
        return PHOTO
    if "/sendMessage" in url:
        return {"ok": True, "result": {"message_id": 99}}
    raise AssertionError(url)


integrations.http_request = fake_http
check("Telegram: importa 2 (ignora los grupos)", integrations.sync(tg_id) == {"imported": 2})
check("guarda el offset para no repetir", integrations.get(tg_id)["state"]["offset"] == 503)
check("descarga la foto más grande", any("file_id=big" in c[1] for c in calls))
check("siguiente sincronización pide desde el offset", integrations.sync(tg_id) == {"imported": 0} and "offset=503" in calls[-1][1])
sofia = next(c for c in ana.get("/api/clients")[1] if c["name"] == "Sofía Navarro")
tl = marta = Session("marta").get(f"/api/clients/{sofia['id']}/timeline?scope=mine")[1]
check("entra como conversación de la dueña (Marta)", [m["body"] for m in tl][-2:] == ["Hola, ¿tenéis bolsas kraft?", "Este modelo"]
      and tl[-1]["attachments"][0]["filename"] == "foto_3.jpg", tl[-2:])
with get_conn() as conn:
    tg_conv = conn.execute("SELECT id FROM conversations WHERE client_id = ? AND channel = 'telegram' AND owner_user_id = 3",
                           (sofia["id"],)).fetchone()[0]
integrations.send_reply(tg_conv, {"id": 3, "name": "Marta López", "role": "user"}, "¡Sí! Desde 500 unidades.")
check("responder por Telegram al chat del cliente", calls[-1][2] == {"chat_id": 777, "text": "¡Sí! Desde 500 unidades."})

# ---------------------------------------------------------------- WhatsApp: webhook firmado (servidor real) y envío
st, r = ana.post("/api/admin/integrations", {"kind": "whatsapp", "name": "WhatsApp empresa", "owner_user_id": 1,
                                             "config": {"phone_number_id": "1111", "access_token": "EAAX", "app_secret": "shh"}})
wa_id = r["id"]
verify = integrations.get(wa_id)["config"]["verify_token"]
check("genera el verify token", len(verify) > 20)


def raw(method, path, data=None, headers=None):
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


import urllib.error  # noqa: E402

check("verificación del webhook con el token correcto", raw("GET", f"/api/webhooks/whatsapp/{wa_id}?hub.mode=subscribe&hub.verify_token={verify}&hub.challenge=42") == (200, "42"))
check("token incorrecto = 403", raw("GET", f"/api/webhooks/whatsapp/{wa_id}?hub.mode=subscribe&hub.verify_token=x&hub.challenge=42")[0] == 403)
payload = json.dumps({"entry": [{"changes": [{"value": {
    "contacts": [{"wa_id": "34600111222", "profile": {"name": "Laura"}}],
    "messages": [{"from": "34600111222", "id": "wamid.1", "timestamp": "1790000000", "type": "text",
                  "text": {"body": "¿Me mandáis la factura?"}}]}}]}]}).encode()
check("sin firma = 403", raw("POST", f"/api/webhooks/whatsapp/{wa_id}", payload, {"Content-Type": "application/json"})[0] == 403)
sig = "sha256=" + hmac.new(b"shh", payload, hashlib.sha256).hexdigest()
check("firma mala = 403", raw("POST", f"/api/webhooks/whatsapp/{wa_id}", payload, {"X-Hub-Signature-256": "sha256=00"})[0] == 403)
st, body = raw("POST", f"/api/webhooks/whatsapp/{wa_id}", payload, {"X-Hub-Signature-256": sig})
check("firma válida: mensaje importado", st == 200 and json.loads(body)["imported"] == 1, body)
check("reenvío del mismo mensaje no duplica", json.loads(raw("POST", f"/api/webhooks/whatsapp/{wa_id}", payload, {"X-Hub-Signature-256": sig})[1])["imported"] == 0)
tl = ana.get("/api/clients/1/timeline?scope=mine&channel=whatsapp")[1]
check("va a Laura (mismo teléfono) y a su conversación de WhatsApp", tl[-1]["body"] == "¿Me mandáis la factura?", tl[-1])
with get_conn() as conn:
    wa_conv = conn.execute("SELECT id FROM conversations WHERE client_id = 1 AND channel = 'whatsapp' AND owner_user_id = 1").fetchone()[0]
    calls.clear()
integrations.http_request = lambda method, url, **kw: calls.append((url, kw)) or {"messages": [{"id": "wamid.out1"}]}
integrations.send_reply(wa_conv, {"id": 1, "name": "Ana Ruiz", "role": "admin"}, "Te la envío ahora")
url, kw = calls[-1]
check("responder por WhatsApp (Cloud API)", url.endswith("/1111/messages") and kw["body"]["to"] == "34600111222"
      and kw["headers"]["Authorization"] == "Bearer EAAX", calls[-1])
check("desactivada: el webhook la rechaza", (ana.patch(f"/api/admin/integrations/{wa_id}", {"enabled": False}),
      raw("POST", f"/api/webhooks/whatsapp/{wa_id}", payload, {"X-Hub-Signature-256": sig})[0])[1] == 403)
check("registro de cambios de integraciones", any(e["action"] == "integration_change" for e in ana.get("/api/admin/audit")[1]["entries"]))
check("Telegram con el token revocado: se marca para revisarlo",
      integrations._explain("telegram", integrations.IntegrationError("401", status=401)).needs_attention)
check("borrar integración", ana.delete(f"/api/admin/integrations/{tg_id}")[0] == 200)

# ---------------------------------------------------------------- WhatsApp: comprobar las credenciales con Meta
ana.patch(f"/api/admin/integrations/{wa_id}", {"enabled": True})
graph = []


def meta_ok(method, url, *, body=None, headers=None, raw=False, timeout=30):
    graph.append((method, url, headers))
    return {"display_phone_number": "+34 600 000 000", "verified_name": "Asesoría Pruebas", "id": "1111"}


def meta_error(status, code, message=""):
    def fake(method, url, **kw):
        raise integrations.IntegrationError(f"El servicio respondió {status}", status=status,
                                            error={"code": code, "message": message})
    return fake


integrations.http_request = meta_ok
before = notices()
r = integrations.check_connection(wa_id)
proof = hmac.new(b"shh", b"EAAX", hashlib.sha256).hexdigest()
check("WhatsApp: «Conectar y probar» pregunta a Meta por el número",
      r["ok"] and r["detail"] == "+34 600 000 000 · Asesoría Pruebas" and "/1111?" in graph[-1][1]
      and graph[-1][2]["Authorization"] == "Bearer EAAX", (r, graph[-1:]))
check("y comprueba el app secret (appsecret_proof)", f"appsecret_proof={proof}" in graph[-1][1], graph[-1][1])
check("queda como conectada", integrations.get(wa_id)["last_error"] is None and integrations.get(wa_id)["last_sync_at"])

integrations.http_request = meta_error(400, 190, "Error validating access token: Session has expired")
r = integrations.check_connection(wa_id)
check("token caducado: lo explica", not r["ok"] and r["error"] == integrations.META_TOKEN_REJECTED, r)
check("la cuenta queda marcada con el motivo", integrations.get(wa_id)["last_error"] == integrations.META_TOKEN_REJECTED)
check("su dueña recibe un aviso en la campana", notices() == before + 1)
integrations.check_connection(wa_id)
check("una sola vez, no en cada comprobación", notices() == before + 1)
integrations.http_request = meta_error(400, 100, "Invalid appsecret_proof provided in the API argument")
check("app secret de otra app", "app secret no corresponde" in integrations.check_connection(wa_id)["error"])
integrations.http_request = meta_error(400, 100, "Unsupported get request. Object with ID '1111' does not exist")
check("Phone number ID equivocado", "Phone number ID no existe" in integrations.check_connection(wa_id)["error"])
integrations.http_request = meta_error(403, 200, "Permissions error")
check("faltan permisos", "faltan permisos" in integrations.check_connection(wa_id)["error"])
integrations.http_request = meta_error(500, 2, "Service temporarily unavailable")
n = notices()
r = integrations.check_connection(wa_id)
check("un fallo pasajero de Meta: lo dice, pero no avisa", r["error"].startswith("Meta ha respondido con un error") and notices() == n, r)


def no_network(method, url, **kw):
    raise integrations.IntegrationError("No se pudo conectar: [WinError 10061] conexión rechazada")


integrations.http_request = no_network
r = integrations.check_connection(wa_id)
check("sin conexión con Meta: lo dice, pero no avisa", r["error"].startswith("No se pudo conectar con Meta") and notices() == n, r)
integrations.http_request = meta_ok
integrations.check_connection(wa_id)
check("al volver a funcionar se quita la marca", integrations.get(wa_id)["last_error"] is None)
utc = lambda hours: (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731
check("se vuelve a comprobar sola cada 6 horas",
      not integrations._due({"kind": "whatsapp", "config": "", "last_sync_at": utc(5)})
      and integrations._due({"kind": "whatsapp", "config": "", "last_sync_at": utc(7)}))

# Foto con el token caducado: el mensaje entra igualmente, sin el archivo y con una nota
n = notices()
integrations.http_request = meta_error(401, 190, "Session has expired")
photo = {"entry": [{"changes": [{"value": {
    "contacts": [{"wa_id": "34600111222", "profile": {"name": "Laura"}}],
    "messages": [{"from": "34600111222", "id": "wamid.foto1", "timestamp": "1790000500", "type": "image",
                  "image": {"id": "media1", "mime_type": "image/jpeg", "caption": "La factura"}}]}}]}]}
check("foto con el token caducado: el mensaje no se pierde", integrations.receive_whatsapp(integrations.get(wa_id), photo) == 1)
tl = ana.get("/api/clients/1/timeline?scope=mine&channel=whatsapp")[1]
foto = next((m for m in tl if m["body"].startswith("La factura")), {})
check("sin el archivo y con una nota", "⚠ No se pudo descargar" in foto.get("body", "") and not foto.get("attachments"), foto)
check("la cuenta queda marcada y se avisa", integrations.get(wa_id)["last_error"] == integrations.META_TOKEN_REJECTED
      and notices() == n + 1)
try:
    integrations.send_reply(wa_conv, {"id": 1, "name": "Ana Ruiz", "role": "admin"}, "¿Me la reenvías?")
    check("enviar con el token caducado da error", False)
except Exception as exc:  # noqa: BLE001
    check("enviar con el token caducado explica qué pasa", "access token" in str(exc), str(exc))

# Por el webhook real: el servidor de pruebas no llega a Meta, pero el documento no hace perder el mensaje
doc = json.dumps({"entry": [{"changes": [{"value": {
    "contacts": [{"wa_id": "34600111222", "profile": {"name": "Laura"}}],
    "messages": [{"from": "34600111222", "id": "wamid.doc1", "timestamp": "1790000600", "type": "document",
                  "document": {"id": "media2", "filename": "nomina.pdf", "mime_type": "application/pdf"}}]}}]}]}).encode()
st, body = raw("POST", f"/api/webhooks/whatsapp/{wa_id}", doc,
               {"X-Hub-Signature-256": "sha256=" + hmac.new(b"shh", doc, hashlib.sha256).hexdigest()})
check("webhook con un documento que no se puede descargar: responde bien y guarda el mensaje",
      st == 200 and json.loads(body)["imported"] == 1, body)
check("con la nota del archivo", any(m["body"].startswith("📎 nomina.pdf\n⚠ No se pudo descargar")
                                      for m in ana.get("/api/clients/1/timeline?scope=mine&channel=whatsapp")[1]))
sys.exit(0 if results["ok"] else 1)
