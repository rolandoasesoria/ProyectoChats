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
      <span class="chat-avatar ${avatarClass(c.name)}">${escapeHtml(initialsOf(c.name))}</span>
      <div class="chat-item-body">
        <div class="chat-item-top"><strong>${escapeHtml(c.name)}</strong><span class="chat-item-time">${escapeHtml(chatTime(c.last_at))}</span></div>
        <div class="chat-item-bottom">
          <span class="chat-preview">${draftPreviewHtml(c.id) || `${c.last_direction === "out" ? "↪ " : ""}${escapeHtml(c.last_body)}`}</span>${unreadBadge(c.unread)}
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
  loadChats(); // con «Sin responder», la bandeja (inbox.js), en la misma lista
}

/* ---------- Lista de contactos (al abrir uno desde Contactos) ---------- */

// Los mismos contactos que la tabla, con sus filtros, en formato compacto.
function contactMiniHtml(c) {
  return `
    <li data-client="${c.id}" class="${c.id === chatState.clientId ? "active" : ""}${c.unread ? " has-unread" : ""}">
      <span class="chat-avatar ${avatarClass(c.name)}">${escapeHtml(initialsOf(c.name))}</span>
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
    const query = contactsQuery();
    const items = await api(`/api/contacts?${query}`);
    // Bajo «Contactos»: cuántos hay en la lista y si la tabla tiene filtros puestos.
    const filtered = [...query.entries()].some(([k, v]) => v && k !== "q") || !!query.get("q")?.trim();
    $("#contacts-mini-count").textContent =
      `${items.length} ${items.length === 1 ? "contacto" : "contactos"}${filtered ? " · con filtros" : ""}`;
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
  // Lo que se estaba escribiendo se queda en su chat (borrador); la caja se vacía para el nuevo contacto.
  const draftsChanged = changed && (saveChatDraft(chatState.clientId) || Boolean(chatDrafts()[clientId]));
  if (changed) {
    clearComposerText();
    chatState.composing = false; // el «está respondiendo» era para el otro contacto
    setChatFile(null); // el archivo elegido era para otro contacto
    discardVoice(); // y la nota de voz que se estaba grabando, también
    clearReply();
    resetComposerExtras();
    closeResults();
    $("#presence-bar").hidden = true;
  }
  chatState.clientId = clientId;
  state.clientId = clientId;
  markActiveContact();
  if (changed) heartbeat();
  if (draftsChanged) loadChats(); // «Borrador: …» aparece en el chat que se deja y se quita del que se abre
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
  if (changed) restoreChatDraft(clientId);
  $("#chat-avatar").textContent = initialsOf(data.name);
  $("#chat-avatar").className = `chat-avatar ${avatarClass(data.name)}`;
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
    $("#chat-timeline").dataset.sig = "";
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
  // Al refrescar sola, la conversación no se vuelve a pintar si no ha cambiado nada, ni mientras suena un audio o un
  // vídeo o está abierto el menú de reacciones (se cortarían).
  const sig = JSON.stringify(messages.map((m) => [m.id, m.status, m.reactions, m.reply_to_id, m.body.length]));
  const busy = [...list.querySelectorAll("audio, video")].some((x) => !x.paused)
    || !$("#react-tray").hidden || !$("#emoji-picker").hidden;
  if (keepScroll && (sig === list.dataset.sig || busy)) return prepareComposer();
  list.dataset.sig = sig;
  chatState.messagesById = new Map(messages.map((m) => [m.id, m]));
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
  list.innerHTML = messages.length ? timelineHtml(messages) : `<li class="muted">Sin mensajes por este canal.</li>`;
  if (!keepScroll || atBottom) list.scrollTop = list.scrollHeight;
  hydrateLinkPreviews(list);
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
  syncComposerTools();
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
    syncComposerTools();
    loadChatAI(conv?.channel === "whatsapp" ? conv.id : null);
  };
  if (!conv) {
    const other = chatState.data.conversations.find((c) => c.channel === channel);
    return disable(other ? `Esta conversación entró por la cuenta de ${other.owner}: se responde desde su cuenta.` : "");
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
    syncComposerTools();
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
  // Las fotos, con su miniatura (como al adjuntarlas en WhatsApp)
  const thumb = file?.type.startsWith("image/") && file.size <= 8 * 1024 * 1024;
  chip.hidden = !file;
  chip.innerHTML = file ? `${thumb ? '<img class="chip-thumb" alt="">' : "📎"} ${escapeHtml(file.name)} <span class="muted small">(${Math.max(1, Math.round(file.size / 1024))} KB)</span>
    <button type="button" class="link small" id="chat-file-remove" aria-label="Quitar el archivo">×</button>` : "";
  if (thumb) {
    const reader = new FileReader();
    reader.onload = () => { if (chatState.file === file) chip.querySelector(".chip-thumb")?.setAttribute("src", reader.result); };
    reader.readAsDataURL(file);
  }
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
    dropChatDraft(chatState.clientId);
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
    // La cita solo vale en la conversación por la que se responde (si se cambió de canal, se envía sin ella)
    const quote = chatState.replyTo?.conversationId === convId ? chatState.replyTo.id : null;
    payload = { text, file: file ? { filename: file.name, mime: file.type || null, data: await fileToBase64(file) } : null,
                reply_to_message_id: quote };
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
      if (!(await appConfirm(`${err.message}\n\n¿Enviar de todos modos?`, { ok: "Enviar igualmente" }))) {
        $("#chat-text").value = text; // se recupera lo escrito
        return;
      }
      await send(true);
    }
    setChatFile(null);
    clearReply();
    dropChatDraft(chatState.clientId);
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

// Color del avatar de cada persona: siempre el mismo para el mismo nombre (8 tonos suaves, ver .av-N en styles.css).
function avatarClass(name) {
  let h = 0;
  for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `av-${h % 8}`;
}

const CHANNEL_ICONS = {
  email: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>`,
  whatsapp: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 11.5a8.5 8.5 0 0 1-12.6 7.4L3.5 20l1.2-4.2a8.5 8.5 0 1 1 15.8-4.3z"/><path d="M9 8.5c0 3.5 3 6.5 6.5 6.5l1-1.6-2-1-1 1a5 5 0 0 1-2.4-2.4l1-1-1-2z"/></svg>`,
  telegram: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 4L3 11l6 2.5L19 7l-8 8v5l3.5-3.5L18 19z"/></svg>`,
  phone: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/></svg>`,
  other: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>`,
};
const EDIT_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>`;
const COPY_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>`;

// Fechas de la tarjeta Actividad, todas con el mismo formato: «Hoy, 10:41», «Ayer, 16:31» o «5 ago 2026».
function activityDate(iso) {
  const at = new Date(iso);
  const days = Math.round((new Date(new Date().toDateString()) - new Date(at.toDateString())) / 86400000);
  const time = at.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  if (days === 0) return `Hoy, ${time}`;
  if (days === 1) return `Ayer, ${time}`;
  return at.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" }).replace(".", "");
}

// Panel derecho, pestaña Detalles: la identidad centrada con sus acciones rápidas y, debajo, tarjetas con el contacto,
// el responsable, las etiquetas, los datos clave (de la Ficha) y la actividad.
function renderChatDetails(data) {
  const convs = data.conversations || [];
  const first = convs.map((c) => c.first_at).filter(Boolean).sort()[0];
  const last = convs.map((c) => c.last_at).filter(Boolean).sort().at(-1);
  const messages = convs.reduce((n, c) => n + (c.messages || 0), 0);
  const actions = chatState.channels.map((ch) => `
      <button type="button" class="cd-action ${escapeHtml(ch)}" data-cd-channel="${escapeHtml(ch)}" title="Ver la conversación por ${escapeHtml(IDENTITY_LABELS[ch] || ch)}">
        <span class="cd-action-icon">${CHANNEL_ICONS[ch] || CHANNEL_ICONS.other}</span>${escapeHtml(ch === "email" ? "Correo" : IDENTITY_LABELS[ch] || ch)}</button>`).join("");
  const identities = data.identities.map((i) => `
      <li class="cd-identity ${escapeHtml(i.channel)}">
        <span class="cd-ch-icon" title="${escapeHtml(IDENTITY_LABELS[i.channel] || i.channel)}">${CHANNEL_ICONS[i.channel] || CHANNEL_ICONS.other}</span>
        <span class="cd-handle">${escapeHtml(i.handle)}</span>
        <button type="button" class="cd-copy" data-copy="${escapeHtml(i.handle)}" title="Copiar" aria-label="Copiar ${escapeHtml(i.handle)}">${COPY_ICON}</button>
      </li>`).join("");
  const row = (label, value, id = "") => `<div class="cd-row"${id ? ` id="${id}"` : ""}><span>${label}</span><strong>${value}</strong></div>`;
  $("#chat-details-body").innerHTML = `
    <div class="cd-hero">
      <span class="chat-avatar xl ${avatarClass(data.name)}">${escapeHtml(initialsOf(data.name))}</span>
      <h3 class="cd-name">${escapeHtml(data.name)}</h3>
      ${data.company ? `<span class="cd-company">${escapeHtml(data.company)}</span>` : ""}
      <div class="cd-pills">
        <span class="status-pill ${escapeHtml(data.status)}">${statusDot(data.status)}${escapeHtml(STATUS_LABELS[data.status] || data.status)}</span>
        <span id="cd-priority"></span>
      </div>
      <div class="cd-actions">${actions}
        <button type="button" class="cd-action" data-cd-edit title="Editar sus datos, responsable y etiquetas">
          <span class="cd-action-icon">${EDIT_ICON}</span>Editar</button>
      </div>
    </div>
    <section class="cd-card">
      <h4>Contacto</h4>
      ${identities ? `<ul class="cd-identities">${identities}</ul>` : `<p class="cd-empty">Sin datos de contacto.</p>`}
    </section>
    <section class="cd-card cd-pop-card">
      <h4>Responsable</h4>
      ${data.assignee ? `<button type="button" class="cd-person" data-cd-assign aria-haspopup="menu" title="Cambiar el responsable">
          ${userAvatarHtml(team.find((u) => u.id === data.assignee_user_id) || { name: data.assignee }, "small")}
          <span class="cd-person-name">${escapeHtml(data.assignee)}</span><span class="cd-change">Cambiar</span></button>`
        : `<button type="button" class="cd-add" data-cd-assign aria-haspopup="menu">+ Asignar responsable</button>`}
      <div class="menu cd-menu" id="cd-assign-menu" role="menu" hidden></div>
    </section>
    <section class="cd-card cd-pop-card">
      <h4>Etiquetas</h4>
      <div class="chip-row">${data.tags.map((t) => `<span class="chip-tag cd-tag">${escapeHtml(t)}<button type="button" class="cd-untag"
          data-cd-untag="${escapeHtml(t)}" title="Quitar la etiqueta" aria-label="Quitar la etiqueta ${escapeHtml(t)}">×</button></span>`).join("")}
        <button type="button" class="cd-add" data-cd-tag aria-haspopup="true">+ ${data.tags.length ? "Añadir" : "Añadir etiqueta"}</button></div>
      <div class="menu cd-menu cd-tag-menu" id="cd-tag-menu" hidden>
        <input id="cd-tag-input" maxlength="40" placeholder="Escribe o elige una etiqueta" autocomplete="off">
        <ul class="cd-menu-list" id="cd-tag-options"></ul>
      </div>
    </section>
    <section class="cd-card" id="cd-key">
      <h4>Datos clave</h4>
      <div id="cd-key-rows"><p class="cd-empty">Cargando…</p></div>
      <button type="button" class="cd-link" data-cd-tab="profile">Ver la ficha completa →</button>
    </section>
    <section class="cd-card">
      <h4>Actividad</h4>
      ${row("Primer contacto", first ? escapeHtml(activityDate(first)) : "—")}
      ${row("Último mensaje", last ? escapeHtml(activityDate(last)) : "—")}
      ${row("Conversaciones", `${convs.length} · ${messages} ${messages === 1 ? "mensaje" : "mensajes"}`)}
      ${row("Tareas abiertas", "—", "cd-tasks")}
    </section>`;
  // Al redibujar el mismo contacto (tras cambiar su responsable o sus etiquetas) se conserva lo que ya se cargó:
  // prioridad, datos clave y tareas. Con otro contacto se espera a que lleguen los suyos.
  if (chatState.detailsFor !== data.id) {
    chatState.detailsFor = data.id;
    chatState.keyFacts = null;
    chatState.keyProps = null;
    chatState.detailsProfile = null;
    chatState.detailsTasks = null;
    return;
  }
  if (chatState.detailsProfile) $("#cd-priority").innerHTML = priorityChips(chatState.detailsProfile);
  renderDetailsKeyData();
  if (chatState.detailsTasks) setDetailsTasks(data.id, chatState.detailsTasks);
}

// Datos clave: los de la Ficha (los extrae la IA o se añaden a mano) y las propiedades rellenas (DNI, origen…).
function renderDetailsKeyData() {
  const box = $("#cd-key-rows");
  if (!box || chatState.keyFacts === null) return;
  const items = [...(chatState.keyProps || []), ...chatState.keyFacts].slice(0, 5);
  box.innerHTML = items.length
    ? items.map((f) => `<div class="cd-row"><span>${escapeHtml(f.label)}</span><strong title="${escapeHtml(f.value)}">${escapeHtml(f.value)}</strong></div>`).join("")
    : `<p class="cd-empty">Todavía no hay datos. Pulsa «✨ Actualizar con IA» en la Ficha o añádelos a mano.</p>`;
}

// Al cargar la Ficha (profile.js): prioridad que ve la IA y sus datos clave.
function setDetailsProfile(clientId, p) {
  if (chatState.clientId !== clientId || !$("#cd-priority")) return;
  chatState.detailsProfile = p;
  $("#cd-priority").innerHTML = priorityChips(p);
  chatState.keyFacts = p.facts.map((f) => ({ label: f.label, value: f.value }));
  renderDetailsKeyData();
}

// Al cargar las propiedades (contacts.js): las que tienen valor.
function setDetailsProperties(clientId, props, values) {
  if (chatState.clientId !== clientId) return;
  chatState.keyProps = props.filter((p) => values[p.id]).map((p) => ({ label: p.label, value: String(values[p.id]) }));
  renderDetailsKeyData();
}

// Al cargar sus tareas (profile.js).
function setDetailsTasks(clientId, open) {
  const row = $("#cd-tasks");
  if (chatState.clientId !== clientId || !row) return;
  chatState.detailsTasks = open;
  const overdue = open.filter((t) => t.due_date && t.due_date <= todayIso()).length;
  row.querySelector("strong").innerHTML = open.length
    ? `${open.length}${overdue ? ` <span class="cd-overdue">· ${overdue} para hoy o vencida${overdue === 1 ? "" : "s"}</span>` : ""}` : "Ninguna";
}

/* ---------- Responsable y etiquetas, directamente desde Detalles ---------- */

function closeDetailsMenus(except = null) {
  document.querySelectorAll("#chat-details-body .cd-menu").forEach((m) => { if (m !== except) m.hidden = true; });
}

function toggleAssignMenu() {
  const menu = $("#cd-assign-menu");
  if (!menu.hidden) return closeDetailsMenus();
  closeDetailsMenus(menu);
  const current = chatState.data?.assignee_user_id ?? null;
  const option = (id, label, avatar) => `<button type="button" role="menuitem" class="cd-menu-item${id === current ? " selected" : ""}"
      data-assign-to="${id ?? ""}">${avatar}<span>${escapeHtml(label)}</span></button>`;
  menu.innerHTML = team.map((u) => option(u.id, u.id === currentUser.id ? `${u.name} (tú)` : u.name,
    userAvatarHtml(u, "tiny"))).join("")
    + option(null, "Sin responsable", `<span class="chat-avatar tiny cd-none">–</span>`);
  menu.hidden = false;
}

async function assignClient(userId) {
  closeDetailsMenus();
  const clientId = chatState.clientId;
  try {
    await api(`/api/clients/${clientId}`, { method: "PATCH", body: JSON.stringify({ assignee_user_id: userId }) });
    if (chatState.clientId !== clientId) return;
    const data = await refreshCurrentClient();
    toast(data.assignee ? `Ahora lleva a ${data.name}: ${data.assignee}.` : `${data.name} queda sin responsable.`, "success");
    loadClients();
  } catch (err) {
    alert(err.message);
  }
}

// Sugerencias al añadir una etiqueta: las básicas y las que ya usa el equipo, filtradas por lo escrito.
function renderDetailsTagOptions() {
  const typed = $("#cd-tag-input").value.trim();
  const have = new Set((chatState.data?.tags || []).map((t) => t.toLowerCase()));
  const all = [...new Set([...BASIC_TAGS, ...knownTags.map((t) => t.tag)])].filter((t) => !have.has(t.toLowerCase()));
  const matches = all.filter((t) => normText(t).includes(normText(typed))).slice(0, 8);
  const create = typed && !all.some((t) => t.toLowerCase() === typed.toLowerCase()) && !have.has(typed.toLowerCase());
  $("#cd-tag-options").innerHTML = (create ? [`<li><button type="button" class="cd-menu-item" data-add-tag="${escapeHtml(typed)}">Crear «${escapeHtml(typed)}»</button></li>`] : [])
    .concat(matches.map((t) => `<li><button type="button" class="cd-menu-item" data-add-tag="${escapeHtml(t)}">${escapeHtml(t)}</button></li>`))
    .join("") || `<li class="muted small cd-menu-empty">Ya tiene todas las etiquetas.</li>`;
}

function toggleTagMenu() {
  const menu = $("#cd-tag-menu");
  if (!menu.hidden) return closeDetailsMenus();
  closeDetailsMenus(menu);
  menu.hidden = false;
  $("#cd-tag-input").value = "";
  renderDetailsTagOptions();
  $("#cd-tag-input").focus();
}

async function saveTags(tags, message) {
  closeDetailsMenus();
  const clientId = chatState.clientId;
  try {
    await api(`/api/clients/${clientId}/tags`, { method: "PUT", body: JSON.stringify({ tags }) });
    if (chatState.clientId !== clientId) return;
    await refreshCurrentClient();
    toast(message, "success");
    loadTagOptions().catch(() => {});
    loadClients();
  } catch (err) {
    alert(err.message);
  }
}

function addDetailsTag(tag) {
  const tags = [...(chatState.data?.tags || []), tag.trim()];
  return saveTags(tags, `Etiqueta «${tag.trim()}» añadida.`);
}

async function onDetailsClick(e) {
  if (e.target.closest("[data-cd-assign]")) return toggleAssignMenu();
  const assign = e.target.closest("[data-assign-to]");
  if (assign) return assignClient(assign.dataset.assignTo ? Number(assign.dataset.assignTo) : null);
  if (e.target.closest("[data-cd-tag]")) return toggleTagMenu();
  const add = e.target.closest("[data-add-tag]");
  if (add) return addDetailsTag(add.dataset.addTag);
  const untag = e.target.closest("[data-cd-untag]");
  if (untag) {
    const tag = untag.dataset.cdUntag;
    return saveTags((chatState.data?.tags || []).filter((t) => t !== tag), `Etiqueta «${tag}» quitada.`);
  }
  const channel = e.target.closest("[data-cd-channel]");
  if (channel) {
    showDetailTab("conversation");
    chatState.channel = channel.dataset.cdChannel;
    setActiveChannelTab($("#chat-tabs"), chatState.channel);
    return loadChatConversation();
  }
  if (e.target.closest("[data-cd-edit]")) return openClientDialog("edit");
  const tab = e.target.closest("[data-cd-tab]");
  if (tab) return showDetailTab(tab.dataset.cdTab);
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    try {
      await navigator.clipboard.writeText(copy.dataset.copy);
      copy.classList.add("copied");
      copy.title = "¡Copiado!";
      setTimeout(() => { copy.classList.remove("copied"); copy.title = "Copiar"; }, 1500);
    } catch { /* sin portapapeles: se puede seleccionar el texto */ }
  }
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
  const draftsChanged = saveChatDraft(chatState.clientId);
  clearComposerText();
  clearReply();
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
  if (draftsChanged) loadChats();
  updateBreadcrumb();
}

// «Mis chats / Todo el equipo»: los administradores y quien tenga el permiso que da un administrador.
function canViewTeamChats() {
  return currentUser.role === "admin" || !!currentUser.can_view_team_chats;
}

/* ---------- Eventos ---------- */

function bindChatsEvents() {
  document.querySelectorAll(".sidebar [data-view]").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  $("#chats-scope").hidden = !canViewTeamChats();
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
    // Los de «Sin responder» los abre la bandeja (inbox.js), en el mensaje que espera respuesta.
    if (li && !li.classList.contains("inbox-item")) openChat(Number(li.dataset.client)).catch((err) => alert(err.message));
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
    clearReply();
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
  // Al recargar o cerrar la página, lo escrito se guarda como borrador de su chat
  window.addEventListener("pagehide", () => saveChatDraft(chatState.clientId));
  $("#chat-file").addEventListener("change", (e) => setChatFile(e.target.files[0]));
  $("#chat-new-email").addEventListener("click", () => {
    if (chatState.newEmail) prepareComposer().then(() => setNewEmail(false)); else setNewEmail(true);
  });
  $("#chat-file-chip").addEventListener("click", (e) => { if (e.target.closest("#chat-file-remove")) setChatFile(null); });
  $("#chat-details-toggle").addEventListener("click", () => toggleChatDetails());
  $("#chat-details-body").addEventListener("click", onDetailsClick);
  $("#chat-details-body").addEventListener("input", (e) => { if (e.target.id === "cd-tag-input") renderDetailsTagOptions(); });
  $("#chat-details-body").addEventListener("keydown", (e) => {
    if (e.target.id !== "cd-tag-input") return;
    if (e.key === "Escape") { e.stopPropagation(); closeDetailsMenus(); }
    if (e.key === "Enter" && e.target.value.trim()) { e.preventDefault(); addDetailsTag(e.target.value); }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".cd-pop-card")) closeDetailsMenus(); });
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
