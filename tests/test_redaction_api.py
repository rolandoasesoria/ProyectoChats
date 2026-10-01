"""Datos sensibles (detectar y ocultar) y retención de mensajes antiguos."""
import sys

from apitest import Session, check, results
from app import privacy
from app.db import get_conn

# ---- Detección (sin servidor)
text = "Mi IBAN es ES91 2100 0418 4502 0005 1332 y mi DNI 12345678Z. Tarjeta 4111 1111 1111 1111, tel 600111222."
found = privacy.find(text)
check("detecta IBAN, DNI y tarjeta", [k for k, _ in found] == ["IBAN", "DNI", "tarjeta"], found)
check("no confunde un teléfono ni un CIF con datos personales",
      privacy.find("Llámame al 600 111 222, CIF B12345678, pedido 1234567890123") == [],
      privacy.find("Llámame al 600 111 222, CIF B12345678, pedido 1234567890123"))
check("NIE", [k for k, _ in privacy.find("NIE X1234567L")] == ["DNI"])
body, kinds = privacy.redact_text(text)
check("oculta con una marca por tipo", "[IBAN oculto]" in body and "[DNI oculto]" in body and "[tarjeta oculto]" in body
      and "2100" not in body and kinds == ["IBAN", "DNI", "tarjeta"], body)

# ---- API
ana, carlos = Session("ana"), Session("carlos")
with get_conn() as conn:
    conv = conn.execute("SELECT id FROM conversations WHERE client_id = 1 ORDER BY id LIMIT 1").fetchone()["id"]
    msg = conn.execute("""INSERT INTO messages (conversation_id, direction, sender, body, sent_at)
                          VALUES (?, 'in', 'Laura', ?, localtimestamp(0)) RETURNING id""",
                       (conv, "Os paso el IBAN para la domiciliación: ES9121000418450200051332")).lastrowid
st, items = ana.get("/api/clients/1/sensitive")
check("lista los mensajes con datos sensibles", st == 200 and [i["id"] for i in items] == [msg]
      and items[0]["found"][0]["kind"] == "IBAN", items)
check("solo administradores = 403", carlos.get("/api/clients/1/sensitive")[0] == 403
      and carlos.post(f"/api/messages/{msg}/redact", {})[0] == 403)
check("antes de ocultarlo, el IBAN se encuentra al buscarlo",
      any(r["message_id"] == msg for r in ana.get("/api/search?q=ES9121000418450200051332&scope=team&client_id=1")[1]))
st, r = ana.post(f"/api/messages/{msg}/redact", {})
check("ocultar", st == 200 and r["hidden"] == ["IBAN"] and r["body"].endswith("[IBAN oculto]"), r)
check("ya no se encuentra al buscarlo",
      not any(x["message_id"] == msg for x in ana.get("/api/search?q=ES9121000418450200051332&scope=team&client_id=1")[1]))
check("ni aparece como pendiente", ana.get("/api/clients/1/sensitive")[1] == [])
check("queda en el registro de accesos", ana.get("/api/admin/audit?action=message_redact")[1]["entries"][0]["detail"]
      == f"mensaje {msg}: IBAN")
st, r = ana.post(f"/api/messages/{msg}/redact", {"text": "domiciliación"})
check("ocultar un texto concreto", r["body"].startswith("Os paso el IBAN para la [dato oculto]"), r)
check("mensaje inexistente = 404", ana.post("/api/messages/999999/redact", {})[0] == 404)

# ---- Retención
with get_conn() as conn:
    conn.execute("UPDATE messages SET sent_at = localtimestamp - interval '30 months' WHERE id = ?", (msg,))
    total = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
check("vista previa: cuántos se borrarían", ana.get("/api/admin/retention?months=24")[1] == {"months": 24, "messages": 1})
check("plazo no válido = 422", ana.get("/api/admin/retention?months=0")[0] == 422)
check("sin plazo guardado no borra nada", ana.post("/api/admin/retention/apply")[1]["messages"] == 0)
ana.patch("/api/admin/settings", {"retention_months": 24})
st, r = ana.post("/api/admin/retention/apply")
with get_conn() as conn:
    left = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
check("aplica el plazo guardado", st == 200 and r["messages"] == 1 and left == total - 1, (r, left, total))
check("retención solo administradores = 403", carlos.post("/api/admin/retention/apply")[0] == 403)
sys.exit(0 if results["ok"] else 1)
