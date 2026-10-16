// Paleta de comandos (Ctrl+K) y atajos de teclado.
//
// Atajos (fuera de los cuadros de texto):
//   Ctrl+K / ⌘K  paleta          /  buscar en la lista     ?  ver atajos
//   j / k        chat o contacto siguiente / anterior      r  escribir la respuesta
//   g y luego c, s, t   ir a Contactos, Sin responder, Tareas

const SHORTCUTS = [
  ["Ctrl + K", "Abrir esta paleta: clientes y acciones"],
  ["/", "Buscar en la lista (chats o contactos)"],
  ["j / k", "Chat o contacto siguiente / anterior"],
  ["r", "Escribir la respuesta al contacto abierto"],
  ["g  c", "Ir a Contactos"],
  ["g  s", "Ir a Sin responder (Mis Chats)"],
  ["g  t", "Ir a Tareas"],
  ["?", "Ver los atajos"],
  ["Esc", "Cerrar"],
];

function paletteActions() {
  const actions = [
    { label: "Ir a Mis Chats", run: () => showView("chats") },
    { label: "Ir a Contactos", hint: "g c", run: () => goToSide("contacts") },
    { label: "Ir a Sin responder", hint: "g s", run: () => goToSide("inbox") },
    { label: "Ir a Tareas", hint: "g t", run: () => goToSide("tasks") },
    { label: "Consulta general al asistente", run: () => showView("assistant") },
    { label: "Nuevo cliente", run: () => openClientDialog("create") },
    { label: "Panel de actividad", run: () => openDashboard() },
    { label: "Respuestas guardadas", run: () => openRepliesDialog() },
    { label: "Mis cuentas (correo, Telegram, WhatsApp)", run: () => openAccountsDialog() },
    { label: "Cambiar tema claro / oscuro", run: () => toggleTheme() },
    { label: "Ver el tutorial", run: () => startTour() },
    { label: "Preguntar a Chispa (ayuda)", run: () => toggleHelp(true) },
    { label: "Ver los atajos de teclado", hint: "?", run: () => showShortcuts() },
  ];
  if (state.clientId) {
    actions.unshift(
      { label: "Escribir la respuesta", hint: "r", run: () => startReply() },
      { label: "Actualizar la ficha con IA", run: () => { showDetailTab("profile"); analyzeClient(); } },
      { label: "Editar cliente", run: () => openClientDialog("edit") },
    );
  }
  return actions;
}

let paletteItems = [];
let paletteActive = 0;
let paletteTimer = null;
let paletteSeq = 0;

function renderPalette() {
  $("#palette-list").innerHTML = paletteItems.length ? paletteItems.map((it, i) => `
    <li role="option" class="palette-item ${i === paletteActive ? "active" : ""}" data-i="${i}" aria-selected="${i === paletteActive}">
      <span class="palette-kind">${it.kind}</span>
      <span class="palette-label">${it.html}</span>
      ${it.hint ? `<kbd>${escapeHtml(it.hint)}</kbd>` : ""}
    </li>`).join("") : `<li class="muted small palette-empty">Sin resultados</li>`;
  $("#palette-list .active")?.scrollIntoView({ block: "nearest" });
}

async function updatePalette() {
  const q = $("#palette-input").value.trim();
  const n = normText(q);
  const actions = paletteActions().filter((a) => !n || normText(a.label).includes(n))
    .map((a) => ({ kind: "Acción", html: escapeHtml(a.label), hint: a.hint, run: a.run }));
  const seq = ++paletteSeq;
  let clients = [];
  if (q) {
    try {
      clients = (await api(`/api/clients?q=${encodeURIComponent(q)}`)).slice(0, 8);
    } catch { /* solo acciones */ }
  }
  if (seq !== paletteSeq) return; // llegó tarde: ya se escribió otra cosa
  paletteItems = [
    ...clients.map((c) => ({
      kind: "Cliente",
      html: `${statusDot(c.status)}${escapeHtml(c.name)}${c.company ? ` <span class="muted">· ${escapeHtml(c.company)}</span>` : ""}`,
      run: () => selectClient(c.id),
    })),
    ...actions,
  ];
  paletteActive = 0;
  renderPalette();
}

function openPalette() {
  const dialog = $("#palette-dialog");
  if (dialog.open) return;
  $("#palette-input").value = "";
  dialog.showModal();
  updatePalette();
  $("#palette-input").focus();
}

function runPaletteItem(i) {
  const item = paletteItems[i];
  if (!item) return;
  $("#palette-dialog").close();
  item.run();
}

function showShortcuts() {
  $("#shortcuts-list").innerHTML = SHORTCUTS.map(([k, d]) =>
    `<tr><td>${k.split("  ").map((x) => `<kbd>${escapeHtml(x)}</kbd>`).join(" ")}</td><td>${escapeHtml(d)}</td></tr>`).join("");
  $("#shortcuts-dialog").showModal();
}

function startReply() {
  if (!state.clientId) return;
  showDetailTab("conversation");
  $("#chat-text").focus();
}

// Atajos «g c / g s / g t»: Contactos, Sin responder (en Mis Chats) y Tareas.
function goToSide(side) {
  if (side === "contacts") return showView("contacts");
  if (side === "tasks") return showView("tasks");
  if (currentView() !== "chats") showView("chats");
  setChatsFilter("inbox");
}

// La lista de la izquierda que se ve: los chats o, en un contacto abierto desde Contactos, los contactos.
function visibleList() {
  return currentView() === "client" ? $("#contacts-mini") : $("#chats-list");
}

// Chat o contacto siguiente (+1) o anterior (-1) de la lista visible.
function moveClient(step) {
  if (currentView() !== "chats" && currentView() !== "client") showView("chats");
  if (chatState.filter === "inbox") setChatsFilter("all");
  const items = [...visibleList().querySelectorAll("li[data-client]")];
  if (!items.length) return;
  const current = items.findIndex((li) => li.classList.contains("active"));
  const next = items[Math.min(items.length - 1, Math.max(0, current + step))];
  next.scrollIntoView({ block: "nearest" });
  openChat(Number(next.dataset.client));
}

function focusListSearch() {
  if (currentView() === "contacts") return $("#contacts-search").focus();
  if (currentView() === "client") return $("#contacts-mini-search").focus();
  if (currentView() !== "chats") showView("chats");
  if (chatState.filter === "inbox") setChatsFilter("all");
  $("#chats-search").focus();
}

function isTyping(e) {
  const el = e.target;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

let pendingG = 0; // momento en que se pulsó «g» (espera la segunda tecla)

function onGlobalKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    openPalette();
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e) || document.querySelector("dialog[open]") || tour) return;
  if (Date.now() - pendingG < 1500) {
    pendingG = 0;
    const side = { c: "contacts", s: "inbox", t: "tasks" }[e.key];
    if (side) { e.preventDefault(); goToSide(side); }
    return;
  }
  const actions = {
    "/": focusListSearch,
    "?": showShortcuts,
    j: () => moveClient(1),
    k: () => moveClient(-1),
    r: startReply,
    g: () => { pendingG = Date.now(); },
  };
  if (actions[e.key]) {
    e.preventDefault();
    actions[e.key]();
  }
}

function bindPaletteEvents() {
  document.addEventListener("keydown", onGlobalKey);
  $("#palette-btn").addEventListener("click", openPalette);
  $("#palette-input").addEventListener("input", () => {
    clearTimeout(paletteTimer);
    paletteTimer = setTimeout(updatePalette, 120);
  });
  $("#palette-input").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!paletteItems.length) return;
      paletteActive = (paletteActive + (e.key === "ArrowDown" ? 1 : paletteItems.length - 1)) % paletteItems.length;
      renderPalette();
    } else if (e.key === "Enter") {
      e.preventDefault();
      runPaletteItem(paletteActive);
    }
  });
  $("#palette-list").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-i]");
    if (li) runPaletteItem(Number(li.dataset.i));
  });
  $("#palette-dialog").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) e.currentTarget.close(); // clic fuera de la caja
  });
}
