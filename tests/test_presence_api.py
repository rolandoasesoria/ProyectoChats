"""Presencia (quién tiene abierto un cliente y quién responde) y aviso al enviar si ha llegado algo nuevo."""
import sys

from apitest import Session, check, results
from app.db import get_conn

ana, carlos, marta = Session("ana"), Session("carlos"), Session("marta")

check("nadie más en el cliente", ana.post("/api/presence", {"client_id": 1})[1] == [])
carlos.post("/api/presence", {"client_id": 1, "composing": True})
marta.post("/api/presence", {"client_id": 1})
st, others = ana.post("/api/presence", {"client_id": 1})
check("ve a los compañeros, primero quien está respondiendo", others == [
    {"name": "Carlos Pérez", "composing": True}, {"name": "Marta López", "composing": False}], others)
check("en otro cliente no los ve", ana.post("/api/presence", {"client_id": 2})[1] == [])
carlos.post("/api/presence", {"client_id": None})
check("al cerrar el cliente desaparece", [o["name"] for o in marta.post("/api/presence", {"client_id": 1})[1]] == [])
ana.post("/api/presence", {"client_id": 1})
with get_conn() as conn:
    conn.execute("UPDATE presence SET seen_at = localtimestamp - interval '2 minutes' WHERE user_id = 1")
check("si deja de avisar, caduca", marta.post("/api/presence", {"client_id": 1})[1] == [])
check("cliente inexistente = 404", ana.post("/api/presence", {"client_id": 999})[0] == 404)

# Aviso al enviar
with get_conn() as conn:
    conv = conn.execute("SELECT id FROM conversations WHERE client_id = 1 ORDER BY id LIMIT 1").fetchone()["id"]
st, s = ana.get(f"/api/conversations/{conv}/sender")
check("el estado de envío incluye el último mensaje", st == 200 and s["last_message_id"] > 0, s)
check("sin novedades pasa la comprobación (y falla después por no tener integración)",
      ana.post(f"/api/conversations/{conv}/send", {"text": "hola", "after_message_id": s["last_message_id"]})[0] == 400)
with get_conn() as conn:
    conn.execute("""INSERT INTO messages (conversation_id, direction, sender, body, sent_at)
                    VALUES (?, 'out', 'Carlos', 'Ya le he contestado yo', localtimestamp(0))""", (conv,))
st, r = ana.post(f"/api/conversations/{conv}/send", {"text": "hola", "after_message_id": s["last_message_id"]})
check("si un compañero ha respondido mientras tanto = 409", st == 409 and "un compañero ha respondido" in r["detail"], r)
check("con force se intenta enviar igualmente",
      ana.post(f"/api/conversations/{conv}/send", {"text": "hola", "after_message_id": s["last_message_id"], "force": True})[0] == 400)
sys.exit(0 if results["ok"] else 1)
