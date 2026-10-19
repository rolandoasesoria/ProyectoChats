"""Recorrido de todos los controles de la interfaz con el ratón y el teclado reales: en cada pantalla y ventana, cada
desplegable se abre y deja elegir otra opción, cada campo deja escribir y cada casilla se marca. También comprueba que
ninguno esté tapado o bloqueado (p. ej. una lista fuera de la ventana abierta). Mientras se prueban, los avisos
«input» y «change» no llegan a la app, para no buscar, guardar ni enviar nada: se mira solo que los controles
respondan. Al terminar cada uno se deja como estaba."""
import sys

from apitest import BASE, check, results
from browser import Browser

HELPERS = r"""
window.__sweep = {
  events: [],
  block: false,
  scope() { return [...document.querySelectorAll('dialog[open]')].at(-1) || document; },
  visible(el) {
    // Como lo ve una persona: fuera lo oculto, lo plegado (p. ej. un <details> cerrado) y lo de tamaño cero.
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2 && el.checkVisibility({contentVisibilityAuto: true, visibilityProperty: true})
      && !el.closest('[hidden]');
  },
  name(el) {
    return '#' + (el.id || el.name || el.getAttribute('aria-label') || el.placeholder || el.className || el.tagName);
  },
  list(selector) {
    return [...this.scope().querySelectorAll(selector)].filter((el) => this.visible(el) && !el.disabled && !el.readOnly);
  },
  center(el) {
    el.scrollIntoView({block: 'center', inline: 'nearest'});
    const r = el.getBoundingClientRect();
    return [Math.round(r.left + Math.min(r.width / 2, 24)), Math.round(r.top + r.height / 2)];
  },
  reachable(el) {
    const [x, y] = this.center(el);
    const top = document.elementFromPoint(x, y);
    return !!top && (top === el || el.contains(top) || top.contains(el) || top.closest('label')?.contains(el));
  },
};
for (const type of ['input', 'change']) {
  window.addEventListener(type, (e) => {
    if (!window.__sweep.block) return;
    window.__sweep.events.push(type + ':' + window.__sweep.name(e.target));
    e.stopImmediatePropagation();
  }, true);
}
"""

TEXT_INPUTS = ("input:not([type]), input[type=text], input[type=search], input[type=email], input[type=password], "
               "input[type=number], input[type=tel], input[type=url], textarea")
problems = []
seen = set()


def mouse(b, kind, x, y):
    b.send("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left",
           buttons=1 if kind == "mousePressed" else 0, clickCount=1)


def click_at(b, x, y):
    mouse(b, "mousePressed", x, y)
    mouse(b, "mouseReleased", x, y)


def sweep(b, where):
    """Prueba los controles visibles de la pantalla o ventana que esté delante."""
    b.js("window.__sweep.block = true")
    count = 0
    # Desplegables
    n = b.js("window.__sweep.list('select:not([multiple])').length")
    for i in range(n):
        name = b.js(f"window.__sweep.name(window.__sweep.list('select:not([multiple])')[{i}])")
        key = (where, "select", name)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        sel = f"window.__sweep.list('select:not([multiple])')[{i}]"
        mouse(b, "mouseMoved", *b.js(f"window.__sweep.center({sel})"))  # algunos solo aparecen al pasar el ratón
        if not b.js(f"window.__sweep.reachable({sel})"):
            problems.append(f"{where}: desplegable {name} tapado o bloqueado")
            continue
        info = b.js(f"""(() => {{ const s = {sel}; const opts = [...s.options];
            const target = opts.findIndex((o, k) => k !== s.selectedIndex && !o.disabled && !o.hidden);
            return {{original: s.value, target}}; }})()""")
        x, y = b.js(f"window.__sweep.center({sel})")
        click_at(b, x, y)
        b.pump(0.25)
        opened = b.js("!!document.querySelector('.select-menu')?.matches(':popover-open')")
        if not opened:
            problems.append(f"{where}: el desplegable {name} no abre su lista")
            continue
        in_place = b.js(f"(() => {{ const d = {sel}.closest('dialog'); const m = document.querySelector('.select-menu');"
                        " return d ? d.contains(m) : !m.closest('dialog'); })()")
        if not in_place:
            problems.append(f"{where}: la lista de {name} queda fuera de su ventana")
        if info["target"] < 0:
            b.js(f"{sel}.focus(); closeSelect()")
            continue
        ox, oy = b.js(f"""(() => {{ const o = document.querySelector('.select-menu [data-i="{info['target']}"]');
            o.scrollIntoView({{block: 'nearest'}}); const r = o.getBoundingClientRect();
            return [Math.round(r.left + 16), Math.round(r.top + r.height / 2)]; }})()""")
        b.js("window.__sweep.events = []")
        click_at(b, ox, oy)
        b.pump(0.25)
        ok = b.js(f"{sel}.selectedIndex") == info["target"] and any(e.startswith("change:") for e in b.js("window.__sweep.events"))
        if not ok:
            problems.append(f"{where}: en {name} no se puede elegir otra opción con el ratón")
        b.js(f"(() => {{ const s = {sel}; s.value = {info['original']!r}; }})()")
    # Campos de texto
    n = b.js(f"window.__sweep.list({TEXT_INPUTS!r}).length")
    for i in range(n):
        el = f"window.__sweep.list({TEXT_INPUTS!r})[{i}]"
        name = b.js(f"window.__sweep.name({el})")
        key = (where, "campo", name)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        if not b.js(f"window.__sweep.reachable({el})"):
            problems.append(f"{where}: campo {name} tapado o bloqueado")
            continue
        original = b.js(f"{el}.value")
        x, y = b.js(f"window.__sweep.center({el})")
        click_at(b, x, y)
        b.pump(0.1)
        if not b.js(f"document.activeElement === {el}"):
            problems.append(f"{where}: el campo {name} no recibe el foco al pulsarlo")
            continue
        text = "7" if b.js(f"{el}.type") == "number" else "Prueba 7"
        b.send("Input.insertText", text=text)
        if text not in (b.js(f"{el}.value") or ""):
            problems.append(f"{where}: no se puede escribir en {name}")
        b.js(f"(() => {{ const e = {el}; e.value = {original!r}; e.blur(); }})()")
    # Casillas
    n = b.js("window.__sweep.list('input[type=checkbox]').length")
    for i in range(n):
        el = f"window.__sweep.list('input[type=checkbox]')[{i}]"
        name = b.js(f"window.__sweep.name({el})")
        key = (where, "casilla", name)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        if not b.js(f"window.__sweep.reachable({el})"):
            problems.append(f"{where}: casilla {name} tapada o bloqueada")
            continue
        before = b.js(f"{el}.checked")
        x, y = b.js(f"window.__sweep.center({el})")
        click_at(b, x, y)
        b.pump(0.1)
        if b.js(f"{el}.checked") == before:
            problems.append(f"{where}: la casilla {name} no se marca al pulsarla")
        b.js(f"(() => {{ const e = {el}; e.checked = {str(before).lower()}; }})()")
    b.js("window.__sweep.block = false")
    return count


b = Browser()
total = 0
try:
    b.goto(BASE + "/login.html")
    b.wait("!!document.querySelector('#username')")
    b.fill("#username", "ana")
    b.fill("#password", "demo1234")
    b.click("#login-btn")
    b.wait("location.pathname === '/' && !!currentUser")
    b.pump(1.5)
    b.js(HELPERS)

    # Mis Chats con un contacto abierto: conversación (con buscador, borrador, respuestas y correo nuevo), ficha,
    # tareas, notas, detalles (responsable y etiquetas) y asistente
    b.js("showView('chats')")
    b.wait("document.querySelectorAll('#chats-list li[data-client]').length > 0")
    b.js("document.querySelector('#chats-list li[data-client]').click()")
    b.wait("!!chatState.data && document.querySelectorAll('#chat-timeline .msg-row').length > 0")
    b.pump(1)
    total += sweep(b, "Mis Chats")
    b.js("document.querySelector('#msg-search-toggle').click()")
    total += sweep(b, "Mis Chats · buscador")
    b.js("document.querySelector('#chat-ai-draft').click()")
    total += sweep(b, "Mis Chats · Redactar con IA")
    b.js("document.body.click(); document.querySelector('#reply-open').click()")
    b.pump(0.5)
    total += sweep(b, "Mis Chats · Respuestas")
    b.js("document.body.click()")
    for tab in ("profile", "tasks", "notes"):
        b.js(f"showDetailTab('{tab}')")
        b.pump(0.6)
        total += sweep(b, f"Contacto · {tab}")
    b.js("showDetailTab('conversation')")
    b.js("document.querySelector('[data-cd-tag]').click()")
    total += sweep(b, "Detalles · etiquetas")
    b.js("document.body.click(); showDetailsPane('assistant')")
    b.pump(0.5)
    total += sweep(b, "Detalles · asistente")
    b.js("showDetailsPane('info')")
    b.js("setChatsFilter('inbox')")
    b.wait("document.querySelectorAll('#chats-list .inbox-item').length > 0")
    total += sweep(b, "Mis Chats · Sin responder")
    b.js("setChatsFilter('all')")

    # Contactos (tabla y columnas) y contacto abierto desde la tabla
    b.js("showView('contacts')")
    b.wait("document.querySelectorAll('#contacts-body tr[data-client]').length > 0")
    total += sweep(b, "Contactos")
    b.js("document.querySelector('#contacts-columns-btn').click()")
    total += sweep(b, "Contactos · columnas")
    b.js("document.body.click(); document.querySelector('#contacts-body tr[data-client]').click()")
    b.wait("currentView() === 'client' && !!chatState.data")
    total += sweep(b, "Contacto desde la tabla")

    # Tareas, Asistente, Plantillas (con el editor), Respuestas con IA y Panel
    b.js("showView('tasks')")
    b.pump(1)
    total += sweep(b, "Tareas")
    b.js("showView('assistant')")
    b.pump(0.5)
    total += sweep(b, "Asistente")
    b.js("showView('templates')")
    b.pump(1)
    total += sweep(b, "Plantillas")
    b.js("document.querySelector('#tpl-new').disabled = false; startNewTemplate()")
    b.pump(0.3)
    total += sweep(b, "Plantillas · nueva")
    b.js("showView('ai')")
    b.wait("document.querySelector('#ai-mode .active') !== null")
    b.js("document.querySelector('#ai-schedule').value = 'out_of_hours'; document.querySelector('#ai-hours-box').hidden = false")
    total += sweep(b, "Respuestas con IA")
    b.js("showView('dashboard')")
    b.pump(1)
    total += sweep(b, "Panel de actividad")

    # Ventanas
    b.js("showView('chats')")
    b.wait("document.querySelectorAll('#chats-list li[data-client]').length > 0")
    b.js("document.querySelector('#chats-list li[data-client]').click()")
    b.wait("!!chatState.data")
    b.js("openClientDialog('edit')")
    b.wait("document.querySelector('#client-dialog').open")
    total += sweep(b, "Editar cliente")
    b.js("document.querySelector('#client-dialog').close()")
    b.js("openAdminDialog()")
    b.wait("document.querySelector('#admin-dialog').open && document.querySelectorAll('#users-tbody tr').length > 0")
    total += sweep(b, "Administración · usuarios")
    for tab in ("audit", "settings", "properties"):
        b.js(f"showAdminTab('{tab}')")
        b.pump(0.8)
        total += sweep(b, f"Administración · {tab}")
    b.js("document.querySelector('#admin-dialog').close()")
    b.js("openAccountsDialog()")
    b.wait("document.querySelector('#accounts-dialog').open && document.querySelectorAll('#if-fields input').length > 0")
    b.js("document.querySelector('#if-advanced')?.setAttribute('open', '')")  # «Ajustes avanzados» del correo
    total += sweep(b, "Mis cuentas")
    for kind in ("telegram", "whatsapp"):
        b.js(f"document.querySelector('#if-kind').value = '{kind}'; renderIntegrationFields()")
        b.js("document.querySelector('#if-manual')?.setAttribute('open', '')")
        total += sweep(b, f"Mis cuentas · {kind}")
    b.js("document.querySelector('#accounts-scope [data-accounts-scope=\"team\"]').click()")
    b.pump(1)
    total += sweep(b, "Mis cuentas · equipo")
    b.js("document.querySelector('#accounts-dialog').close()")
    b.js("openCompanyDialog()")
    total += sweep(b, "Datos de la empresa")
    b.js("document.querySelector('#company-dialog').close()")
    b.js("openRepliesDialog()")
    b.wait("document.querySelector('#replies-dialog').open")
    b.pump(0.5)
    total += sweep(b, "Respuestas guardadas")
    b.js("document.querySelector('#replies-dialog').close()")
    b.js("openProfileDialog()")
    total += sweep(b, "Mi perfil")
    b.js("document.querySelector('#profile-dialog').close()")
    b.js("openPasswordDialog()")
    total += sweep(b, "Cambiar contraseña")
    b.js("document.querySelector('#password-dialog')?.close()")
    b.js("openPalette()")
    total += sweep(b, "Buscar o ir a… (Ctrl+K)")
    b.js("document.querySelector('#palette-dialog').close()")
finally:
    b.pump(0.3)
    b.close()

print(f"Controles probados: {total}")
for p in problems:
    print("  ·", p)
check(f"todos los controles responden ({total} probados)", not problems and total > 60, "\n".join(problems))
errors = [e for e in b.errors if "favicon" not in e and "status of 401" not in e]
check("sin errores de JavaScript en la consola", not errors, "\n".join(errors))
sys.exit(0 if results["ok"] else 1)
