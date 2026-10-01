"""Posponer conversaciones de la bandeja y seguimientos «avísame si no contesta»."""
import sys
from datetime import datetime, timedelta, timezone

from apitest import Session, check, results
from app.db import get_conn

ana, carlos = Session("ana"), Session("carlos")


def inbox_ids(session, **params):
    query = "&".join(f"{k}={v}" for k, v in {"scope": "mine", **params}.items())
    return [i["conversation_id"] for i in session.get(f"/api/inbox?{query}")[1]]


def future(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


# ---- Posponer
item = ana.get("/api/inbox?scope=mine")[1][0]
conv = item["conversation_id"]
st, r = ana.post(f"/api/conversations/{conv}/snooze", {"until": future(days=2), "message_id": item["message_id"]})
check("posponer", st == 200, r)
check("la pospuesta sale de la bandeja y del recuento", conv not in inbox_ids(ana)
      and ana.get("/api/inbox/counts")[1]["mine"] == 1)
snoozed = ana.get("/api/inbox?scope=mine&snoozed=true")[1]
check("aparece en «pospuestas» con su fecha", [i["conversation_id"] for i in snoozed] == [conv] and snoozed[0]["snoozed_until"], snoozed)
check("fecha pasada = 400", ana.post(f"/api/conversations/{conv}/snooze",
                                     {"until": future(minutes=-5), "message_id": item["message_id"]})[0] == 400)
check("conversación inexistente = 404", ana.post("/api/conversations/9999/snooze",
                                                 {"until": future(days=1), "message_id": 1})[0] == 404)
check("quitar el aplazamiento la devuelve", ana.delete(f"/api/conversations/{conv}/snooze")[0] == 200 and conv in inbox_ids(ana))

# Vence: vuelve sola
ana.post(f"/api/conversations/{conv}/snooze", {"until": future(days=1), "message_id": item["message_id"]})
with get_conn() as db:
    db.execute("UPDATE conversations SET snoozed_until = localtimestamp - interval '1 minute' WHERE id = ?", (conv,))
check("al vencer el plazo vuelve a la bandeja", conv in inbox_ids(ana) and not ana.get("/api/inbox?scope=mine&snoozed=true")[1])

# Si el cliente escribe, vuelve antes
ana.post(f"/api/conversations/{conv}/snooze", {"until": future(days=3), "message_id": item["message_id"]})
with get_conn() as db:
    db.execute("""INSERT INTO messages (conversation_id, direction, sender, body, sent_at)
                  VALUES (?, 'in', 'Cliente', ?, localtimestamp(0))""", (conv, "¿Alguna novedad?"))
check("si el cliente escribe, vuelve antes de tiempo", conv in inbox_ids(ana))

# ---- Seguimientos
laura_wa = carlos.get("/api/clients/1")[1]["conversations"]
target = laura_wa[0]["id"]
st, f = carlos.post(f"/api/conversations/{target}/follow-up", {"days": 3})
check("crear seguimiento a 3 días", st == 200 and f["due_at"], f)
check("aún no vence", carlos.get("/api/follow-ups")[1] == [])
check("días fuera de rango = 422", carlos.post(f"/api/conversations/{target}/follow-up", {"days": 0})[0] == 422)
check("conversación inexistente = 404", carlos.post("/api/conversations/9999/follow-up", {"days": 1})[0] == 404)
with get_conn() as db:
    db.execute("UPDATE follow_ups SET due_at = localtimestamp - interval '1 hour' WHERE id = ?", (f["id"],))
due = carlos.get("/api/follow-ups")[1]
check("vencido y sin respuesta: aparece", [d["id"] for d in due] == [f["id"]] and due[0]["client"] == "Laura Gómez", due)
check("solo lo ve quien lo pidió", ana.get("/api/follow-ups")[1] == [])
st, f2 = carlos.post(f"/api/conversations/{target}/follow-up", {"days": 1})
check("uno nuevo sustituye al anterior", carlos.get("/api/follow-ups")[1] == [])
with get_conn() as db:
    db.execute("UPDATE follow_ups SET due_at = localtimestamp - interval '1 hour' WHERE id = ?", (f2["id"],))
    db.execute("""INSERT INTO messages (conversation_id, direction, sender, body, sent_at)
                  VALUES (?, 'in', 'Laura', 'Perfecto, gracias', localtimestamp(0))""", (target,))
check("si el cliente contesta, se resuelve solo", carlos.get("/api/follow-ups")[1] == [])
with get_conn() as db:
    left = db.execute("SELECT count(*) FROM follow_ups").fetchone()[0]
check("y se borra", left == 0, left)
st, f3 = carlos.post(f"/api/conversations/{target}/follow-up", {"days": 2})
check("borrar ajeno = 404", ana.delete(f"/api/follow-ups/{f3['id']}")[0] == 404)
check("borrar propio", carlos.delete(f"/api/follow-ups/{f3['id']}")[0] == 200)
sys.exit(0 if results["ok"] else 1)
