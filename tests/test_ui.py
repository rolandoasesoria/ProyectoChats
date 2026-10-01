"""Recorrido de la interfaz en Edge: login, tutorial, cliente, pestañas, notas, tareas, diálogos, tema, Chispa."""
import sys
from pathlib import Path

from apitest import check, results
from app.db import get_conn
from browser import Browser

# Jorge Martín (cliente 2) con un análisis de la IA que lo marca como urgente y molesto.
with get_conn() as conn:
    conn.execute("""INSERT INTO client_analysis (client_id, summary, last_message_id, priority, mood, priority_reason)
                    VALUES (2, 'Pide etiquetas resistentes a aceite.', 0, 'alta', 'molesto', 'Espera respuesta desde hace días')""")
    # Un mensaje antiguo de Laura (cliente 1) con su IBAN, para ocultarlo desde la ficha.
    conn.execute("""INSERT INTO messages (conversation_id, direction, sender, body, sent_at)
                    SELECT id, 'in', 'Laura', ?, '2026-07-01T10:00:00' FROM conversations WHERE client_id = 1 ORDER BY id LIMIT 1""",
                 ("Para domiciliar: ES91 2100 0418 4502 0005 1332",))

BASE = "http://127.0.0.1:8001"
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
    check(f"tutorial de {steps} pasos (admin)", int(steps) == 13, steps)
    b.click('.tour-card [data-tour="next"]')
    b.wait("!document.querySelector('.tour-card')")
    check("tutorial se cierra al terminar", True)

    # Lista de clientes y filtros
    check("3 clientes + consulta general", b.js("document.querySelectorAll('#client-list li[data-id]').length") == 4)
    b.shot("04-inicio")

    # Abrir Laura
    b.click('#client-list li[data-id="1"]')
    b.wait("document.querySelector('#detail-name').textContent === 'Laura Gómez'")
    b.wait("document.querySelector('#summary-text').textContent.length > 0")
    check("ficha de Laura con estado", b.js("document.querySelector('#detail-status').textContent") == "Activo")
    b.shot("05-ficha")

    # Documentos: se sube un archivo con el selector real (DevTools) y aparece en la lista
    check("sección de documentos vacía al principio", "Sin documentos" in b.js("document.querySelector('#documents').textContent"))
    node = b.send("DOM.getDocument")["root"]["nodeId"]
    inp = b.send("DOM.querySelector", nodeId=node, selector="#doc-upload")["nodeId"]
    sample = str(__import__("pathlib").Path(__file__).resolve().parent / ".tmp" / "sample.txt")
    __import__("pathlib").Path(sample).write_text("Contrato de suministro 2026", encoding="utf-8")
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
    b.click("#user-menu-btn")
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
    b.fill("#cf-tags", "VIP, mayorista")
    b.shot("10-editar-cliente")
    b.js("document.querySelector('#client-form').requestSubmit()")
    b.wait("!document.querySelector('#client-dialog').open")
    b.wait("document.querySelector('#detail-status').textContent === 'Incidencia'")
    check("estado y etiquetas guardados", "VIP" in b.js("document.querySelector('#detail-tags').textContent"))

    # Importar (diálogo)
    b.click("#import-btn")
    b.wait("document.querySelector('#import-dialog').open")
    b.shot("11-importar")
    b.js("document.querySelector('#import-dialog').close()")

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
    b.wait("document.querySelectorAll('#dash-weekly .viz-seg').length > 0")
    b.click('#dash-range [data-days="90"]')
    b.wait("document.querySelector('#dash-tiles').textContent.includes('13')")
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

    # Administración
    b.click("#user-menu-btn")
    b.click("#menu-admin")
    b.wait("document.querySelectorAll('#users-tbody tr').length === 3")
    b.shot("14-admin")
    check("administración de usuarios", True)

    # Ajustes: plazo de respuesta
    b.click('[data-admin-tab="settings"]')
    b.wait("document.querySelector('#set-sla').value === '24'")
    b.fill("#set-sla", "2")
    b.js("document.querySelector('#settings-form').requestSubmit()")
    b.wait("!document.querySelector('#set-saved').hidden")
    check("cambiar el plazo de respuesta", b.js("slaHours") == 2)
    b.fill("#set-retention", "1")
    b.wait("document.querySelector('#retention-preview').textContent.includes('se borrarían')")
    check("la retención avisa de cuántos mensajes borraría", True)
    b.shot("14b-ajustes")

    # Integraciones: alta de un bot de Telegram desde el formulario
    b.click('[data-admin-tab="integrations"]')
    b.wait("document.querySelectorAll('#if-fields input').length > 0")
    b.js("document.querySelector('#if-kind').value = 'telegram'; document.querySelector('#if-kind').dispatchEvent(new Event('change'))")
    b.fill("#if-name", "Bot de pruebas")
    b.fill('#if-fields input[name="bot_token"]', "123:ABC")
    b.js("document.querySelector('#integration-form').requestSubmit()")
    b.wait("document.querySelector('#integrations-list').textContent.includes('Bot de pruebas')")
    check("alta de integración desde la interfaz", "Pendiente de la primera sincronización" in b.js("document.querySelector('#integrations-list').textContent"))
    b.shot("17-integraciones")
    b.js("document.querySelector('#admin-dialog').close()")

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
    b.errors[:] = [e for e in b.errors if "ANTHROPIC_API_KEY" not in e and "/api/drafts/rewrite" not in e]
    b.shot("18-enviar")
finally:
    b.pump(0.5)
    b.close()

# Los 401 de antes de iniciar sesión y de la contraseña incorrecta son esperados.
errors = [e for e in b.errors if "favicon" not in e and "status of 401" not in e]
check("sin errores de JavaScript en la consola", not errors, "\n".join(errors))
sys.exit(0 if results["ok"] else 1)
