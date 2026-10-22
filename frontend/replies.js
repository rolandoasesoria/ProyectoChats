// Respuestas guardadas y macros: selector en la caja de escribir (botón o escribiendo /atajo) y su sección en la
// barra lateral (lista · la respuesta elegida o el editor).

let savedReplies = [];

async function loadSavedReplies() {
  savedReplies = await api("/api/replies");
  return savedReplies;
}

function normText(s) {
  return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function replyMatches(q) {
  const n = normText(q);
  return savedReplies.filter((r) => !n || normText(r.title).includes(n) || normText(r.shortcut).startsWith(n));
}

function macroSummary(r) {
  const parts = [];
  if (r.set_status) parts.push(`estado: ${STATUS_LABELS[r.set_status]}`);
  if (r.add_tag) parts.push(`etiqueta «${r.add_tag}»`);
  if (r.mark_done) parts.push("marca como atendida");
  return parts.join(" · ");
}

function replyOption(r, i, active) {
  const macro = macroSummary(r);
  return `<li role="option" class="reply-option ${i === active ? "active" : ""}" data-i="${i}">
    <span class="reply-option-head"><strong>${escapeHtml(r.title)}</strong>${r.shortcut ? `<span class="muted small">/${escapeHtml(r.shortcut)}</span>` : ""}</span>
    ${macro ? `<span class="macro-tag" title="Al usarla también se aplica al cliente">Macro · ${escapeHtml(macro)}</span>` : ""}
  </li>`;
}

// Inserta el texto de la respuesta (con las variables rellenas) en la caja de escribir y aplica la macro, si lo es.
async function useSavedReply(reply, replaceFrom = null) {
  const clientId = state.clientId;
  if (!clientId) return;
  const res = await api(`/api/replies/${reply.id}/use`, {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, conversation_id: chatState.conversationId || null }),
  });
  if (state.clientId !== clientId) return;
  const text = $("#chat-text");
  const end = text.selectionEnd;
  const start = replaceFrom ?? text.selectionStart;
  setComposerText(text.value.slice(0, start) + res.text + text.value.slice(end));
  text.selectionStart = text.selectionEnd = start + res.text.length;
  showComposerNote(res.applied.length ? `Aplicado: ${res.applied.join(", ")}.` : "");
  if (res.applied.length) {
    const data = await api(`/api/clients/${clientId}`);
    if (state.clientId === clientId) {
      state.clientData = data;
      chatState.data = data;
      renderClientHeader(data);
      renderChatDetails(data);
    }
    refreshInboxCount();
  }
}

/* ---------- Selector desde el botón ---------- */

function renderReplyPicker() {
  const items = replyMatches($("#reply-filter").value);
  $("#reply-options").innerHTML = items.length
    ? items.map((r, i) => replyOption(r, i, -1)).join("")
    : `<li class="muted small reply-empty">No hay respuestas guardadas${$("#reply-filter").value ? " con ese nombre" : ""}.</li>`;
  return items;
}

async function toggleReplyPicker(open) {
  const picker = $("#reply-picker");
  const show = open ?? picker.hidden;
  picker.hidden = !show;
  if (!show) return;
  $("#reply-filter").value = "";
  try {
    await loadSavedReplies();
  } catch (err) {
    alert(err.message);
  }
  renderReplyPicker();
  $("#reply-filter").focus();
}

/* ---------- Escribir /atajo en el borrador ---------- */

function attachReplyShortcuts(textarea, list) {
  attachAutocomplete(textarea, list, {
    pattern: /(^|\s)\/([\w-]*)$/,
    search: (q) => replyMatches(q).slice(0, 8),
    render: replyOption,
    choose: (r, from) => useSavedReply(r, from).catch((err) => alert(err.message)),
  });
}

/* ---------- Sección Respuestas guardadas: lista · la respuesta elegida o el editor ---------- */

const repliesState = { selected: null, editing: null, filter: "all", query: "" }; // editing: id o «new»
// Un cliente de ejemplo para la vista previa (los datos clave se ven como hueco: dependen de cada ficha)
const SAMPLE_CLIENT = { nombre: "Laura", cliente: "Laura Gómez", empresa: "Floristería Gómez" };
const VARIABLE_RE = /\{(nombre|cliente|empresa|yo|dato:[^{}]{1,100})\}/gi;

function canEditReply(r) {
  return r.created_by === currentUser.id || currentUser.role === "admin";
}

// El texto con las variables resaltadas
function replyTextHtml(body) {
  return escapeHtml(body).replace(VARIABLE_RE, (m) => `<span class="var-chip static">${m}</span>`);
}

// El texto como lo recibiría el cliente de ejemplo
function replyPreviewHtml(body) {
  if (!body.trim()) return `<span class="muted">Aquí verás el texto con los datos de un cliente de ejemplo.</span>`;
  return escapeHtml(body).replace(VARIABLE_RE, (m, key) => {
    const k = key.toLowerCase();
    if (k === "yo") return `<mark class="var-value">${escapeHtml(currentUser.name)}</mark>`;
    if (k.startsWith("dato:")) return `<mark class="var-value missing">${escapeHtml(key.slice(5).trim() || "dato")} del cliente</mark>`;
    return `<mark class="var-value">${escapeHtml(SAMPLE_CLIENT[k])}</mark>`;
  });
}

function shortDate(iso) {
  return iso ? new Date(iso).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" }) : "";
}

function visibleReplies() {
  const q = normText(repliesState.query.trim());
  return savedReplies.filter((r) => {
    if (repliesState.filter === "mine" && r.created_by !== currentUser.id) return false;
    if (repliesState.filter === "macro" && !macroSummary(r)) return false;
    return !q || normText(r.title).includes(q) || normText(r.shortcut).includes(q) || normText(r.body).includes(q);
  });
}

function renderRepliesList() {
  const list = visibleReplies();
  const active = repliesState.editing && repliesState.editing !== "new" ? repliesState.editing : repliesState.selected;
  $("#replies-list").innerHTML = list.length ? list.map((r) => `
    <li class="reply-item${r.id === active ? " active" : ""}" data-reply="${r.id}" tabindex="0">
      <div class="reply-item-top"><strong>${escapeHtml(r.title)}</strong>${r.shortcut ? `<span class="shortcut-chip">/${escapeHtml(r.shortcut)}</span>` : ""}</div>
      <span class="reply-item-snippet">${escapeHtml(r.body.replace(/\s+/g, " "))}</span>
      <span class="reply-item-meta">${macroSummary(r) ? '<span class="macro-chip">Macro</span>' : ""}<span>${escapeHtml(r.author || "—")}</span></span>
    </li>`).join("")
    : `<li class="muted small replies-empty">${savedReplies.length ? "Ninguna respuesta coincide." : "Todavía no hay respuestas guardadas: crea la primera con «Nueva»."}</li>`;
}

function macroListHtml(r) {
  const items = [];
  if (r.set_status) items.push(`Cambia el estado del cliente a <span class="status-pill mini ${r.set_status}">${escapeHtml(STATUS_LABELS[r.set_status])}</span>`);
  if (r.add_tag) items.push(`Añade la etiqueta <span class="chip-tag">${escapeHtml(r.add_tag)}</span>`);
  if (r.mark_done) items.push("Marca la conversación como atendida (sale de «Sin responder»)");
  return items.length ? `<ul class="macro-list">${items.map((i) => `<li>${i}</li>`).join("")}</ul>`
    : `<p class="muted">Solo inserta el texto en la caja de escribir; no cambia nada más.</p>`;
}

function renderReplyDetail() {
  const r = savedReplies.find((x) => x.id === repliesState.selected);
  $("#replies-intro").hidden = Boolean(r || repliesState.editing);
  $("#reply-detail").hidden = !r || Boolean(repliesState.editing);
  $("#reply-form").hidden = !repliesState.editing;
  updateBreadcrumb();
  if (!r || repliesState.editing) return;
  const edited = r.updated_at ? ` · editada el ${escapeHtml(shortDate(r.updated_at))}` : "";
  $("#reply-detail").innerHTML = `
    <header class="reply-detail-head">
      <div class="reply-detail-title">
        <h2>${escapeHtml(r.title)}</h2>
        <p class="muted small">Creada por ${escapeHtml(r.author || "—")}${r.created_at ? ` el ${escapeHtml(shortDate(r.created_at))}` : ""}${edited}</p>
      </div>
      ${canEditReply(r) ? `<div class="reply-detail-actions">
        <button type="button" class="ghost small-btn" data-edit-reply>Editar</button>
        <button type="button" class="ghost small-btn danger" data-delete-reply>Borrar</button></div>` : ""}
    </header>
    <div class="reply-facts">
      <div><span>Atajo</span><strong>${r.shortcut ? `<span class="shortcut-chip">/${escapeHtml(r.shortcut)}</span>` : '<span class="muted">Sin atajo</span>'}</strong></div>
      <div><span>Tipo</span><strong>${macroSummary(r) ? '<span class="macro-chip">Macro</span>' : "Solo texto"}</strong></div>
    </div>
    <section class="reply-block"><h3>Texto</h3><div class="reply-text">${replyTextHtml(r.body)}</div></section>
    <section class="reply-block"><h3>Así lo recibe el cliente <span class="muted">(con un cliente de ejemplo)</span></h3>
      <div class="reply-bubble">${replyPreviewHtml(r.body)}</div></section>
    <section class="reply-block"><h3>Al usarla</h3>${macroListHtml(r)}</section>
    ${canEditReply(r) ? "" : '<p class="muted small">Solo la puede cambiar quien la creó o un administrador.</p>'}`;
}

function selectReply(id) {
  repliesState.selected = id;
  repliesState.editing = null;
  renderRepliesList();
  renderReplyDetail();
}

// Cerrar la respuesta abierta (o el editor) y volver a la explicación
function closeReplyDetail() {
  selectReply(null);
}

function openReplyEditor(id = "new") {
  const r = id === "new" ? null : savedReplies.find((x) => x.id === id);
  repliesState.editing = r ? r.id : "new";
  $("#reply-form").reset();
  $("#rf-title-h").textContent = r ? `Editar «${r.title}»` : "Nueva respuesta";
  $("#rf-submit").textContent = r ? "Guardar cambios" : "Guardar respuesta";
  $("#rf-title").value = r?.title || "";
  $("#rf-shortcut").value = r?.shortcut || "";
  $("#rf-body").value = r?.body || "";
  $("#rf-status").value = r?.set_status || "";
  $("#rf-tag").value = r?.add_tag || "";
  $("#rf-done").checked = Boolean(r?.mark_done);
  showError($("#rf-error"), "");
  $("#rf-preview").innerHTML = replyPreviewHtml($("#rf-body").value);
  renderRepliesList();
  renderReplyDetail();
  $("#replies-main").scrollTop = 0;
  $("#rf-title").focus();
}

function cancelReplyEditor() {
  repliesState.editing = null;
  renderRepliesList();
  renderReplyDetail();
}

async function loadRepliesView() {
  try {
    await loadSavedReplies();
  } catch (err) {
    $("#replies-list").innerHTML = `<li class="form-error">${escapeHtml(err.message)}</li>`;
    return;
  }
  if (!savedReplies.some((r) => r.id === repliesState.selected)) repliesState.selected = null;
  renderRepliesList();
  renderReplyDetail();
}

async function submitReplyForm(e) {
  e.preventDefault();
  const body = {
    title: $("#rf-title").value.trim(),
    shortcut: $("#rf-shortcut").value.trim().replace(/^\//, "") || null,
    body: $("#rf-body").value.trim(),
    set_status: $("#rf-status").value || null,
    add_tag: $("#rf-tag").value.trim() || null,
    mark_done: $("#rf-done").checked,
  };
  if (!body.title) return showError($("#rf-error"), "Ponle un título (es lo que se ve en la lista).");
  if (!body.body) return showError($("#rf-error"), "Escribe el texto de la respuesta.");
  const editing = repliesState.editing;
  try {
    const saved = await api(editing !== "new" ? `/api/replies/${editing}` : "/api/replies", {
      method: editing !== "new" ? "PATCH" : "POST", body: JSON.stringify(body),
    });
    await loadSavedReplies();
    toast(editing !== "new" ? "Cambios guardados." : "Respuesta guardada.", "success");
    selectReply(saved.id);
  } catch (err) {
    showError($("#rf-error"), err.message);
  }
}

async function deleteSelectedReply() {
  const r = savedReplies.find((x) => x.id === repliesState.selected);
  if (!r || !(await appConfirm(`¿Borrar la respuesta «${r.title}» para todo el equipo?`, { ok: "Borrar", danger: true }))) return;
  try {
    await api(`/api/replies/${r.id}`, { method: "DELETE" });
    await loadSavedReplies();
    selectReply(null);
  } catch (err) {
    alert(err.message);
  }
}

// Variables: se insertan donde está el cursor del texto (en {dato:…}, el cursor queda para escribir el nombre del dato)
function insertReplyVariable(variable) {
  const area = $("#rf-body");
  const { selectionStart: start, selectionEnd: end, value } = area;
  area.value = value.slice(0, start) + variable + value.slice(end);
  const caret = variable === "{dato:}" ? start + variable.length - 1 : start + variable.length;
  area.focus();
  area.setSelectionRange(caret, caret);
  $("#rf-preview").innerHTML = replyPreviewHtml(area.value);
}

// Gestionarlas: la sección de la barra lateral (desde el selector del chat, también)
function openRepliesView(id = null) {
  $("#reply-picker").hidden = true;
  repliesState.selected = id;
  repliesState.editing = null;
  showView("replies");
}

function bindReplyEvents() {
  $("#reply-open").addEventListener("click", (e) => { e.stopPropagation(); toggleReplyPicker(); });
  $("#reply-picker").addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => { if (!$("#reply-picker").hidden) toggleReplyPicker(false); });
  $("#reply-filter").addEventListener("input", renderReplyPicker);
  $("#reply-filter").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.stopPropagation(); toggleReplyPicker(false); }
    if (e.key === "Enter") {
      e.preventDefault();
      const first = replyMatches($("#reply-filter").value)[0];
      if (first) { toggleReplyPicker(false); useSavedReply(first).catch((err) => alert(err.message)); }
    }
  });
  $("#reply-options").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-i]");
    if (!li) return;
    const r = replyMatches($("#reply-filter").value)[Number(li.dataset.i)];
    toggleReplyPicker(false);
    useSavedReply(r).catch((err) => alert(err.message));
  });
  $("#reply-manage").addEventListener("click", () => openRepliesView());
  attachReplyShortcuts($("#chat-text"), $("#reply-suggest"));

  // Sección
  $("#replies-search").addEventListener("input", (e) => { repliesState.query = e.target.value; renderRepliesList(); });
  $("#replies-filter").addEventListener("click", (e) => {
    const b = e.target.closest("[data-filter]");
    if (!b) return;
    repliesState.filter = b.dataset.filter;
    document.querySelectorAll("#replies-filter [data-filter]").forEach((x) => x.classList.toggle("active", x === b));
    renderRepliesList();
  });
  $("#replies-new").addEventListener("click", () => openReplyEditor());
  $("#replies-list").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-reply]");
    if (li) selectReply(Number(li.dataset.reply));
  });
  $("#replies-list").addEventListener("keydown", (e) => {
    const li = e.target.closest("li[data-reply]");
    if (li && e.key === "Enter") selectReply(Number(li.dataset.reply));
  });
  $("#reply-detail").addEventListener("click", (e) => {
    if (e.target.closest("[data-edit-reply]")) openReplyEditor(repliesState.selected);
    else if (e.target.closest("[data-delete-reply]")) deleteSelectedReply();
  });
  $("#reply-form").addEventListener("submit", submitReplyForm);
  $("#rf-cancel").addEventListener("click", cancelReplyEditor);
  $("#rf-body").addEventListener("input", (e) => { $("#rf-preview").innerHTML = replyPreviewHtml(e.target.value); });
  document.querySelector(".var-chips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-insert-var]");
    if (b) insertReplyVariable(b.dataset.insertVar);
  });
  loadSavedReplies().catch(() => { /* se reintenta al abrir el selector */ });
}
