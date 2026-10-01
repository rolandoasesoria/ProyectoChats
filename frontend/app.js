// ProyectoChats — pantalla principal. Utilidades comunes en common.js; cuenta en account.js; tutorial en tour.js.

const GENERAL = "general"; // clave del hilo sin cliente seleccionado

const state = {
  clientId: null,
  scope: "team",  // historial del cliente: todo el equipo, salvo «Solo mis conversaciones»
  channel: "",
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

function appendBubble(container, role, html) {
  container.querySelector(".empty-chat")?.remove();
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = html;
  container.appendChild(div);
  return div;
}

const TYPING = `<span class="typing"><i></i><i></i><i></i></span>`;

/* ---------- Clientes ---------- */

const clientNames = new Map();

function threadDot() {
  return `<span class="has-thread" title="Tienes una conversación abierta"></span>`;
}

async function loadClients(q = "") {
  const params = clientFilterParams();
  params.set("q", q);
  const clients = await api(`/api/clients?${params}`);
  clients.forEach((c) => clientNames.set(c.id, c.name));
  const general = `
    <li data-id="" class="general ${state.clientId === null ? "active" : ""}">
      <span class="client-name">Consulta general</span>
      <span class="muted">Buscar en todos los clientes</span>
    </li>`;
  const items = clients.map((c) => `
    <li data-id="${c.id}" class="${c.id === state.clientId ? "active" : ""}">
      <span class="client-name">${statusDot(c.status)}${escapeHtml(c.name)}${state.convClients.has(c.id) ? threadDot() : ""}${c.unread ? `<span class="unread" title="Mensajes nuevos desde tu última visita">${c.unread}</span>` : ""}</span>
      ${c.company ? `<span class="muted">${escapeHtml(c.company)}</span>` : ""}
      <span class="client-meta">${(c.channels || "").split(",").filter(Boolean).map(badge).join("")}${tagChips(c.tags, 2)}</span>
    </li>`).join("");
  $("#client-list").innerHTML = general + (items || `<li class="muted">Sin resultados</li>`);
}

function setThreadDot(clientId, on) {
  if (clientId === null) return;
  if (on) state.convClients.add(clientId);
  else state.convClients.delete(clientId);
  const name = document.querySelector(`#client-list li[data-id="${clientId}"] .client-name`);
  if (!name) return;
  const dot = name.querySelector(".has-thread");
  if (on && !dot) name.insertAdjacentHTML("beforeend", threadDot());
  if (!on) dot?.remove();
}

async function selectClient(id) {
  state.clientId = id;
  document.querySelectorAll("#client-list li[data-id]").forEach((li) =>
    li.classList.toggle("active", (li.dataset.id ? Number(li.dataset.id) : null) === id));
  showThread(id);
  closeDraftPanel();
  closeResults();

  if (id === null) {
    $("#chat-context").textContent = "Consulta general · puede buscar en todos los clientes";
    $(".detail-empty").hidden = false;
    $(".detail-body").hidden = true;
    return;
  }

  const data = await api(`/api/clients/${id}`);
  clientNames.set(id, data.name);
  state.clientData = data;
  if (state.clientId !== id) return; // el usuario ya cambió de cliente
  $("#chat-context").textContent = `Conversación sobre ${data.name}`;
  $(".detail-empty").hidden = true;
  $(".detail-body").hidden = false;
  renderClientHeader(data);

  const channels = [...new Set(data.conversations.map((c) => c.channel))];
  state.channel = "";
  $("#channel-filter").innerHTML = `<option value="">Todos los canales</option>` +
    channels.map((ch) => `<option value="${escapeHtml(ch)}">${escapeHtml(IDENTITY_LABELS[ch] || ch)}</option>`).join("");
  await Promise.all([loadTimeline(), openClientDetail(id), recordVisit(id), loadDuplicates(id)]);
}

async function loadTimeline() {
  if (!state.clientId) return;
  const clientId = state.clientId;
  const params = new URLSearchParams({ scope: state.scope });
  if (state.channel) params.set("channel", state.channel);
  const messages = await api(`/api/clients/${clientId}/timeline?${params}`);
  if (state.clientId !== clientId) return;
  const list = $("#timeline");
  if (!messages.length) {
    list.innerHTML = `<li class="muted">${state.scope === "mine"
      ? "Tú no has hablado con este cliente. Desmarca «Solo mis conversaciones» para ver las del equipo."
      : "Sin mensajes."}</li>`;
    return;
  }
  list.innerHTML = messages.map((m) => `
    <li class="${escapeHtml(m.channel)} ${m.direction}" data-id="${m.id}">
      <div class="meta">${badge(m.channel)} ${escapeHtml(m.sender)} · ${formatDate(m.sent_at)}${m.owner_id !== currentUser.id ? ` · <span class="owner-tag" title="Conversación que lleva ${escapeHtml(m.owner)}">la lleva ${escapeHtml(m.owner)}</span>` : ""}</div>
      ${escapeHtml(m.body)}${attachmentChips(m.attachments)}
    </li>`).join("");
  list.scrollTop = list.scrollHeight;
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

function createThread(clientId) {
  const el = document.createElement("div");
  el.className = "thread";
  el.innerHTML = emptyChatHtml(clientId);
  $("#chat-log").appendChild(el);
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
    if (turns.length) thread.el.querySelector(".empty-chat")?.remove();
    turns.forEach((t) => {
      const html = t.role === "user" ? escapeHtml(t.text) : renderMarkdown(t.text) + renderTrace(t.tool_calls);
      const div = document.createElement("div");
      div.className = `msg ${t.role === "user" ? "user" : "bot"}`;
      div.innerHTML = html;
      thread.el.insertBefore(div, pendingNodes[0] || null);
    });
    thread.loaded = true;
    if (state.threads.get(state.clientId ?? GENERAL) === thread) scrollChat();
  } catch (err) {
    appendBubble(thread.el, "error", `No se pudo cargar la conversación: ${escapeHtml(err.message)}`);
  }
}

function currentThread() {
  return state.threads.get(state.clientId ?? GENERAL) || createThread(state.clientId);
}

function scrollChat() {
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
}

function showThread(clientId) {
  const key = clientId ?? GENERAL;
  const thread = state.threads.get(key) || createThread(clientId);
  state.threads.forEach((t, k) => { t.el.hidden = k !== key; });
  $("#send-btn").disabled = thread.busy;
  scrollChat();
}

async function resetCurrentThread() {
  const clientId = state.clientId;
  const key = clientId ?? GENERAL;
  const thread = state.threads.get(key);
  if (thread?.busy) return;
  if (thread?.el.querySelector(".msg.user") && !confirm("¿Empezar una conversación nueva? La actual dejará de mostrarse.")) return;
  try {
    await api("/api/conversations/agent/reset", { method: "POST", body: JSON.stringify({ client_id: clientId }) });
  } catch (err) {
    alert(err.message);
    return;
  }
  thread?.el.remove();
  state.threads.delete(key);
  setThreadDot(clientId, false);
  if (state.clientId === clientId) showThread(clientId);
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

async function sendMessage(text) {
  if (!text.trim()) return;
  // Se fija el hilo al enviar: si el usuario cambia de cliente mientras espera,
  // la respuesta llega igualmente al hilo correcto.
  const clientId = state.clientId;
  const thread = currentThread();
  if (thread.busy) return;
  thread.busy = true;
  $("#send-btn").disabled = true;
  appendBubble(thread.el, "user", escapeHtml(text));
  const pending = appendBubble(thread.el, "bot", TYPING);
  scrollChat();
  try {
    const res = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: text, client_id: clientId }),
    });
    pending.innerHTML = renderMarkdown(res.reply) + renderTrace(res.tool_calls);
    setThreadDot(clientId, true);
  } catch (err) {
    pending.className = "msg error";
    pending.textContent = err.message;
  } finally {
    thread.busy = false;
    if (state.threads.get(state.clientId ?? GENERAL) === thread) {
      $("#send-btn").disabled = false;
      scrollChat();
    }
  }
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
    turns.forEach((t) => appendBubble(log, t.role === "user" ? "user" : "bot",
      t.role === "user" ? escapeHtml(t.text) : renderMarkdown(t.text)));
    log.scrollTop = log.scrollHeight;
  } catch { state.helpLoaded = false; }
}

async function sendHelp(text) {
  if (!text.trim()) return;
  const log = $("#help-log");
  appendBubble(log, "user", escapeHtml(text));
  const pending = appendBubble(log, "bot", TYPING);
  log.scrollTop = log.scrollHeight;
  $("#help-send").disabled = true;
  try {
    const res = await api("/api/help", { method: "POST", body: JSON.stringify({ message: text }) });
    pending.innerHTML = renderMarkdown(res.reply);
  } catch (err) {
    pending.className = "msg error";
    pending.textContent = err.message;
  } finally {
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
    if (e.key === "Enter" && !e.shiftKey) {
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
  let searchTimer;
  $("#client-search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadClients(e.target.value), 200);
  });
  $("#client-list").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-id]");
    if (li) selectClient(li.dataset.id ? Number(li.dataset.id) : null);
  });

  $("#only-mine").addEventListener("change", (e) => {
    state.scope = e.target.checked ? "mine" : "team";
    loadTimeline();
  });
  $("#channel-filter").addEventListener("change", (e) => {
    state.channel = e.target.value;
    loadTimeline();
  });

  bindComposer($("#chat-form"), $("#chat-input"), sendMessage);
  $("#chat-log").addEventListener("click", (e) => {
    if (e.target.classList.contains("chip")) sendMessage(e.target.textContent);
  });
  $("#new-chat").addEventListener("click", resetCurrentThread);

  bindComposer($("#help-form"), $("#help-input"), sendHelp);
  $("#mascot").addEventListener("click", () => toggleHelp());
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
  initAccount(user);
  document.body.classList.remove("booting");
  bindAccountEvents();
  bindImportEvents();
  bindProfileEvents();
  bindInboxEvents();
  bindDraftEvents();
  bindReplyEvents();
  bindPaletteEvents();
  bindNotesEvents();
  bindClientEvents();
  bindDashboardEvents();
  bindDocumentEvents();
  bindSearchEvents();
  bindIntegrationEvents();
  bindEvents();
  try {
    state.convClients = new Set(await api("/api/conversations/agent/clients"));
    await Promise.all([initProfile(), loadSettings()]);
    await loadTagOptions();
    refreshInboxCount();
    loadNotifications();
    await loadClients();
    await selectClient(null);
  } catch (err) {
    appendBubble($("#chat-log"), "error", `No se pudo conectar con el servidor: ${escapeHtml(err.message)}`);
  }
  maybeStartTour();
})();
