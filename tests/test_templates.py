"""Plantillas de mensaje de WhatsApp: listarlas y enviarlas a revisión de Meta (simulada), desde «Mis cuentas»."""
import sys

from apitest import Session, check, results

from app import integrations, whatsapp_templates
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

integrations.delete(with_account)
integrations.delete(without_account)
sys.exit(0 if results["ok"] else 1)
