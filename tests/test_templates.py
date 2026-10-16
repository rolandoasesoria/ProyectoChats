"""Plantillas de mensaje de WhatsApp: listarlas y enviarlas a revisión de Meta (simulada), desde «Mis cuentas»."""
import sys

from apitest import Session, check, receive, results

from app import conversations, integrations, whatsapp_templates
from app.errors import InvalidInput

carlos, marta, ana = Session("carlos"), Session("marta"), Session("ana")
CFG = {"phone_number_id": "888", "access_token": "EAAG-plantillas", "app_secret": "s"}
with_account = integrations.create("whatsapp", "WhatsApp plantillas", 2, {**CFG, "waba_id": "waba-9"})
without_account = integrations.create("whatsapp", "WhatsApp sin cuenta", 2, CFG)

# ---------------------------------------------------------------- Permisos y datos (servidor real, sin salir a Meta)
st, res = carlos.get(f"/api/me/integrations/{without_account}/templates")
check("sin el identificador de la cuenta, explica qué falta", st == 400 and "Editar" in res["detail"], res)
check("las plantillas de Carlos no las ve Marta", marta.get(f"/api/me/integrations/{with_account}/templates")[0] == 404)
st, _ = carlos.post(f"/api/me/integrations/{with_account}/templates",
                    {"name": "x", "category": "OTRA", "body": "Hola"})
check("solo categorías de Meta (servicio o marketing)", st == 422)
check("un administrador puede consultarlas", ana.get(f"/api/admin/integrations/{without_account}/templates")[0] == 400)
st, res = carlos.post(f"/api/me/integrations/{with_account}/templates",
                      {"name": "Cita", "category": "UTILITY", "body": "Hola {{1}}, te esperamos."})
check("crearlas es de un administrador, aunque la cuenta sea suya = 403", st == 403 and "administrador" in res["detail"], res)
check("y borrarlas también = 403", carlos.delete(f"/api/me/integrations/{with_account}/templates/cita")[0] == 403)

# ---------------------------------------------------------------- Cuentas de WhatsApp Business de Meta (WABA)
# Los números de una misma cuenta comparten las plantillas; se avisa del que está en otra cuenta que el resto del equipo.
marta_same = integrations.create("whatsapp", "WhatsApp de Marta", 3, {**CFG, "phone_number_id": "889", "waba_id": "waba-9"})
ana_other = integrations.create("whatsapp", "WhatsApp de Ana", 1, {**CFG, "phone_number_id": "890", "waba_id": "waba-otra"})
mine = {i["id"]: i for i in carlos.get("/api/me/integrations")[1]["items"]}
check("cada número dice con quién comparte las plantillas (aunque sea de un compañero)",
      mine[with_account]["waba_id"] == "waba-9" and mine[with_account]["waba_shared_with"] == ["WhatsApp de Marta (Marta López)"],
      mine[with_account])
check("un número sin identificador de cuenta no se agrupa ni se marca",
      mine[without_account]["waba_id"] == "" and not mine[without_account]["waba_other"])
team = {i["id"]: i for i in ana.get("/api/admin/integrations")[1]["items"]}
check("se marca el número que está en otra cuenta de Meta que el resto del equipo",
      team[ana_other]["waba_other"] and team[ana_other]["waba_main"] == "waba-9" and not team[with_account]["waba_other"],
      {k: team[k] for k in (ana_other, with_account)})
for integration_id in (marta_same, ana_other):
    integrations.delete(integration_id)

# ---------------------------------------------------------------- Con Meta simulada
calls = []


def meta(method, url, *, body=None, headers=None, raw=False, timeout=30):
    calls.append((method, url.replace(integrations.GRAPH_API, ""), body, headers))
    if method == "POST":
        return {"id": "tpl-1", "status": "PENDING", "category": body["category"]}
    return {"data": [{"id": "tpl-0", "name": "bienvenida", "status": "APPROVED", "category": "UTILITY", "language": "es",
                      "components": [{"type": "HEADER", "text": "Hola"}, {"type": "BODY", "text": "Gracias por escribir"}]},
                     {"id": "tpl-2", "name": "oferta", "status": "REJECTED", "category": "MARKETING", "language": "es",
                      "rejected_reason": "INVALID_FORMAT", "components": []}]}


integrations.http_request = meta
integ = integrations.get(with_account)
items = whatsapp_templates.list_templates(integ)
check("lista las plantillas de la cuenta con su estado y su texto",
      [(t["name"], t["status"], t["body"]) for t in items]
      == [("bienvenida", "APPROVED", "Gracias por escribir"), ("oferta", "REJECTED", "")], items)
check("con el token de la cuenta", calls[0][1].startswith("/waba-9/message_templates")
      and calls[0][3]["Authorization"] == "Bearer EAAG-plantillas", calls)
check("y el motivo si Meta la rechaza", items[1]["rejected_reason"] == "INVALID_FORMAT")

calls.clear()
r = whatsapp_templates.create_template(integ, "Recordatorio de cita ñ", "UTILITY", "es",
                                       "Hola {{1}}, te esperamos el {{2}}.", ["Laura", "lunes a las 10"])
sent = calls[0][2]
check("el nombre se adapta a lo que admite Meta", r["name"] == "recordatorio_de_cita_n" and sent["name"] == r["name"], r)
check("envía categoría, idioma y texto con los ejemplos de las variables",
      sent["category"] == "UTILITY" and sent["language"] == "es"
      and sent["components"] == [{"type": "BODY", "text": "Hola {{1}}, te esperamos el {{2}}.",
                                  "example": {"body_text": [["Laura", "lunes a las 10"]]}}], sent)
check("y queda en revisión", r["status"] == "PENDING")


def rejected(*args):
    try:
        whatsapp_templates.create_template(integ, *args)
    except InvalidInput as exc:
        return str(exc)
    return None


check("sin ejemplos de las variables no se envía", "faltan 1" in (rejected("a", "UTILITY", "es", "Hola {{1}}", []) or ""))
check("variables mal numeradas", "seguidas" in (rejected("a", "UTILITY", "es", "Hola {{2}}", ["x"]) or ""))
check("sin texto", rejected("a", "UTILITY", "es", "   ") is not None)
check("sin nombre válido", rejected("¡¡!!", "UTILITY", "es", "Hola") is not None)
check("un texto sin variables se envía sin ejemplos",
      rejected("aviso", "MARKETING", "es", "Novedades de octubre") is None)

# ---------------------------------------------------------------- Enviar una plantilla desde el chat (Meta simulada)
integrations.delete(without_account)  # Carlos responde por WhatsApp con la cuenta que tiene la WABA
sent = []


def meta_send(method, url, *, body=None, headers=None, raw=False, timeout=30):
    path = url.replace(integrations.GRAPH_API, "")
    sent.append((method, path, body))
    if method == "DELETE":
        return {"success": True}
    if path.endswith("/messages"):
        return {"messages": [{"id": "wamid.plantilla1"}]}
    return {"data": [
        {"id": "t1", "name": "cita", "status": "APPROVED", "category": "UTILITY", "language": "es",
         "components": [{"type": "BODY", "text": "Hola {{1}}, te esperamos el {{2}}."}]},
        {"id": "t2", "name": "pendiente", "status": "PENDING", "category": "UTILITY", "language": "es",
         "components": [{"type": "BODY", "text": "Sin aprobar"}]}]}


integrations.http_request = meta_send
conv = receive("whatsapp", "+34600555444", "Hola, ¿tenéis hueco?", client_name="Paula", owner=2)["conversation_id"]
CARLOS = {"id": 2, "name": "Carlos Pérez", "role": "user"}
approved = whatsapp_templates.approved_for(conv, CARLOS)
check("en el chat solo se ofrecen las aprobadas, con cuántas variables tienen",
      [(t["name"], t["variables"]) for t in approved] == [("cita", 2)], approved)
r = whatsapp_templates.send_template(conv, CARLOS, "cita", "es", ["Paula", "lunes a las 10"])
msg = next(c for c in sent if c[0] == "POST")
check("se envía a Meta como plantilla con sus parámetros",
      msg[1] == "/888/messages" and msg[2]["type"] == "template" and msg[2]["to"] == "34600555444"
      and msg[2]["template"] == {"name": "cita", "language": {"code": "es"}, "components": [
          {"type": "body", "parameters": [{"type": "text", "text": "Paula"}, {"type": "text", "text": "lunes a las 10"}]}]},
      msg)
check("devuelve el mensaje guardado", r["message_id"] and r["via"] == "WhatsApp plantillas", r)
tl = carlos.get(f"/api/clients/{conversations.conversation_client_id(conv)}/timeline")[1]
check("y queda en la conversación con el texto ya rellenado",
      any(m["direction"] == "out" and m["body"] == "Hola Paula, te esperamos el lunes a las 10." for m in tl), tl)


def refused(*args):
    try:
        whatsapp_templates.send_template(conv, CARLOS, *args)
    except InvalidInput as exc:
        return str(exc)
    return None


check("sin rellenar todas las variables no se envía", "variables" in (refused("cita", "es", ["Paula"]) or ""))
check("una plantilla sin aprobar no se envía", "aprobada" in (refused("pendiente", "es", []) or ""))
check("Marta no puede enviar en la conversación de Carlos",
      marta.post(f"/api/conversations/{conv}/send-template", {"name": "cita", "language": "es", "params": ["a", "b"]})[0] == 400)
whatsapp_templates.delete_template(integrations.get(with_account), "Cita")
check("borrar una plantilla la quita en Meta por su nombre",
      any(c[0] == "DELETE" and c[1] == "/waba-9/message_templates?name=cita" for c in sent), sent[-1])

integrations.delete(with_account)
sys.exit(0 if results["ok"] else 1)
