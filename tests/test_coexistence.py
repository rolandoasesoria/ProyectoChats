"""Coexistencia: alta del WhatsApp Business del móvil con el registro insertado de Meta (simulado) y avisos del
webhook de la app (mensajes enviados desde el móvil, historial, contactos y desconexión)."""
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request

from apitest import BASE, Session, check, results

from app import insights, integrations, whatsapp_signup
from app.db import get_conn
from app.errors import Conflict

ana, carlos = Session("ana"), Session("carlos")
CARLOS = {"id": 2, "name": "Carlos Pérez", "role": "user"}
MARTA = {"id": 3, "name": "Marta López", "role": "user"}
SECRET = b"secreto-de-prueba"  # META_APP_SECRET de run_tests.ps1

# ---------------------------------------------------------------- Lo que recibe el navegador
st, s = carlos.get("/api/meta/whatsapp-signup")
check("el navegador recibe lo necesario para el alta, sin secretos",
      st == 200 and s["ready"] and s["app_id"] == "1234" and s["config_id"] == "5678" and "webhook" not in s
      and "secreto" not in json.dumps(s), s)
check("los administradores ven los datos del webhook de la app",
      ana.get("/api/meta/whatsapp-signup")[1]["webhook"]["verify_token"] == "verifica-prueba")

# ---------------------------------------------------------------- Alta (Meta simulada)
calls = []


def meta(method, url, *, body=None, headers=None, raw=False, timeout=30):
    calls.append((method, url, body, headers))
    if "/oauth/access_token" in url:
        return {"access_token": "EAAG-empresa"}
    if "/debug_token" in url:
        return {"data": {"granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": ["waba-1"]}]}}
    if "/phone_numbers" in url:
        return {"data": [{"id": "777", "display_phone_number": "+34 625 55 40 73", "verified_name": "Asesoría Pruebas"}]}
    if url.endswith("/subscribed_apps") or url.endswith("/smb_app_data"):
        return {"success": True}
    if "/777?" in url:
        return {"display_phone_number": "+34 625 55 40 73", "verified_name": "Asesoría Pruebas"}
    raise AssertionError(url)


integrations.http_request = meta
r = whatsapp_signup.connect(CARLOS, "codigo-1", "waba-1")
paths = [(c[0], c[1].replace(integrations.GRAPH_API, "")) for c in calls]
check("canjea el código con la app de Meta", any(p.startswith("/oauth/access_token") and "client_secret=secreto-de-prueba" in p
                                                  and "code=codigo-1" in p for _, p in paths), paths)
check("suscribe la app a los avisos de la cuenta", ("POST", "/waba-1/subscribed_apps") in paths, paths)
check("pide a la app del móvil los contactos y el historial",
      [c[2]["sync_type"] for c in calls if c[1].endswith("/smb_app_data")] == ["smb_app_state_sync", "history"])
check("no registra el número (ya está en la app del móvil)", not any("/register" in p for _, p in paths))
integ = integrations.get(r["id"])
check("la cuenta es de Carlos y guarda el token de la empresa",
      integ["owner_user_id"] == 2 and integ["config"]["access_token"] == "EAAG-empresa"
      and integ["config"]["phone_number_id"] == "777" and integ["config"]["waba_id"] == "waba-1", integ["config"])
check("y la prueba de conexión sale bien", r["test"]["ok"] and r["test"]["detail"] == "+34 625 55 40 73 · Asesoría Pruebas", r)
with get_conn() as conn:
    stored = conn.execute("SELECT config FROM integrations WHERE id = ?", (r["id"],)).fetchone()[0]
check("el token se guarda cifrado", "EAAG-empresa" not in stored)
item = next(i for i in carlos.get("/api/me/integrations")[1]["items"] if i["id"] == r["id"])
check("aparece como coexistencia, con el historial solicitado", item["coexistence"] and item["history"] == "solicitado", item)
check("sin el token a la vista", item["config"]["access_token"] == "••••••")

calls.clear()
again = whatsapp_signup.connect(CARLOS, "codigo-2", "")
check("volver a conectarlo renueva la misma cuenta (sin duplicar)", again["id"] == r["id"])
check("si el navegador no recibió la cuenta, se saca del token", any("/debug_token" in c[1] for c in calls))
try:
    whatsapp_signup.connect(MARTA, "codigo-3", "waba-1")
    check("otra persona no puede quedarse el número de Carlos", False)
except Conflict:
    check("otra persona no puede quedarse el número de Carlos", True)

# ---------------------------------------------------------------- Webhook de la app (servidor real)


def webhook(payload, secret=SECRET):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"{BASE}/api/webhooks/whatsapp", data=raw, method="POST",
                                 headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def change(field, value, waba="waba-1"):
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "34625554073",
                                                           "phone_number_id": "777"}, **value}
    return {"object": "whatsapp_business_account", "entry": [{"id": waba, "changes": [{"field": field, "value": value}]}]}


def get(path):
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


check("Meta verifica el webhook de la app con su token",
      get("/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=verifica-prueba&hub.challenge=99") == (200, "99"))
check("con otro token = 403", get("/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=x&hub.challenge=1")[0] == 403)
echo = change("smb_message_echoes", {"message_echoes": [
    {"from": "34625554073", "to": "34600999888", "id": "wamid.eco1", "timestamp": "1790000000", "type": "text",
     "text": {"body": "Te envío el presupuesto"}}]})
check("con otra firma = 403", webhook(echo, b"otra")[0] == 403)
st, res = webhook(echo)
check("lo enviado desde el móvil entra en ProyectoChats", st == 200 and res["imported"] == 1, res)
pedro = next((c for c in carlos.get("/api/clients?q=600999888")[1]), None)
tl = carlos.get(f"/api/clients/{pedro['id']}/timeline?scope=mine")[1] if pedro else []
check("como mensaje enviado por Carlos, en la conversación del cliente",
      [(m["direction"], m["sender"], m["body"]) for m in tl] == [("out", "Carlos Pérez", "Te envío el presupuesto")], tl)
check("repetir el aviso no lo duplica", webhook(echo)[1]["imported"] == 0)
st, res = webhook(change("messages", {
    "contacts": [{"wa_id": "34600999888", "profile": {"name": "Pedro"}}],
    "messages": [{"from": "34600999888", "id": "wamid.in1", "timestamp": "1790000100", "type": "text", "text": {"body": "¡Gracias!"}}]}))
check("lo que escribe el cliente también entra", st == 200 and res["imported"] == 1, res)

contacts = change("smb_app_state_sync", {"state_sync": [
    {"type": "contact", "action": "add", "contact": {"full_name": "Pedro Vidal", "first_name": "Pedro", "phone_number": "+34 600 999 888"},
     "metadata": {"timestamp": "1790000200"}},
    {"type": "contact", "action": "add", "contact": {"full_name": "Mi cuñado", "phone_number": "+34 699 000 111"},
     "metadata": {"timestamp": "1790000200"}}]})
webhook(contacts)
check("la agenda del móvil pone nombre al cliente que solo tenía el número",
      carlos.get(f"/api/clients/{pedro['id']}")[1]["name"] == "Pedro Vidal" if pedro else False)
check("pero no crea clientes por cada contacto de la agenda", not carlos.get("/api/clients?q=699000111")[1])

# Historial (en el propio proceso para poder comprobar que no se lanza la IA)
analyses = []
insights.schedule_analysis = lambda client_id, *a, **k: analyses.append(client_id)
history = change("history", {"history": [{"metadata": {"phase": 0, "chunk_order": 1, "progress": 100}, "threads": [{
    "id": "34611222333", "messages": [
        {"from": "34611222333", "id": "wamid.h1", "timestamp": "1785000000", "type": "text", "text": {"body": "¿Tenéis cita el lunes?"},
         "history_context": {"status": "READ"}},
        {"from": "34625554073", "id": "wamid.h2", "timestamp": "1785000300", "type": "text", "text": {"body": "Sí, a las 10"},
         "history_context": {"status": "READ"}},
        {"from": "34611222333", "id": "wamid.h3", "timestamp": "1785000600", "type": "image",
         "image": {"id": "m1", "mime_type": "image/jpeg", "caption": "La factura"}}]}]}]})
check("el historial se importa", integrations.receive_whatsapp_app(history) == 3)
client = next(c for c in carlos.get("/api/clients?q=611222333")[1])
tl = carlos.get(f"/api/clients/{client['id']}/timeline?scope=mine")[1]
check("con cada mensaje en su sentido (cliente / Carlos)", [(m["direction"], m["sender"]) for m in tl]
      == [("in", "+34611222333"), ("out", "Carlos Pérez"), ("in", "+34611222333")], tl)
check("los archivos antiguos no se descargan (se dice en el mensaje)", "archivo del historial" in tl[-1]["body"])
check("y no lanza análisis con IA (es historia, no mensajes nuevos)", analyses == [])
check("el progreso queda en la cuenta", integrations.list_integrations(2)[0]["history"] == "importado")
st, res = webhook(history)
check("por el webhook, el historial se guarda en segundo plano", st == 200 and res.get("queued"), res)
integrations.receive_whatsapp_app(change("history", {"history": [{"errors": [{"code": 2593109, "title": "History sync is turned off"}]}]}))
check("si la empresa no comparte el historial, se indica", integrations.list_integrations(2)[0]["history"] == "rechazado en el móvil")

# Desconexión desde el móvil
with get_conn() as conn:
    before = conn.execute("SELECT count(*) FROM notifications WHERE user_id = 2 AND kind = 'integration_error'").fetchone()[0]
integrations.receive_whatsapp_app({"entry": [{"id": "waba-1", "changes": [{"field": "account_update", "value": {
    "event": "PARTNER_REMOVED", "disconnection_info": {"reason": "user_action", "initiated_by": "business"}}}]}]})
integ = integrations.get(r["id"])
with get_conn() as conn:
    after = conn.execute("SELECT count(*) FROM notifications WHERE user_id = 2 AND kind = 'integration_error'").fetchone()[0]
check("si se desconecta desde el móvil, la cuenta se pausa y lo explica",
      not integ["enabled"] and integ["last_error"] == integrations.WHATSAPP_DISCONNECTED)
check("y Carlos recibe un aviso", after == before + 1)
check("pausada, ya no recibe mensajes", webhook(change("messages", {"messages": [
    {"from": "34600999888", "id": "wamid.in2", "timestamp": "1790000900", "type": "text", "text": {"body": "¿Hola?"}}]}))[1]["imported"] == 0)
sys.exit(0 if results["ok"] else 1)
