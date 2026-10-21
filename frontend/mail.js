// Sección Correo: los correos en bandejas, como en un programa de correo. A la izquierda las carpetas (Recibidos,
// Enviados y Destacados), en el centro la lista y a la derecha el correo abierto con su hilo, para responder ahí
// mismo. Son los mismos correos que se ven como chat en Mis Chats (pestaña Email de cada cliente): «Ver en el chat»
// y «Ver como bandeja» pasan de una vista a la otra.

const MAIL_FOLDERS = { inbox: "Recibidos", sent: "Enviados", starred: "Destacados" };
const ICON_CLIP = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5l-8.6 8.6a5 5 0 0 1-7-7l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9"/></svg>';
const mailState = {
  folder: "inbox", scope: "mine", query: "", clientId: null, clientName: "", items: [], more: false, key: "",
  openId: null, open: null, file: null, newTo: null,
};
let mailSearchTimer = null;
let mailNewTimer = null;
let mailNewMatches = [];

/* ---------- Carpetas y lista ---------- */

function mailSnippet(text) {
  return (text || "").replace(/\s+/g, " ").trim();
}

function mailItemHtml(m) {
  const who = m.direction === "out" ? `Para: ${m.client}` : m.sender;
  const owner = m.owner_id !== currentUser.id ? `<span class="account-tag">cuenta de ${escapeHtml(m.owner)}</span>` : "";
  return `<li class="mail-item${m.unread ? " is-unread" : ""}${m.id === mailState.openId ? " active" : ""}" data-mail="${m.id}" tabindex="0">
    <span class="chat-avatar ${avatarClass(m.client)}" aria-hidden="true">${escapeHtml(initialsOf(m.client))}</span>
    <div class="mail-item-body">
      <div class="mail-item-top"><strong>${escapeHtml(who)}</strong><span class="mail-item-time">${escapeHtml(chatTime(m.sent_at))}</span></div>
      <div class="mail-item-subject">${escapeHtml(m.subject || "(sin asunto)")}</div>
      <div class="mail-item-snippet">${escapeHtml(mailSnippet(m.snippet))}</div>
      ${m.has_files || m.starred || owner ? `<div class="mail-item-meta">${m.has_files ? `<span class="mail-flag" title="Con adjuntos">${ICON_CLIP}</span>` : ""}${m.starred ? `<span class="star-mark" title="Destacado">${ICON_STAR}</span>` : ""}${owner}</div>` : ""}
    </div>
  </li>`;
}

function renderMailList() {
  const list = $("#mail-list");
  const empty = mailState.query ? "Ningún correo coincide con la búsqueda."
    : { inbox: "No hay correos recibidos.", sent: "No has enviado correos.", starred: "No hay correos destacados: ábrelos y pulsa ★." }[mailState.folder];
  list.innerHTML = mailState.items.length ? mailState.items.map(mailItemHtml).join("") : `<li class="chats-empty muted small">${empty}</li>`;
  $("#mail-more").hidden = !mailState.more;
}

function setMailUnread(n) {
  const badge = $("#mail-unread");
  badge.textContent = n > 99 ? "99+" : n;
  badge.hidden = !n;
}

async function loadMail(append = false) {
  const params = new URLSearchParams({ folder: mailState.folder, scope: mailState.scope, q: mailState.query,
                                       offset: append ? mailState.items.length : 0 });
  if (mailState.clientId) params.set("client_id", mailState.clientId);
  const key = params.toString();
  mailState.key = key;
  let data;
  try {
    data = await api(`/api/mail?${params}`);
  } catch (err) {
    $("#mail-list").innerHTML = `<li class="form-error">${escapeHtml(err.message)}</li>`;
    return;
  }
  if (mailState.key !== key) return;
  mailState.items = append ? [...mailState.items, ...data.items] : data.items;
  mailState.more = data.more;
  renderMailList();
  setMailUnread(data.unread);
}

function setMailFolder(folder) {
  mailState.folder = folder;
  document.querySelectorAll("#mail-folders [data-folder]").forEach((b) => {
    b.classList.toggle("active", b.dataset.folder === folder);
    b.setAttribute("aria-current", b.dataset.folder === folder ? "true" : "false");
  });
  updateBreadcrumb();
  loadMail();
}

// Solo los correos de un cliente (al venir de su chat con «Ver como bandeja»), o de todos.
function setMailClient(clientId, name = "") {
  mailState.clientId = clientId;
  mailState.clientName = name;
  $("#mail-client-filter").hidden = !clientId;
  $("#mail-client-name").textContent = name;
}

// Desde la pestaña Email de un chat: la bandeja con los correos de ese cliente.
function openMailbox(clientId = null, name = "") {
  setMailClient(clientId, name);
  mailState.query = "";
  $("#mail-search").value = "";
  showView("mail");
}

/* ---------- El correo abierto ---------- */

function mailAddress(name, address) {
  return address ? `${escapeHtml(name)} <span class="muted">&lt;${escapeHtml(address)}&gt;</span>` : escapeHtml(name);
}

function mailThreadHtml(m) {
  if (m.thread.length < 2) return "";
  return `<section class="mail-thread"><h3>En este hilo · ${m.thread.length} correos</h3><ol>${m.thread.map((t) => `
    <li${t.id === m.id ? ' class="current"' : ""}><button type="button" data-mail-open="${t.id}"${t.id === m.id ? " disabled" : ""}>
      <span class="mail-thread-top"><strong>${escapeHtml(t.direction === "out" ? `${t.sender} (equipo)` : t.sender)}</strong>
        <span class="muted small">${escapeHtml(infoDate(t.sent_at))}</span></span>
      <span class="mail-thread-snippet">${escapeHtml(mailSnippet(t.snippet))}</span></button></li>`).join("")}</ol></section>`;
}

function renderMailReader(m) {
  const out = m.direction === "out";
  const files = m.attachments || [];
  const inline = files.filter((a) => showsInline(a, "email"));
  const others = files.filter((a) => !showsInline(a, "email"));
  const from = out ? mailAddress(m.sender, m.account) : mailAddress(m.sender, m.client_addresses[0]);
  const to = out ? mailAddress(m.client, m.client_addresses[0]) : mailAddress(`${m.owner}`, m.account);
  $("#mail-empty").hidden = true;
  const box = $("#mail-open");
  box.hidden = false;
  box.innerHTML = `
    <header class="mail-head">
      <h2>${escapeHtml(m.subject || "(sin asunto)")}</h2>
      <div class="mail-head-actions">
        <button type="button" class="icon-btn mail-star${m.starred ? " on" : ""}" data-mail-star aria-pressed="${Boolean(m.starred)}"
          title="${m.starred ? "Quitar de destacados" : "Destacar"}" aria-label="${m.starred ? "Quitar de destacados" : "Destacar"}">${ICON_STAR}</button>
        <button type="button" class="ghost small-btn" data-mail-chat title="Ver este correo en el chat de ${escapeHtml(m.client)}">Ver en el chat</button>
      </div>
    </header>
    <div class="mail-from">
      <span class="chat-avatar ${avatarClass(m.sender)}" aria-hidden="true">${escapeHtml(initialsOf(m.sender))}</span>
      <div class="mail-from-text">
        <span class="mail-from-name">${from}${m.by_ai ? ' <span class="ai-mark">🤖 IA</span>' : ""}</span>
        <span class="muted small">Para: ${to}</span>
      </div>
      <span class="mail-date muted small">${escapeHtml(infoDate(m.sent_at))}</span>
    </div>
    ${files.length ? `<div class="mail-files">${mediaHtml(inline, m)}${attachmentChips(others)}</div>` : ""}
    <div class="mail-body">${formatMessage(m.body, "email")}</div>
    ${mailThreadHtml(m)}
    <div class="mail-reply">
      <p class="muted small" id="mail-reply-note" hidden></p>
      <button type="button" class="primary" id="mail-reply-open" disabled>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg> Responder</button>
      <form id="mail-reply-form" class="mail-reply-form" hidden>
        <textarea id="mail-reply-text" rows="6" maxlength="10000" placeholder="Escribe tu respuesta…"></textarea>
        <div class="mail-reply-actions">
          <label class="ghost small-btn mail-attach" title="Adjuntar un archivo (máximo 15 MB)">${ICON_CLIP} Adjuntar<input type="file" id="mail-reply-file" hidden></label>
          <span class="chat-file-chip" id="mail-reply-chip" hidden></span>
          <span class="spacer"></span>
          <button type="button" class="link small" id="mail-reply-cancel">Descartar</button>
          <button type="submit" class="primary" id="mail-reply-send">Enviar</button>
        </div>
      </form>
    </div>`;
}

// ¿Se puede responder desde aquí? (con tu cuenta de correo y en una conversación que entró por ella)
function renderMailReplyState(m) {
  const note = $("#mail-reply-note");
  if (!note || mailState.open !== m) return;
  $("#mail-reply-open").disabled = !m.canReply;
  $("#mail-reply-open").title = m.via ? `Responder por ${m.via}` : "";
  note.hidden = m.canReply;
  note.textContent = m.canReply ? "" : m.owner_id !== currentUser.id
    ? `Este correo entró por la cuenta de ${m.owner}: se responde desde su cuenta.`
    : "Conecta tu correo en «Mis cuentas» para responder desde aquí.";
}

async function openMail(id) {
  mailState.openId = id;
  document.querySelectorAll("#mail-list .mail-item").forEach((li) => li.classList.toggle("active", Number(li.dataset.mail) === id));
  let m;
  try {
    m = await api(`/api/mail/${id}`);
  } catch (err) {
    return alert(err.message);
  }
  if (mailState.openId !== id) return;
  mailState.open = m;
  mailState.file = null;
  const item = mailState.items.find((x) => x.id === id);
  if (item?.unread) {
    item.unread = false;
    setMailUnread(Math.max(0, Number($("#mail-unread").textContent || 0) - 1));
    renderMailList();
    refreshNavCounts();
  }
  renderMailReader(m);
  updateBreadcrumb();
  const sender = await api(`/api/conversations/${m.conversation_id}/sender`).catch(() => null);
  Object.assign(m, { canReply: Boolean(sender?.can_send), via: sender?.via, baseline: sender?.last_message_id });
  renderMailReplyState(m);
}

function closeMail() {
  mailState.openId = null;
  mailState.open = null;
  $("#mail-open").hidden = true;
  $("#mail-empty").hidden = false;
  document.querySelectorAll("#mail-list .mail-item.active").forEach((li) => li.classList.remove("active"));
  updateBreadcrumb();
}

async function toggleMailStar() {
  const m = mailState.open;
  try {
    await api(`/api/messages/${m.id}/star`, { method: "POST", body: JSON.stringify({ starred: !m.starred }) });
  } catch (err) {
    return alert(err.message);
  }
  m.starred = !m.starred;
  const item = mailState.items.find((x) => x.id === m.id);
  if (item) item.starred = m.starred;
  renderMailList();
  const btn = $("#mail-open [data-mail-star]");
  btn.classList.toggle("on", m.starred);
  btn.setAttribute("aria-pressed", String(m.starred));
  btn.title = m.starred ? "Quitar de destacados" : "Destacar";
  btn.setAttribute("aria-label", btn.title);
}

// «Ver en el chat»: el chat del cliente, en su pestaña Email, con el correo resaltado.
async function mailToChat() {
  const m = mailState.open;
  showView("chats");
  chatState.channel = "email";
  await openChat(m.client_id);
  if (chatState.channel !== "email") {
    chatState.channel = "email";
    setActiveChannelTab($("#chat-tabs"), "email");
    await loadChatConversation();
  }
  jumpToMessage(m.id);
}

/* ---------- Responder ---------- */

function setMailFile(file) {
  if (file && file.size > CHAT_MAX_FILE) {
    alert("El archivo supera el máximo de 15 MB.");
    file = null;
  }
  mailState.file = file || null;
  const chip = $("#mail-reply-chip");
  chip.hidden = !file;
  chip.innerHTML = file ? `📎 ${escapeHtml(file.name)} <button type="button" class="link small" data-mail-file-remove aria-label="Quitar el archivo">×</button>` : "";
}

async function sendMailReply(e) {
  e.preventDefault();
  const m = mailState.open;
  const text = $("#mail-reply-text").value.trim();
  const file = mailState.file;
  if (!m || (!text && !file)) return;
  const button = $("#mail-reply-send");
  button.disabled = true;
  try {
    const payload = { text, file: file ? { filename: file.name, mime: file.type || null, data: await fileToBase64(file) } : null,
                      after_message_id: m.baseline ?? null };
    const send = (force) => api(`/api/conversations/${m.conversation_id}/send`, {
      method: "POST", body: JSON.stringify({ ...payload, force }),
    });
    try {
      await send(false);
    } catch (err) {
      if (err.status !== 409) throw err;
      if (!(await appConfirm(`${err.message}\n\n¿Enviar de todos modos?`, { ok: "Enviar igualmente" }))) return;
      await send(true);
    }
    toast("Respuesta enviada.", "success");
    await Promise.all([loadMail(), openMail(m.id)]);
  } catch (err) {
    alert(err.message);
  } finally {
    button.disabled = false;
  }
}

/* ---------- Correo nuevo ---------- */

function openNewMail() {
  $("#mail-new-form").reset();
  $("#mail-new-results").hidden = true;
  mailState.newTo = null;
  showFormError($("#mail-new-error"), "");
  if (mailState.clientId) searchMailRecipients(mailState.clientName, true);
  $("#mail-new-dialog").showModal();
  $("#mail-new-to").focus();
}

async function searchMailRecipients(q = $("#mail-new-to").value.trim(), pickFirst = false) {
  const list = $("#mail-new-results");
  mailState.newTo = null;
  if (q.length < 2) {
    list.hidden = true;
    return;
  }
  let found;
  try {
    found = await api(`/api/contacts?${new URLSearchParams({ q })}`);
  } catch {
    return;
  }
  mailNewMatches = found.flatMap((c) => (c.emails || []).map((email) => ({ id: c.id, name: c.name, email }))).slice(0, 6);
  if (pickFirst) {
    const own = mailNewMatches.findIndex((c) => c.id === mailState.clientId);
    if (own >= 0) return pickMailRecipient(own);
  }
  if ($("#mail-new-to").value.trim() !== q) return;
  list.innerHTML = mailNewMatches.length ? mailNewMatches.map((c, i) => `<li><button type="button" role="option" data-pick-recipient="${i}">
      <span class="chat-avatar contact-card-avatar ${avatarClass(c.name)}" aria-hidden="true">${escapeHtml(initialsOf(c.name))}</span>
      <span class="contact-result-body"><strong>${escapeHtml(c.name)}</strong><span class="muted small">${escapeHtml(c.email)}</span></span>
    </button></li>`).join("") : `<li class="muted small contact-none">Ningún cliente con email coincide.</li>`;
  list.hidden = false;
}

function pickMailRecipient(i) {
  const c = mailNewMatches[i];
  if (!c) return;
  mailState.newTo = c;
  $("#mail-new-to").value = `${c.name} <${c.email}>`;
  $("#mail-new-results").hidden = true;
  $("#mail-new-subject").focus();
}

async function sendNewMail(e) {
  e.preventDefault();
  const error = $("#mail-new-error");
  const to = mailState.newTo;
  const subject = $("#mail-new-subject").value.trim();
  const text = $("#mail-new-text").value.trim();
  if (!to) return showFormError(error, "Elige a quién va: busca el cliente por su nombre o su email.");
  if (!subject) return showFormError(error, "Ponle un asunto al correo.");
  if (!text) return showFormError(error, "Escribe el correo.");
  showFormError(error, "");
  const button = $("#mail-new-send");
  button.disabled = true;
  try {
    await api(`/api/clients/${to.id}/emails`, { method: "POST", body: JSON.stringify({ subject, text, to: to.email }) });
  } catch (err) {
    return showFormError(error, err.message);
  } finally {
    button.disabled = false;
  }
  $("#mail-new-dialog").close();
  toast("Correo enviado.", "success");
  if (mailState.folder === "sent") loadMail(); else setMailFolder("sent");
}

/* ---------- Eventos ---------- */

function bindMail() {
  $("#mail-folders").addEventListener("click", (e) => {
    const b = e.target.closest("[data-folder]");
    if (b) setMailFolder(b.dataset.folder);
  });
  $("#mail-scope").addEventListener("change", (e) => {
    mailState.scope = e.target.value;
    loadMail();
  });
  $("#mail-search").addEventListener("input", (e) => {
    clearTimeout(mailSearchTimer);
    mailSearchTimer = setTimeout(() => { mailState.query = e.target.value.trim(); loadMail(); }, 250);
  });
  $("#mail-client-clear").addEventListener("click", () => {
    setMailClient(null);
    loadMail();
  });
  $("#mail-more").addEventListener("click", () => loadMail(true));
  $("#mail-read-all").addEventListener("click", async () => {
    try {
      await api(`/api/mail/read-all?scope=${mailState.scope}`, { method: "POST" });
    } catch (err) {
      return alert(err.message);
    }
    await loadMail();
    refreshNavCounts();
  });
  $("#mail-list").addEventListener("click", (e) => {
    const li = e.target.closest("[data-mail]");
    if (li) openMail(Number(li.dataset.mail));
  });
  $("#mail-list").addEventListener("keydown", (e) => {
    const li = e.target.closest("[data-mail]");
    if (li && e.key === "Enter") openMail(Number(li.dataset.mail));
    if (!li || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
    e.preventDefault();
    (e.key === "ArrowDown" ? li.nextElementSibling : li.previousElementSibling)?.focus();
  });
  $("#mail-to-chats").addEventListener("click", () => showView("chats"));
  $("#mail-compose").addEventListener("click", openNewMail);
  $("#mail-reader").addEventListener("click", (e) => {
    const thread = e.target.closest("[data-mail-open]");
    const media = e.target.closest("[data-viewer]");
    if (thread) openMail(Number(thread.dataset.mailOpen));
    else if (media) openMediaViewer(media.dataset.viewer, media.dataset.name);
    else if (e.target.closest("[data-mail-star]")) toggleMailStar();
    else if (e.target.closest("[data-mail-chat]")) mailToChat();
    else if (e.target.closest("[data-mail-file-remove]")) setMailFile(null);
    else if (e.target.closest("#mail-reply-open")) {
      $("#mail-reply-open").hidden = true;
      $("#mail-reply-form").hidden = false;
      $("#mail-reply-text").focus();
    } else if (e.target.closest("#mail-reply-cancel")) {
      $("#mail-reply-form").reset();
      setMailFile(null);
      $("#mail-reply-form").hidden = true;
      $("#mail-reply-open").hidden = false;
    }
  });
  $("#mail-reader").addEventListener("change", (e) => { if (e.target.id === "mail-reply-file") setMailFile(e.target.files[0]); });
  $("#mail-reader").addEventListener("submit", (e) => { if (e.target.id === "mail-reply-form") sendMailReply(e); });
  $("#mail-new-to").addEventListener("input", () => {
    clearTimeout(mailNewTimer);
    mailNewTimer = setTimeout(() => searchMailRecipients(), 250);
  });
  $("#mail-new-results").addEventListener("click", (e) => {
    const b = e.target.closest("[data-pick-recipient]");
    if (b) pickMailRecipient(Number(b.dataset.pickRecipient));
  });
  $("#mail-new-form").addEventListener("submit", sendNewMail);
  $("#chat-mail-view").addEventListener("click", () => openMailbox(chatState.clientId, chatState.data?.name || ""));
}
