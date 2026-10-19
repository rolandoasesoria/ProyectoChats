// Piezas de interfaz con el estilo de la app en lugar de las del navegador:
//   · tooltips: el atributo title de cualquier elemento se muestra en una burbuja propia;
//   · desplegables (<select>): la lista que se abre es propia (el <select> sigue guardando el valor y avisando con
//     «change», así que el resto del código no cambia);
//   · avisos (alert): notificaciones flotantes que se cierran solas;
//   · confirmaciones y preguntas: appConfirm() y appPrompt(), ventanas de la app que devuelven una promesa.
// Tooltips, listas y avisos van en la capa superior (popover) para verse también por encima de las ventanas.

function popoverBox(className, role) {
  const el = document.createElement("div");
  el.className = className;
  el.setAttribute("popover", "manual");
  if (role) el.setAttribute("role", role);
  document.body.append(el);
  return el;
}

// Vuelve a ponerla encima de todo (p. ej. si se abrió una ventana después).
function bringToFront(el) {
  if (el.matches(":popover-open")) el.hidePopover();
  el.showPopover();
}

/* ---------- Tooltips ---------- */

const TIP_DELAY = 350;
let tipEl = null;
let tipFor = null;
let tipTimer = null;
let lastPointerAt = 0; // el foco que llega justo después de un clic no es de teclado: no lleva tooltip

// El title pasa a data-tip al pasar por encima: así el navegador no muestra el suyo. Se lee en el momento, así que
// vale también para los title que el código pone o cambia después.
function adoptTitle(el) {
  const text = el.getAttribute("title");
  if (text === null) return;
  el.removeAttribute("title");
  if (!text) {
    delete el.dataset.tip;
    return;
  }
  el.dataset.tip = text;
  if (!el.hasAttribute("aria-label") && !el.textContent.trim()) el.setAttribute("aria-label", text);
}

function showTip(el) {
  const text = el.dataset.tip;
  if (!text || !el.isConnected) return;
  tipEl ||= popoverBox("app-tip", "tooltip");
  tipEl.textContent = text;
  bringToFront(tipEl);
  const r = el.getBoundingClientRect();
  const t = tipEl.getBoundingClientRect();
  const above = r.top - t.height - 8 >= 4;
  tipEl.classList.toggle("below", !above);
  const top = above ? r.top - t.height - 8 : r.bottom + 8;
  const left = Math.min(Math.max(r.left + r.width / 2 - t.width / 2, 6), innerWidth - t.width - 6);
  tipEl.style.top = `${Math.round(top)}px`;
  tipEl.style.left = `${Math.round(left)}px`;
}

function hideTip() {
  clearTimeout(tipTimer);
  tipFor = null;
  if (tipEl?.matches(":popover-open")) tipEl.hidePopover();
}

function tipTarget(node) {
  return node?.closest?.("[title], [data-tip]") || null;
}

function bindTooltips() {
  document.addEventListener("pointerover", (e) => {
    const el = tipTarget(e.target);
    if (el === tipFor) return;
    hideTip();
    if (!el || openSel) return; // con una lista abierta, sin tooltips
    adoptTitle(el);
    if (!el.dataset.tip) return;
    tipFor = el;
    tipTimer = setTimeout(() => showTip(el), TIP_DELAY);
  });
  document.addEventListener("pointerout", (e) => {
    if (tipFor && !tipFor.contains(e.relatedTarget)) hideTip();
  });
  document.addEventListener("focusin", (e) => {
    const el = tipTarget(e.target);
    if (!el || !e.target.matches(":focus-visible") || Date.now() - lastPointerAt < 600 || openSel) return;
    hideTip();
    adoptTitle(el);
    tipFor = el;
    showTip(el);
  });
  document.addEventListener("focusout", hideTip);
  ["pointerdown", "wheel"].forEach((ev) => document.addEventListener(ev, () => {
    lastPointerAt = Date.now();
    hideTip();
  }, true));
  document.addEventListener("scroll", hideTip, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
}

/* ---------- Desplegables ---------- */

let selectMenu = null;
let openSel = null; // { select, active }
let typeahead = { text: "", at: 0 };

function isMenuSelect(el) {
  return el?.tagName === "SELECT" && !el.multiple && el.size <= 1;
}

function visibleOptions() {
  return [...openSel.select.options].map((o, i) => ({ o, i })).filter(({ o }) => !o.hidden);
}

function renderSelectMenu() {
  const { select, active } = openSel;
  selectMenu.innerHTML = visibleOptions().map(({ o, i }) => `
    <div class="select-option${i === select.selectedIndex ? " selected" : ""}${i === active ? " active" : ""}${o.disabled ? " disabled" : ""}"
         role="option" data-i="${i}" aria-selected="${i === select.selectedIndex}">${escapeHtml(o.textContent)}</div>`).join("");
  selectMenu.querySelector(".active")?.scrollIntoView({ block: "nearest" });
}

function openSelect(select) {
  if (select.disabled) return;
  selectMenu ||= popoverBox("select-menu", "listbox");
  openSel = { select, active: select.selectedIndex };
  select.setAttribute("aria-expanded", "true");
  bringToFront(selectMenu);
  renderSelectMenu();
  const r = select.getBoundingClientRect();
  selectMenu.style.minWidth = `${Math.round(r.width)}px`;
  selectMenu.style.maxHeight = "";
  const h = selectMenu.getBoundingClientRect().height;
  const below = innerHeight - r.bottom - 8;
  const above = r.top - 8;
  const down = h <= below || below >= above;
  selectMenu.style.maxHeight = `${Math.max(120, Math.min(320, down ? below : above))}px`;
  const height = selectMenu.getBoundingClientRect().height;
  const width = selectMenu.getBoundingClientRect().width;
  selectMenu.style.top = `${Math.round(down ? r.bottom + 4 : r.top - height - 4)}px`;
  selectMenu.style.left = `${Math.round(Math.min(Math.max(r.left, 6), innerWidth - width - 6))}px`;
  renderSelectMenu(); // con la altura ya fijada, la opción elegida queda a la vista
}

function closeSelect(refocus = true) {
  if (!openSel) return;
  const { select } = openSel;
  select.removeAttribute("aria-expanded");
  openSel = null;
  if (selectMenu.matches(":popover-open")) selectMenu.hidePopover();
  if (refocus) select.focus();
}

function chooseOption(i) {
  const { select } = openSel;
  if (select.options[i]?.disabled) return;
  const changed = select.selectedIndex !== i;
  closeSelect();
  if (!changed) return;
  select.selectedIndex = i;
  select.dispatchEvent(new Event("input", { bubbles: true }));
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function moveActive(step) {
  const opts = visibleOptions().filter(({ o }) => !o.disabled);
  if (!opts.length) return;
  const pos = opts.findIndex(({ i }) => i === openSel.active);
  const next = step === Infinity ? opts.at(-1) : step === -Infinity ? opts[0]
    : opts[Math.min(opts.length - 1, Math.max(0, (pos < 0 ? 0 : pos) + step))];
  openSel.active = next.i;
  renderSelectMenu();
}

// Escribir unas letras salta a la primera opción que empiece así.
function typeToFind(key) {
  typeahead = { text: (Date.now() - typeahead.at < 800 ? typeahead.text : "") + key.toLowerCase(), at: Date.now() };
  const found = visibleOptions().find(({ o }) => !o.disabled && normText(o.textContent).startsWith(normText(typeahead.text)));
  if (found) {
    openSel.active = found.i;
    renderSelectMenu();
  }
}

function bindSelectMenus() {
  document.addEventListener("mousedown", (e) => {
    if (openSel && selectMenu.contains(e.target)) {
      e.preventDefault(); // que el desplegable no pierda el foco
      return;
    }
    const select = e.target.closest?.("select");
    if (isMenuSelect(select) && e.button === 0) {
      e.preventDefault(); // en lugar de la lista del navegador, la de la app
      if (openSel?.select === select) return closeSelect();
      closeSelect(false);
      select.focus();
      return openSelect(select);
    }
    closeSelect(false);
  }, true);
  document.addEventListener("click", (e) => {
    const option = openSel && e.target.closest?.(".select-option");
    if (option) chooseOption(Number(option.dataset.i));
  });
  document.addEventListener("pointermove", (e) => {
    const option = openSel && e.target.closest?.(".select-option:not(.disabled)");
    if (option && Number(option.dataset.i) !== openSel.active) {
      openSel.active = Number(option.dataset.i);
      selectMenu.querySelectorAll(".select-option").forEach((el) => el.classList.toggle("active", el === option));
    }
  });
  document.addEventListener("keydown", (e) => {
    if (!openSel) {
      // Abrir con el teclado como la lista del navegador: Alt+↓, F4, espacio o Intro.
      const select = e.target;
      if (isMenuSelect(select) && ((e.altKey && e.key === "ArrowDown") || e.key === "F4" || e.key === " " || e.key === "Enter")) {
        e.preventDefault();
        openSelect(select);
      }
      return;
    }
    const keys = {
      ArrowDown: () => moveActive(1), ArrowUp: () => moveActive(-1), PageDown: () => moveActive(8), PageUp: () => moveActive(-8),
      Home: () => moveActive(-Infinity), End: () => moveActive(Infinity),
      Enter: () => chooseOption(openSel.active), " ": () => chooseOption(openSel.active),
      Escape: () => closeSelect(), Tab: () => closeSelect(false),
    };
    if (keys[e.key]) {
      if (e.key !== "Tab") {
        e.preventDefault();
        e.stopPropagation(); // Esc cierra la lista, no la ventana en la que está
      }
      keys[e.key]();
    } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      typeToFind(e.key);
    }
  }, true);
  document.addEventListener("scroll", (e) => { if (openSel && !selectMenu.contains(e.target)) closeSelect(false); }, true);
  window.addEventListener("resize", () => closeSelect(false));
}

/* ---------- Avisos ---------- */

let toastBox = null;
const TOAST_ICONS = {
  info: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>`,
  success: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5 5.5-6"/></svg>`,
};

// Aviso flotante abajo a la derecha: se cierra solo (o al pulsarlo).
function toast(message, kind = "info") {
  toastBox ||= popoverBox("toasts", "status");
  const item = document.createElement("div");
  item.className = `toast ${kind}`;
  item.innerHTML = `<span class="toast-icon">${TOAST_ICONS[kind] || TOAST_ICONS.info}</span><span class="toast-text"></span>
    <button type="button" class="toast-close" aria-label="Cerrar">×</button>`;
  item.querySelector(".toast-text").textContent = message;
  const close = () => {
    item.classList.add("leaving");
    setTimeout(() => {
      item.remove();
      if (!toastBox.children.length && toastBox.matches(":popover-open")) toastBox.hidePopover();
    }, 180);
  };
  item.addEventListener("click", close);
  toastBox.append(item);
  bringToFront(toastBox);
  setTimeout(close, Math.min(12000, 4500 + message.length * 40));
}

// alert() del resto del código: un aviso de la app en lugar de la ventana del navegador.
window.alert = (message) => toast(String(message ?? ""));

/* ---------- Confirmaciones y preguntas ---------- */

// Ventana de la app que devuelve una promesa: true si se acepta. `danger` pinta el botón en rojo (borrar…).
function appConfirm(message, { ok = "Aceptar", cancel = "Cancelar", danger = false } = {}) {
  return appDialog(message, { ok, cancel, danger }).then((r) => r !== null);
}

// Pregunta con un campo de texto: devuelve lo escrito o null si se cancela.
function appPrompt(message, value = "", { ok = "Aceptar", placeholder = "", danger = false } = {}) {
  return appDialog(message, { ok, cancel: "Cancelar", danger, input: { value, placeholder } });
}

function appDialog(message, { ok, cancel, danger = false, input = null }) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "dialog app-dialog";
    dialog.innerHTML = `
      <form method="dialog" class="app-dialog-form">
        <p class="app-dialog-text"></p>
        ${input ? `<input class="app-dialog-input" autocomplete="off">` : ""}
        <div class="dialog-actions">
          <button type="button" class="ghost" data-answer="no"></button>
          <button type="submit" class="primary${danger ? " danger-btn" : ""}" data-answer="yes"></button>
        </div>
      </form>`;
    dialog.querySelector(".app-dialog-text").textContent = message;
    dialog.querySelector('[data-answer="no"]').textContent = cancel;
    dialog.querySelector('[data-answer="yes"]').textContent = ok;
    const field = dialog.querySelector(".app-dialog-input");
    if (field) {
      field.value = input.value;
      field.placeholder = input.placeholder;
    }
    let answer = null;
    dialog.querySelector("form").addEventListener("submit", (e) => {
      e.preventDefault();
      answer = field ? field.value : "";
      dialog.close();
    });
    dialog.querySelector('[data-answer="no"]').addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
      dialog.remove();
      resolve(answer);
    });
    document.body.append(dialog);
    dialog.showModal();
    (field || dialog.querySelector('[data-answer="yes"]')).focus();
    field?.select();
  });
}

function bindUiEvents() {
  bindTooltips();
  bindSelectMenus();
}
