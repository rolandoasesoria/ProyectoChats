"""Chat al estilo de WhatsApp en el navegador: checks de entrega, cita y «Respondiendo a…», reacciones, foto en la
burbuja y su visor, formato y enlaces, selector de emojis y refresco sin volver a pintar."""
import struct
import sys
import zlib

from apitest import BASE, check, results
from browser import Browser

from app import attachments, integrations
from app.db import get_conn


def png(w, h):
    raw = b"".join(b"\x00" + b"".join(struct.pack("BBB", 120 + x * 100 // w, 110, 200 - y * 80 // h) for x in range(w))
                   for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# La conversación de WhatsApp de Laura (cliente 1, entró por la cuenta de Ana): como si hubiera llegado por la API, con
# un mensaje leído, otro entregado que cita al primero del cliente, reacciones y una foto.
with get_conn() as conn:
    msgs = [dict(r) for r in conn.execute(
        """SELECT m.id, m.direction, m.conversation_id FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE c.client_id = 1 AND c.channel = 'whatsapp' ORDER BY m.sent_at, m.id""")]
    for m in msgs:
        conn.execute("UPDATE messages SET external_id = ? WHERE id = ?", (f"wa:wamid.{m['id']}", m["id"]))
    outs = [m["id"] for m in msgs if m["direction"] == "out"]
    ins = [m["id"] for m in msgs if m["direction"] == "in"]
    conn.execute("""UPDATE messages SET status = 'read', delivered_at = '2026-08-05T10:06:00', read_at = '2026-08-05T10:07:00'
                     WHERE id = ?""", (outs[0],))
    conn.execute("UPDATE messages SET status = 'delivered', delivered_at = '2026-08-05T10:09:00', reply_to_id = ?, body = ? WHERE id = ?",
                 (ins[0], "Te preparo el *presupuesto* hoy: https://hilvana.example/presupuesto", outs[-1]))
    conn.execute("INSERT INTO message_reactions (message_id, side, emoji) VALUES (?, 'client', '👍')", (outs[0],))
    attachments.save(conn, 1, "caja.png", png(240, 150), "image/png", ins[-1], None)
integrations.create("whatsapp", "WhatsApp de Ana", 1, {"phone_number_id": "999", "access_token": "EAAG", "app_secret": "s"})

b = Browser()
try:
    b.goto(BASE + "/login.html")
    b.fill("#username", "ana")
    b.fill("#password", "demo1234")
    b.click("#login-btn")
    b.wait("location.pathname === '/' && !!currentUser && !document.body.classList.contains('booting')")
    b.click("#nav-chats")
    b.wait("document.querySelector('#chats-list li[data-client=\"1\"]')")
    b.click('#chats-list li[data-client="1"]')
    b.wait("document.querySelector('#chat-timeline .msg-row')")
    b.js("chatState.channel = 'whatsapp'; setActiveChannelTab(document.querySelector('#chat-tabs'), 'whatsapp'); loadChatConversation()")
    b.wait("document.querySelector('#chat-timeline .bubble-media img') && !document.querySelector('#chat-send').disabled")
    # Para comprobar qué se envía sin depender de Meta: se anota cada petición de la página
    b.js("""window.__sent = []; const realFetch = window.fetch;
            window.fetch = (url, opts = {}) => { window.__sent.push({url: String(url), body: opts.body || null}); return realFetch(url, opts); };""")

    # ---------------------------------------------------------------- Checks de entrega
    ticks = b.js("[...document.querySelectorAll('#chat-timeline .ticks')].map((t) => [t.classList[1], t.title])")
    check("checks: leído (azules) y entregado, con la hora al pasar el ratón",
          ["read", "Leído · entregado a las 10:06 · leído a las 10:07"] in ticks
          and any(t[0] == "delivered" for t in ticks), ticks)

    # ---------------------------------------------------------------- Cita, formato y enlace
    quote = f"#chat-timeline li[data-id='{outs[-1]}'] .bubble-quote"
    check("la respuesta muestra el mensaje citado",
          b.js(f"document.querySelector(\"{quote}\").textContent").find("Laura") >= 0)
    check("formato de WhatsApp: *negrita* y el enlace se puede pulsar",
          b.js(f"document.querySelector(\"#chat-timeline li[data-id='{outs[-1]}'] .bubble-text strong\")?.textContent") == "presupuesto"
          and b.js(f"document.querySelector(\"#chat-timeline li[data-id='{outs[-1]}'] .bubble-text a\")?.rel") == "noopener noreferrer")
    b.click(quote)
    b.wait(f"document.querySelector(\"#chat-timeline li[data-id='{ins[0]}']\").classList.contains('flash')")
    check("al pulsar la cita se resalta el mensaje citado", True)
    b.pump(1)  # que acabe el desplazamiento suave (al desplazarse, el menú de reacciones se cierra)

    # ---------------------------------------------------------------- Reacciones
    check("la reacción del cliente se ve en el borde del mensaje",
          b.js(f"document.querySelector(\"#chat-timeline li[data-id='{outs[0]}'] .bubble-reactions\")?.textContent.trim()") == "👍")
    b.click(f"#chat-timeline li[data-id='{ins[0]}'] [data-react]")
    b.wait("!document.querySelector('#react-tray').hidden")
    check("reaccionar: menú con las reacciones rápidas", b.js("document.querySelectorAll('#react-tray [data-emoji]:not([data-emoji-remove])').length") == 6)
    b.shot("13a-reacciones")
    b.click("#react-tray [data-emoji='👍']")
    b.wait("window.__sent.some((r) => r.url.endsWith('/reaction'))")
    sent = b.js("window.__sent.find((r) => r.url.endsWith('/reaction'))")
    check("la reacción se pide al servidor para ese mensaje",
          sent["url"].endswith(f"/api/messages/{ins[0]}/reaction") and '"emoji":"👍"' in sent["body"], sent)
    b.wait("document.querySelector('#react-tray').hidden")
    b.js("document.querySelector('.toast')?.click()")

    # ---------------------------------------------------------------- Responder citando
    b.click(f"#chat-timeline li[data-id='{ins[0]}'] [data-quote-reply]")
    b.wait("!document.querySelector('#chat-reply').hidden")
    check("«Respondiendo a…» muestra a quién y qué se cita",
          b.js("document.querySelector('#chat-reply-sender').textContent") == "Laura"
          and b.js("document.querySelector('#chat-reply-text').textContent").startswith("Hola Ana"))
    b.shot("13b-respondiendo")
    b.fill("#chat-text", "Claro, te lo mando")
    b.js("window.__sent = []")
    b.click("#chat-send")
    b.wait("window.__sent.some((r) => r.url.endsWith('/send'))")
    body = b.js("window.__sent.find((r) => r.url.endsWith('/send')).body")
    check("al enviar, va la cita", f'"reply_to_message_id":{ins[0]}' in body, body)
    b.wait("!document.querySelector('#chat-send').disabled")
    b.js("document.querySelector('.toast')?.click()")
    b.click("#chat-reply-cancel")
    check("la cita se puede quitar", b.js("document.querySelector('#chat-reply').hidden"))

    # ---------------------------------------------------------------- Emojis en la caja de escribir
    b.fill("#chat-text", "Gracias ")
    b.js("const t = document.querySelector('#chat-text'); t.selectionStart = t.selectionEnd = t.value.length")
    b.click("#chat-emoji")
    b.wait("!document.querySelector('#emoji-picker').hidden")
    b.shot("13c-emojis")
    b.click("#emoji-grid [data-pick='🙏']")
    check("el emoji se escribe donde está el cursor", b.js("document.querySelector('#chat-text').value") == "Gracias 🙏"
          and b.js("document.querySelector('#emoji-picker').hidden"))
    b.fill("#chat-text", "")

    # ---------------------------------------------------------------- Foto en la burbuja y visor
    check("la foto se ve dentro de la burbuja, sin el «📎 caja.png»",
          b.js(f"!!document.querySelector(\"#chat-timeline li[data-id='{ins[-1]}'] .bubble-media img\")"))
    b.click(f"#chat-timeline li[data-id='{ins[-1]}'] .bubble-media")
    b.wait("document.querySelector('#media-viewer').open")
    check("al pulsarla se abre en grande, con «Descargar»",
          b.js("document.querySelector('#media-viewer-download').href").endswith("?download=true")
          and b.js("document.querySelector('#media-viewer-name').textContent") == "caja.png")
    b.shot("13d-visor")
    b.js("document.querySelector('#media-viewer [data-close]').click()")

    # ---------------------------------------------------------------- Cada chat, su borrador
    b.click(f"#chat-timeline li[data-id='{ins[0]}'] [data-quote-reply]")
    b.fill("#chat-text", "Mañana te llamo para")
    b.click('#chats-list li[data-client="2"]')
    b.wait("chatState.clientId === 2 && chatState.data?.id === 2")
    check("al cambiar de contacto, la caja queda vacía (lo escrito era para el anterior)",
          b.js("document.querySelector('#chat-text').value") == "" and b.js("document.querySelector('#chat-reply').hidden")
          and not b.js("chatState.composing"))
    b.wait("document.querySelector('#chats-list li[data-client=\"1\"] .chat-draft')")
    check("la lista muestra «Borrador: …» en el chat que se deja",
          b.js("document.querySelector('#chats-list li[data-client=\"1\"] .chat-preview').textContent") == "Borrador: Mañana te llamo para")
    b.shot("13e-borrador")
    b.click('#chats-list li[data-client="1"]')
    b.wait("chatState.clientId === 1 && document.querySelector('#chat-text').value !== ''")
    check("al volver, se recupera lo escrito y la cita",
          b.js("document.querySelector('#chat-text').value") == "Mañana te llamo para"
          and not b.js("document.querySelector('#chat-reply').hidden")
          and b.js("document.querySelector('#chat-reply-sender').textContent") == "Laura")
    check("y en el chat abierto no sale «Borrador»", not b.js("document.querySelector('#chats-list li[data-client=\"1\"] .chat-draft')"))
    b.js("chatState.channel = 'whatsapp'; setActiveChannelTab(document.querySelector('#chat-tabs'), 'whatsapp'); loadChatConversation()")
    b.wait("document.querySelector('#chat-timeline .bubble-media img')")
    b.fill("#chat-text", "")
    b.click("#chat-reply-cancel")

    # ---------------------------------------------------------------- Refresco sin volver a pintar
    b.js("window.__keep = document.querySelector('#chat-timeline li[data-id]')")
    b.js("loadChatConversation(true)")
    b.pump(1)
    check("al refrescar sin cambios no se vuelve a pintar (no corta un audio)", b.js("window.__keep.isConnected"))
    b.shot("13-chat")
finally:
    b.pump(0.5)
    b.close()

# Meta no está (las pruebas no llaman a servicios reales): enviar y reaccionar fallan con 502, como es de esperar.
errors = [e for e in b.errors if "favicon" not in e and "status of 502" not in e]
check("sin errores de JavaScript en la consola", not errors, "\n".join(errors))
sys.exit(0 if results["ok"] else 1)
