// Sección Chats: la lista de conversaciones por cliente (Todos / No leídos), la conversación separada por canal
// (WhatsApp, Email, Telegram) con la caja de escribir abajo, y los datos del contacto a la derecha. Se envía por la
// cuenta conectada del canal, igual que desde el borrador. También cambia entre las secciones de la barra lateral.

const VIEW_KEY = "pc-view";
const CHATS_REFRESH = 20000; // la lista y la conversación abierta se actualizan solas cada 20 s
const chatState = {
  clientId: null, data: null, channel: null, unread: false, scope: "mine", query: "",
  conversationId: null, baseline: null, // conversación por la que se responde y su último mensaje al abrirla
  details: true, // panel «Detalles del contacto» visible
};
let chatsSearchTimer = null;

/* ---------- Secciones de la barra lateral ---------- */

function showView(name) {
  const chats = name === "chats";
  $("#view-chats").hidden = !chats;
  $(".layout").hidden = chats;
  document.querySelectorAll(".sidebar [data-view]").forEach((b) => {
    const active = b.dataset.view === name;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  try { localStorage.setItem(VIEW_KEY, name); } catch { /* almacenamiento no disponible */ }
  if (chats) loadChats();
}

function savedView() {
  try { return localStorage.getItem(VIEW_KEY) === "clients" ? "clients" : "chats"; } catch { return "chats"; }
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

function chatItemHtml(c) {
  const unread = c.unread ? `<span class="unread" title="Mensajes sin leer">${c.unread > 99 ? "99+" : c.unread}</span>` : "";
  return `
    <li data-client="${c.id}" class="${c.id === chatState.clientId ? "active" : ""}${c.unread ? " has-unread" : ""}">
      <span class="chat-avatar">${escapeHtml(initialsOf(c.name))}</span>
      <div class="chat-item-body">
        <div class="chat-item-top"><strong>${escapeHtml(c.name)}</strong><span class="chat-item-time">${escapeHtml(chatTime(c.last_at))}</span></div>
        <div class="chat-item-bottom">
          <span class="chat-preview">${c.last_direction === "out" ? "↪ " : ""}${escapeHtml(c.last_body)}</span>${unread}
        </div>
        <div class="chat-item-meta">${c.channels.map(badge).join("")}${tagChips(c.tags, 2)}</div>
      </div>
    </li>`;
}

async function loadChats() {
  const params = new URLSearchParams({ scope: chatState.scope, q: chatState.query });
  if (chatState.unread) params.set("unread", "true");
  try {
    const items = await api(`/api/chats?${params}`);
    $("#chats-list").innerHTML = items.length ? items.map(chatItemHtml).join("")
      : `<li class="chats-empty muted small">${chatState.unread ? "No tienes chats sin leer." : chatState.query
        ? "Ningún chat coincide con la búsqueda." : "Todavía no hay conversaciones. Conecta tus cuentas en «Mis cuentas»."}</li>`;
  } catch (err) {
    $("#chats-list").innerHTML = `<li class="form-error">${escapeHtml(err.message)}</li>`;
  }
}

/* ---------- Conversación abierta ---------- */

function chatConversations() {
  const convs = chatState.data?.conversations || [];
  return chatState.scope === "team" ? convs : convs.filter((c) => c.is_mine);
}

async function openChat(clientId) {
  chatState.clientId = clientId;
  document.querySelectorAll("#chats-list li[data-client]").forEach((li) =>
    li.classList.toggle("active", Number(li.dataset.client) === clientId));
  const data = await api(`/api/clients/${clientId}`);
  if (chatState.clientId !== clientId) return; // ya se eligió otro chat
  chatState.data = data;
  // Pestañas: los canales en los que hay conversación, el más reciente primero.
  const channels = [...new Set(chatConversations().map((c) => c.channel))];
  if (!channels.includes(chatState.channel)) chatState.channel = channels[0] || null;
  $("#chat-empty").hidden = true;
  $("#chat-open").hidden = false;
  $("#chat-avatar").textContent = initialsOf(data.name);
  $("#chat-name").textContent = data.name;
  $("#chat-sub").textContent = [data.company, STATUS_LABELS[data.status], data.assignee ? `responsable: ${data.assignee}` : ""]
    .filter(Boolean).join(" · ");
  $("#chat-tabs").innerHTML = channels.map((ch) =>
    `<button role="tab" data-channel="${escapeHtml(ch)}" class="${ch === chatState.channel ? "active" : ""}">${badge(ch)}</button>`).join("");
  renderChatDetails(data);
  toggleChatDetails(chatState.details);
  await Promise.all([loadChatConversation(), api(`/api/clients/${clientId}/visit`, { method: "POST" })]);
  const item = document.querySelector(`#chats-list li[data-client="${clientId}"]`);
  item?.classList.remove("has-unread");
  item?.querySelector(".unread")?.remove();
}

async function loadChatConversation(keepScroll = false) {
  const { clientId, channel } = chatState;
  if (!clientId || !channel) {
    $("#chat-timeline").innerHTML = `<li class="muted">Sin mensajes.</li>`;
    return;
  }
  const params = new URLSearchParams({ scope: chatState.scope, channel });
  const messages = await api(`/api/clients/${clientId}/timeline?${params}`);
  if (chatState.clientId !== clientId || chatState.channel !== channel) return;
  const list = $("#chat-timeline");
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
  list.innerHTML = messages.length ? timelineHtml(messages) : `<li class="muted">Sin mensajes por este canal.</li>`;
  if (!keepScroll || atBottom) list.scrollTop = list.scrollHeight;
  await prepareComposer();
}

// Por dónde se responde: la conversación propia del canal (la más reciente) y si hay cuenta conectada para enviar.
async function prepareComposer() {
  const conv = chatState.data.conversations.find((c) => c.channel === chatState.channel && c.is_mine);
  const note = $("#chat-send-note");
  const disable = (text) => {
    chatState.conversationId = conv?.id || null;
    note.textContent = text;
    note.hidden = !text;
    $("#chat-send").disabled = true;
    $("#chat-ai-draft").disabled = !conv;
  };
  if (!conv) {
    const other = chatState.data.conversations.find((c) => c.channel === chatState.channel);
    return disable(other ? `Esta conversación la lleva ${other.owner}: responde ella o él.` : "");
  }
  try {
    const s = await api(`/api/conversations/${conv.id}/sender`);
    if (chatState.channel !== conv.channel) return;
    chatState.baseline = s.last_message_id;
    if (!s.can_send) {
      return disable(`Para responder desde aquí, conecta tu cuenta de ${IDENTITY_LABELS[conv.channel] || conv.channel} en «Mis cuentas».`);
    }
    chatState.conversationId = conv.id;
    note.hidden = true;
    $("#chat-send").disabled = false;
    $("#chat-ai-draft").disabled = false;
    $("#chat-send").textContent = `Enviar por ${s.via}`;
  } catch {
    disable("No se ha podido comprobar la cuenta de envío.");
  }
}

async function sendChatMessage(text) {
  text = text.trim();
  const convId = chatState.conversationId;
  if (!text || !convId || $("#chat-send").disabled) return;
  const btn = $("#chat-send");
  btn.disabled = true;
  const send = (force) => api(`/api/conversations/${convId}/send`, {
    method: "POST", body: JSON.stringify({ text, after_message_id: chatState.baseline, force }),
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

async function draftChatReply() {
  const btn = $("#chat-ai-draft");
  if (!chatState.conversationId) return;
  btn.disabled = true;
  btn.textContent = "✨ Redactando…";
  try {
    const res = await api(`/api/conversations/${chatState.conversationId}/draft`, {
      method: "POST", body: JSON.stringify({ instructions: "" }),
    });
    const input = $("#chat-text");
    input.value = res.draft;
    input.dispatchEvent(new Event("input"));
    input.focus();
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ Redactar con IA";
  }
}

/* ---------- Detalles del contacto ---------- */

function renderChatDetails(data) {
  const row = (label, value) => value ? `<div class="detail-row"><span class="muted small">${label}</span><span>${value}</span></div>` : "";
  const identities = data.identities.map((i) =>
    `<div class="detail-row"><span class="muted small">${escapeHtml(IDENTITY_LABELS[i.channel] || i.channel)}</span><span>${escapeHtml(i.handle)}</span></div>`).join("");
  $("#chat-details-body").innerHTML = `
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

function toggleChatDetails(show) {
  const panel = $("#chat-details");
  const open = show ?? panel.hidden;
  chatState.details = open;
  panel.hidden = !open;
  $("#chat-details-toggle").setAttribute("aria-pressed", String(open));
}

// «Abrir ficha»: el cliente en la sección Clientes (ficha, tareas, notas y asistente).
async function openChatClient() {
  if (!chatState.clientId) return;
  showView("clients");
  await selectClient(chatState.clientId);
}

/* ---------- Eventos ---------- */

function bindChatsEvents() {
  document.querySelectorAll(".sidebar [data-view]").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  $("#chats-scope").hidden = currentUser.role !== "admin";
  $("#chats-search").addEventListener("input", (e) => {
    clearTimeout(chatsSearchTimer);
    chatsSearchTimer = setTimeout(() => { chatState.query = e.target.value; loadChats(); }, 200);
  });
  document.querySelectorAll("#chats-filter [data-unread]").forEach((b) => b.addEventListener("click", () => {
    chatState.unread = b.dataset.unread === "true";
    document.querySelectorAll("#chats-filter [data-unread]").forEach((x) => x.classList.toggle("active", x === b));
    loadChats();
  }));
  $("#chats-scope").addEventListener("change", (e) => {
    chatState.scope = e.target.value;
    loadChats();
    if (chatState.clientId) openChat(chatState.clientId);
  });
  $("#chats-list").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-client]");
    if (li) openChat(Number(li.dataset.client)).catch((err) => alert(err.message));
  });
  $("#chat-tabs").addEventListener("click", (e) => {
    const tab = e.target.closest("[data-channel]");
    if (!tab) return;
    chatState.channel = tab.dataset.channel;
    document.querySelectorAll("#chat-tabs [data-channel]").forEach((t) => t.classList.toggle("active", t === tab));
    loadChatConversation();
  });
  bindComposer($("#chat-composer"), $("#chat-text"), sendChatMessage);
  $("#chat-ai-draft").addEventListener("click", draftChatReply);
  $("#chat-open-client").addEventListener("click", openChatClient);
  $("#chat-details-toggle").addEventListener("click", () => toggleChatDetails());
  setInterval(() => {
    if (document.hidden || $("#view-chats").hidden) return;
    loadChats();
    if (chatState.clientId && !$("#chat-text").value) loadChatConversation(true).catch(() => {});
  }, CHATS_REFRESH);
}
