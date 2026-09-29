// ProyectoChats — frontend sin frameworks.

const state = {
  userId: null,
  clientId: null,
  clientName: null,
  sessionId: null,
  scope: "mine",
  channel: "",
};

const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": String(state.userId ?? ""),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* sin cuerpo JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

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
  return `<span class="badge ${escapeHtml(channel)}">${escapeHtml(channel)}</span>`;
}

/* ---------- Usuarios ---------- */

async function loadUsers() {
  const users = await api("/api/users");
  const select = $("#user-select");
  select.innerHTML = users.map((u) => `<option value="${u.id}">${escapeHtml(u.name)}</option>`).join("");
  let saved = null;
  try { saved = localStorage.getItem("userId"); } catch { /* almacenamiento no disponible */ }
  if (saved && users.some((u) => String(u.id) === saved)) select.value = saved;
  state.userId = Number(select.value) || null;
  select.addEventListener("change", () => {
    state.userId = Number(select.value);
    try { localStorage.setItem("userId", select.value); } catch { /* ignorar */ }
    resetChat();
    if (state.clientId) selectClient(state.clientId);
  });
}

/* ---------- Clientes ---------- */

async function loadClients(q = "") {
  const clients = await api(`/api/clients?q=${encodeURIComponent(q)}`);
  const list = $("#client-list");
  if (!clients.length) {
    list.innerHTML = `<li class="muted">Sin resultados</li>`;
    return;
  }
  list.innerHTML = clients.map((c) => `
    <li data-id="${c.id}" class="${c.id === state.clientId ? "active" : ""}">
      <span class="client-name">${escapeHtml(c.name)}</span>
      ${c.company ? `<span class="muted">${escapeHtml(c.company)}</span>` : ""}
      <span class="client-meta">${(c.channels || "").split(",").filter(Boolean).map(badge).join("")}</span>
    </li>`).join("");
}

async function selectClient(id) {
  state.clientId = id;
  document.querySelectorAll("#client-list li").forEach((li) => li.classList.toggle("active", Number(li.dataset.id) === id));
  const data = await api(`/api/clients/${id}`);
  state.clientName = data.name;
  $("#chat-context").textContent = `Cliente: ${data.name} · las preguntas se centrarán en este cliente`;

  $(".detail-empty").hidden = true;
  $(".detail-body").hidden = false;
  $("#detail-name").textContent = data.name;
  $("#detail-company").textContent = data.company || "";
  $("#detail-identities").innerHTML = data.identities
    .map((i) => `<div>${badge(i.channel)} ${escapeHtml(i.handle)}</div>`).join("");

  const channels = [...new Set(data.identities.map((i) => i.channel))];
  state.channel = "";
  $("#channel-filter").innerHTML = `<option value="">Todos los canales</option>` +
    channels.map((ch) => `<option value="${escapeHtml(ch)}">${escapeHtml(ch)}</option>`).join("");
  await loadTimeline();
}

async function loadTimeline() {
  if (!state.clientId) return;
  const params = new URLSearchParams({ scope: state.scope });
  if (state.channel) params.set("channel", state.channel);
  const messages = await api(`/api/clients/${state.clientId}/timeline?${params}`);
  const list = $("#timeline");
  if (!messages.length) {
    list.innerHTML = `<li class="muted">${state.scope === "mine"
      ? "No tienes conversaciones con este cliente. Prueba con «Equipo»."
      : "Sin mensajes."}</li>`;
    return;
  }
  list.innerHTML = messages.map((m) => `
    <li class="${escapeHtml(m.channel)} ${m.direction}">
      <div class="meta">${badge(m.channel)} ${escapeHtml(m.sender)} · ${formatDate(m.sent_at)}${state.scope === "team" ? ` · de ${escapeHtml(m.owner)}` : ""}</div>
      ${escapeHtml(m.body)}
    </li>`).join("");
  list.scrollTop = list.scrollHeight;
}

/* ---------- Chat ---------- */

function resetChat() {
  state.sessionId = null;
  $("#chat-log").innerHTML = "";
}

function appendMessage(role, html) {
  const log = $("#chat-log");
  log.querySelector(".empty-chat")?.remove();
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = html;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

const TOOL_LABELS = {
  buscar_cliente: "buscó cliente",
  resumen_cliente: "consultó ficha",
  buscar_mensajes: "buscó",
  leer_contexto: "leyó contexto",
};

function renderTrace(toolCalls) {
  if (!toolCalls.length) return "";
  const items = toolCalls.map((t) => {
    const team = t.input.alcance === "equipo";
    const detail = t.input.consulta || t.input.texto || "";
    const label = `${TOOL_LABELS[t.name] || t.name}${detail ? ` «${escapeHtml(detail)}»` : ""}${team ? " · equipo" : ""}`;
    return `<span class="${team ? "team" : ""}">${label}</span>`;
  });
  return `<div class="trace">${items.join("")}</div>`;
}

async function sendMessage(text) {
  if (!text.trim() || !state.userId) return;
  appendMessage("user", escapeHtml(text));
  const pending = appendMessage("bot", `<span class="typing"><i></i><i></i><i></i></span>`);
  $("#send-btn").disabled = true;
  try {
    const res = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: text, session_id: state.sessionId, client_id: state.clientId }),
    });
    state.sessionId = res.session_id;
    pending.innerHTML = renderMarkdown(res.reply) + renderTrace(res.tool_calls);
  } catch (err) {
    pending.className = "msg error";
    pending.textContent = err.message;
  } finally {
    $("#send-btn").disabled = false;
    $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  }
}

/* ---------- Eventos ---------- */

function bindEvents() {
  let searchTimer;
  $("#client-search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadClients(e.target.value), 200);
  });
  $("#client-list").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-id]");
    if (li) selectClient(Number(li.dataset.id));
  });

  document.querySelectorAll(".segmented button").forEach((btn) => btn.addEventListener("click", () => {
    state.scope = btn.dataset.scope;
    document.querySelectorAll(".segmented button").forEach((b) => b.classList.toggle("active", b === btn));
    loadTimeline();
  }));
  $("#channel-filter").addEventListener("change", (e) => {
    state.channel = e.target.value;
    loadTimeline();
  });

  const input = $("#chat-input");
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    input.style.height = "";
    sendMessage(text);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("#chat-form").requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  });

  $("#chat-log").addEventListener("click", (e) => {
    if (e.target.classList.contains("chip")) sendMessage(e.target.textContent);
  });
  $("#new-chat").addEventListener("click", resetChat);
}

(async function init() {
  bindEvents();
  try {
    await loadUsers();
    await loadClients();
  } catch (err) {
    appendMessage("error", `No se pudo conectar con el servidor: ${escapeHtml(err.message)}`);
  }
})();
