// Mis Chats y la vista de contacto. A la izquierda, la lista de la que se viene: los chats (Todos / No leídos /
// Sin responder) o, si el contacto se abrió desde Contactos, la lista de contactos. En el centro, el contacto con sus
// pestañas: Conversación (por canal, con la caja de escribir), Ficha, Tareas y Notas. A la derecha, Detalles o el
// asistente. Se envía por la cuenta conectada del canal. También cambia entre las secciones de la barra lateral.

const VIEW_KEY = "pc-view";
const CHATS_REFRESH = 20000; // la lista y la conversación abierta se actualizan solas cada 20 s
const chatState = {
  clientId: null, data: null, channel: null, channels: [], filter: "all", scope: "mine", query: "",
  origin: "chats", // de dónde se abrió el contacto: «chats» (Mis Chats) o «contacts» (Contactos)
  tab: "conversation", // pestaña del contacto: conversation, profile, tasks o notes
  conversationId: null, baseline: null, // conversación por la que se responde y su último mensaje al abrirla
  details: true, // panel derecho visible
  file: null, // archivo elegido para enviar con el próximo mensaje
  newEmail: false, // escribiendo un correo nuevo (con asunto) en vez de responder en el hilo
  detailsPane: "info", // panel derecho: «info» (detalles del contacto) o «assistant» (asistente IA)
  composing: false, // hay texto en la caja de escribir (se avisa a los compañeros: «está respondiendo»)
};
const CHAT_MAX_FILE = 15 * 1024 * 1024;
let chatsSearchTimer = null;
let contactsMiniTimer = null;

/* ---------- Secciones de la barra lateral ---------- */

// Vistas. «client» es la vista de contacto abierta desde Contactos: usa la misma pantalla que Mis Chats, con la lista
// de contactos a la izquierda, y en la barra lateral cuenta como Contactos.
const VIEWS = { chats: "#view-chats", client: "#view-chats", contacts: "#view-contacts", tasks: "#view-tasks",
                assistant: "#view-assistant", templates: "#view-templates", ai: "#view-ai", dashboard: "#view-dashboard" };
let viewName = null;

function currentView() {
  return viewName;
}

function showView(name) {
  if (!VIEWS[name]) name = "chats";
  new Set(Object.values(VIEWS)).forEach((sel) => { $(sel).hidden = sel !== VIEWS[name]; });
  viewName = name;
  if (name === "chats" || name === "client") {
    const origin = name === "client" ? "contacts" : "chats";
    if (chatState.origin !== origin) closeChat(); // el contacto abierto era del otro sitio
    chatState.origin = origin;
    $("#view-chats").dataset.origin = origin;
  }
  const section = name === "client" ? "contacts" : name;
  document.querySelectorAll(".sidebar [data-view]").forEach((b) => {
    const active = b.dataset.view === section;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  try { localStorage.setItem(VIEW_KEY, section); } catch { /* almacenamiento no disponible */ }
  updateBreadcrumb();
  if (name === "chats") loadChats();
  if (name === "client") {
    $("#contacts-mini-search").value = $("#contacts-search").value;
    loadContactsMini();
  }
  if (name === "contacts") loadContacts();
  if (name === "tasks") loadMyTasks().catch((err) => alert(err.message));
  if (name === "assistant") showGeneralAssistant();
  if (name === "ai") loadAISettings().catch((err) => alert(err.message));
  if (name === "dashboard") loadDashboard().catch((err) => alert(err.message));
  else hideTooltip();
  if (name === "templates") {
    if (tplState.accounts.length) loadTemplateList(); else openTemplatesView(); // el estado en Meta cambia: se relee
  }
}

function savedView() {
  try {
    const saved = localStorage.getItem(VIEW_KEY);
    return ["contacts", "tasks", "assistant", "templates", "ai", "dashboard"].includes(saved) ? saved : "chats";
  } catch { return "chats"; }
}

/* ---------- Lista de chats ---------- */

function initialsOf(name) {
  return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
}

// «10:41» si es de hoy, «Ayer», el día de la semana si es de esta semana y la fecha si es anterior.
function chatTime(iso) {
  const at = new Date(iso);
  const today = new Date();
  const days = Math.round((new Date(today.toDateString()) - new Date(at.toDateString())) / 86400000);
  if (days === 0) return at.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  if (days === 1) return "Ayer";
  if (days < 7) return at.toLocaleDateString("es-ES", { weekday: "long" });
  return at.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

function unreadBadge(n) {
  return n ? `<span class="unread" title="Mensajes sin leer">${n > 99 ? "99+" : n}</span>` : "";
}

function chatItemHtml(c) {
  return `
    <li data-client="${c.id}" class="${c.id === chatState.clientId ? "active" : ""}${c.unread ? " has-unread" : ""}">
      <span class="chat-avatar">${escapeHtml(initialsOf(c.name))}</span>
      <div class="chat-item-body">
        <div class="chat-item-top"><strong>${escapeHtml(c.name)}</strong><span class="chat-item-time">${escapeHtml(chatTime(c.last_at))}</span></div>
        <div class="chat-item-bottom">
          <span class="chat-preview">${c.last_direction === "out" ? "↪ " : ""}${escapeHtml(c.last_body)}</span>${unreadBadge(c.unread)}
        </div>
        <div class="chat-item-meta">${c.channels.map(badge).join("")}${tagChips(c.tags, 2)}</div>
      </div>
    </li>`;
}

async function loadChats() {
  if (chatState.filter === "inbox") return loadInbox().catch(() => { /* se reintenta en la siguiente actualización */ });
  const params = new URLSearchParams({ scope: chatState.scope, q: chatState.query });
  if (chatState.filter === "unread") params.set("unread", "true");
  try {
    const items = await api(`/api/chats?${params}`);
    $("#chats-list").innerHTML = items.length ? items.map(chatItemHtml).join("")
      : `<li class="chats-empty muted small">${chatState.filter === "unread" ? "No tienes chats sin leer." : chatState.query
        ? "Ningún chat coincide con la búsqueda." : "Todavía no hay conversaciones. Conecta tus cuentas en «Mis cuentas»."}</li>`;
  } catch (err) {
    $("#chats-list").innerHTML = `<li class="form-error">${escapeHtml(err.message)}</li>`;
  }
}

// Todos · No leídos · Sin responder (la bandeja: quién espera respuesta, con sus plazos).
function setChatsFilter(filter) {
  chatState.filter = filter;
  document.querySelectorAll("#chats-filter [data-filter]").forEach((b) => b.classList.toggle("active", b.dataset.filter === filter));
  const inbox = filter === "inbox";
  $("#chats-list").hidden = inbox;
  $("#chats-search").hidden = inbox;
  $("#chats-scope").hidden = inbox || currentUser.role !== "admin"; // la bandeja tiene su propio «Mías / Todo el equipo»
  $("#side-inbox").hidden = !inbox;
  loadChats();
}

/* ---------- Lista de contactos (al abrir uno desde Contactos) ---------- */

// Los mismos contactos que la tabla, con sus filtros, en formato compacto.
function contactMiniHtml(c) {
  return `
    <li data-client="${c.id}" class="${c.id === chatState.clientId ? "active" : ""}${c.unread ? " has-unread" : ""}">
      <span class="chat-avatar">${escapeHtml(initialsOf(c.name))}</span>
      <div class="chat-item-body">
        <div class="chat-item-top"><strong>${statusDot(c.status)}${escapeHtml(c.name)}</strong>
          ${c.last_message_at ? `<span class="chat-item-time">${escapeHtml(chatTime(c.last_message_at))}</span>` : ""}</div>
        <div class="chat-item-bottom"><span class="chat-preview">${escapeHtml(c.company || "")}</span>${unreadBadge(c.unread)}</div>
        <div class="chat-item-meta">${c.channels.map(badge).join("")}${tagChips(c.tags, 2)}</div>
      </div>
    </li>`;
}

async function loadContactsMini() {
  try {
    const items = await api(`/api/contacts?${contactsQuery()}`);
    $("#contacts-mini").innerHTML = items.length ? items.map(contactMiniHtml).join("")
      : `<li class="chats-empty muted small">Ningún contacto coincide con los filtros.</li>`;
  } catch (err) {
    $("#contacts-mini").innerHTML = `<li class="form-error">${escapeHtml(err.message)}</li>`;
  }
}

/* ---------- Contacto abierto ---------- */

// Conversaciones que se ven: todas las del cliente o, con «Solo mis conversaciones», las tuyas.
function chatConversations() {
  const convs = chatState.data?.conversations || [];
  return state.scope === "team" ? convs : convs.filter((c) => c.is_mine);
}

function syncScope() {
  state.scope = $("#only-mine").checked ? "mine" : "team";
}

// Pestañas de canal: los canales con conversación (la más reciente primero) y, si tiene email, también Email para
// escribirle un correo nuevo aunque no haya hilos. Se mantiene la elegida («Todos los canales» = "") si la hay.
function renderChannelTabs() {
  const channels = [...new Set(chatConversations().map((c) => c.channel))];
  if (chatState.data.identities.some((i) => i.channel === "email") && !channels.includes("email")) channels.push("email");
  chatState.channels = channels;
  if (chatState.channel !== "" && !channels.includes(chatState.channel)) chatState.channel = channels[0] || null;
  $("#chat-tabs").innerHTML = channelTabsHtml(channels, chatState.channel);
}

function markActiveContact() {
  document.querySelectorAll("#chats-list li[data-client], #contacts-mini li[data-client]").forEach((li) =>
    li.classList.toggle("active", Number(li.dataset.client) === chatState.clientId));
}

// Abre un contacto en esta vista (o lo recarga, si ya estaba abierto).
async function openChat(clientId) {
  const changed = chatState.clientId !== clientId;
  if (changed) {
    setChatFile(null); // el archivo elegido era para otro contacto
    resetComposerExtras();
    closeResults();
    $("#presence-bar").hidden = true;
  }
  chatState.clientId = clientId;
  state.clientId = clientId;
  markActiveContact();
  if (changed) heartbeat();
  const data = await api(`/api/clients/${clientId}`);
  if (chatState.clientId !== clientId) return; // ya se eligió otro
  chatState.data = data;
  state.clientData = data;
  clientNames.set(clientId, data.name);
  // Desde Mis Chats se ven tus conversaciones (o las del equipo, si un administrador lo eligió); desde Contactos,
  // todo el historial del cliente.
  if (changed) $("#only-mine").checked = chatState.origin === "chats" && chatState.scope === "mine";
  syncScope();
  renderChannelTabs();
  $("#chat-empty").hidden = true;
  $("#chat-open").hidden = false;
  $("#chat-avatar").textContent = initialsOf(data.name);
  renderClientHeader(data);
  renderChatDetails(data);
  toggleChatDetails(chatState.details);
  showDetailsPane(chatState.detailsPane);
  showDetailTab(chatState.tab);
  await Promise.all([loadChatConversation(), openClientDetail(clientId), recordVisit(clientId), loadDuplicates(clientId)]);
}

async function loadChatConversation(keepScroll = false) {
  const { clientId, channel } = chatState;
  if (!clientId || channel === null) {
    $("#chat-timeline").innerHTML = `<li class="muted">${state.scope === "mine" && chatState.data?.conversations.length
      ? "Tú no has hablado con este cliente. Desmarca «Solo mis conversaciones» para ver las del equipo." : "Sin mensajes."}</li>`;
    if (chatState.data) await prepareComposer();
    return;
  }
  const params = new URLSearchParams({ scope: state.scope });
  if (channel) params.set("channel", channel);
  const messages = await api(`/api/clients/${clientId}/timeline?${params}`);
  if (chatState.clientId !== clientId || chatState.channel !== channel) return;
  const list = $("#chat-timeline");
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
  list.innerHTML = messages.length ? timelineHtml(messages) : `<li class="muted">Sin mensajes por este canal.</li>`;
  if (!keepScroll || atBottom) list.scrollTop = list.scrollHeight;
  await prepareComposer();
}

// Por dónde se responde: la conversación propia del canal (la más reciente) y si hay cuenta conectada para enviar.
// Correo nuevo: aparece el asunto y se envía como hilo nuevo (POST /api/clients/{id}/emails).
function setNewEmail(on) {
  chatState.newEmail = on;
  $("#chat-subject").hidden = !on;
  $("#chat-new-email").textContent = on ? "Responder en el hilo" : "✉ Nuevo correo";
  if (!on) $("#chat-send").textContent = "Enviar"; // prepareComposer pone «Enviar por …» si hay cuenta
  if (on) {
    $("#chat-send").disabled = false;
    $("#chat-file").disabled = false;
    $("#draft-copy").hidden = true;
    $("#chat-send").textContent = "Enviar correo";
    $("#chat-send-note").hidden = true;
    $("#chat-subject").focus();
  }
}

// Canal por el que se responde: el de la pestaña o, en «Todos los canales», el más reciente.
function replyChannel() {
  return chatState.channel || chatState.channels[0] || null;
}

async function prepareComposer() {
  const channel = replyChannel();
  const conv = chatState.data.conversations.find((c) => c.channel === channel && c.is_mine);
  const note = $("#chat-send-note");
  const email = channel === "email";
  $("#chat-new-email").hidden = !email;
  if (!email || conv) setNewEmail(false);
  if (email && !chatState.data.conversations.some((c) => c.channel === "email")) {
    chatState.conversationId = null;
    $("#chat-template").hidden = true;
    $("#chat-ai-draft").disabled = true;
    $("#chat-new-email").hidden = true; // sin hilo al que responder: solo correo nuevo
    return setNewEmail(true);
  }
  const disable = (text) => {
    chatState.conversationId = conv?.id || null;
    note.textContent = text;
    note.hidden = !text;
    $("#chat-send").disabled = true;
    $("#chat-file").disabled = true;
    $("#chat-ai-draft").disabled = !conv;
    $("#draft-copy").hidden = !conv; // sin cuenta conectada: se copia para pegarlo en el móvil o el correo
    $("#chat-template").hidden = true;
    loadChatAI(conv?.channel === "whatsapp" ? conv.id : null);
  };
  if (!conv) {
    const other = chatState.data.conversations.find((c) => c.channel === channel);
    return disable(other ? `Esta conversación la lleva ${other.owner}: responde ella o él.` : "");
  }
  try {
    const s = await api(`/api/conversations/${conv.id}/sender`);
    if (replyChannel() !== conv.channel) return;
    chatState.baseline = s.last_message_id;
    if (!s.can_send) {
      return disable(`Para responder desde aquí, conecta tu cuenta de ${IDENTITY_LABELS[conv.channel] || conv.channel} en «Mis cuentas».`);
    }
    chatState.conversationId = conv.id;
    $("#chat-template").hidden = conv.channel !== "whatsapp"; // las plantillas solo existen en WhatsApp
    note.hidden = true;
    $("#chat-send").disabled = false;
    $("#chat-file").disabled = false;
    $("#chat-ai-draft").disabled = false;
    $("#draft-copy").hidden = true;
    $("#chat-send").textContent = `Enviar por ${s.via}`;
    loadChatAI(conv.channel === "whatsapp" ? conv.id : null);
  } catch {
    disable("No se ha podido comprobar la cuenta de envío.");
  }
}

// El archivo elegido, en base64 para enviarlo con el mensaje.
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("No se pudo leer el archivo."));
    reader.readAsDataURL(file);
  });
}

function setChatFile(file) {
  if (file && file.size > CHAT_MAX_FILE) {
    alert("El archivo supera el máximo de 15 MB.");
    file = null;
  }
  chatState.file = file || null;
  $("#chat-file").value = "";
  const chip = $("#chat-file-chip");
  chip.hidden = !file;
  chip.innerHTML = file ? `📎 ${escapeHtml(file.name)} <span class="muted small">(${Math.max(1, Math.round(file.size / 1024))} KB)</span>
    <button type="button" class="link small" id="chat-file-remove" aria-label="Quitar el archivo">×</button>` : "";
}

async function sendNewEmail(text) {
  const subject = $("#chat-subject").value.trim();
  if (!subject) {
    $("#chat-text").value = text;
    $("#chat-subject").focus();
    return alert("Ponle un asunto al correo.");
  }
  const file = chatState.file;
  const btn = $("#chat-send");
  btn.disabled = true;
  try {
    const payload = { subject, text, file: file ? { filename: file.name, mime: file.type || null, data: await fileToBase64(file) } : null };
    await api(`/api/clients/${chatState.clientId}/emails`, { method: "POST", body: JSON.stringify(payload) });
    $("#chat-subject").value = "";
    setChatFile(null);
    chatState.channel = "email";
    await openChat(chatState.clientId); // el correo abre un hilo nuevo: se recargan las conversaciones
    loadChats();
  } catch (err) {
    $("#chat-text").value = text;
    alert(err.message);
  } finally {
    btn.disabled = false;
  }
}

async function sendChatMessage(text) {
  text = text.trim();
  if (chatState.newEmail) return sendNewEmail(text);
  const convId = chatState.conversationId;
  const file = chatState.file;
  if ((!text && !file) || !convId || $("#chat-send").disabled) return;
  const btn = $("#chat-send");
  btn.disabled = true;
  let payload;
  try {
    payload = { text, file: file ? { filename: file.name, mime: file.type || null, data: await fileToBase64(file) } : null };
  } catch (err) {
    btn.disabled = false;
    $("#chat-text").value = text;
    return alert(err.message);
  }
  const send = (force) => api(`/api/conversations/${convId}/send`, {
    method: "POST", body: JSON.stringify({ ...payload, after_message_id: chatState.baseline, force }),
  });
  try {
    try {
      await send(false);
    } catch (err) {
      if (err.status !== 409) throw err;
      if (!confirm(`${err.message}\n\n¿Enviar de todos modos?`)) {
        $("#chat-text").value = text; // se recupera lo escrito
        return;
      }
      await send(true);
    }
    setChatFile(null);
    resetComposerExtras({ keepFollowUp: true });
    const note = await scheduleFollowUp(convId);
    showComposerNote(note);
    setComposing(false);
    await loadChatConversation();
    loadChats();
    refreshInboxCount();
  } catch (err) {
    $("#chat-text").value = text;
    alert(err.message);
  } finally {
    btn.disabled = !chatState.conversationId;
  }
}

// Avisa a los compañeros de que estás respondiendo a este cliente mientras hay algo escrito.
function setComposing(on) {
  if (chatState.composing === on) return;
  chatState.composing = on;
  heartbeat();
}

/* ---------- Detalles del contacto ---------- */

function renderChatDetails(data) {
  const row = (label, value) => value ? `<div class="detail-row"><span class="muted small">${label}</span><span>${value}</span></div>` : "";
  const identities = data.identities.map((i) =>
    `<div class="detail-row"><span class="muted small">${escapeHtml(IDENTITY_LABELS[i.channel] || i.channel)}</span><span>${escapeHtml(i.handle)}</span></div>`).join("");
  $("#chat-details-body").innerHTML = `
    <h3>Detalles del contacto</h3>
    <div class="chat-details-card">
      <span class="chat-avatar large">${escapeHtml(initialsOf(data.name))}</span>
      <strong>${escapeHtml(data.name)}</strong>
      ${data.company ? `<span class="muted small">${escapeHtml(data.company)}</span>` : ""}
    </div>
    <h4>Información básica</h4>
    ${row("Estado", `${statusDot(data.status)} ${escapeHtml(STATUS_LABELS[data.status] || data.status)}`)}
    ${identities || `<p class="muted small">Sin datos de contacto.</p>`}
    <h4>Responsable</h4>
    ${row("Agente asignado", escapeHtml(data.assignee || "Sin asignar"))}
    <h4>Etiquetas</h4>
    <div class="chip-row">${data.tags.length ? tagChips(data.tags) : `<span class="muted small">Sin etiquetas</span>`}</div>`;
}

/* ---------- Panel derecho: detalles del contacto o el asistente ---------- */

function showDetailsPane(pane) {
  chatState.detailsPane = pane;
  document.querySelectorAll("#chat-details-tabs [data-pane]").forEach((b) => b.classList.toggle("active", b.dataset.pane === pane));
  $("#chat-details-body").hidden = pane !== "info";
  $("#chats-assistant").hidden = pane !== "assistant";
  if (pane === "assistant" && chatState.clientId) {
    $("#chats-assistant-context").textContent = `Conversación sobre ${chatState.data?.name || "este contacto"}`;
    showThread(chatState.clientId, ASSISTANT_PANELS.chats);
    $("#chats-assistant-input").focus();
  }
}

function toggleChatDetails(show) {
  const panel = $("#chat-details");
  const open = show ?? panel.hidden;
  chatState.details = open;
  panel.hidden = !open;
  $("#chat-details-toggle").setAttribute("aria-pressed", String(open));
}

// Sin ningún contacto abierto (al pulsar la sección en la ruta de navegación, al cambiar de sección, al borrarlo…).
function closeChat() {
  const had = chatState.clientId !== null;
  chatState.clientId = null;
  chatState.data = null;
  state.clientId = null;
  state.clientData = null;
  markActiveContact();
  $("#chat-open").hidden = true;
  $("#chat-empty").hidden = false;
  $("#chat-empty").textContent = chatState.origin === "contacts"
    ? "Elige un contacto de la lista para ver su ficha y sus conversaciones."
    : "Elige un chat de la lista para ver la conversación.";
  $("#chat-details").hidden = true;
  setChatFile(null);
  chatState.composing = false;
  if (had) heartbeat();
  updateBreadcrumb();
}

/* ---------- Eventos ---------- */

function bindChatsEvents() {
  document.querySelectorAll(".sidebar [data-view]").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  $("#chats-scope").hidden = currentUser.role !== "admin";
  $("#chats-search").addEventListener("input", (e) => {
    clearTimeout(chatsSearchTimer);
    chatsSearchTimer = setTimeout(() => { chatState.query = e.target.value; loadChats(); }, 200);
  });
  document.querySelectorAll("#chats-filter [data-filter]").forEach((b) =>
    b.addEventListener("click", () => setChatsFilter(b.dataset.filter)));
  $("#chats-scope").addEventListener("change", (e) => {
    chatState.scope = e.target.value;
    loadChats();
    if (chatState.clientId) {
      $("#only-mine").checked = chatState.scope === "mine";
      openChat(chatState.clientId);
    }
  });
  ["#chats-list", "#contacts-mini"].forEach((sel) => $(sel).addEventListener("click", (e) => {
    const li = e.target.closest("li[data-client]");
    if (li) openChat(Number(li.dataset.client)).catch((err) => alert(err.message));
  }));
  $("#contacts-back").addEventListener("click", () => showView("contacts"));
  $("#contacts-mini-search").addEventListener("input", (e) => {
    $("#contacts-search").value = e.target.value; // la misma búsqueda que la tabla
    clearTimeout(contactsMiniTimer);
    contactsMiniTimer = setTimeout(loadContactsMini, 200);
  });
  document.querySelectorAll(".contact-tabs [data-tab]").forEach((b) =>
    b.addEventListener("click", () => showDetailTab(b.dataset.tab)));
  $("#chat-tabs").addEventListener("click", (e) => {
    const tab = e.target.closest("[data-channel]");
    if (!tab) return;
    chatState.channel = tab.dataset.channel;
    setActiveChannelTab($("#chat-tabs"), chatState.channel);
    loadChatConversation();
  });
  $("#only-mine").addEventListener("change", () => {
    syncScope();
    renderChannelTabs();
    loadChatConversation();
  });
  $("#msg-search-toggle").addEventListener("click", () => {
    const form = $("#msg-search-form");
    form.hidden = !form.hidden;
    $("#msg-search-toggle").setAttribute("aria-pressed", String(!form.hidden));
    if (form.hidden) closeResults(); else $("#msg-search").focus();
  });
  bindComposer($("#chat-composer"), $("#chat-text"), sendChatMessage);
  $("#chat-text").addEventListener("input", (e) => setComposing(!!e.target.value.trim()));
  $("#chat-file").addEventListener("change", (e) => setChatFile(e.target.files[0]));
  $("#chat-new-email").addEventListener("click", () => {
    if (chatState.newEmail) prepareComposer().then(() => setNewEmail(false)); else setNewEmail(true);
  });
  $("#chat-file-chip").addEventListener("click", (e) => { if (e.target.closest("#chat-file-remove")) setChatFile(null); });
  $("#chat-details-toggle").addEventListener("click", () => toggleChatDetails());
  $("#chat-details-tabs").addEventListener("click", (e) => {
    const tab = e.target.closest("[data-pane]");
    if (tab) showDetailsPane(tab.dataset.pane);
  });
  bindAssistant(ASSISTANT_PANELS.chats);
  setInterval(() => {
    if (document.hidden || $("#view-chats").hidden) return;
    if (chatState.origin === "chats") loadChats(); else loadContactsMini();
    if (chatState.clientId && chatState.tab === "conversation" && !$("#chat-text").value) loadChatConversation(true).catch(() => {});
  }, CHATS_REFRESH);
}
