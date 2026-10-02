"""Cada persona conecta sus propias cuentas (correo, Telegram, WhatsApp) y solo gestiona las suyas."""
import sys

from apitest import Session, check, results

ana, carlos, marta = Session("ana"), Session("carlos"), Session("marta")

st, r = carlos.get("/api/me/integrations")
check("sin cuentas al principio, con los campos de cada tipo", st == 200 and r["items"] == []
      and {"email", "telegram", "whatsapp"} <= set(r["fields"]), r)

st, wa = carlos.post("/api/me/integrations", {"kind": "whatsapp", "name": "WhatsApp de Carlos", "config": {
    "phone_number_id": "123", "access_token": "tok", "app_secret": "sec"}})
# Al conectar se pregunta a Meta por el número; en las pruebas no hay salida a internet, así que no conecta.
check("conectar su WhatsApp Business: queda a su nombre y se prueba con Meta",
      st == 200 and wa["test"]["ok"] is False and wa["test"]["error"].startswith("No se pudo conectar con Meta"), wa)
items = carlos.get("/api/me/integrations")[1]["items"]
check("aparece en sus cuentas, con los secretos ocultos", [(i["kind"], i["owner"]) for i in items] == [("whatsapp", "Carlos Pérez")]
      and items[0]["config"]["access_token"] == "••••••" and items[0]["config"]["verify_token"], items)
check("el administrador la ve en todas las integraciones",
      any(i["id"] == wa["id"] for i in ana.get("/api/admin/integrations")[1]["items"]))
check("los demás no la ven", marta.get("/api/me/integrations")[1]["items"] == [])
check("ni pueden tocarla = 404", marta.patch(f"/api/me/integrations/{wa['id']}", {"enabled": False})[0] == 404
      and marta.delete(f"/api/me/integrations/{wa['id']}")[0] == 404
      and marta.post(f"/api/me/integrations/{wa['id']}/sync")[0] == 404)

st, em = carlos.post("/api/me/integrations", {"kind": "email", "name": "Mi correo", "config": {
    "address": "carlos@ejemplo.com", "password": "x", "imap_host": "imap.no-existe.invalid", "smtp_host": "smtp.no-existe.invalid"}})
check("al conectar se prueba y devuelve el error si falla", st == 200 and em["test"]["ok"] is False and em["test"]["error"], em)
item = next(i for i in carlos.get("/api/me/integrations")[1]["items"] if i["id"] == em["id"])
check("el error queda guardado para verlo en la lista", item["last_error"], item)
check("falta un campo obligatorio = 400",
      carlos.post("/api/me/integrations", {"kind": "telegram", "name": "Bot", "config": {}})[0] == 400)

st, r = carlos.patch(f"/api/me/integrations/{em['id']}", {"enabled": False, "name": "Correo de Carlos"})
item = next(i for i in carlos.get("/api/me/integrations")[1]["items"] if i["id"] == em["id"])
check("pausar y renombrar la suya", st == 200 and not item["enabled"] and item["name"] == "Correo de Carlos", item)
check("borrar la suya", carlos.delete(f"/api/me/integrations/{em['id']}")[0] == 200
      and [i["id"] for i in carlos.get("/api/me/integrations")[1]["items"]] == [wa["id"]])
check("queda en el registro de accesos", any("conectó su cuenta" in (e["detail"] or "")
                                              for e in ana.get("/api/admin/audit?action=integration_change")[1]["entries"]))
sys.exit(0 if results["ok"] else 1)
