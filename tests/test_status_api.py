"""Estado de los clientes: lo decide la IA o la regla de inactividad, y una persona puede cambiarlo a mano."""
import sys

from apitest import Session, check, results
from app import clients
from app.db import get_conn

ana, carlos = Session("ana"), Session("carlos")

c = carlos.get("/api/clients/1")[1]
check("por defecto el estado es automático", c["status_source"] == "auto" and c["status_updated_by"] is None, c)
st, c = carlos.patch("/api/clients/1", {"status": "lead"})
check("cambiarlo a mano lo marca como manual y guarda quién", st == 200 and c["status"] == "lead"
      and c["status_source"] == "manual" and c["status_updated_by"] == "Carlos Pérez" and c["status_updated_at"], c)
st, c = carlos.patch("/api/clients/1", {"company": "Otra S.L."})
check("cambiar otros datos no toca el origen del estado", c["status_source"] == "manual")

# Regla de inactividad (sin IA)
with get_conn() as conn:
    conn.execute("""UPDATE messages SET sent_at = sent_at - interval '200 days'
                     WHERE conversation_id IN (SELECT id FROM conversations WHERE client_id IN (1, 2))""")
changed = clients.mark_inactive(90)
statuses = {cid: carlos.get(f"/api/clients/{cid}")[1] for cid in (1, 2, 3)}
check("pasa a Inactivo a quien lleva 90 días sin mensajes (Jorge)", statuses[2]["status"] == "inactive"
      and statuses[2]["status_source"] == "auto" and statuses[2]["status_reason"] == "Sin mensajes en los últimos 90 días",
      statuses[2])
check("respeta el estado puesto a mano (Laura) y no toca a quien tiene actividad (Sofía)",
      statuses[1]["status"] == "lead" and statuses[3]["status"] == "active" and changed == 1, (changed, statuses))
check("con 0 días no hace nada", clients.mark_inactive(0) == 0)

# Vuelve a escribir: pasa a Activo
st, r = ana.post("/api/import", {"channel": "email", "handle": "jorge@talleresmartin.com", "client_id": 2,
                                 "messages": [{"direction": "in", "sender": "Jorge", "body": "Hola de nuevo",
                                               "sent_at": "2099-01-01T10:00:00"}]})
check("llega un mensaje nuevo de Jorge", st == 200 and r["messages"] == 1, r)
with get_conn() as conn:
    conn.execute("UPDATE messages SET sent_at = localtimestamp(0) WHERE body = 'Hola de nuevo'")
check("un inactivo que vuelve a escribir pasa a Activo", clients.reactivate(2, 90)
      and carlos.get("/api/clients/2")[1]["status_reason"] == "Ha vuelto a escribir")
check("si no está inactivo no hace nada", not clients.reactivate(2, 90))

check("ajuste de días de inactividad", ana.get("/api/settings")[1]["inactive_days"] == 90
      and ana.patch("/api/admin/settings", {"inactive_days": 30})[1]["inactive_days"] == 30)
sys.exit(0 if results["ok"] else 1)
