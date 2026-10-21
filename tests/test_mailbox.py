"""Correo en bandejas: Recibidos, Enviados y Destacados (uno por correo, el más reciente primero), sin leer hasta
abrirlo en la bandeja o abrir el chat del cliente, el correo abierto con su hilo, buscar, filtrar por cliente, páginas
y el permiso para ver los del equipo."""
import sys
from datetime import datetime, timedelta

from apitest import Session, check, receive, results

from app import integrations
from app.db import get_conn

ana, carlos, marta = Session("ana"), Session("carlos"), Session("marta")
integrations.create("email", "Correo de Carlos", 2, {"address": "carlos@miempresa.com", "password": "x",
                                                     "imap_host": "imap.x", "smtp_host": "smtp.x"})


def folder(session, query=""):
    st, body = session.get(f"/api/mail{query}")
    assert st == 200, body
    return body


now = datetime.now()


def rosa_email(body, minutes, direction="in", sender="Rosa Gil"):
    """Un correo del hilo «Presupuesto de cajas» de una clienta de Carlos (por su cuenta de correo)."""
    return integrations.ingest({"kind": "email", "owner_user_id": 2}, handle="rosa@cliente.es", client_name="Rosa Gil",
                               direction=direction, sender=sender, body=body, external_id=None,
                               sent_at=(now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S"),
                               subject="Presupuesto de cajas")


rosa_email("Te lo preparo hoy.", 20, "out", "Carlos Pérez")
first = rosa_email("Hola Carlos, ¿me mandáis el presupuesto?", 10)
rosa_email("Perdona, y también el plazo de entrega.", 5)
rosa = first["client_id"]

inbox = folder(carlos)
mine = [m for m in inbox["items"] if m["client_id"] == rosa]
check("Recibidos: un correo por fila, el más reciente primero, con asunto y extracto",
      [m["snippet"] for m in mine] == ["Perdona, y también el plazo de entrega.", "Hola Carlos, ¿me mandáis el presupuesto?"]
      and all(m["subject"] == "Presupuesto de cajas" and m["direction"] == "in" for m in mine), mine)
with get_conn() as conn:
    channels = {r["channel"] for r in conn.execute("SELECT channel FROM conversations WHERE id = ANY(?)",
                                                   ([m["conversation_id"] for m in inbox["items"]],))}
check("solo correos (ni WhatsApp ni Telegram), y solo los de tus conversaciones",
      channels == {"email"} and all(m["owner_id"] == 2 for m in inbox["items"]), channels)
check("los nuevos, sin leer, y cuántos hay", all(m["unread"] for m in mine) and inbox["unread"] >= 2, inbox["unread"])
sent = folder(carlos, "?folder=sent")
check("Enviados: lo que respondió el equipo", any(m["snippet"] == "Te lo preparo hoy." for m in sent["items"])
      and all(m["direction"] == "out" for m in sent["items"]))

# ---------------------------------------------------------------- Abrir un correo
latest = mine[0]
st, mail = carlos.get(f"/api/mail/{latest['id']}")
check("el correo abierto trae el texto entero, el asunto, las direcciones y el hilo",
      st == 200 and mail["body"] == "Perdona, y también el plazo de entrega." and mail["subject"] == "Presupuesto de cajas"
      and mail["client_addresses"] == ["rosa@cliente.es"] and mail["account"] == "carlos@miempresa.com"
      and [t["snippet"] for t in mail["thread"]] == ["Te lo preparo hoy.", "Hola Carlos, ¿me mandáis el presupuesto?",
                                                     "Perdona, y también el plazo de entrega."], mail)
after = folder(carlos)
check("al abrirlo queda leído (y baja el número)",
      not next(m for m in after["items"] if m["id"] == latest["id"])["unread"] and after["unread"] == inbox["unread"] - 1)
carlos.post(f"/api/clients/{rosa}/visit")
check("abrir el chat de la clienta también los deja leídos", not any(m["unread"] for m in folder(carlos)["items"] if m["client_id"] == rosa))
st, counts = carlos.get("/api/me/counts")
check("la barra lateral sabe cuántos correos quedan sin leer", "unread_mail" in counts, counts)

# ---------------------------------------------------------------- Buscar, filtrar, destacar y páginas
check("buscar por el texto, el asunto o el remitente",
      [m["id"] for m in folder(carlos, "?q=plazo%20de%20entrega")["items"]] == [latest["id"]]
      and {m["id"] for m in folder(carlos, "?q=presupuesto%20de%20cajas")["items"]} >= {mine[0]["id"], mine[1]["id"]})
check("solo los de un cliente", {m["client_id"] for m in folder(carlos, f"?client_id={rosa}")["items"]} == {rosa})
carlos.post(f"/api/messages/{latest['id']}/star", {"starred": True})
check("Destacados: los correos con ★", [m["id"] for m in folder(carlos, "?folder=starred")["items"]] == [latest["id"]])
for i in range(55):
    receive("email", f"lote{i}@cliente.es", f"Correo de prueba {i}", owner=2, client_name=f"Lote {i}")
page = folder(carlos)
rest = folder(carlos, "?offset=50")
check("de 50 en 50, con «hay más»", len(page["items"]) == 50 and page["more"] and rest["items"]
      and not {m["id"] for m in page["items"]} & {m["id"] for m in rest["items"]})
st, body = carlos.post("/api/mail/read-all")
check("marcar todo como leído", st == 200 and body["marked"] >= 55 and folder(carlos)["unread"] == 0, body)

# ---------------------------------------------------------------- Permisos
st, body = marta.get("/api/mail?scope=team")
check("los correos de todo el equipo necesitan permiso", st == 403)
team = folder(ana, "?scope=team")
check("un administrador ve los de todo el equipo", any(m["owner_id"] == 2 for m in team["items"]))
check("y en los suyos, solo los suyos", all(m["owner_id"] == 1 for m in folder(ana)["items"]))
st, body = carlos.get("/api/mail/999999")
check("un correo que no existe = 404", st == 404)
st, body = carlos.get(f"/api/mail/{latest['id'] + 100000}")
check("ni uno que no es correo", st == 404)
st, body = Session().get("/api/mail")
check("sin sesión = 401", st == 401)

sys.exit(0 if results["ok"] else 1)
