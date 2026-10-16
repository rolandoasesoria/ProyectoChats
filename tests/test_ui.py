"""Recorrido de la interfaz en Edge: login, tutorial, cliente, pestañas, notas, tareas, diálogos, tema, Chispa."""
import sys

from apitest import BASE, check, results
from browser import Browser
from testdb import TMP

from app.db import get_conn

# Jorge Martín (cliente 2) con un análisis de la IA que lo marca como urgente y molesto.
with get_conn() as conn:
    conn.execute("""INSERT INTO client_analysis (client_id, summary, last_message_id, priority, mood, priority_reason)
                    VALUES (2, 'Pide etiquetas resistentes a aceite.', 0, 'alta', 'molesto', 'Espera respuesta desde hace días')""")
    # Un mensaje antiguo de Laura (cliente 1) con su IBAN, para ocultarlo desde la ficha.
    conn.execute("""INSERT INTO messages (conversation_id, direction, sender, body, sent_at)
                    SELECT id, 'in', 'Laura', ?, '2026-07-01T10:00:00' FROM conversations WHERE client_id = 1 ORDER BY id LIMIT 1""",
                 ("Para domiciliar: ES91 2100 0418 4502 0005 1332",))

b = Browser()
try:
    # Sin sesión: redirige al login
    b.goto(BASE + "/")
    b.wait("location.pathname === '/login.html'")
    check("sin sesión redirige al login", True)
    b.shot("01-login")

    b.fill("#username", "ana")
    b.fill("#password", "mala")
    b.click("#login-btn")
    b.wait("!document.querySelector('#login-error').hidden")
    check("contraseña incorrecta muestra error", "incorrectos" in b.js("document.querySelector('#login-error').textContent"))

    b.fill("#password", "demo1234")
    b.click("#login-btn")
    b.wait("location.pathname === '/' && document.querySelector('.tour-card')")
    check("login correcto y arranca el tutorial", True)
    b.shot("02-tour-inicio")

    # Recorre el tutorial entero
    steps = b.js("document.querySelector('.tour-progress').textContent.split('/')[1].trim()")
    for i in range(int(steps) - 1):
        b.click('.tour-card [data-tour="next"]')
        if i in (1, 4, 7):
            b.shot(f"03-tour-paso-{i + 2}")
    check(f"tutorial de {steps} pasos (admin)", int(steps) == 19, steps)
    b.click('.tour-card [data-tour="next"]')
    b.wait("!document.querySelector('.tour-card')")
    check("tutorial se cierra al terminar", True)

    # Sección Chats: lista, conversación por canal y detalles del contacto
    b.click("#nav-chats")
    b.wait("document.querySelectorAll('#chats-list li[data-client]').length > 0")
    check("chats: la lista con el último mensaje", b.js("!!document.querySelector('#chats-list .chat-preview').textContent"))
    b.js("document.querySelector('#chats-list li[data-client]').click()")
    b.wait("!document.querySelector('#chat-open').hidden && document.querySelectorAll('#chat-timeline .msg-row').length > 0")
    check("chats: pestañas por canal", b.js("document.querySelectorAll('#chat-tabs [data-channel]').length") >= 1)
    check("chats: detalles del contacto", b.js("!document.querySelector('#chat-details').hidden"))
    cw = lambda sel: b.js(f"Math.round(document.querySelector('{sel}').getBoundingClientRect().width)")  # noqa: E731
    list_w, det_w = cw(".chats-pane"), cw("#chat-details")
    b.js("document.querySelector('#view-chats > .resizer[data-zone=\"list\"]').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight'}))")
    b.js("document.querySelector('#view-chats > .resizer[data-zone=\"details\"]').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft'}))")
    check("chats: las columnas se ensanchan con sus separadores",
          (cw(".chats-pane"), cw("#chat-details")) == (list_w + 16, det_w + 16), (list_w, det_w, cw(".chats-pane"), cw("#chat-details")))
    for zone in ("list", "details"):
        b.js(f"document.querySelector('#view-chats > .resizer[data-zone=\"{zone}\"]').dispatchEvent(new MouseEvent('dblclick'))")
    check("chats: doble clic vuelve al ancho inicial", (cw(".chats-pane"), cw("#chat-details")) == (list_w, det_w))
    b.click('#chat-details-tabs [data-pane="assistant"]')
    b.wait("!document.querySelector('#chats-assistant').hidden && !!document.querySelector('#chats-assistant-log .thread:not([hidden])')")
    check("chats: pestaña del asistente IA del contacto", b.js("document.querySelector('#chat-details-body').hidden"))
    check("chats: es el mismo asistente que el de la ficha (mismo hilo, mismo diseño)",
          b.js("state.threads.get(chatState.clientId).el.parentElement.id === 'chats-assistant-log'"
               " && document.querySelector('#chats-assistant').matches('.panel.chat')"
               " && document.querySelector('#chats-assistant-context').textContent.startsWith('Conversación sobre')"))
    b.pump(1)
    b.shot("04-chats-asistente")
    b.click('#chat-details-tabs [data-pane="info"]')
    check("chats: y se vuelve a los detalles", b.js("!document.querySelector('#chat-details-body').hidden"))
    b.pump(1)
    check("chats: sin cuenta conectada no se puede adjuntar", b.js("document.querySelector('#chat-file').disabled"))
    b.js("setChatFile(new File(['hola'], 'presupuesto.pdf', {type: 'application/pdf'}))")
    check("chats: el archivo elegido se ve sobre la caja de escribir",
          "presupuesto.pdf" in b.js("document.querySelector('#chat-file-chip').textContent")
          and not b.js("document.querySelector('#chat-file-chip').hidden"))
    b.click("#chat-file-remove")
    check("chats: y se puede quitar", b.js("document.querySelector('#chat-file-chip').hidden && chatState.file === null"))
    # Correo nuevo (pestaña Email del chat de Jorge)
    b.js("[...document.querySelectorAll('#chats-list li[data-client]')].find((li) => li.textContent.includes('Jorge')).click()")
    b.wait("chatState.channel === 'email' && !document.querySelector('#chat-new-email').hidden")
    b.click("#chat-new-email")
    check("correo nuevo: aparece el asunto", not b.js("document.querySelector('#chat-subject').hidden")
          and b.js("document.querySelector('#chat-send').textContent") == "Enviar correo")
    b.shot("04i-correo-nuevo")
    b.click("#chat-new-email")
    b.wait("document.querySelector('#chat-subject').hidden")
    check("correo nuevo: «Responder en el hilo» vuelve a la respuesta normal", True)
    b.js("[...document.querySelectorAll('#chats-list li[data-client]')].find((li) => li.textContent.includes('Laura')).click()")
    b.wait("document.querySelector('#chat-name').textContent === 'Laura Gómez' && !!document.querySelector('#chat-tabs [data-channel=\"whatsapp\"]')")
    check("correo nuevo: con email pero sin hilos de correo propios, sale igualmente la pestaña Email",
          b.js("!!document.querySelector('#chat-tabs [data-channel=\"email\"]')"))
    b.js("document.querySelector('#chat-tabs [data-channel=\"whatsapp\"]').click()")
    b.wait("chatState.channel === 'whatsapp'")
    b.pump(0.8)
    check("correo nuevo: al volver a WhatsApp el botón ya no dice «Enviar correo»",
          b.js("document.querySelector('#chat-send').textContent") != "Enviar correo"
          and b.js("document.querySelector('#chat-subject').hidden"))
    first_tab = b.js("document.querySelector('#chat-tabs .active').dataset.channel")
    check("chats: cada pestaña muestra solo su canal",
          b.js(f"[...document.querySelectorAll('#chat-timeline .msg-row')].every((r) => r.classList.contains('{first_tab}'))"))
    one = b.js("document.querySelectorAll('#chat-timeline .msg-row').length")
    b.click('#chat-tabs [data-channel=""]')
    b.wait("chatState.channel === '' && document.querySelectorAll('#chat-timeline .msg-row').length > 0")
    b.pump(0.8)
    check("chats: «Todos los canales» junta los mensajes de todos los canales",
          b.js("document.querySelectorAll('#chat-timeline .msg-row').length") >= one)
    check("y se responde por el canal más reciente", b.js("replyChannel() === chatState.channels[0]"))
    b.shot("04a2-chats-todos")
    b.click(f'#chat-tabs [data-channel="{first_tab}"]')
    b.wait(f"chatState.channel === '{first_tab}'")
    b.click('#chats-filter [data-unread="true"]')
    b.pump(0.6)
    check("chats: filtro «No leídos»", b.js("document.querySelector('#chats-filter .active').dataset.unread") == "true")
    b.click('#chats-filter [data-unread="false"]')
    b.shot("04a-chats")
    b.click('#chat-details-tabs [data-pane="assistant"]')
    b.wait("state.threads.get(chatState.clientId)?.el.parentElement.id === 'chats-assistant-log'")
    b.click("#chat-open-client")
    b.wait("!document.querySelector('.layout').hidden && !document.querySelector('.detail-body').hidden")
    check("chats: «Abrir ficha» lleva a la ficha del contacto", True)
    check("y su asistente es la misma conversación, de vuelta en la ficha",
          b.js("const t = state.threads.get(state.clientId); t.el.parentElement.id === 'chat-log' && !t.el.hidden"))
    b.js("showView('chats')")
    b.click('#chat-details-tabs [data-pane="info"]')
    b.js("showView('client')")

    # Sección Contactos: tabla, columnas, filtros y abrir la ficha
    b.click("#nav-contacts")
    b.wait("document.querySelectorAll('#contacts-body tr[data-client]').length === 3")
    check("contactos: la tabla con los 3 contactos", True)
    check("contactos: Contactos activo en la barra", b.js("document.querySelector('#nav-contacts').classList.contains('active')"))
    b.click("#contacts-columns-btn")
    b.js("const e = document.querySelector('#contacts-columns [data-column=\"company\"]'); e.checked = true;"
         "e.dispatchEvent(new Event('change', {bubbles: true}))")
    b.wait("[...document.querySelectorAll('#contacts-head th')].some((th) => th.textContent === 'Empresa')")
    check("contactos: elegir columnas (Empresa)", True)
    b.js("document.body.click()")
    b.js("{ const s = document.querySelector('#contacts-channel'); s.value = 'telegram'; s.dispatchEvent(new Event('change')); }")
    b.wait("document.querySelectorAll('#contacts-body tr[data-client]').length === 2")
    check("contactos: filtro por canal (Telegram)", True)
    b.js("{ const s = document.querySelector('#contacts-channel'); s.value = ''; s.dispatchEvent(new Event('change')); }")
    b.wait("document.querySelectorAll('#contacts-body tr[data-client]').length === 3")
    # Un contacto con cinco emails (como los que deja el spam de varias direcciones de una misma empresa)
    b.js("api('/api/contacts').then((cs) => { cs[0].emails = ['ventas@kinzeno.es', 'info@kinzeno.es', 'pagos@kinzeno.es',"
         " 'soporte@kinzeno.es', 'direccion.general.y.administracion@kinzeno.es']; renderContacts(cs); })")
    check("contactos: las filas no crecen con muchos valores (una línea por fila)",
          b.js("[...document.querySelectorAll('#contacts-body tr[data-client]')].every((tr) => tr.offsetHeight < 60)"))
    b.js("document.querySelector('#contacts-body details.cell-more summary').click()")
    b.pump(0.3)
    b.shot("04b2-contactos-desplegable")
    check("contactos: «+N» despliega el resto sin abrir la ficha",
          b.js("!!document.querySelector('#contacts-body details.cell-more[open]') && !document.querySelector('#view-contacts').hidden"))
    b.js("document.querySelector('#contacts-search').click()")
    check("y se cierra al pulsar fuera", b.js("!document.querySelector('#contacts-body details.cell-more[open]')"))
    b.shot("04b-contactos")
    b.js("document.querySelector('#contacts-body tr[data-client]').click()")
    b.wait("!document.querySelector('.layout').hidden && !document.querySelector('.detail-body').hidden")
    check("contactos: al pulsar uno se abre su ficha", b.js("document.querySelector('#nav-contacts').classList.contains('active')"))

    # Sección Plantillas: sin cuenta de WhatsApp conectada explica qué hacer
    b.click("#nav-templates")
    b.wait("document.querySelector('#tpl-list').textContent.includes('Conecta una cuenta de WhatsApp')")
    check("plantillas: sin cuenta de WhatsApp lo explica y no deja crear", b.js("document.querySelector('#tpl-new').disabled"))
    b.shot("04c-plantillas")
    # Con plantillas (datos de ejemplo cargados en la página: las pruebas no llegan a Meta)
    b.js("""tplState.account = {id: 1, label: 'Prueba', base: '/api/me/integrations'};
            tplState.items = [{name: 'cita', status: 'APPROVED', category: 'UTILITY', language: 'es',
                               body: 'Hola {{1}}, te esperamos el {{2}}.'},
                              {name: 'oferta_otono', status: 'PENDING', category: 'MARKETING', language: 'es',
                               body: 'Este otoño, 10 % en todos los servicios.'}];
            renderTemplateList(); selectTemplate('cita', 'es');""")
    check("plantillas: lista con estado y vista previa de la elegida",
          b.js("document.querySelectorAll('#tpl-list li[data-name]').length") == 2
          and b.js("document.querySelector('#tpl-detail .tpl-var').textContent") == "{{1}}")
    b.shot("04d-plantilla")
    b.js("document.querySelector('#tpl-new').disabled = false")  # sin cuenta real está desactivado
    b.click("#tpl-new")
    b.wait("!document.querySelector('#tpl-form').hidden")
    b.fill("#tpl-body", "Hola {{1}}, tu cita es el {{2}}.")
    b.js("{ const i = document.querySelector('#tpl-examples input'); i.value = 'Laura';"
         "i.dispatchEvent(new Event('input', {bubbles: true})); }")
    check("plantillas: el editor pide un ejemplo por variable y lo muestra en la vista previa",
          b.js("document.querySelectorAll('#tpl-examples input').length") == 2
          and "Laura" in b.js("document.querySelector('#tpl-preview').textContent"))
    b.shot("04e-plantilla-nueva")
    b.js("""tplSendItems = [{name: 'cita', language: 'es', body: 'Hola {{1}}, te esperamos el {{2}}.', variables: 2}];
            chatState.data = {name: 'Laura Gómez'}; document.querySelector('#tpl-send-dialog').showModal();
            document.querySelector('#tpl-send-select').innerHTML = '<option value="0">cita · es</option>';
            renderTemplateSendVars();""")
    check("enviar plantilla: propone el nombre del cliente en {{1}}",
          b.js("document.querySelector('#tpl-send-vars input').value") == "Laura"
          and "Hola Laura" in b.js("document.querySelector('#tpl-send-preview').textContent"))
    b.shot("04f-enviar-plantilla")
    b.js("document.querySelector('#tpl-send-dialog').close(); chatState.data = null;")

    # Sección IA: configurarla y activarla (después se desactiva para no afectar al resto)
    b.click("#nav-ai")
    b.wait("document.querySelector('#ai-mode .active') !== null")
    check("IA: desactivada y supervisada por defecto",
          not b.js("document.querySelector('#ai-enabled').checked")
          and b.js("document.querySelector('#ai-mode .active').dataset.mode") == "supervised")
    b.js("document.querySelector('#ai-enabled').click()")
    b.wait("!document.querySelector('#ai-error').hidden")
    check("IA: no se activa sin instrucciones", not b.js("document.querySelector('#ai-enabled').checked"))
    b.fill("#ai-instructions", "Somos una floristería en Madrid. Envíos en 24 h.")
    b.click('#ai-inactivity [data-hours="24"]')
    b.js("document.querySelector('#ai-enabled').checked = true; document.querySelector('#ai-form').requestSubmit()")
    b.wait("!document.querySelector('#ai-saved').hidden")
    check("IA: activada con instrucciones e inactividad de 24 h",
          b.js("fetch('/api/ai-reply/settings').then((r) => r.json()).then((s) => s.enabled && s.inactivity_hours === 24)",
               await_promise=True))
    b.fill("#ai-test-message", "¿Hacéis envíos?")
    b.click("#ai-test-btn")
    b.wait("document.querySelector('#ai-test-result .form-error') !== null")
    check("IA: probarla sin clave de Claude lo explica",
          "ANTHROPIC_API_KEY" in b.js("document.querySelector('#ai-test-result').textContent"))
    b.shot("04g-ia")
    b.js("document.querySelector('#ai-enabled').click()")
    b.wait("fetch('/api/ai-reply/settings').then((r) => r.json()).then((s) => !s.enabled)")
    # Cómo se ve en el chat una propuesta de la IA (cargada en la página: sin cuenta de WhatsApp real no hay propuestas)
    b.click("#nav-chats")
    b.wait("document.querySelectorAll('#chats-list li[data-client]').length > 0")
    b.js("document.querySelector('#chats-list li[data-client]').click()")
    b.wait("!document.querySelector('#chat-open').hidden")
    b.pump(1.5)  # que termine de consultar el estado de la IA del chat (sin propuesta real, la ocultaría)
    b.js("""{ const t = document.querySelector('#chat-ai-toggle'); t.hidden = false; t.textContent = '🤖 IA activa';
            document.querySelector('#chat-ai-text').value = '¡Hola Laura! Sí, enviamos a Madrid en 24 h. ¿Te preparo el pedido?';
            document.querySelector('#chat-ai-suggestion').hidden = false; }""")
    check("IA: la propuesta aparece sobre la caja de escribir",
          b.js("document.querySelector('#chat-ai-suggestion').getBoundingClientRect().height") > 60)
    b.shot("04h-ia-propuesta")
    b.js("document.querySelector('#chat-ai-suggestion').hidden = true; document.querySelector('#chat-ai-toggle').hidden = true;")
    b.js("showView('client')")  # lo que sigue es de la ficha del contacto
    b.js("showView('client')")  # lo que sigue (zonas, ficha, pestañas) es de la ficha del contacto

    # Lista de clientes y filtros
    check("3 clientes + consulta general", b.js("document.querySelectorAll('#client-list li[data-id]').length") == 4)
    b.shot("04-inicio")
    check("barra lateral con sus secciones (y Administración para un administrador)",
          b.js("['#dashboard-btn', '#nav-chats', '#menu-accounts', '#menu-replies', '#menu-admin']"
               ".every((s) => { const e = document.querySelector(s); return e && e.closest('.sidebar') && !e.hidden; })"))

    # Zonas ajustables: arrastrar, teclado, doble clic, se recuerda y siempre se ven las tres
    width = lambda sel: b.js(f"Math.round(document.querySelector('{sel}').getBoundingClientRect().width)")  # noqa: E731
    check("anchos iniciales", (width(".clients"), width("#assistant")) == (290, 400), (width(".clients"), width("#assistant")))
    x = b.js("document.querySelector('.resizer[data-zone=\"clients\"]').getBoundingClientRect().left")
    for kind, px in (("mousePressed", x), ("mouseMoved", x + 60), ("mouseReleased", x + 60)):
        b.send("Input.dispatchMouseEvent", type=kind, x=px, y=400, button="left", buttons=1 if kind != "mouseReleased" else 0,
               clickCount=1)
    b.pump(0.3)
    check("arrastrar el separador ensancha la lista de clientes", width(".clients") == 350, width(".clients"))
    b.js("document.querySelector('.resizer[data-zone=\"chat\"]').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft'}))")
    check("con el teclado: flecha izquierda ensancha el asistente", width("#assistant") == 416, width("#assistant"))
    b.js("document.querySelector('.resizer[data-zone=\"chat\"]').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight'}))")
    b.js("document.querySelector('.resizer[data-zone=\"chat\"]').dispatchEvent(new MouseEvent('dblclick'))")
    check("doble clic vuelve al ancho inicial", width("#assistant") == 400, width("#assistant"))
    b.js("document.querySelector('.resizer[data-zone=\"clients\"]').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight'}))")
    b.send("Emulation.setDeviceMetricsOverride", width=1100, height=900, deviceScaleFactor=1, mobile=False)
    b.js("for (let i = 0; i < 40; i++) document.querySelector('.resizer[data-zone=\"chat\"]').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft'}))")
    check("el asistente no crece tanto como para dejar la ficha por debajo de su mínimo", width(".detail") >= 300, width(".detail"))
    b.js("document.querySelector('.resizer[data-zone=\"chat\"]').dispatchEvent(new MouseEvent('dblclick'))")
    b.send("Emulation.setDeviceMetricsOverride", width=1400, height=900, deviceScaleFactor=1, mobile=False)
    b.goto(BASE + "/")
    b.wait("document.querySelectorAll('#client-list li[data-id]').length > 1")
    b.js("showView('client')")  # al recargar se abre la última sección (Contactos): estas zonas son las de la ficha
    check("el ancho elegido se recuerda al recargar", width(".clients") == 366, width(".clients"))
    b.send("Emulation.setDeviceMetricsOverride", width=760, height=900, deviceScaleFactor=1, mobile=False)
    b.pump(0.3)
    visible = b.js("['.clients', '.detail', '#assistant'].map(s => Math.round(document.querySelector(s).getBoundingClientRect().width))")
    check("pantalla estrecha: siguen las tres zonas", all(w >= 150 for w in visible), visible)
    b.shot("04b-estrecha")
    b.send("Emulation.setDeviceMetricsOverride", width=1400, height=900, deviceScaleFactor=1, mobile=False)
    b.js("localStorage.removeItem('pc-layout')")
    b.goto(BASE + "/")
    b.wait("document.querySelectorAll('#client-list li[data-id]').length > 1")
    b.js("showView('client')")  # al recargar se abre la última sección (Contactos): estas zonas son las de la ficha
    check("sin preferencia guardada vuelve a los anchos iniciales", width(".clients") == 290, width(".clients"))

    # Abrir Laura (Carlos la tiene abierta y está respondiendo)
    with get_conn() as conn:
        conn.execute("INSERT INTO presence (user_id, client_id, composing, seen_at) VALUES (2, 1, 1, localtimestamp(0))")
    b.click('#client-list li[data-id="1"]')
    b.wait("document.querySelector('#detail-name').textContent === 'Laura Gómez'")
    b.wait("!document.querySelector('#presence-bar').hidden")
    check("avisa de que un compañero está respondiendo al mismo cliente",
          b.js("document.querySelector('#presence-bar').textContent") == "Carlos Pérez está respondiendo a este cliente")
    b.wait("document.querySelector('#summary-text').textContent.length > 0")
    check("ficha de Laura con estado", b.js("document.querySelector('#detail-status').textContent") == "Activo")
    b.shot("05-ficha")

    # Documentos: se sube un archivo con el selector real (DevTools) y aparece en la lista
    check("sección de documentos vacía al principio", "Sin documentos" in b.js("document.querySelector('#documents').textContent"))
    node = b.send("DOM.getDocument")["root"]["nodeId"]
    inp = b.send("DOM.querySelector", nodeId=node, selector="#doc-upload")["nodeId"]
    sample = str(TMP / "sample.txt")
    (TMP / "sample.txt").write_text("Contrato de suministro 2026", encoding="utf-8")
    b.send("DOM.setFileInputFiles", nodeId=inp, files=[sample])
    b.js("document.querySelector('#doc-upload').dispatchEvent(new Event('change'))")
    b.wait("document.querySelector('#documents').textContent.includes('sample.txt')")
    b.click("#documents [data-show-text]")
    b.wait("document.querySelector('#documents .doc-text:not([hidden])')")
    check("subir documento y ver su texto", "Contrato de suministro" in b.js("document.querySelector('#documents .doc-text').textContent"))

    # Dato manual
    b.fill("#fact-label", "CIF")
    b.fill("#fact-value", "B12345678")
    b.js("document.querySelector('#fact-form').requestSubmit()")
    b.wait("document.querySelector('#facts').textContent.includes('B12345678')")
    check("añadir dato en la ficha", True)

    # Tareas
    b.click('.detail-tabs [data-tab="tasks"]')
    b.fill("#task-title", "Llamar a Laura por el pedido")
    b.js("document.querySelector('#task-due').value = '2020-01-01'")
    b.js("document.querySelector('#task-form').requestSubmit()")
    b.wait("document.querySelector('#client-tasks').textContent.includes('Llamar a Laura')")
    check("crear tarea (vencida en rojo)", b.js("!!document.querySelector('#client-tasks .due.overdue')"))
    b.wait("document.querySelector('#my-tasks-count').textContent === '1'")
    check("contador de mis tareas en rojo", b.js("document.querySelector('#my-tasks-count').classList.contains('alert')"))
    b.click('.side-tabs [data-side="tasks"]')
    b.wait("document.querySelector('#my-tasks .task-title')")
    check("en la columna izquierda la tarea se ve (sin desbordarse)",
          b.js("document.querySelector('#my-tasks .task-title').getBoundingClientRect().width > 80 && "
               "document.querySelector('#side-tasks').scrollWidth <= document.querySelector('#side-tasks').clientWidth"))
    b.click('.side-tabs [data-side="clients"]')
    b.shot("06-tareas")

    # Notas con mención (autocompletado)
    b.click('.detail-tabs [data-tab="notes"]')
    b.js("const t = document.querySelector('#note-body'); t.focus(); t.value = 'Paga tarde, avisar a @car'; "
         "t.selectionStart = t.selectionEnd = t.value.length; t.dispatchEvent(new Event('input'))")
    b.wait("!document.querySelector('#mention-list').hidden")
    check("autocompletado de @menciones", "Carlos Pérez" in b.js("document.querySelector('#mention-list').textContent"))
    b.js("document.querySelector('#note-body').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'}))")
    check("elegir mención completa el nombre", b.js("document.querySelector('#note-body').value").endswith("@Carlos Pérez "))
    b.js("document.querySelector('#note-form').requestSubmit()")
    b.wait("document.querySelector('#notes-list .mention')")
    check("nota guardada con la mención resaltada", True)
    b.shot("07-notas")

    # Mensajes y borrador
    b.click('.detail-tabs [data-tab="messages"]')
    b.wait("document.querySelectorAll('#timeline li').length > 0")
    total = b.js("document.querySelectorAll('#timeline li').length")
    check("por defecto se ve el historial completo, con quién lleva cada conversación",
          b.js("document.querySelectorAll('#timeline .owner-tag').length") > 0)
    b.click("#only-mine")
    b.wait(f"document.querySelectorAll('#timeline li').length < {total}")
    check("«Solo mis conversaciones» oculta las de los compañeros",
          b.js("document.querySelectorAll('#timeline .owner-tag').length") == 0)
    b.click("#only-mine")
    b.wait(f"document.querySelectorAll('#timeline li').length === {total}")
    check("mensajes: pestañas por canal, con «Todos los canales» activa",
          b.js("document.querySelector('#channel-tabs .active').dataset.channel === ''"
               " && document.querySelectorAll('#channel-tabs [data-channel]').length > 2"))
    b.click('#channel-tabs [data-channel="whatsapp"]')
    b.wait(f"document.querySelectorAll('#timeline li').length < {total}")
    check("mensajes: la pestaña de un canal muestra solo ese canal",
          b.js("[...document.querySelectorAll('#timeline .msg-row')].every((r) => r.classList.contains('whatsapp'))"))
    b.shot("09b-mensajes-whatsapp")
    b.click('#channel-tabs [data-channel=""]')
    b.wait(f"document.querySelectorAll('#timeline li').length === {total}")
    b.fill("#msg-search", "direccion")
    b.js("document.querySelector('#msg-search-form').requestSubmit()")
    b.wait("document.querySelector('#msg-results mark')")
    check("buscador de mensajes con resaltado", "dirección" in b.js("document.querySelector('#msg-results mark').textContent"))
    b.shot("08b-buscador")
    b.click("#msg-results .result")
    b.wait("document.querySelector('#timeline li.flash')")
    check("clic en un resultado lleva al mensaje", True)
    b.click("#msg-results-close")
    b.click("#draft-open")
    check("panel de borrador con las conversaciones", b.js("document.querySelectorAll('#draft-conversation option').length") >= 1)
    b.shot("08-mensajes-borrador")
    # Respuestas guardadas: desde el botón y escribiendo /atajo
    b.click("#reply-open")
    b.wait("document.querySelectorAll('#reply-options .reply-option').length >= 4")
    b.fill("#reply-filter", "factur")
    check("el selector filtra las respuestas guardadas", b.js("document.querySelectorAll('#reply-options .reply-option').length") == 1)
    b.shot("08c-respuestas-guardadas")
    b.click("#reply-options .reply-option")
    b.wait("document.querySelector('#draft-text').value.startsWith('Hola Laura, para preparar la factura')")
    check("insertar respuesta guardada rellena el nombre", b.js("document.querySelector('#draft-text').value").endswith("Ana Ruiz"))
    b.fill("#draft-text", "")
    b.fill("#draft-text", "/presu")
    b.wait("!document.querySelector('#reply-suggest').hidden")
    b.js("document.querySelector('#draft-text').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")
    b.wait("document.querySelector('#draft-text').value.startsWith('Hola Laura, te acabo de enviar el presupuesto')")
    b.wait("!document.querySelector('#draft-applied').hidden")
    check("una macro avisa de lo que ha aplicado y actualiza la ficha",
          "Potencial" in b.js("document.querySelector('#draft-applied').textContent")
          and b.js("document.querySelector('#detail-status').textContent") == "Potencial")
    b.js("document.querySelector('#draft-followup').value = '3'")
    b.click("#draft-copy")
    b.wait("document.querySelector('#draft-applied').textContent.includes('Te avisaré')")
    check("al copiar programa el aviso de seguimiento", True)
    b.click("#draft-close")
    b.click("#menu-replies")
    b.wait("document.querySelector('#replies-dialog').open && document.querySelectorAll('#replies-list .reply-row').length >= 4")
    b.fill("#rf-title", "Horario")
    b.fill("#rf-body", "Abrimos de 9 a 14, {nombre}.")
    b.js("document.querySelector('#reply-form').requestSubmit()")
    b.wait("[...document.querySelectorAll('#replies-list .reply-row strong')].some(s => s.textContent === 'Horario')")
    check("crear respuesta guardada desde el diálogo", True)
    b.shot("08d-gestionar-respuestas")
    b.js("document.querySelector('#replies-dialog').close()")

    # Bandeja sin responder
    b.click('.side-tabs [data-side="inbox"]')
    b.wait("document.querySelectorAll('#inbox-list .inbox-item').length > 0")
    check("la bandeja marca la prioridad y el tono que detectó la IA",
          b.js("[...document.querySelectorAll('#inbox-list .inbox-item')].find(li => li.textContent.includes('Jorge Martín'))"
               ".querySelectorAll('.prio-chip').length") == 2)
    check("bandeja sin responder con elementos", b.js("document.querySelectorAll('#inbox-list .inbox-item').length") == 2)
    b.wait("document.querySelector('#inbox-count-team').textContent !== ''")
    check("el selector muestra cuántas hay en cada lado", b.js(
        "document.querySelector('#inbox-count-mine').textContent + '/' + document.querySelector('#inbox-count-team').textContent") == "2/5")
    b.click('#inbox-scope [data-inbox-scope="team"]')
    b.wait("document.querySelectorAll('#inbox-list .inbox-item').length === 5")
    check("con «Todo el equipo» el selector sigue visible",
          b.js("document.querySelector('#inbox-scope').getBoundingClientRect().height") > 20)
    check("cada conversación dice quién la lleva", "La lleva Carlos Pérez" in b.js("document.querySelector('#inbox-list').textContent"))
    b.shot("09b-bandeja-equipo")
    b.click('#inbox-scope [data-inbox-scope="mine"]')
    b.wait("document.querySelectorAll('#inbox-list .inbox-item').length === 2")
    b.js("{ const s = document.querySelector('#inbox-list [data-snooze]'); s.value = 'tomorrow'; s.dispatchEvent(new Event('change', {bubbles: true})); }")
    b.wait("document.querySelector('.inbox-snoozed summary')?.textContent === 'Pospuestas (1)'")
    check("posponer la quita de la bandeja y la deja en «Pospuestas»",
          b.js("document.querySelectorAll('#inbox-list > .inbox-item').length") == 1 and b.js("document.querySelector('#inbox-count').textContent") == "1")
    b.js("document.querySelector('.inbox-snoozed details').open = true")
    b.shot("09c-pospuestas")
    b.click(".inbox-snoozed [data-unsnooze]")
    b.wait("document.querySelectorAll('#inbox-list > .inbox-item').length === 2 && !document.querySelector('.inbox-snoozed')")
    check("«Volver ahora» la devuelve", True)
    b.shot("09-bandeja")
    b.click("#inbox-list .inbox-item strong")
    b.wait("document.querySelector('#timeline li.flash')")
    check("clic en la bandeja lleva al mensaje resaltado", True)

    # Paleta de comandos y atajos
    b.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, bubbles: true}))")
    b.wait("document.querySelector('#palette-dialog').open")
    b.fill("#palette-input", "sofia")
    b.wait("document.querySelector('#palette-list .palette-item.active .palette-label')?.textContent.includes('Sofía Navarro')")
    b.shot("09d-paleta")
    b.js("document.querySelector('#palette-input').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")
    b.wait("!document.querySelector('#palette-dialog').open && document.querySelector('#detail-name').textContent === 'Sofía Navarro'")
    check("Ctrl+K: buscar un cliente y abrirlo con Enter", True)
    b.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, bubbles: true}))")
    b.fill("#palette-input", "sin respon")
    b.wait("document.querySelector('#palette-list .palette-item.active .palette-label')?.textContent === 'Ir a Sin responder'")
    b.click("#palette-list .palette-item.active")
    b.wait("!document.querySelector('#side-inbox').hidden")
    check("la paleta también ejecuta acciones", True)
    b.js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'g', bubbles: true}))")
    b.js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'c', bubbles: true}))")
    b.wait("!document.querySelector('#side-clients').hidden")
    b.js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'j', bubbles: true}))")
    b.wait("document.querySelector('#detail-name').textContent === 'Laura Gómez'")
    check("atajos: g c va a Clientes y j pasa al cliente siguiente", True)
    b.js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: '?', bubbles: true}))")
    b.wait("document.querySelector('#shortcuts-dialog').open")
    check("? muestra los atajos", b.js("document.querySelectorAll('#shortcuts-list tr').length") >= 8)
    b.js("document.querySelector('#shortcuts-dialog').close()")

    # Editar cliente
    b.click('.side-tabs [data-side="clients"]')
    b.click("#edit-client-btn")
    b.wait("document.querySelector('#client-dialog').open")
    b.click("#sensitive-btn")
    b.wait("document.querySelectorAll('#sensitive-list li[data-message]').length === 1")
    check("encuentra el IBAN en sus mensajes", "IBAN" in b.js("document.querySelector('#sensitive-list li').textContent"))
    b.click("#sensitive-list [data-redact]")
    b.wait("document.querySelectorAll('#sensitive-list li[data-message]').length === 0")
    check("ocultarlo lo quita de la ficha", "[IBAN oculto]" in b.js("document.querySelector('#timeline').textContent"))
    b.js("document.querySelector('#cf-status').value = 'issue'")
    # Etiquetas: desplegable con las básicas y las del equipo, y también a mano
    b.js("document.querySelector('#tag-input').focus()")
    b.wait("!document.querySelector('#tag-options').hidden")
    opts = b.js("[...document.querySelectorAll('#tag-options li')].map(li => li.firstElementChild.textContent)")
    check("el desplegable ofrece las etiquetas básicas", {"VIP", "Mayorista", "Paga tarde"} <= set(opts), opts)
    b.js("[...document.querySelectorAll('#tag-options li')].find(li => li.textContent.includes('VIP'))"
         ".dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
    b.fill("#tag-input", "Cliente de feria")
    check("lo escrito que no existe se ofrece para crearlo",
          b.js("document.querySelector('#tag-options li').textContent").strip() == "Crear «Cliente de feria»")
    b.js("document.querySelector('#tag-input').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")
    b.shot("10-editar-cliente")
    check("las elegidas quedan como fichas", b.js("[...document.querySelectorAll('#tag-editor-chips .chip-tag')].map(c => c.firstChild.textContent)")
          == ["presupuesto enviado", "VIP", "Cliente de feria"])
    b.js("document.querySelector('#client-form').requestSubmit()")
    b.wait("!document.querySelector('#client-dialog').open")
    b.wait("document.querySelector('#detail-status').textContent === 'Incidencia'")
    check("estado y etiquetas guardados", all(t in b.js("document.querySelector('#detail-tags').textContent")
                                                for t in ("VIP", "Cliente de feria", "presupuesto enviado")))
    check("el estado puesto en ✎ queda como manual", "puesto a mano por Ana Ruiz" in b.js("document.querySelector('#status-note').textContent"))
    b.click("#detail-status")
    b.wait("!document.querySelector('#status-menu').hidden")
    b.shot("10b-menu-estado")
    b.click('#status-menu [data-status="active"]')
    b.wait("document.querySelector('#detail-status').textContent === 'Activo'")
    check("cambiar el estado desde la cabecera", b.js("document.querySelector('#client-list li[data-id=\"1\"] .status-dot').className") == "status-dot active")
    b.click("#detail-status")
    b.click("#status-menu [data-status-auto]")
    b.wait("document.querySelector('#detail-status').classList.contains('auto') && document.querySelector('#status-note').hidden")
    check("«Que lo decida la IA» quita el estado manual", True)

    # Ya no hay importación de chats: los mensajes llegan por las integraciones
    check("sin botón ni diálogo de importar", b.js("!document.querySelector('#import-btn') && !document.querySelector('#import-dialog')"))

    # Menú, avisos, tema oscuro, Chispa
    b.click("#bell")
    b.shot("12-avisos")
    b.click("#bell")
    before = b.js("effectiveTheme()")
    b.click("#theme-toggle")
    after = b.js("document.documentElement.dataset.theme")
    check(f"el botón de tema cambia de {before} a {after}", after == ("light" if before == "dark" else "dark"))
    if after != "dark":
        b.click("#theme-toggle")
        b.wait("document.documentElement.dataset.theme === 'dark'")
    b.click("#mascot")
    b.wait("!document.querySelector('#help-panel').hidden")
    b.shot("13-oscuro-chispa")
    check("tema oscuro y panel de Chispa", True)

    # Panel de actividad (en oscuro y en claro)
    b.click("#help-close")
    b.click("#dashboard-btn")
    # Los datos de ejemplo tienen fechas fijas (julio a septiembre de 2026): con «1 año» siguen dentro del periodo.
    b.wait("document.querySelector('#dashboard-dialog').open")
    b.click('#dash-range [data-days="365"]')
    b.wait("document.querySelectorAll('#dash-weekly .viz-seg').length > 0")
    b.wait("document.querySelector('#dash-tiles').textContent.includes('14')")  # mensajes recibidos en el año
    check("panel: indicadores y columnas", b.js("document.querySelectorAll('#dash-weekly .viz-seg').length") >= 6)
    check("panel: tabla por persona (admin)", b.js("document.querySelectorAll('#dash-people tbody tr').length") == 3)
    b.js("""(() => { const hit = [...document.querySelectorAll('#dash-weekly .viz-hit')]
              .find((h, i) => document.querySelectorAll('#dash-weekly .viz-hit').length && h.getBoundingClientRect().width);
              const bars = document.querySelectorAll('#dash-weekly .viz-hit'); const target = bars[bars.length - 3];
              const r = target.getBoundingClientRect();
              target.dispatchEvent(new PointerEvent('pointermove', {clientX: r.left + r.width / 2, clientY: r.top + 60, bubbles: true})); })()""")
    check("panel: % respondido en plazo", "Respondidas en plazo (24 h)" in b.js("document.querySelector('#dash-tiles').textContent"))
    check("panel: aviso al pasar el ratón", b.js("!document.querySelector('#viz-tooltip').hidden"))
    b.shot("15-panel-oscuro")
    b.click("#theme-toggle")
    b.js("loadDashboard()")
    b.pump(0.6)
    b.shot("16-panel-claro")
    b.js("document.querySelector('#dashboard-dialog').close()")
    b.click("#nav-chats")
    b.js("document.querySelector('#chats-list li[data-client]').click()")
    b.wait("document.querySelectorAll('#chat-timeline .msg-row').length > 0")
    b.pump(0.6)
    b.shot("16b-chats-claro")

    # Administración
    b.click("#menu-admin")
    b.wait("document.querySelectorAll('#users-tbody tr').length === 3")
    b.shot("14-admin")
    check("administración de usuarios", True)

    # Ajustes: plazo de respuesta
    b.click('[data-admin-tab="settings"]')
    b.wait("document.querySelector('#set-sla').value === '24'")
    check("ruta: sin nombre de empresa, el administrador ve el enlace para ponerlo",
          b.js("!!document.querySelector('#breadcrumb [data-crumb=\"company\"]')"))
    b.fill("#set-company", "  Asesoría   Ocaña ")
    b.fill("#set-sla", "2")
    b.js("document.querySelector('#settings-form').requestSubmit()")
    b.wait("!document.querySelector('#set-saved').hidden")
    check("cambiar el plazo de respuesta", b.js("slaHours") == 2)
    check("nombre de la empresa guardado (sin espacios de sobra)", b.js("companyName") == "Asesoría Ocaña")
    check("el análisis automático con IA aparece activado", b.js("document.querySelector('#set-auto-analysis').checked"))
    b.fill("#set-retention", "1")
    b.wait("document.querySelector('#retention-preview').textContent.includes('se borrarían')")
    check("la retención avisa de cuántos mensajes borraría", True)
    b.shot("14b-ajustes")

    # Propiedades de contacto: crearlas en Administración y rellenarlas en la ficha
    b.click('[data-admin-tab="properties"]')
    b.fill("#prop-label", "DNI")
    b.js("document.querySelector('#prop-form').requestSubmit()")
    b.wait("document.querySelector('#props-admin-list').textContent.includes('DNI')")
    b.js("{ const k = document.querySelector('#prop-kind'); k.value = 'select'; k.dispatchEvent(new Event('change')); }")
    b.fill("#prop-label", "Origen")
    b.fill("#prop-options", "Web, Referido")
    b.js("document.querySelector('#prop-form').requestSubmit()")
    b.wait("document.querySelector('#props-admin-list').textContent.includes('Referido')")
    check("propiedades: crear de texto y de lista", True)
    b.shot("14c-propiedades")

    b.js("document.querySelector('#admin-dialog').close()")
    b.js("selectClient(1)")
    b.wait("document.querySelectorAll('#client-props [data-prop]').length === 2")
    crumbs = lambda: b.js("[...document.querySelectorAll('#breadcrumb .crumb')].map((c) => c.textContent.trim())")  # noqa: E731
    check("ruta en la ficha: Empresa › Contactos › contacto",
          crumbs() == ["Asesoría Ocaña", "Contactos", b.js("state.clientData.name")], crumbs())
    b.shot("19-ruta-ficha")
    b.js("showDetailTab('profile')")
    b.js("{ const i = document.querySelector('#client-props input[data-prop]'); i.value = '12345678Z';"
         "i.dispatchEvent(new Event('change', {bubbles: true})); }")
    b.wait("document.querySelector('#client-props input[data-prop]').classList.contains('saved')")
    check("propiedades: se rellenan en la ficha y se guardan solas",
          b.js("fetch('/api/clients/1/properties').then((r) => r.json())"
               ".then((d) => Object.values(d.values).includes('12345678Z'))", await_promise=True))

    # Varios posibles duplicados (p. ej. el mismo remitente desde varias direcciones): un solo aviso y «Unir todos aquí»
    b.js("Promise.all([1, 2].map(() => api('/api/clients', {method: 'POST', body: JSON.stringify({name: 'Laura Gómez'})})))")
    b.js("selectClient(1)")
    b.wait("document.querySelector('#duplicates [data-merge-all]') !== null")
    check("duplicados: un solo aviso para varios clientes con el mismo nombre",
          b.js("document.querySelectorAll('#duplicates .duplicate').length") == 1
          and "Hay 2 clientes más" in b.js("document.querySelector('#duplicates').textContent"))
    b.click("#duplicates [data-merge-all]")
    b.wait("api('/api/clients?q=Laura').then((cs) => cs.length === 1)")
    check("duplicados: «Unir todos aquí» los une en este cliente", b.js("document.querySelector('#duplicates').hidden"))

    # Mis cuentas: el correo trae los servidores del proveedor y se conecta un bot de Telegram
    b.click("#menu-accounts")
    b.wait("document.querySelector('#accounts-dialog').open && document.querySelectorAll('#if-fields input').length > 0")
    check("el correo se rellena según el proveedor (Gmail)",
          b.js("document.querySelector('#if-fields input[name=\"imap_host\"]').value") == "imap.gmail.com")
    b.js("document.querySelector('#if-provider').value = 'outlook'; document.querySelector('#if-provider').dispatchEvent(new Event('change'))")
    check("y cambia al elegir otro (Outlook)",
          b.js("document.querySelector('#if-fields input[name=\"smtp_host\"]').value") == "smtp.office365.com")
    b.js("document.querySelector('#if-kind').value = 'telegram'; document.querySelector('#if-kind').dispatchEvent(new Event('change'))")
    b.fill("#if-name", "Bot de pruebas")
    b.fill('#if-fields input[name="bot_token"]', "123:ABC")
    b.js("document.querySelector('#integration-form').requestSubmit()")
    b.wait("document.querySelector('#integrations-list').textContent.includes('Bot de pruebas') && !document.querySelector('#if-result').hidden")
    check("conectar una cuenta propia la prueba y avisa si no conecta",
          "no conecta" in b.js("document.querySelector('#if-result').textContent")
          and "No conecta" in b.js("document.querySelector('#integrations-list').textContent"))
    b.shot("17-integraciones")
    b.js("document.querySelector('#accounts-dialog').close()")

    # Un aviso de una cuenta que ha dejado de funcionar abre «Mis cuentas»
    with get_conn() as conn:
        conn.execute("""INSERT INTO notifications (user_id, kind, text) VALUES (1, 'integration_error',
                        'Tu cuenta «WhatsApp» necesita atención: Meta no acepta el access token')""")
    b.js("loadNotifications()")
    b.wait("document.querySelector('#bell-list [data-kind=\"integration_error\"]')")
    b.click("#bell")
    b.click('#bell-list [data-kind="integration_error"]')
    b.wait("document.querySelector('#accounts-dialog').open")
    check("el aviso de una cuenta que no funciona abre «Mis cuentas»", True)
    b.js("document.querySelector('#accounts-dialog').close()")

    # Con la integración de Telegram, el borrador de Laura (Telegram) permite enviar
    b.click('#client-list li[data-id="1"]')
    b.wait("document.querySelector('#detail-name').textContent === 'Laura Gómez'")
    b.click('.detail-tabs [data-tab="messages"]')
    b.click("#draft-open")
    tg_option = b.js("[...document.querySelectorAll('#draft-conversation option')].find(o => o.textContent.startsWith('Telegram')).value")
    b.js(f"document.querySelector('#draft-conversation').value = '{tg_option}'; document.querySelector('#draft-conversation').dispatchEvent(new Event('change'))")
    b.wait("!document.querySelector('#draft-send').hidden")
    check("botón de enviar por la integración", "Bot de pruebas" in b.js("document.querySelector('#draft-send').textContent"))
    b.click("#draft-write")
    check("escribir sin IA abre el cuadro", b.js("!document.querySelector('#draft-text').hidden"))
    b.fill("#draft-text", "hola, te paso el presu")
    b.js("{ const s = document.querySelector('#draft-rewrite'); s.value = 'fix'; s.dispatchEvent(new Event('change')); }")
    b.wait("!document.querySelector('#draft-rewrite').disabled && document.querySelector('#draft-rewrite').value === ''")
    check("retocar sin clave de IA avisa y deja el texto como estaba",
          "ANTHROPIC_API_KEY" in b.dialogs[-1] and b.js("document.querySelector('#draft-text').value") == "hola, te paso el presu"
          and b.js("document.querySelector('#draft-undo').hidden"), b.dialogs[-1:])
    # Ese aviso (y el 503 que lo provoca) era el esperado: no cuenta como error.
    b.errors[:] = [e for e in b.errors if "ANTHROPIC_API_KEY" not in e and "/api/drafts/rewrite" not in e
                   and "/api/admin/ai-reply" not in e]
    b.shot("18-enviar")

    # Ruta de navegación: cada sección, lo abierto como tercer nivel y volver pulsando la sección
    b.click('#breadcrumb [data-crumb="section"]')
    b.wait("!document.querySelector('#view-contacts').hidden")
    check("ruta: pulsar «Contactos» vuelve a la tabla", crumbs() == ["Asesoría Ocaña", "Contactos"], crumbs())
    b.js("showView('chats')")
    b.wait("document.querySelectorAll('#chats-list li[data-client]').length > 0")
    b.js("document.querySelector('#chats-list li[data-client]').click()")
    b.wait("!!chatState.data && document.querySelectorAll('#breadcrumb .crumb').length === 3")
    check("ruta en Mis Chats con un chat abierto", crumbs() == ["Asesoría Ocaña", "Mis Chats", b.js("chatState.data.name")], crumbs())
    b.shot("19b-ruta-chats")
    b.click('#breadcrumb [data-crumb="section"]')
    b.wait("!document.querySelector('#chat-empty').hidden")
    check("ruta: pulsar «Mis Chats» cierra el chat", crumbs() == ["Asesoría Ocaña", "Mis Chats"]
          and b.js("chatState.clientId === null && document.querySelector('#chat-details').hidden"), crumbs())
    b.js("showView('templates')")
    check("ruta en Plantillas", crumbs() == ["Asesoría Ocaña", "Plantillas de WhatsApp"], crumbs())
    b.js("showView('ai')")
    check("ruta en IA", crumbs() == ["Asesoría Ocaña", "IA que responde"], crumbs())
finally:
    b.pump(0.5)
    b.close()

# Los 401 de antes de iniciar sesión y de la contraseña incorrecta son esperados.
errors = [e for e in b.errors if "favicon" not in e and "status of 401" not in e]
check("sin errores de JavaScript en la consola", not errors, "\n".join(errors))
sys.exit(0 if results["ok"] else 1)
