"""Organizar los chats (como en WhatsApp): fijar (hasta 3), archivar (vuelve si el cliente escribe), silenciar (no
cuenta en los no leídos de la barra lateral), marcar como no leído o leído, mensajes destacados y lo compartido en
cada chat (fotos y vídeos, documentos y enlaces). Cada usuario organiza su propia lista."""
import sys

from apitest import Session, check, receive, results

from app import attachments, clients
from app.db import get_conn

ana, carlos = Session("ana"), Session("carlos")


def chats(session=ana, query=""):
    st, items = session.get(f"/api/chats{query}")
    assert st == 200, items
    return items


def item(client_id, session=ana, query=""):
    return next((c for c in chats(session, query) if c["id"] == client_id), None)


def prefs(client_id, body, session=ana):
    return session.call("PUT", f"/api/chats/{client_id}/prefs", body)


mine = [c["id"] for c in chats()]
check("la lista trae cómo está cada chat (sin fijar, archivar, silenciar ni marcar)",
      all({"pinned", "archived", "muted", "marked_unread"} <= set(c) and not (c["pinned"] or c["archived"] or c["muted"]
          or c["marked_unread"]) for c in chats()))
oldest = mine[-1]

# ---------------------------------------------------------------- Fijar
st, body = prefs(oldest, {"pinned": True})
check("fijar un chat", st == 200 and body["pinned"], body)
check("el fijado sale el primero aunque su último mensaje sea el más antiguo", chats()[0]["id"] == oldest)
with get_conn() as conn:
    ids = [r["id"] for r in conn.execute("SELECT id FROM clients ORDER BY id").fetchall()]
while len(ids) < 4:  # se pueden fijar chats de cualquier cliente
    ids.append(ana.post("/api/clients", {"name": f"Cliente {len(ids)}"})[1]["id"])
others = [c for c in ids if c != oldest]
for cid in others[:2]:
    prefs(cid, {"pinned": True})
st, body = prefs(others[2], {"pinned": True})
check("como en WhatsApp, solo se pueden fijar 3", st == 409 and "3" in body["detail"], body)
st, body = prefs(oldest, {"pinned": True})
check("volver a fijar uno ya fijado no cuenta como otro", st == 200)
prefs(others[1], {"pinned": False})
check("desfijar", not item(others[1])["pinned"] if item(others[1]) else True)
check("cada usuario fija los suyos: Carlos no ve fijado el chat que fijó Ana",
      all(not c["pinned"] for c in chats(carlos)))

# ---------------------------------------------------------------- Archivar
st, body = prefs(oldest, {"archived": True})
check("archivar (y deja de estar fijado)", st == 200 and body["archived"] and not body["pinned"], body)
check("en la lista viene marcado como archivado", item(oldest)["archived"])
laura = 1
prefs(laura, {"archived": True})
receive("whatsapp", "+34600111222", "Hola, ¿al final cuándo me lo traéis?", owner=1, client_name="Laura Gómez")
check("si el cliente escribe, el chat vuelve a la lista (deja de estar archivado)", not item(laura)["archived"])
prefs(oldest, {"archived": False})
check("desarchivar", not item(oldest)["archived"])

# ---------------------------------------------------------------- Silenciar y no leídos
st, counts = ana.get("/api/me/counts")
unread_before = counts["unread_chats"]
check("Laura tiene mensajes sin leer y cuenta en la barra lateral", item(laura)["unread"] > 0 and unread_before >= 1)
st, body = prefs(laura, {"mute": "8h"})
check("silenciar 8 horas", st == 200 and body["muted"] and body["muted_until"], body)
check("un chat silenciado no cuenta en los no leídos de la barra lateral",
      ana.get("/api/me/counts")[1]["unread_chats"] == unread_before - 1)
check("pero sigue en «No leídos»", item(laura, query="?unread=true") is not None)
st, body = prefs(laura, {"mute": "always"})
check("silenciar siempre", body["muted"] and body["muted_until"].startswith("9999"), body)
st, body = prefs(laura, {"mute": "off"})
check("dejar de silenciar", not body["muted"] and ana.get("/api/me/counts")[1]["unread_chats"] == unread_before)
st, body = prefs(laura, {"mute": "un año"})
check("una duración que no existe = 422", st == 422)

st, body = prefs(laura, {"unread": False})
check("«Marcar como leído» lo deja leído (como abrirlo)", st == 200 and item(laura)["unread"] == 0)
read_one = next(c for c in chats() if not c["unread"])["id"]
st, body = prefs(read_one, {"unread": True})
check("«Marcar como no leído»", body["marked_unread"] and item(read_one)["marked_unread"])
check("sale en «No leídos» y cuenta en la barra lateral",
      item(read_one, query="?unread=true") is not None and ana.get("/api/me/counts")[1]["unread_chats"] >= 1)
ana.post(f"/api/clients/{read_one}/visit")
check("al abrirlo deja de estar marcado", not item(read_one)["marked_unread"])
st, body = prefs(999999, {"pinned": True})
check("un cliente que no existe = 404", st == 404)
st, body = Session().call("PUT", f"/api/chats/{laura}/prefs", {"pinned": True})
check("sin sesión = 401", st == 401)

# ---------------------------------------------------------------- Mensajes destacados
st, timeline = ana.get(f"/api/clients/{laura}/timeline?scope=team")
msg = timeline[0]
check("la conversación dice qué mensajes tienes destacados", all(m["starred"] is False for m in timeline))
st, body = ana.post(f"/api/messages/{msg['id']}/star", {"starred": True})
check("destacar un mensaje", st == 200 and body == {"starred": True}, body)
starred = next(m for m in ana.get(f"/api/clients/{laura}/timeline?scope=team")[1] if m["id"] == msg["id"])
check("en la conversación sale destacado", starred["starred"] is True)
check("pero no para Carlos (cada uno destaca los suyos)",
      not any(m["starred"] for m in carlos.get(f"/api/clients/{laura}/timeline?scope=team")[1]))
st, listed = ana.get(f"/api/clients/{laura}/starred")
check("los destacados del chat", st == 200 and [m["id"] for m in listed] == [msg["id"]], listed)
st, everything = ana.get("/api/starred")
check("y los de todos los chats, con el nombre del cliente",
      st == 200 and everything[0]["id"] == msg["id"] and everything[0]["client"] == "Laura Gómez", everything)
ana.post(f"/api/messages/{msg['id']}/star", {"starred": False})
check("quitar de destacados", ana.get(f"/api/clients/{laura}/starred")[1] == [])
st, body = ana.post("/api/messages/999999/star", {"starred": True})
check("un mensaje que no existe = 404", st == 404)

# ---------------------------------------------------------------- Lo compartido en el chat
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
with get_conn() as conn:
    wa = conn.execute("""SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id
                          WHERE c.client_id = ? AND c.channel = 'whatsapp' ORDER BY m.id LIMIT 1""", (laura,)).fetchone()["id"]
    email = conn.execute("""SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id
                             WHERE c.client_id = ? AND c.channel = 'email' ORDER BY m.id LIMIT 1""", (laura,)).fetchone()["id"]
    attachments.save(conn, laura, "foto-caja.png", PNG, "image/png", wa, None)
    attachments.save(conn, laura, "presupuesto.pdf", b"%PDF-1.4 presupuesto", "application/pdf", wa, None)
    attachments.save(conn, laura, "nota-de-voz.ogg", b"OggS", "audio/ogg", wa, None)
    attachments.save(conn, laura, "logo-firma.png", PNG, "image/png", email, None)
    conn.execute("UPDATE messages SET body = ? WHERE id = ?",
                 ("Mira https://hilvana.example/catalogo. Y el mismo: https://hilvana.example/catalogo y https://otra.example/a?b=1", wa))
    conn.execute("UPDATE messages SET body = body || ' https://correo.example/baja' WHERE id = ?", (email,))
st, shared = ana.get(f"/api/clients/{laura}/shared?scope=team")
check("fotos y vídeos del chat (sin los logos de las firmas de correo)",
      st == 200 and [f["filename"] for f in shared["media"]] == ["foto-caja.png"], shared["media"])
check("documentos (las notas de voz no cuentan como documento)", [f["filename"] for f in shared["docs"]] == ["presupuesto.pdf"])
check("enlaces de WhatsApp y Telegram, sin repetir y sin la puntuación final (los del correo no)",
      [link["url"] for link in shared["links"]] == ["https://hilvana.example/catalogo", "https://otra.example/a?b=1"], shared["links"])
st, carlos_shared = carlos.get(f"/api/clients/{laura}/shared?scope=mine")
check("con «Solo mis conversaciones», solo lo de las tuyas", st == 200 and carlos_shared["media"] == [] and carlos_shared["docs"] == [])

# ---------------------------------------------------------------- Al unir dos clientes
st, new = ana.post("/api/clients", {"name": "Laura (duplicado)"})
prefs(new["id"], {"mute": "always"})
clients.merge_clients(new["id"], laura)
check("al unir dos clientes se conserva cómo tenías el chat", item(laura)["muted"])

sys.exit(0 if results["ok"] else 1)
