// Hilvana Chat — pantalla principal. Utilidades comunes en common.js; cuenta en account.js; tutorial en tour.js.

const GENERAL = "general"; // clave del hilo sin cliente seleccionado

const state = {
  clientId: null,
  clientData: null, // el contacto abierto (ver openChat en chats.js)
  scope: "team",  // historial del cliente: todo el equipo, salvo «Solo mis conversaciones»
  // Un hilo del asistente por cliente: clave -> { el (div.thread), busy, loaded }
  threads: new Map(),
  convClients: new Set(), // clientes con conversación guardada
  helpLoaded: false,
};

// Markdown mínimo: negrita, cursiva y código en línea.
function renderMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<em>$2</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleString("es-ES", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function badge(channel) {
  return `<span class="badge ${escapeHtml(channel)}">${escapeHtml(IDENTITY_LABELS[channel] || channel)}</span>`;
}

// Añade una burbuja al chat (al final, o antes de `before`).
function appendBubble(container, role, html, before = null) {
  container.querySelector(".empty-chat")?.remove();
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = html;
  container.insertBefore(div, before);
  return div;
}

const TYPING = `<span class="typing"><i></i><i></i><i></i></span>`;

// Un turno guardado del asistente o de Chispa: lo del usuario como texto, la respuesta en Markdown con su traza.
function turnHtml(t) {
  return t.role === "user" ? escapeHtml(t.text) : renderMarkdown(t.text) + renderTrace(t.tool_calls);
}

// Pregunta y respuesta en un chat: burbuja del usuario, burbuja de «escribiendo…» y, al llegar, la respuesta
// (o el error en su lugar). `answer()` hace la petición y devuelve el HTML. Devuelve si hubo respuesta.
async function askBot(log, text, answer, scroll) {
  appendBubble(log, "user", escapeHtml(text));
  const pending = appendBubble(log, "bot", TYPING);
  scroll();
  try {
    pending.innerHTML = await answer();
    return true;
  } catch (err) {
    pending.className = "msg error";
    pending.textContent = err.message;
    return false;
  }
}

/* ---------- Clientes ---------- */

const clientNames = new Map();

// Tras crear, editar, unir o borrar clientes: se refrescan las listas que se ven.
async function loadClients() {
  const jobs = [loadChats()];
  if (currentView() === "contacts") jobs.push(loadContacts());
  if (currentView() === "client") jobs.push(loadContactsMini());
  await Promise.all(jobs);
}

// Clientes con conversación guardada con el asistente.
function setThreadDot(clientId, on) {
  if (clientId === null) return;
  if (on) state.convClients.add(clientId);
  else state.convClients.delete(clientId);
}

// Abre un contacto (desde la tabla, el buscador, los avisos, la bandeja, las tareas…): en Mis Chats si se está ahí;
// si no, en Contactos. Sin cliente (null), la consulta general del asistente.
async function selectClient(id) {
  if (id === null) return showView("assistant");
  const view = currentView() === "chats" ? "chats" : "client";
  if (currentView() !== view) showView(view);
  await openChat(id);
}

// Pestañas de canal (ficha y Mis Chats): «Todos los canales» y una por canal. `active` "" = todos.
function channelTabsHtml(channels, active) {
  return [`<button role="tab" data-channel="" class="${active === "" ? "active" : ""}">Todos los canales</button>`,
    ...channels.map((ch) =>
      `<button role="tab" data-channel="${escapeHtml(ch)}" class="${ch === active ? "active" : ""}">${badge(ch)}</button>`)].join("");
}

function setActiveChannelTab(container, channel) {
  container.querySelectorAll("[data-channel]").forEach((t) => t.classList.toggle("active", t.dataset.channel === channel));
}

// Conversación al estilo de un chat: el cliente a la izquierda, el equipo a la derecha, un separador por día y
// los mensajes seguidos de la misma persona agrupados (sin repetir el nombre).
const GROUP_MINUTES = 10;

function dayLabel(date) {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Hoy";
  if (date.toDateString() === yesterday.toDateString()) return "Ayer";
  return date.toLocaleDateString("es-ES", {
    weekday: "long", day: "numeric", month: "long",
    ...(date.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}),
  });
}

// Formato de WhatsApp (*negrita*, _cursiva_, ~tachado~, ```monoespaciado```) y enlaces, sobre el texto ya escapado.
const URL_RE = /https?:\/\/[^\s<]+?(?=(?:&quot;|&#39;|[.,;:!?)\]])*(?:\s|<|$))/g;
const STYLE_MARKS = [["*", "strong"], ["_", "em"], ["~", "s"]];

function formatMessage(body, channel) {
  let html = escapeHtml(body).replace(URL_RE, (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`);
  if (channel !== "whatsapp" && channel !== "telegram") return html;
  html = html.replace(/```([\s\S]+?)```/g, "<code>$1</code>");
  for (const [mark, tag] of STYLE_MARKS) {
    const re = new RegExp(`(^|[\\s(])\\${mark}(?=\\S)([^${mark}\\n]*?\\S)\\${mark}(?=$|[\\s).,!?:;])`, "gm");
    html = html.replace(re, `$1<${tag}>$2</${tag}>`);
  }
  return html;
}

// Fotos, vídeos y audios dentro de la burbuja (las fotos se amplían en el visor); el resto, como adjunto.
const INLINE_MEDIA = /^(image|video|audio)\//;

function mediaHtml(files) {
  return files.map((a) => {
    const url = attachmentUrl(a.id);
    const name = escapeHtml(a.filename);
    if (a.mime.startsWith("image/")) {
      return `<button type="button" class="bubble-media" data-viewer="${url}" data-name="${name}" aria-label="Ver ${name}"><img src="${url}" alt="${name}" loading="lazy"></button>`;
    }
    if (a.mime.startsWith("video/")) return `<video class="bubble-video" src="${url}" controls preload="metadata"></video>`;
    return `<audio class="bubble-audio" src="${url}" controls preload="metadata"></audio>`;
  }).join("");
}

// Checks de lo enviado por WhatsApp: uno (enviado), dos (entregado), dos azules (leído) o «No entregado» con el motivo.
function ticksHtml(m) {
  if (m.direction !== "out" || !m.status) return "";
  if (m.status === "failed") {
    const why = escapeHtml(`No entregado${m.status_error ? `: ${m.status_error}` : ""}`);
    return ` <span class="ticks failed" role="img" aria-label="${why}" title="${why}"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 4.8v3.7M8 11.2h.01"/></svg>No entregado</span>`;
  }
  const hm = (t) => new Date(t).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  const label = [{ sent: "Enviado", delivered: "Entregado", read: "Leído" }[m.status],
    m.delivered_at ? `entregado a las ${hm(m.delivered_at)}` : "", m.read_at ? `leído a las ${hm(m.read_at)}` : ""]
    .filter(Boolean).join(" · ");
  const paths = m.status === "sent" ? '<path d="M3 6.5l3 3 6.5-7"/>' : '<path d="M1 6.5l3 3 6.5-7"/><path d="M7.5 8.5l1 1 6.5-7"/>';
  return ` <span class="ticks ${m.status}" role="img" aria-label="${label}" title="${label}"><svg viewBox="0 0 16 12" aria-hidden="true">${paths}</svg></span>`;
}

function quoteHtml(m) {
  if (!m.reply_to_id) return "";
  return `<button type="button" class="bubble-quote ${m.reply_direction === "out" ? "out" : "in"}" data-jump="${m.reply_to_id}" title="Ir al mensaje citado">
    <strong>${escapeHtml(m.reply_sender || "Mensaje")}</strong><span>${escapeHtml(firstLine(m.reply_body) || "📎 Archivo")}</span></button>`;
}

function reactionsHtml(m) {
  if (!m.reactions?.length) return "";
  const who = (r) => (r.side === "client" ? "Reacción del cliente" : `Reacción del equipo${r.user ? ` (${r.user})` : " (desde el móvil)"}`);
  return `<div class="bubble-reactions">${m.reactions.map((r) =>
    `<span class="reaction" title="${escapeHtml(who(r))}">${escapeHtml(r.emoji)}</span>`).join("")}</div>`;
}

// Al pasar el ratón por un mensaje de tus conversaciones de WhatsApp o Telegram: reaccionar (WhatsApp) y citarlo.
const ICON_REACT = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8.5 14.5a4.5 4.5 0 0 0 7 0M9 9.5h.01M15 9.5h.01"/></svg>';
const ICON_REPLY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg>';

function actionsHtml(m) {
  const mine = chatState.data?.conversations.some((c) => c.id === m.conversation_id && c.is_mine);
  if (!mine || m.channel === "email") return "";
  return `<div class="msg-actions">${m.reactable ? `<button type="button" class="msg-act" data-react="${m.id}" title="Reaccionar" aria-label="Reaccionar">${ICON_REACT}</button>` : ""}<button type="button" class="msg-act" data-quote-reply="${m.id}" title="Responder citando" aria-label="Responder citando">${ICON_REPLY}</button></div>`;
}

function timelineHtml(messages) {
  let prev = null;
  return messages.map((m) => {
    const at = new Date(m.sent_at);
    const newDay = !prev || new Date(prev.sent_at).toDateString() !== at.toDateString();
    const grouped = !newDay && prev.sender === m.sender && prev.direction === m.direction && prev.channel === m.channel
      && (at - new Date(prev.sent_at)) / 60000 <= GROUP_MINUTES;
    prev = m;
    // Por qué cuenta del equipo entró la conversación (de ella sale la respuesta). Quién lleva al cliente es su
    // responsable, que se ve en la cabecera y en Detalles.
    const owner = m.owner_id !== currentUser.id
      ? ` · <span class="account-tag" title="Entró por la cuenta de ${escapeHtml(m.owner)}: se responde desde esa cuenta">cuenta de ${escapeHtml(m.owner)}</span>` : "";
    const time = at.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
    const files = m.attachments || [];
    const inline = files.filter((a) => INLINE_MEDIA.test(a.mime || ""));
    const others = files.filter((a) => !INLINE_MEDIA.test(a.mime || ""));
    // «📎 foto.jpg» sin más texto: con la foto a la vista, sobra
    const onlyMedia = inline.length && !others.length && inline.some((a) => m.body === `📎 ${a.filename}`);
    return `${newDay ? `<li class="day-sep"><span>${escapeHtml(dayLabel(at))}</span></li>` : ""}
    <li class="msg-row ${m.direction} ${escapeHtml(m.channel)}${grouped ? " grouped" : ""}${m.reactions?.length ? " has-reactions" : ""}" data-id="${m.id}">
      <div class="bubble" title="${escapeHtml(formatDate(m.sent_at))}">
        ${grouped ? "" : `<div class="bubble-sender">${escapeHtml(m.sender)}</div>`}
        ${quoteHtml(m)}${mediaHtml(inline)}
        ${onlyMedia ? "" : `<div class="bubble-text">${formatMessage(m.body, m.channel)}</div>`}${attachmentChips(others)}
        <div class="bubble-meta">${m.by_ai ? `<span class="ai-mark" title="Escrito por la IA">🤖 IA</span> · ` : ""}<span class="ch-dot"></span>${escapeHtml(IDENTITY_LABELS[m.channel] || m.channel)}${owner} · ${time}${ticksHtml(m)}</div>
        ${reactionsHtml(m)}
      </div>
      ${actionsHtml(m)}
    </li>`;
  }).join("");
}

/* ---------- Asistente: un hilo por cliente, guardado en el servidor ---------- */

function suggestionsFor(clientId) {
  if (clientId === null) {
    return {
      intro: "Consulta general: pregúntame por cualquier cliente.",
      chips: ["¿Qué clientes han pedido presupuesto este mes?", "¿Qué fecha de entrega acordamos con Jorge?"],
    };
  }
  const name = clientNames.get(clientId) || "este cliente";
  return {
    intro: `Pregúntame cualquier dato de ${name}.`,
    chips: [
      "¿Cuál es su dirección de envío?",
      "¿Qué datos de facturación nos dio? Busca también en las del equipo",
      "Resúmeme lo último que hemos hablado",
    ],
  };
}

function emptyChatHtml(clientId) {
  const { intro, chips } = suggestionsFor(clientId);
  return `
    <div class="empty-chat">
      <p>${escapeHtml(intro)}</p>
      <div class="suggestions">${chips.map((c) => `<button class="chip">${escapeHtml(c)}</button>`).join("")}</div>
    </div>`;
}

// El asistente se ve en dos sitios: en la sección Asistente (la consulta general, sobre todos los clientes) y en la
// pestaña «Asistente IA» del contacto abierto (una conversación por cliente). Los hilos se guardan en state.threads
// y cada panel muestra el suyo, llevándolo a su lista.
const ASSISTANT_PANELS = {
  general: {
    log: "#chat-log", form: "#chat-form", input: "#chat-input", send: "#send-btn", reset: "#new-chat",
    clientId: () => null,
  },
  chats: {
    log: "#chats-assistant-log", form: "#chats-assistant-form", input: "#chats-assistant-input",
    send: "#chats-assistant-send", reset: "#chats-assistant-new", clientId: () => chatState.clientId,
  },
};
const FICHA = ASSISTANT_PANELS.general;

function showGeneralAssistant() {
  showThread(null, FICHA);
  $("#chat-input").focus();
}

function createThread(clientId, panel = FICHA) {
  const el = document.createElement("div");
  el.className = "thread";
  el.innerHTML = emptyChatHtml(clientId);
  $(panel.log).appendChild(el);
  const thread = { el, busy: false, loaded: false };
  state.threads.set(clientId ?? GENERAL, thread);
  loadThreadHistory(clientId, thread);
  return thread;
}

async function loadThreadHistory(clientId, thread) {
  const params = clientId === null ? "" : `?client_id=${clientId}`;
  try {
    const { turns } = await api(`/api/conversations/agent${params}`);
    // Si el usuario ya escribió algo mientras cargaba, se coloca el historial antes.
    const pendingNodes = [...thread.el.querySelectorAll(".msg")];
    turns.forEach((t) => appendBubble(thread.el, t.role === "user" ? "user" : "bot", turnHtml(t), pendingNodes[0] || null));
    thread.loaded = true;
    if (!thread.el.hidden) scrollLog(thread.el.parentElement);
  } catch (err) {
    appendBubble(thread.el, "error", `No se pudo cargar la conversación: ${escapeHtml(err.message)}`);
  }
}

function currentThread(panel = FICHA) {
  const clientId = panel.clientId();
  return state.threads.get(clientId ?? GENERAL) || createThread(clientId, panel);
}

function scrollLog(log) {
  if (log) log.scrollTop = log.scrollHeight;
}

// Muestra en el panel el hilo del cliente (si estaba en el otro panel, se trae aquí).
function showThread(clientId, panel = FICHA) {
  const key = clientId ?? GENERAL;
  const log = $(panel.log);
  const thread = state.threads.get(key) || createThread(clientId, panel);
  if (thread.el.parentElement !== log) log.appendChild(thread.el);
  state.threads.forEach((t, k) => { if (t.el.parentElement === log) t.el.hidden = k !== key; });
  $(panel.send).disabled = thread.busy;
  scrollLog(log);
}

// «Enviar» de cada panel: desactivado mientras su hilo espera respuesta.
function refreshSendButtons() {
  for (const panel of Object.values(ASSISTANT_PANELS)) {
    const thread = state.threads.get(panel.clientId() ?? GENERAL);
    if (thread && thread.el.parentElement === $(panel.log)) $(panel.send).disabled = thread.busy;
  }
}

async function resetCurrentThread(panel = FICHA) {
  const clientId = panel.clientId();
  const key = clientId ?? GENERAL;
  const thread = state.threads.get(key);
  if (thread?.busy) return;
  if (thread?.el.querySelector(".msg.user") && !(await appConfirm("¿Empezar una conversación nueva? La actual dejará de mostrarse.", { ok: "Empezar otra" }))) return;
  try {
    await api("/api/conversations/agent/reset", { method: "POST", body: JSON.stringify({ client_id: clientId }) });
  } catch (err) {
    alert(err.message);
    return;
  }
  thread?.el.remove();
  state.threads.delete(key);
  setThreadDot(clientId, false);
  if (panel.clientId() === clientId) showThread(clientId, panel);
}

const TOOL_LABELS = {
  buscar_cliente: "buscó cliente",
  resumen_cliente: "consultó ficha",
  buscar_mensajes: "buscó",
  leer_contexto: "leyó contexto",
};

function renderTrace(toolCalls) {
  if (!toolCalls || !toolCalls.length) return "";
  const items = toolCalls.map((t) => {
    const team = t.input.alcance === "equipo";
    const detail = t.input.consulta || t.input.texto || "";
    const label = `${TOOL_LABELS[t.name] || t.name}${detail ? ` «${escapeHtml(detail)}»` : ""}${team ? " · equipo" : ""}`;
    return `<span class="${team ? "team" : ""}">${label}</span>`;
  });
  return `<div class="trace">${items.join("")}</div>`;
}

async function sendMessage(text, panel = FICHA) {
  if (!text.trim()) return;
  // Se fija el hilo al enviar: si el usuario cambia de cliente (o de panel) mientras espera,
  // la respuesta llega igualmente al hilo correcto.
  const clientId = panel.clientId();
  const thread = currentThread(panel);
  if (thread.busy) return;
  thread.busy = true;
  refreshSendButtons();
  try {
    const answered = await askBot(thread.el, text, async () => {
      const res = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text, client_id: clientId }) });
      return renderMarkdown(res.reply) + renderTrace(res.tool_calls);
    }, () => scrollLog(thread.el.parentElement));
    if (answered) setThreadDot(clientId, true);
  } finally {
    thread.busy = false;
    refreshSendButtons();
    if (!thread.el.hidden) scrollLog(thread.el.parentElement);
  }
}

function bindAssistant(panel) {
  bindComposer($(panel.form), $(panel.input), (text) => sendMessage(text, panel));
  $(panel.log).addEventListener("click", (e) => {
    if (e.target.classList.contains("chip")) sendMessage(e.target.textContent, panel);
  });
  $(panel.reset).addEventListener("click", () => resetCurrentThread(panel));
}

/* ---------- Mascota de ayuda ---------- */

function toggleHelp(open) {
  const panel = $("#help-panel");
  const show = open ?? panel.hidden;
  panel.hidden = !show;
  $("#help").classList.toggle("open", show);
  if (show) {
    if (!state.helpLoaded) loadHelpHistory();
    $("#help-input").focus();
  }
}

async function loadHelpHistory() {
  state.helpLoaded = true;
  try {
    const { turns } = await api("/api/conversations/help");
    const log = $("#help-log");
    turns.forEach((t) => appendBubble(log, t.role === "user" ? "user" : "bot", turnHtml(t)));
    log.scrollTop = log.scrollHeight;
  } catch { state.helpLoaded = false; }
}

async function sendHelp(text) {
  if (!text.trim()) return;
  const log = $("#help-log");
  $("#help-send").disabled = true;
  setChispaThinking(true);
  try {
    await askBot(log, text, async () => {
      const res = await api("/api/help", { method: "POST", body: JSON.stringify({ message: text }) });
      return renderMarkdown(res.reply);
    }, () => { log.scrollTop = log.scrollHeight; });
  } finally {
    setChispaThinking(false);
    $("#help-send").disabled = false;
    log.scrollTop = log.scrollHeight;
  }
}

/* ---------- Eventos ---------- */

// Textarea que crece con el contenido; Enter envía y Mayús+Enter salta de línea.
function bindComposer(form, input, onSend) {
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    input.style.height = "";
    onSend(text);
  });
  input.addEventListener("keydown", (e) => {
    // (Si un desplegable de la caja, como el de /respuestas, ya ha usado el Intro, no se envía.)
    if (e.key === "Enter" && !e.shiftKey && !e.defaultPrevented) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  });
}

function bindEvents() {
  bindAssistant(FICHA);

  bindComposer($("#help-form"), $("#help-input"), sendHelp);
  $("#mascot").addEventListener("click", () => toggleHelp());
  bindChispa();
  bindChatActions();
  $("#help-close").addEventListener("click", () => toggleHelp(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#help-panel").hidden && !tour) toggleHelp(false);
  });
}

(async function init() {
  let user;
  try {
    user = await api("/api/me"); // si no hay sesión, api() redirige a login.html
  } catch {
    return;
  }
  bindUiEvents();
  initAccount(user);
  document.body.classList.remove("booting");
  bindLayoutEvents();
  bindAccountEvents();
  bindProfileEvents();
  bindInboxEvents();
  bindDraftEvents();
  bindReplyEvents();
  bindPaletteEvents();
  bindPresenceEvents();
  bindNotesEvents();
  bindClientEvents();
  bindDashboardEvents();
  bindDocumentEvents();
  bindSearchEvents();
  bindIntegrationEvents();
  bindChatsEvents();
  bindBreadcrumbEvents();
  bindCompanyEvents();
  bindSidebarEvents();
  bindTopbarEvents();
  bindContactsEvents();
  bindTemplatesEvents();
  bindAIEvents();
  bindEvents();
  try {
    state.convClients = new Set(await api("/api/conversations/agent/clients"));
    await Promise.all([initProfile(), loadSettings()]);
    await loadTagOptions();
    refreshInboxCount();
    loadNotifications();
    showView(savedView());
  } catch (err) {
    appendBubble($("#chat-log"), "error", `No se pudo conectar con el servidor: ${escapeHtml(err.message)}`);
  }
  maybeStartTour();
})();
