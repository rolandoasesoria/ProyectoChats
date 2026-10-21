"""Chat al estilo de WhatsApp, fase 2, en el navegador: tarjetas de ubicación y de contacto, el reproductor de notas de
voz (con una grabación real del navegador pasada a Ogg/Opus), la vista previa de un enlace, «Info del mensaje», el menú
de adjuntar con sus diálogos de ubicación y contacto, pegar y arrastrar archivos y grabar una nota de voz con el
micrófono (simulado)."""
import base64
import json
import sys
from datetime import datetime, timedelta

from apitest import BASE, check, results
from browser import Browser

from app import attachments, integrations, voice
from app.db import get_conn
from app.repositories import link_previews
from app.repositories import messages as messages_repo

# Graba 2 s de un tono con MediaRecorder (lo que hace el navegador al grabar una nota de voz) y lo devuelve en base64.
RECORD_TONE = """(async () => {
  const ctx = new AudioContext();
  await Promise.race([ctx.resume(), new Promise((r) => setTimeout(r, 3000))]);
  const osc = ctx.createOscillator(); osc.frequency.value = 440;
  const dest = ctx.createMediaStreamDestination(); osc.connect(dest); osc.start();
  const type = ['audio/ogg;codecs=opus', 'audio/webm;codecs=opus', 'audio/mp4'].find((t) => MediaRecorder.isTypeSupported(t));
  const rec = new MediaRecorder(dest.stream, { mimeType: type });
  const chunks = []; rec.ondataavailable = (e) => chunks.push(e.data);
  const done = new Promise((r) => { rec.onstop = r; });
  rec.start(250); await new Promise((r) => setTimeout(r, 2000)); rec.stop(); await done;
  const buf = new Uint8Array(await new Blob(chunks).arrayBuffer());
  let s = ''; for (const x of buf) s += String.fromCharCode(x);
  return { type: rec.mimeType, data: btoa(s) };
})()"""


def decodes(b, data: bytes) -> dict:
    """¿El navegador entiende el audio? (lo decodifica entero y dice cuánto dura)."""
    return b.js(f"""(async () => {{
      const bin = atob('{base64.b64encode(data).decode()}');
      const bytes = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      try {{ const audio = await new AudioContext().decodeAudioData(bytes.buffer); return {{ ok: true, seconds: audio.duration }}; }}
      catch (e) {{ return {{ ok: false, error: String(e) }}; }}
    }})()""")


PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDK+mmyAAA"
         "AABJRU5ErkJggg==")
GUIDE = "https://hilvana.example/guia-envios"

b = Browser()
try:
    b.goto(BASE + "/login.html")
    # ---------------------------------------------------------------- Una grabación real, pasada a Ogg/Opus
    tone = b.js(RECORD_TONE)
    ogg, ogg_mime = voice.for_sending(base64.b64decode(tone["data"]), tone["type"])
    played = decodes(b, ogg)
    check("una grabación real del navegador pasa a Ogg/Opus y se puede escuchar",
          ogg_mime == "audio/ogg" and ogg[:4] == b"OggS" and played["ok"] and 1.7 < played["seconds"] < 2.4, (tone["type"], played))

    # La conversación de WhatsApp de Laura (cliente 1, por la cuenta de Ana): una ubicación, una tarjeta de contacto y una
    # nota de voz del cliente, y la respuesta de Ana con un enlace (leída), cuya vista previa ya está guardada.
    now = datetime.now()
    at = lambda minutes: (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731
    with get_conn() as conn:
        conv = conn.execute("SELECT id FROM conversations WHERE client_id = 1 AND channel = 'whatsapp'").fetchone()["id"]
        place = messages_repo.insert(conn, conv, "in", "Laura", "📍 Ubicación: Almacén · Calle Mayor 45, Madrid", at(9), "wa:L1",
                                     payload={"type": "location", "latitude": 40.4155, "longitude": -3.7074,
                                              "name": "Almacén", "address": "Calle Mayor 45, Madrid"})
        messages_repo.insert(conn, conv, "in", "Laura", "👤 Contacto: Eva Sanz", at(8), "wa:L2",
                             payload={"type": "contacts", "contacts": [{"name": "Eva Sanz", "phones": ["+34 611 000 999"],
                                                                        "emails": ["eva@sanz.es"], "org": "Transportes Sanz"}]})
        note = messages_repo.insert(conn, conv, "in", "Laura", "🎤 Nota de voz", at(7), "wa:L3", payload={"type": "voice"})
        attachments.save(conn, 1, "nota-de-voz.ogg", ogg, "audio/ogg", note, None)
        link = messages_repo.insert(conn, conv, "out", "Ana Ruiz", f"Aquí tienes la guía: {GUIDE}", at(5), "wa:L4")
        conn.execute("""UPDATE messages SET status = 'read', delivered_at = ?, read_at = ? WHERE id = ?""",
                     (at(4), at(3), link))
        link_previews.put(conn, GUIDE, {"title": "Guía de envíos", "description": "Plazos y horarios de entrega",
                                        "site": "Hilvana", "image": PIXEL})
    integrations.create("whatsapp", "WhatsApp de Ana", 1, {"phone_number_id": "999", "access_token": "EAAG", "app_secret": "s"})

    b.fill("#username", "ana")
    b.fill("#password", "demo1234")
    b.click("#login-btn")
    b.wait("location.pathname === '/' && !!currentUser && !document.body.classList.contains('booting')")
    b.click("#nav-chats")
    b.wait("document.querySelector('#chats-list li[data-client=\"1\"]')")
    b.click('#chats-list li[data-client="1"]')
    b.wait("document.querySelector('#chat-timeline .msg-row')")
    b.js("chatState.channel = 'whatsapp'; setActiveChannelTab(document.querySelector('#chat-tabs'), 'whatsapp'); loadChatConversation()")
    b.wait("document.querySelector('#chat-timeline .place-card') && !document.querySelector('#chat-send').disabled")
    b.js("""window.__sent = []; const realFetch = window.fetch;
            window.fetch = (url, opts = {}) => { window.__sent.push({url: String(url), body: opts.body || null}); return realFetch(url, opts); };""")
    row = lambda mid: f"document.querySelector('#chat-timeline li[data-id=\"{mid}\"]')"  # noqa: E731

    # ---------------------------------------------------------------- Ubicación y contacto recibidos
    card = b.js(f"(() => {{ const li = {row(place)}; const a = li.querySelector('.place-card');"
                " return { text: a.textContent.replace(/\\s+/g, ' ').trim(), href: a.href, body: !!li.querySelector('.bubble-text') }; })()")
    check("la ubicación se ve como tarjeta que abre Google Maps, sin el texto «📍 Ubicación: …»",
          "Almacén" in card["text"] and "Calle Mayor 45" in card["text"] and "query=40.4155,-3.7074" in card["href"]
          and not card["body"], card)
    contact = b.js("document.querySelector('#chat-timeline .contact-card').textContent.replace(/\\s+/g, ' ').trim()")
    check("la tarjeta de contacto muestra nombre, empresa, teléfono y email",
          all(x in contact for x in ("Eva Sanz", "Transportes Sanz", "+34 611 000 999", "eva@sanz.es")), contact)
    check("y sus datos se pueden copiar",
          b.js("document.querySelector('.contact-card-copy').dataset.copy") == "Eva Sanz\nTransportes Sanz\n+34 611 000 999\neva@sanz.es")

    # ---------------------------------------------------------------- Nota de voz
    check("la nota de voz tiene su reproductor (sin el texto «🎤 Nota de voz»)",
          b.js(f"(() => {{ const li = {row(note)}; return !!li.querySelector('.voice-note.is-voice audio') && !li.querySelector('.bubble-text'); }})()"))
    b.wait(f"{row(note)}.querySelector('[data-voice-time]').textContent === '0:02'")
    check("muestra lo que dura", True)
    b.js(f"{row(note)}.querySelector('[data-voice-play]').click()")
    b.wait(f"{row(note)}.querySelector('.voice-note').classList.contains('playing')")
    b.wait(f"{row(note)}.querySelector('audio').currentTime > 0.3")
    check("al pulsar ▶ suena y avanza la barra",
          b.js(f"Number({row(note)}.querySelector('[data-voice-seek]').value) > 0"))
    b.js(f"{row(note)}.querySelector('[data-voice-speed]').click()")
    check("la velocidad cambia a 1,5×", b.js(f"{row(note)}.querySelector('audio').playbackRate") == 1.5
          and b.js(f"{row(note)}.querySelector('[data-voice-speed]').textContent") == "1.5×")
    b.js("loadChatConversation(true)")
    b.pump(0.6)
    check("mientras suena, el refresco no la corta", b.js(f"!{row(note)}.querySelector('audio').paused"))
    b.js(f"{row(note)}.querySelector('[data-voice-play]').click()")
    b.wait(f"!{row(note)}.querySelector('.voice-note').classList.contains('playing')")
    check("y se puede pausar", True)

    # ---------------------------------------------------------------- Vista previa del enlace
    b.wait(f"{row(link)}.querySelector('.link-card')")
    preview = b.js(f"(() => {{ const a = {row(link)}.querySelector('.link-card'); return {{ text: a.textContent, href: a.href, img: !!a.querySelector('img') }}; }})()")
    check("el enlace enviado muestra su vista previa (título, descripción, sitio e imagen)",
          "Guía de envíos" in preview["text"] and "Plazos y horarios" in preview["text"] and preview["href"] == GUIDE
          and preview["img"], preview)

    # ---------------------------------------------------------------- Info del mensaje
    b.js(f"{row(link)}.querySelector('[data-info]').click()")
    b.wait("document.querySelector('#msg-info-dialog').open")
    info = b.js("[...document.querySelectorAll('#msg-info-list .msg-info-row')].map((r) => [r.querySelector('dt').textContent.trim(), r.querySelector('dd').textContent.trim()])")
    labels = [r[0] for r in info]
    check("«Info del mensaje»: leído, entregado y enviado, con la hora de cada uno",
          labels[:3] == ["Leído", "Entregado", "Enviado"] and all(r[1].startswith("Hoy, ") for r in info[:3]), info)
    check("y quién lo envió y por qué cuenta",
          ["Enviado por", "Ana Ruiz"] in info and any(r[0] == "Canal" and "WhatsApp" in r[1] for r in info), info)
    check("con el mensaje tal cual arriba", "Aquí tienes la guía" in b.js("document.querySelector('#msg-info-preview').textContent"))
    b.shot("chat2-01-info")
    b.js("document.querySelector('#msg-info-dialog').close()")
    check("en un mensaje del cliente también hay «Info del mensaje»", b.js(f"!!{row(place)}.querySelector('[data-info]')"))

    # ---------------------------------------------------------------- Menú de adjuntar · Ubicación
    b.click("#chat-attach")
    check("adjuntar abre el menú: documento, ubicación y contacto",
          b.js("!document.querySelector('#attach-menu').hidden && [...document.querySelectorAll('#attach-menu .attach-item')].filter((x) => !x.hidden).length") == 3)
    b.shot("chat2-02-adjuntar")
    coords = b.js("""[parseCoords('40.4168, -3.7038'), parseCoords('40,4168 -3,7038'),
                      parseCoords('https://www.google.com/maps/place/Sol/@40.4168,-3.7038,17z/data=x'),
                      parseCoords('https://maps.google.com/?q=40.4168,-3.7038'), parseCoords('Calle Mayor'), parseCoords('95, 10')]""")
    check("se entienden coordenadas y enlaces de Google Maps (y no direcciones ni valores imposibles)",
          coords[:4] == [{"latitude": 40.4168, "longitude": -3.7038}] * 4 and coords[4:] == [None, None], coords)
    b.click("#attach-location")
    b.wait("document.querySelector('#location-dialog').open && document.querySelector('#attach-menu').hidden")
    b.click("#location-submit")
    check("sin coordenadas no se envía y se explica",
          not b.js("document.querySelector('#location-error').hidden") and not any("/send-location" in r["url"] for r in b.js("window.__sent")))
    b.send("Browser.grantPermissions", permissions=["geolocation"], origin=BASE)
    b.send("Emulation.setGeolocationOverride", latitude=40.41689, longitude=-3.70358, accuracy=20)
    b.click("#location-here")
    b.wait("document.querySelector('#location-coords').value === '40.416890, -3.703580'")
    check("«Usar mi ubicación actual» rellena las coordenadas (y la precisión)",
          "±20 m" in b.js("document.querySelector('#location-status').textContent")
          and not b.js("document.querySelector('#location-map').hidden"))
    b.fill("#location-name", "Oficina")
    b.click("#location-submit")
    b.wait("window.__sent.some((r) => r.url.endsWith('/send-location'))")
    body = json.loads(b.js("window.__sent.find((r) => r.url.endsWith('/send-location')).body"))
    check("se envía la ubicación con su nombre", body == {"latitude": 40.41689, "longitude": -3.70358, "name": "Oficina", "address": ""}, body)
    b.wait("!document.querySelector('#location-error').hidden")
    check("si WhatsApp no la acepta, el diálogo sigue abierto con el motivo",
          b.js("document.querySelector('#location-dialog').open")
          and "No se pudo enviar" in b.js("document.querySelector('#location-error').textContent"))
    b.js("document.querySelector('#location-dialog').close()")

    # ---------------------------------------------------------------- Contacto
    b.click("#chat-attach")
    b.click("#attach-contact")
    b.wait("document.querySelector('#contact-dialog').open")
    b.fill("#contact-search", "Laura")
    b.wait("document.querySelector('#contact-results [data-pick-contact]')")
    b.click("#contact-results [data-pick-contact]")
    check("se elige un contacto de Contactos y se rellena (con el teléfono en formato internacional)",
          b.js("[document.querySelector('#contact-name').value, document.querySelector('#contact-phone').value]")
          == ["Laura Gómez", "+34600111222"])
    b.fill("#contact-phone", "12")
    b.click("#contact-submit")
    check("con un teléfono que no lo es, no se envía",
          "teléfono válido" in b.js("document.querySelector('#contact-error').textContent"))
    b.fill("#contact-phone", "+34600111222")
    b.click("#contact-submit")
    b.wait("window.__sent.some((r) => r.url.endsWith('/send-contact'))")
    body = json.loads(b.js("window.__sent.find((r) => r.url.endsWith('/send-contact')).body"))
    check("se envía el contacto (con su email de Contactos)",
          body == {"name": "Laura Gómez", "phone": "+34600111222", "email": "laura@floristeriagomez.es"}, body)
    b.js("document.querySelector('#contact-dialog').close()")

    # ---------------------------------------------------------------- Pegar y arrastrar archivos
    b.js("""(() => { const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array([137, 80, 78, 71])], 'image.png', {type: 'image/png'}));
            document.querySelector('#chat-text').dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true})); })()""")
    check("pegar una captura la adjunta (con la fecha en el nombre y su miniatura)",
          b.js("chatState.file?.name.startsWith('captura-') && !!document.querySelector('#chat-file-chip .chip-thumb')"))
    b.click("#chat-file-remove")
    b.js("""window.__drag = new DataTransfer(); window.__drag.items.add(new File(['hola'], 'factura.pdf', {type: 'application/pdf'}));
            document.querySelector('#chat-timeline').dispatchEvent(new DragEvent('dragenter', {dataTransfer: window.__drag, bubbles: true, cancelable: true}))""")
    check("al arrastrar un archivo sobre la conversación se ve dónde soltarlo",
          b.js("!document.querySelector('#chat-drop').hidden && !document.querySelector('#chat-drop').classList.contains('blocked')"))
    b.shot("chat2-03-arrastrar")
    b.js("document.querySelector('#chat-timeline').dispatchEvent(new DragEvent('drop', {dataTransfer: window.__drag, bubbles: true, cancelable: true}))")
    check("y al soltarlo queda adjunto", b.js("chatState.file?.name === 'factura.pdf' && document.querySelector('#chat-drop').hidden"))
    b.click("#chat-file-remove")

    # ---------------------------------------------------------------- Grabar una nota de voz (micrófono simulado)
    b.click("#chat-voice")
    b.wait("!document.querySelector('#voice-bar').hidden && document.querySelector('#chat-composer').classList.contains('recording')")
    b.wait("document.querySelector('#voice-time').textContent === '0:01'")
    check("al grabar se ve la barra con el tiempo (y no la caja de escribir)",
          not b.js("document.querySelector('#chat-text').offsetParent"))
    b.click("#voice-cancel")
    check("descartar no envía nada", b.js("document.querySelector('#voice-bar').hidden")
          and not any("/send-voice" in r["url"] for r in b.js("window.__sent")))
    b.click("#chat-voice")
    b.wait("document.querySelector('#voice-time').textContent === '0:02'")
    b.shot("chat2-04-grabando")
    b.click("#voice-send")
    b.wait("window.__sent.some((r) => r.url.endsWith('/send-voice'))", timeout=15)
    sent = json.loads(b.js("window.__sent.find((r) => r.url.endsWith('/send-voice')).body"))
    recorded = base64.b64decode(sent["data"])
    converted, mime = voice.for_sending(recorded, sent["mime"])
    played = decodes(b, converted)
    check("se envía la grabación, con lo que dura, y pasa a una nota de voz que se escucha",
          sent["seconds"] in (2, 3) and mime == "audio/ogg" and played["ok"] and played["seconds"] > 1.5,
          (sent["mime"], sent["seconds"], len(recorded), played))
    # Meta no está: el envío falla y se avisa; el micrófono vuelve a estar disponible
    b.wait("!document.querySelector('#chat-voice').disabled && !document.querySelector('#chat-voice').classList.contains('sending')", timeout=15)
    check("si no se puede enviar, se avisa", "No se pudo enviar" in b.js("document.querySelector('.toasts')?.textContent || ''"))
    b.js("document.querySelectorAll('.toast').forEach((t) => t.click())")

    # Al cambiar de chat mientras se graba, la grabación se descarta
    b.click("#chat-voice")
    b.wait("!document.querySelector('#voice-bar').hidden")
    b.js("window.__sent = []")
    b.js("[...document.querySelectorAll('#chats-list li[data-client]')].find((li) => li.dataset.client !== '1').click()")
    b.wait("document.querySelector('#voice-bar').hidden && chatState.clientId !== 1")
    check("al cambiar de chat, la nota de voz a medias se descarta (no se envía sola)",
          not any("/send-voice" in r["url"] for r in b.js("window.__sent")))

finally:
    b.close()

# Meta no está (las pruebas no llaman a servicios reales): enviar falla con 502, como es de esperar.
errors = [e for e in b.errors if "favicon" not in e and "status of 502" not in e]
check("sin errores de JavaScript en la consola", not errors, "\n".join(errors))
sys.exit(0 if results["ok"] else 1)
