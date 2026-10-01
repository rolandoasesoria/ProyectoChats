"""Integraciones con servidores simulados: IMAP/SMTP falsos, API de Telegram simulada y webhook de WhatsApp firmado."""
import hashlib
import hmac
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from apitest import BASE, Session, check, results  # noqa: E402

from app import integrations  # noqa: E402
from app.db import get_conn  # noqa: E402

ana, carlos = Session("ana"), Session("carlos")

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
integrations.IMAP_CLASS = FakeIMAP

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
check("borrar integración", ana.delete(f"/api/admin/integrations/{tg_id}")[0] == 200)
sys.exit(0 if results["ok"] else 1)
