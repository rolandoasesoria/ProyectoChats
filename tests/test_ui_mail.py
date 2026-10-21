"""Correo en bandejas en el navegador: la sección Correo con sus carpetas, la lista (sin leer en negrita), el correo
abierto con su hilo, responder, destacar, buscar, «Ver en el chat», «Ver como bandeja» desde la pestaña Email de un
chat y escribir un correo nuevo."""
import json
import sys
from datetime import datetime, timedelta

from apitest import BASE, check, results
from browser import Browser

from app import attachments, integrations
from app.db import get_conn

# Una clienta de Carlos con un hilo de correo: su pregunta (con un PDF), la respuesta de Carlos y otra pregunta.
integrations.create("email", "Correo de Carlos", 2, {"address": "carlos@miempresa.com", "password": "x",
                                                     "imap_host": "imap.x", "smtp_host": "smtp.x"})
now = datetime.now()
at = lambda minutes: (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731


def rosa_email(body, minutes, direction="in", sender="Rosa Gil"):
    return integrations.ingest({"kind": "email", "owner_user_id": 2}, handle="rosa@cliente.es", client_name="Rosa Gil",
                               direction=direction, sender=sender, body=body, sent_at=at(minutes), external_id=None,
                               subject="Presupuesto de cajas")


first = rosa_email("Hola Carlos, ¿me mandáis el presupuesto de las cajas?", 30)
rosa_email("Te lo preparo hoy mismo.", 20, "out", "Carlos Pérez")
rosa_email("Perdona, ¿y el plazo de entrega?", 10)
rosa = first["client_id"]
with get_conn() as conn:
    question = conn.execute("SELECT id FROM messages WHERE conversation_id = ? ORDER BY sent_at LIMIT 1",
                            (first["conversation_id"],)).fetchone()["id"]
    attachments.save(conn, rosa, "medidas.pdf", b"%PDF-1.4 medidas", "application/pdf", question, None)
    latest = conn.execute("SELECT id FROM messages WHERE conversation_id = ? ORDER BY sent_at DESC LIMIT 1",
                          (first["conversation_id"],)).fetchone()["id"]

b = Browser()
try:
    b.goto(BASE + "/login.html")
    b.fill("#username", "carlos")
    b.fill("#password", "demo1234")
    b.click("#login-btn")
    b.wait("location.pathname === '/' && !!currentUser && !document.body.classList.contains('booting')")
    b.js("""window.__sent = []; const realFetch = window.fetch;
            window.fetch = (url, opts = {}) => { window.__sent.push({url: String(url), body: opts.body || null}); return realFetch(url, opts); };""")
    item = lambda mid: f"document.querySelector('#mail-list [data-mail=\"{mid}\"]')"  # noqa: E731

    # ---------------------------------------------------------------- La sección Correo
    b.click("#nav-mail")
    b.wait(f"!document.querySelector('#view-mail').hidden && {item(latest)}")
    check("Correo: carpetas, lista y lector; abre en Recibidos",
          b.js("document.querySelector('#mail-folders .active').dataset.folder") == "inbox"
          and b.js("!document.querySelector('#mail-empty').hidden"))
    check("los correos nuevos salen sin leer (en negrita) y la carpeta dice cuántos",
          b.js(f"{item(latest)}.classList.contains('is-unread')") and b.js("Number(document.querySelector('#mail-unread').textContent)") >= 2)
    check("cada fila: remitente, asunto y extracto",
          all(x in b.js(f"{item(latest)}.textContent") for x in ("Rosa Gil", "Presupuesto de cajas", "plazo de entrega")))
    b.shot("mail-01-recibidos")

    # ---------------------------------------------------------------- Abrir un correo
    b.click(f'#mail-list [data-mail="{latest}"]')
    b.wait("!document.querySelector('#mail-open').hidden && document.querySelector('#mail-open h2')")
    reader = b.js("document.querySelector('#mail-open').textContent.replace(/\\s+/g, ' ')")
    check("el correo abierto: asunto, de quién (con su dirección) y para quién",
          all(x in reader for x in ("Presupuesto de cajas", "Rosa Gil <rosa@cliente.es>", "Para: Carlos Pérez <carlos@miempresa.com>")), reader)
    check("con el hilo entero (3 correos)", b.js("document.querySelectorAll('#mail-open .mail-thread li').length") == 3)
    check("y queda leído", not b.js(f"{item(latest)}.classList.contains('is-unread')"))
    check("la ruta de navegación lleva la carpeta y el asunto",
          b.js("[...document.querySelectorAll('#breadcrumb .crumb')].map((c) => c.textContent.trim())")[-3:]
          == ["Correo", "Recibidos", "Presupuesto de cajas"])
    b.wait("!document.querySelector('#mail-reply-open').disabled")
    b.shot("mail-02-correo")
    b.click(f'#mail-open [data-mail-open="{question}"]')
    b.wait(f"mailState.openId === {question} && document.querySelector('#mail-open .mail-files')")
    check("desde el hilo se abre otro correo (con su adjunto)", "medidas.pdf" in b.js("document.querySelector('#mail-open .mail-files').textContent"))
    b.click(f'#mail-list [data-mail="{latest}"]')
    b.wait(f"mailState.openId === {latest} && !document.querySelector('#mail-reply-open').disabled")

    # ---------------------------------------------------------------- Responder
    b.click("#mail-reply-open")
    check("«Responder» abre la caja de respuesta", b.js("!document.querySelector('#mail-reply-form').hidden"))
    b.fill("#mail-reply-text", "El plazo es de una semana.")
    b.js("document.querySelector('#mail-reply-form').requestSubmit()")
    b.wait("window.__sent.some((r) => r.url.endsWith('/send'))")
    sent = b.js("window.__sent.find((r) => r.url.endsWith('/send'))")
    check("la respuesta va en el hilo (la conversación del correo)",
          f"/api/conversations/{first['conversation_id']}/send" in sent["url"] and json.loads(sent["body"])["text"] == "El plazo es de una semana.")
    b.pump(1)
    b.js("document.querySelectorAll('.toast').forEach((t) => t.click())")

    # ---------------------------------------------------------------- Destacar y buscar
    b.click("#mail-open [data-mail-star]")
    b.wait("document.querySelector('#mail-open [data-mail-star]').classList.contains('on')")
    b.click('#mail-folders [data-folder="starred"]')
    b.wait(f"document.querySelectorAll('#mail-list [data-mail]').length === 1 && {item(latest)}")
    check("★ lo pone en Destacados", True)
    b.click('#mail-folders [data-folder="inbox"]')
    b.fill("#mail-search", "presupuesto de las cajas")
    b.wait(f"document.querySelectorAll('#mail-list [data-mail]').length === 1 && {item(question)}")
    check("buscar en el correo", True)
    b.fill("#mail-search", "")
    b.wait(f"!!{item(latest)}")
    b.click('#mail-folders [data-folder="sent"]')
    b.wait("[...document.querySelectorAll('#mail-list [data-mail]')].some((li) => li.textContent.includes('Te lo preparo hoy'))")
    check("Enviados: lo respondido, «Para: …»", "Para: Rosa Gil" in b.js("document.querySelector('#mail-list').textContent"))
    b.click('#mail-folders [data-folder="inbox"]')
    b.wait(f"!!{item(latest)}")

    # ---------------------------------------------------------------- De una vista a la otra
    b.click(f'#mail-list [data-mail="{latest}"]')
    b.wait(f"mailState.openId === {latest} && document.querySelector('#mail-open [data-mail-chat]')")
    b.click("#mail-open [data-mail-chat]")
    b.wait(f"currentView() === 'chats' && chatState.clientId === {rosa} && chatState.channel === 'email'"
           f" && document.querySelector('#chat-timeline li[data-id=\"{latest}\"]')")
    check("«Ver en el chat» abre el chat de la clienta en su pestaña Email", True)
    check("y ahí está «Ver como bandeja»", b.js("!document.querySelector('#chat-mail-view').hidden"))
    b.click("#chat-mail-view")
    b.wait("currentView() === 'mail' && !document.querySelector('#mail-client-filter').hidden")
    check("«Ver como bandeja» muestra solo los correos de esa clienta",
          b.js("document.querySelector('#mail-client-name').textContent") == "Rosa Gil"
          and b.js("[...document.querySelectorAll('#mail-list [data-mail]')].every((li) => li.textContent.includes('Rosa Gil'))"))
    b.click("#mail-client-clear")
    b.wait("document.querySelector('#mail-client-filter').hidden")

    # ---------------------------------------------------------------- Correo nuevo
    b.click("#mail-compose")
    b.wait("document.querySelector('#mail-new-dialog').open")
    b.click("#mail-new-send")
    check("sin destinatario no se envía", "Elige a quién va" in b.js("document.querySelector('#mail-new-error').textContent"))
    b.fill("#mail-new-to", "rosa@cliente")
    b.wait("document.querySelector('#mail-new-results [data-pick-recipient]')")
    b.click("#mail-new-results [data-pick-recipient]")
    check("se elige el cliente y su dirección", b.js("document.querySelector('#mail-new-to').value") == "Rosa Gil <rosa@cliente.es>")
    b.fill("#mail-new-subject", "Factura de octubre")
    b.fill("#mail-new-text", "Te adjunto la factura.")
    b.click("#mail-new-send")
    b.wait("window.__sent.some((r) => r.url.endsWith('/emails'))")
    sent = b.js("window.__sent.find((r) => r.url.endsWith('/emails'))")
    check("el correo nuevo va al cliente, con asunto y a esa dirección",
          sent["url"].endswith(f"/api/clients/{rosa}/emails")
          and json.loads(sent["body"]) == {"subject": "Factura de octubre", "text": "Te adjunto la factura.", "to": "rosa@cliente.es"})
    b.wait("!document.querySelector('#mail-new-error').hidden")
    check("si no se puede enviar, se explica sin cerrar la ventana", b.js("document.querySelector('#mail-new-dialog').open"))
    b.js("document.querySelector('#mail-new-dialog').close()")
finally:
    b.close()

# El correo de pruebas no sale a internet (smtp.x no existe): enviar falla, como es de esperar.
errors = [e for e in b.errors if "favicon" not in e and "status of 502" not in e and "status of 400" not in e]
check("sin errores de JavaScript en la consola", not errors, "\n".join(errors))
sys.exit(0 if results["ok"] else 1)
