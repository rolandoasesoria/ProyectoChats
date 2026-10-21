"""Organizar los chats en el navegador: el menú de cada chat (fijar, silenciar, marcar como no leído, archivar) y la
lista de archivados, destacar un mensaje (★), lo compartido en el chat (Detalles y su ventana: fotos, documentos,
enlaces y destacados) y los destacados de todos los chats."""
import struct
import sys
import zlib

from apitest import BASE, check, results
from browser import Browser

from app import attachments
from app.db import get_conn


def png(w, h):
    rows = b"".join(b"\x00" + b"".join(struct.pack("BBB", 80 + x * 150 // w, 120, 220 - y * 100 // h) for x in range(w))
                    for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


# En la conversación de WhatsApp de Laura (cliente 1): una foto, un PDF y un enlace.
with get_conn() as conn:
    wa = [r["id"] for r in conn.execute("""SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id
                                            WHERE c.client_id = 1 AND c.channel = 'whatsapp' ORDER BY m.sent_at, m.id""")]
    attachments.save(conn, 1, "caja-muestra.png", png(160, 120), "image/png", wa[0], None)
    attachments.save(conn, 1, "presupuesto.pdf", b"%PDF-1.4 presupuesto", "application/pdf", wa[1], None)
    conn.execute("UPDATE messages SET body = body || ' https://hilvana.example/catalogo' WHERE id = ?", (wa[2],))

b = Browser()
try:
    b.goto(BASE + "/login.html")
    b.fill("#username", "ana")
    b.fill("#password", "demo1234")
    b.click("#login-btn")
    b.wait("location.pathname === '/' && !!currentUser && !document.body.classList.contains('booting')")
    b.click("#nav-chats")
    b.wait("document.querySelectorAll('#chats-list li[data-client]').length >= 2")
    first = b.js("Number(document.querySelector('#chats-list li[data-client]').dataset.client)")
    last = b.js("Number([...document.querySelectorAll('#chats-list li[data-client]')].at(-1).dataset.client)")
    li = lambda cid: f"document.querySelector('#chats-list li[data-client=\"{cid}\"]')"  # noqa: E731
    menu_items = "[...document.querySelectorAll('#chat-item-menu [data-chat-act]')].map((x) => x.textContent.trim())"

    def menu(cid):
        b.js(f"{li(cid)}.querySelector('[data-chat-menu]').click()")
        b.wait("!document.querySelector('#chat-item-menu').hidden")

    def act(label):
        b.js(f"[...document.querySelectorAll('#chat-item-menu [data-chat-act]')].find((x) => x.textContent.trim() === {label!r}).click()")
        b.pump(0.6)

    # ---------------------------------------------------------------- Menú de cada chat
    menu(last)
    options = b.js(menu_items)
    check("la flecha del chat abre sus opciones", options[:3] == ["Archivar chat", "Silenciar…", "Fijar chat"]
          and options[3] in ("Marcar como no leído", "Marcar como leído"), options)
    b.shot("chat3-01-menu")
    if options[3] == "Marcar como leído":
        act("Marcar como leído")
        b.wait(f"!{li(last)}.querySelector('.unread')")
        check("«Marcar como leído» quita los no leídos", True)
        menu(last)
    act("Fijar chat")
    b.wait(f"Number(document.querySelector('#chats-list li[data-client]').dataset.client) === {last}")
    check("fijar lo sube arriba del todo, con su chincheta", b.js(f"!!{li(last)}.querySelector('.chat-flag')"))
    menu(last)
    act("Silenciar…")
    check("«Silenciar…» pregunta cuánto tiempo", b.js(menu_items) == ["Durante 8 horas", "Durante 1 semana", "Siempre"])
    act("Durante 8 horas")
    b.wait(f"{li(last)}.classList.contains('muted')")
    check("silenciado: se ve el icono (con hasta cuándo al pasar el ratón)",
          "Silenciado hasta" in b.js(f"[...{li(last)}.querySelectorAll('.chat-flag')].map((x) => x.title).join(' ')"))
    menu(last)
    act("Marcar como no leído")
    b.wait(f"!!{li(last)}.querySelector('.unread.dot')")
    check("marcar como no leído pone el punto", True)
    b.js(f"{li(first)}.dispatchEvent(new MouseEvent('contextmenu', {{bubbles: true, cancelable: true}}))")
    check("el clic derecho en un chat abre el mismo menú", not b.js("document.querySelector('#chat-item-menu').hidden")
          and "Archivar chat" in b.js(menu_items))
    act("Archivar chat")
    b.wait(f"!{li(first)} && !!document.querySelector('#chats-list [data-archived-open]')")
    check("archivar lo quita de la lista y aparece «Archivados»",
          "Archivados" in b.js("document.querySelector('#chats-list [data-archived-open]').textContent"))
    b.click("#chats-list [data-archived-open]")
    b.wait(f"!!document.querySelector('#chats-list .chats-archived-head') && !!{li(first)}")
    check("en «Archivados» está el chat archivado", b.js("document.querySelectorAll('#chats-list li[data-client]').length") == 1)
    b.shot("chat3-02-archivados")
    menu(first)
    check("y se puede desarchivar", "Desarchivar chat" in b.js(menu_items))
    act("Desarchivar chat")
    b.click("#chats-list [data-archived-back]")
    b.wait(f"!!{li(first)} && !document.querySelector('#chats-list [data-archived-open]')")
    check("volver a los chats", True)

    # ---------------------------------------------------------------- Destacar un mensaje
    b.click('#chats-list li[data-client="1"]')
    b.wait("document.querySelector('#chat-timeline .msg-row') && document.querySelector('#cd-shared-body .cd-shared-count')")
    counts = b.js("[...document.querySelectorAll('#cd-shared-body .cd-shared-count')]"
                  ".map((x) => `${x.querySelector('strong').textContent} ${x.querySelector('span').textContent}`)")
    check("Detalles: lo compartido en el chat, con la última foto", counts == ["1 Fotos y vídeos", "1 Documentos", "1 Enlaces", "0 Destacados"]
          and b.js("!!document.querySelector('#cd-shared-body .cd-shared-thumb img')"), counts)
    target = b.js("Number(document.querySelector('#chat-timeline li.msg-row').dataset.id)")
    b.js(f"document.querySelector('#chat-timeline li[data-id=\"{target}\"] [data-star]').click()")
    b.wait(f"!!document.querySelector('#chat-timeline li[data-id=\"{target}\"] .star-mark')")
    check("★ destaca el mensaje (se ve la estrella junto a la hora)", True)
    b.wait("[...document.querySelectorAll('#cd-shared-body .cd-shared-count')].at(-1).textContent.includes('1')")
    check("y cuenta en «Destacados»", True)

    # ---------------------------------------------------------------- Ventana de lo compartido
    b.js("document.querySelector('#cd-shared-body [data-shared-open=\"media\"]').click()")
    b.wait("document.querySelector('#shared-dialog').open && document.querySelector('#shared-body .shared-thumb img')")
    check("fotos y vídeos, agrupados por mes", b.js("!!document.querySelector('#shared-body .shared-month')"))
    b.shot("chat3-03-compartido")
    b.click("#shared-body .shared-thumb")
    b.wait("document.querySelector('#media-viewer').open")
    check("la foto se abre en el visor", True)
    b.js("document.querySelector('#media-viewer').close()")
    b.click('#shared-tabs [data-shared-tab="docs"]')
    check("documentos", "presupuesto.pdf" in b.js("document.querySelector('#shared-body').textContent"))
    b.click('#shared-tabs [data-shared-tab="links"]')
    check("enlaces", "https://hilvana.example/catalogo" in b.js("document.querySelector('#shared-body').textContent"))
    b.click('#shared-tabs [data-shared-tab="starred"]')
    check("destacados", b.js("document.querySelectorAll('#shared-body .starred-item').length") == 1)
    b.click("#shared-body [data-go-message]")
    b.wait(f"!document.querySelector('#shared-dialog').open && document.querySelector('#chat-timeline li[data-id=\"{target}\"]').classList.contains('flash')")
    check("«Ir al mensaje» cierra la ventana y lo resalta en la conversación", True)

    # ---------------------------------------------------------------- Destacados de todos los chats
    b.click("#chats-starred")
    b.wait("document.querySelector('#shared-dialog').open && document.querySelectorAll('#shared-body .starred-item').length === 1")
    check("los destacados de todos los chats, con el nombre del cliente",
          b.js("document.querySelector('#shared-tabs').hidden")
          and "Laura Gómez" in b.js("document.querySelector('#shared-body .starred-head').textContent"))
    b.click("#shared-body [data-unstar]")
    b.wait("document.querySelectorAll('#shared-body .starred-item').length === 0")
    check("y se pueden quitar desde ahí", True)
    b.js("document.querySelector('#shared-dialog').close()")
    b.wait(f"!document.querySelector('#chat-timeline li[data-id=\"{target}\"] .star-mark')")
    check("la conversación deja de mostrarlo destacado", True)
finally:
    b.close()

errors = [e for e in b.errors if "favicon" not in e]
check("sin errores de JavaScript en la consola", not errors, "\n".join(errors))
sys.exit(0 if results["ok"] else 1)
