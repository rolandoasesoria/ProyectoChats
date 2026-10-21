// Organizar los chats como en WhatsApp: desde la flecha de cada chat de la lista, fijarlo arriba, archivarlo,
// silenciarlo o marcarlo como no leído; destacar mensajes (★) y ver lo compartido en cada chat (fotos y vídeos,
// documentos, enlaces y destacados) y los destacados de todos los chats. La lista se pinta en chats.js.

const ICON_PIN_SMALL = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 3.5h5l-.8 5.2 3.3 3.3v1.8H7v-1.8l3.3-3.3z"/><path d="M12 13.8v6.7"/></svg>';
const ICON_MUTED = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5.5L6.8 9H3.5v6h3.3l4.2 3.5z"/><path d="M15.5 9.5l5 5M20.5 9.5l-5 5"/></svg>';
const ICON_ARCHIVE = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="4.5" rx="1.2"/><path d="M5 8.5V18a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5M10 12.5h4"/></svg>';
const ICON_STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6l2.6 5.2 5.8.9-4.2 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.2-4.1 5.8-.9z"/></svg>';
const ICON_UNREAD = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12.5V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h8.5"/><circle class="solid" cx="19" cy="6" r="2.8"/></svg>';
const ICON_CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5"/></svg>';
const ICON_PHOTO = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-8 8"/></svg>';
const ICON_FILE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>';
const ICON_LINK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4.5 4.5 0 0 0 6.4.4l3-3a4.5 4.5 0 0 0-6.4-6.4l-1.2 1.2"/><path d="M14 10a4.5 4.5 0 0 0-6.4-.4l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2"/></svg>';

/* ---------- La lista: fijados, silenciados, marcados como no leídos y archivados ---------- */

// Iconos junto al número de no leídos: silenciado y fijado.
function chatFlagsHtml(c) {
  return `${c.muted ? `<span class="chat-flag" title="Silenciado${c.muted_until?.startsWith("9999") ? "" : ` hasta ${escapeHtml(infoDate(c.muted_until).toLowerCase())}`}">${ICON_MUTED}</span>` : ""}`
    + `${c.pinned ? `<span class="chat-flag" title="Fijado">${ICON_PIN_SMALL}</span>` : ""}`;
}

function chatMenuButtonHtml(c) {
  return `<button type="button" class="chat-item-more" data-chat-menu="${c.id}" aria-label="Opciones del chat" aria-haspopup="menu" title="Opciones del chat">${ICON_CHEVRON}</button>`;
}

// Los archivados no salen en la lista: una fila «Archivados» los abre (y una flecha vuelve).
function chatListHtml(items, emptyText) {
  chatState.items = new Map(items.map((c) => [c.id, c]));
  const archived = items.filter((c) => c.archived);
  if (chatState.archivedView) {
    return `<li class="chats-archived-head"><button type="button" class="icon-btn" data-archived-back aria-label="Volver a los chats" title="Volver a los chats">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6l-6 6 6 6"/></svg></button><strong>Archivados</strong></li>`
      + (archived.length ? archived.map(chatItemHtml).join("")
        : `<li class="chats-empty muted small">No tienes chats archivados. Un chat archivado vuelve a la lista cuando el cliente escribe.</li>`);
  }
  const list = items.filter((c) => !c.archived);
  const unread = archived.filter((c) => c.unread || c.marked_unread).length;
  const row = archived.length ? `<li class="chats-archived-row" data-archived-open tabindex="0" role="button">
      <span class="archived-ico">${ICON_ARCHIVE}</span><span class="archived-label">Archivados</span>
      ${unread ? `<span class="unread muted-badge" title="Con mensajes sin leer">${unread}</span>` : `<span class="muted small">${archived.length}</span>`}</li>` : "";
  return row + (list.length ? list.map(chatItemHtml).join("") : `<li class="chats-empty muted small">${emptyText}</li>`);
}

function setArchivedView(on) {
  chatState.archivedView = on;
  closeChatMenu();
  loadChats();
}

/* ---------- Menú de cada chat ---------- */

let chatMenuFor = null;

const CHAT_ACTIONS = {
  pin: { body: { pinned: true } },
  unpin: { body: { pinned: false } },
  archive: { body: { archived: true }, note: "Chat archivado: vuelve a la lista cuando el cliente escriba." },
  unarchive: { body: { archived: false }, note: "Chat desarchivado." },
  unmute: { body: { mute: "off" }, note: "Ya no está silenciado." },
  unread: { body: { unread: true } },
  read: { body: { unread: false } },
};

function renderChatMenu(c, page = "main") {
  const menu = $("#chat-item-menu");
  const item = (act, icon, label, extra = "") => `<button type="button" role="menuitem" data-chat-act="${act}"${extra}>${icon}<span>${label}</span></button>`;
  if (page === "mute") {
    menu.innerHTML = `<div class="menu-head"><strong>Silenciar el chat</strong><span class="muted small">No contará en los chats sin leer de la barra lateral.</span></div>`
      + item("mute", ICON_MUTED, "Durante 8 horas", ' data-value="8h"')
      + item("mute", ICON_MUTED, "Durante 1 semana", ' data-value="week"')
      + item("mute", ICON_MUTED, "Siempre", ' data-value="always"');
    return;
  }
  const unread = c.unread || c.marked_unread;
  menu.innerHTML = [
    item(c.archived ? "unarchive" : "archive", ICON_ARCHIVE, c.archived ? "Desarchivar chat" : "Archivar chat"),
    c.muted ? item("unmute", ICON_MUTED, "Dejar de silenciar") : item("mute-menu", ICON_MUTED, "Silenciar…"),
    c.archived ? "" : item(c.pinned ? "unpin" : "pin", ICON_PIN_SMALL, c.pinned ? "Desfijar chat" : "Fijar chat"),
    item(unread ? "read" : "unread", ICON_UNREAD, unread ? "Marcar como leído" : "Marcar como no leído"),
  ].join("");
}

function openChatMenu(button, clientId) {
  const c = chatState.items?.get(clientId);
  if (!c) return;
  if (chatMenuFor === clientId && !$("#chat-item-menu").hidden) return closeChatMenu();
  chatMenuFor = clientId;
  renderChatMenu(c);
  const menu = $("#chat-item-menu");
  menu.hidden = false;
  document.querySelectorAll("[data-chat-menu]").forEach((b) => b.classList.toggle("open", b === button));
  const r = button.getBoundingClientRect();
  menu.style.left = `${Math.min(r.right - menu.offsetWidth, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${r.bottom + 6 + menu.offsetHeight > window.innerHeight ? r.top - menu.offsetHeight - 6 : r.bottom + 6}px`;
}

function closeChatMenu() {
  $("#chat-item-menu").hidden = true;
  document.querySelectorAll("[data-chat-menu].open").forEach((b) => b.classList.remove("open"));
  chatMenuFor = null;
}

async function chatMenuAction(act, value) {
  const id = chatMenuFor;
  if (act === "mute-menu") return renderChatMenu(chatState.items.get(id), "mute");
  const action = act === "mute" ? { body: { mute: value }, note: "Chat silenciado." } : CHAT_ACTIONS[act];
  closeChatMenu();
  try {
    await api(`/api/chats/${id}/prefs`, { method: "PUT", body: JSON.stringify(action.body) });
  } catch (err) {
    return alert(err.message);
  }
  if (action.note) toast(action.note, "success");
  await loadChats();
  refreshNavCounts();
}

/* ---------- Mensajes destacados ---------- */

async function toggleStar(id) {
  const m = chatState.messagesById?.get(id);
  if (!m) return;
  try {
    await api(`/api/messages/${id}/star`, { method: "POST", body: JSON.stringify({ starred: !m.starred }) });
  } catch (err) {
    return alert(err.message);
  }
  await loadChatConversation(true);
  if (!$("#shared-dialog").open) return;
  sharedState.starred = await api(sharedState.global ? "/api/starred" : `/api/clients/${sharedState.clientId}/starred`);
  renderShared();
}

/* ---------- Lo compartido en el chat: fotos y vídeos, documentos, enlaces y destacados ---------- */

const SHARED_TABS = { media: "Fotos y vídeos", docs: "Documentos", links: "Enlaces", starred: "Destacados" };
const sharedState = { clientId: null, data: null, starred: [], tab: "media", global: false };

// Los números del panel Detalles (y las últimas fotos). Se piden al pintar la conversación.
async function loadSharedCounts(clientId) {
  try {
    const [data, starred] = await Promise.all([api(`/api/clients/${clientId}/shared?scope=${state.scope}`),
      api(`/api/clients/${clientId}/starred`)]);
    if (chatState.clientId !== clientId) return;
    chatState.shared = { clientId, data, starred };
    renderSharedCard();
  } catch {
    /* se reintenta al volver a pintar la conversación */
  }
}

function renderSharedCard() {
  const box = $("#cd-shared-body");
  const s = chatState.shared;
  if (!box || !s || s.clientId !== chatState.clientId) return;
  const photos = s.data.media.filter((f) => f.mime.startsWith("image/")).slice(0, 4);
  const count = (tab, icon, n) => `<button type="button" class="cd-shared-count" data-shared-open="${tab}" title="${SHARED_TABS[tab]}">
      ${icon}<strong>${n}</strong><span>${SHARED_TABS[tab]}</span></button>`;
  box.innerHTML = `${photos.length ? `<div class="cd-shared-thumbs">${photos.map((f) => `<button type="button" class="cd-shared-thumb" data-shared-open="media"
      aria-label="Ver fotos y vídeos"><img src="${attachmentUrl(f.id)}" alt="" loading="lazy"></button>`).join("")}</div>` : ""}
    <div class="cd-shared-counts">${count("media", ICON_PHOTO, s.data.media.length)}${count("docs", ICON_FILE, s.data.docs.length)}
      ${count("links", ICON_LINK, s.data.links.length)}${count("starred", ICON_STAR, s.starred.length)}</div>`;
}

// «Octubre de 2026»: los archivos se agrupan por mes, como en WhatsApp.
function monthLabel(iso) {
  const d = new Date(iso);
  const label = d.toLocaleDateString("es-ES", { month: "long", year: "numeric" });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function byMonth(items, render) {
  let current = null;
  return items.map((x) => {
    const month = monthLabel(x.sent_at);
    const head = month !== current ? `<li class="shared-month">${escapeHtml(month)}</li>` : "";
    current = month;
    return head + render(x);
  }).join("");
}

function sharedMeta(x) {
  const who = x.direction === "out" ? `${x.sender} (equipo)` : x.sender;
  return `${escapeHtml(who)} · ${escapeHtml(infoDate(x.sent_at))}`;
}

function goButton(x, clientId) {
  return `<button type="button" class="link small" data-go-message="${x.message_id ?? x.id}" data-go-client="${clientId}" data-go-channel="${escapeHtml(x.channel)}">Ir al mensaje</button>`;
}

function sharedListHtml() {
  const { tab, data, starred, global, clientId } = sharedState;
  const empty = (text) => `<p class="shared-empty muted">${text}</p>`;
  if (tab === "starred") {
    if (!starred.length) {
      return empty("Sin mensajes destacados. Pasa el ratón por un mensaje y pulsa ★ para encontrarlo luego aquí.");
    }
    return `<ul class="shared-list starred-list">${starred.map((m) => `
      <li class="starred-item ${m.direction}">
        <div class="starred-head">${global ? `<strong>${escapeHtml(m.client)}</strong> · ` : ""}<span>${sharedMeta(m)}</span>
          <span class="ch-label">${escapeHtml(IDENTITY_LABELS[m.channel] || m.channel)}</span></div>
        <div class="starred-body">${formatMessage(m.body.length > 600 ? `${m.body.slice(0, 600)}…` : m.body, m.channel)}</div>
        <div class="starred-actions">${goButton(m, m.client_id)}
          <button type="button" class="link small danger" data-unstar="${m.id}">Quitar de destacados</button></div>
      </li>`).join("")}</ul>`;
  }
  if (tab === "media") {
    if (!data.media.length) return empty("No se han compartido fotos ni vídeos en este chat.");
    return `<ul class="shared-grid">${byMonth(data.media, (f) => f.mime.startsWith("image/")
      ? `<li><button type="button" class="shared-thumb" data-viewer="${attachmentUrl(f.id)}" data-name="${escapeHtml(f.filename)}" title="${sharedMeta(f)}">
          <img src="${attachmentUrl(f.id)}" alt="${escapeHtml(f.filename)}" loading="lazy"></button></li>`
      : `<li><a class="shared-thumb video" href="${attachmentUrl(f.id)}" target="_blank" rel="noopener" title="${sharedMeta(f)}">
          <video src="${attachmentUrl(f.id)}#t=0.5" preload="metadata" muted></video><span class="play-mark">▶</span></a></li>`)}</ul>`;
  }
  if (tab === "docs") {
    if (!data.docs.length) return empty("No se han compartido documentos en este chat.");
    return `<ul class="shared-list">${byMonth(data.docs, (f) => `
      <li class="shared-row"><span class="shared-ico">${ICON_FILE}<small>${escapeHtml((f.filename.split(".").pop() || "").slice(0, 4).toUpperCase())}</small></span>
        <div class="shared-row-body"><a href="${attachmentUrl(f.id)}" target="_blank" rel="noopener">${escapeHtml(f.filename)}</a>
          <span class="muted small">${formatSize(f.size)} · ${sharedMeta(f)}</span></div>${goButton(f, clientId)}</li>`)}</ul>`;
  }
  if (!data.links.length) return empty("No se han compartido enlaces en este chat (en WhatsApp y Telegram).");
  return `<ul class="shared-list">${byMonth(data.links, (l) => `
    <li class="shared-row"><span class="shared-ico">${ICON_LINK}</span>
      <div class="shared-row-body"><a href="${escapeHtml(l.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(l.url)}</a>
        <span class="muted small">${escapeHtml(siteOf(l.url))} · ${sharedMeta(l)}</span></div>${goButton(l, clientId)}</li>`)}</ul>`;
}

function renderShared() {
  const { tab, data, starred, global } = sharedState;
  $("#shared-title").textContent = global ? "Mensajes destacados" : `Compartido con ${chatState.data?.name || "el cliente"}`;
  $("#shared-tabs").hidden = global;
  document.querySelectorAll("#shared-tabs [data-shared-tab]").forEach((b) => {
    b.classList.toggle("active", b.dataset.sharedTab === tab);
    b.setAttribute("aria-selected", String(b.dataset.sharedTab === tab));
    const n = b.dataset.sharedTab === "starred" ? starred.length : data?.[b.dataset.sharedTab]?.length;
    b.querySelector(".count").textContent = n ?? "";
  });
  $("#shared-body").innerHTML = sharedListHtml();
}

async function openShared(tab, global = false) {
  const clientId = chatState.clientId;
  Object.assign(sharedState, { tab: global ? "starred" : tab, global, clientId });
  try {
    if (global) {
      sharedState.starred = await api("/api/starred");
      sharedState.data = null;
    } else {
      const [data, starred] = await Promise.all([api(`/api/clients/${clientId}/shared?scope=${state.scope}`),
        api(`/api/clients/${clientId}/starred`)]);
      Object.assign(sharedState, { data, starred });
    }
  } catch (err) {
    return alert(err.message);
  }
  renderShared();
  if (!$("#shared-dialog").open) $("#shared-dialog").showModal();
}

// Ir a un mensaje (de este chat o, desde los destacados de todos, de otro): se abre su chat y su canal.
async function goToMessage(clientId, channel, messageId) {
  $("#shared-dialog").close();
  if (currentView() !== "chats" && currentView() !== "client") showView("chats");
  if (chatState.clientId !== clientId) await openChat(clientId);
  showDetailTab("conversation");
  if (chatState.channel && chatState.channel !== channel) {
    chatState.channel = channel;
    setActiveChannelTab($("#chat-tabs"), channel);
    await loadChatConversation();
  }
  jumpToMessage(messageId);
}

async function unstar(id) {
  try {
    await api(`/api/messages/${id}/star`, { method: "POST", body: JSON.stringify({ starred: false }) });
  } catch (err) {
    return alert(err.message);
  }
  sharedState.starred = sharedState.starred.filter((m) => m.id !== id);
  renderShared();
  if (chatState.messagesById?.has(id)) loadChatConversation(true);
}

/* ---------- Eventos ---------- */

function bindChatOrganize() {
  $("#chats-list").addEventListener("click", (e) => {
    const more = e.target.closest("[data-chat-menu]");
    if (more) {
      e.stopPropagation();
      return openChatMenu(more, Number(more.dataset.chatMenu));
    }
    if (e.target.closest("[data-archived-open]")) setArchivedView(true);
    else if (e.target.closest("[data-archived-back]")) setArchivedView(false);
  });
  $("#chats-list").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("[data-archived-open]")) setArchivedView(true);
  });
  $("#chats-list").addEventListener("contextmenu", (e) => {
    const li = e.target.closest("li[data-client]");
    if (!li) return;
    e.preventDefault(); // clic derecho: el mismo menú, como en WhatsApp
    openChatMenu(li.querySelector("[data-chat-menu]"), Number(li.dataset.client));
  });
  $("#chat-item-menu").addEventListener("click", (e) => {
    e.stopPropagation();
    const b = e.target.closest("[data-chat-act]");
    if (b) chatMenuAction(b.dataset.chatAct, b.dataset.value);
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("#chat-item-menu")) closeChatMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeChatMenu(); });
  $("#chats-list").addEventListener("scroll", closeChatMenu, { passive: true });

  $("#chat-timeline").addEventListener("click", (e) => {
    const b = e.target.closest("[data-star]");
    if (b) toggleStar(Number(b.dataset.star));
  });
  $("#chat-details-body").addEventListener("click", (e) => {
    const b = e.target.closest("[data-shared-open]");
    if (b) openShared(b.dataset.sharedOpen);
  });
  $("#chats-starred").addEventListener("click", () => openShared("starred", true));
  $("#shared-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-shared-tab]");
    if (!b) return;
    sharedState.tab = b.dataset.sharedTab;
    renderShared();
  });
  $("#shared-body").addEventListener("click", (e) => {
    const go = e.target.closest("[data-go-message]");
    const photo = e.target.closest("[data-viewer]");
    const off = e.target.closest("[data-unstar]");
    if (go) goToMessage(Number(go.dataset.goClient), go.dataset.goChannel, Number(go.dataset.goMessage));
    else if (photo) openMediaViewer(photo.dataset.viewer, photo.dataset.name);
    else if (off) unstar(Number(off.dataset.unstar));
  });
}
