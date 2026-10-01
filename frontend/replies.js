// Respuestas guardadas y macros: selector en el borrador (botón o escribiendo /atajo) y gestión en un diálogo.

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

// Inserta el texto de la respuesta (con las variables rellenas) en el borrador y aplica la macro, si lo es.
async function useSavedReply(reply, replaceFrom = null) {
  const clientId = state.clientId;
  const res = await api(`/api/replies/${reply.id}/use`, {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, conversation_id: Number($("#draft-conversation").value) || null }),
  });
  if (state.clientId !== clientId) return;
  const text = $("#draft-text");
  text.hidden = false;
  $("#draft-result-actions").hidden = false;
  const end = text.selectionEnd;
  const start = replaceFrom ?? text.selectionStart;
  text.value = text.value.slice(0, start) + res.text + text.value.slice(end);
  text.selectionStart = text.selectionEnd = start + res.text.length;
  text.focus();
  const note = $("#draft-applied");
  note.textContent = res.applied.length ? `Aplicado: ${res.applied.join(", ")}.` : "";
  note.hidden = !res.applied.length;
  if (res.applied.length) {
    const data = await api(`/api/clients/${clientId}`);
    if (state.clientId === clientId) {
      state.clientData = data;
      renderClientHeader(data);
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
  let matches = [];
  let active = 0;
  let from = 0;

  const close = () => { list.hidden = true; matches = []; };
  const render = () => {
    list.innerHTML = matches.map((r, i) => replyOption(r, i, active)).join("");
    list.hidden = !matches.length;
  };
  const choose = async (r) => {
    close();
    try {
      await useSavedReply(r, from);
    } catch (err) {
      alert(err.message);
    }
  };

  textarea.addEventListener("input", () => {
    const before = textarea.value.slice(0, textarea.selectionStart);
    const m = before.match(/(^|\s)\/([\w-]*)$/);
    if (!m) return close();
    from = before.length - m[2].length - 1;
    matches = replyMatches(m[2]).slice(0, 8);
    active = 0;
    render();
  });
  textarea.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : matches.length - 1)) % matches.length;
      render();
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      choose(matches[active]);
    } else if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  });
  textarea.addEventListener("blur", () => setTimeout(close, 150));
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-i]");
    if (!li) return;
    e.preventDefault();
    choose(matches[Number(li.dataset.i)]);
  });
}

/* ---------- Gestión (diálogo) ---------- */

let editingReply = null;

function renderRepliesTable() {
  $("#replies-list").innerHTML = savedReplies.length ? savedReplies.map((r) => {
    const canEdit = r.created_by === currentUser.id || currentUser.role === "admin";
    const macro = macroSummary(r);
    return `<li class="reply-row" data-reply="${r.id}">
      <div class="reply-row-head">
        <strong>${escapeHtml(r.title)}</strong>
        ${r.shortcut ? `<span class="muted small">/${escapeHtml(r.shortcut)}</span>` : ""}
        <span class="spacer"></span>
        ${canEdit ? `<button class="link small" data-edit-reply>Editar</button><button class="link small danger" data-delete-reply>Borrar</button>` : ""}
      </div>
      <div class="reply-body">${escapeHtml(r.body)}</div>
      <div class="muted small">${macro ? `Macro · ${escapeHtml(macro)} · ` : ""}de ${escapeHtml(r.author || "—")}</div>
    </li>`;
  }).join("") : `<li class="muted small">Todavía no hay respuestas guardadas.</li>`;
}

function resetReplyForm() {
  editingReply = null;
  $("#reply-form").reset();
  $("#rf-title-h").textContent = "Nueva respuesta";
  $("#rf-submit").textContent = "Guardar respuesta";
  $("#rf-cancel").hidden = true;
  $("#rf-error").hidden = true;
}

async function openRepliesDialog() {
  $("#reply-picker").hidden = true;
  resetReplyForm();
  try {
    await loadSavedReplies();
  } catch (err) {
    alert(err.message);
    return;
  }
  renderRepliesTable();
  $("#replies-dialog").showModal();
}

async function submitReplyForm(e) {
  e.preventDefault();
  const body = {
    title: $("#rf-title").value.trim(),
    shortcut: $("#rf-shortcut").value.trim() || null,
    body: $("#rf-body").value.trim(),
    set_status: $("#rf-status").value || null,
    add_tag: $("#rf-tag").value.trim() || null,
    mark_done: $("#rf-done").checked,
  };
  try {
    await api(editingReply ? `/api/replies/${editingReply}` : "/api/replies", {
      method: editingReply ? "PATCH" : "POST", body: JSON.stringify(body),
    });
    await loadSavedReplies();
    renderRepliesTable();
    resetReplyForm();
  } catch (err) {
    $("#rf-error").textContent = err.message;
    $("#rf-error").hidden = false;
  }
}

async function onRepliesListClick(e) {
  const li = e.target.closest("li[data-reply]");
  if (!li) return;
  const r = savedReplies.find((x) => x.id === Number(li.dataset.reply));
  if (e.target.closest("[data-edit-reply]")) {
    editingReply = r.id;
    $("#rf-title").value = r.title;
    $("#rf-shortcut").value = r.shortcut || "";
    $("#rf-body").value = r.body;
    $("#rf-status").value = r.set_status || "";
    $("#rf-tag").value = r.add_tag || "";
    $("#rf-done").checked = r.mark_done;
    $("#rf-title-h").textContent = `Editar «${r.title}»`;
    $("#rf-submit").textContent = "Guardar cambios";
    $("#rf-cancel").hidden = false;
    $("#rf-title").focus();
  } else if (e.target.closest("[data-delete-reply]")) {
    if (!confirm(`¿Borrar la respuesta «${r.title}» para todo el equipo?`)) return;
    try {
      await api(`/api/replies/${r.id}`, { method: "DELETE" });
      if (editingReply === r.id) resetReplyForm();
      await loadSavedReplies();
      renderRepliesTable();
    } catch (err) {
      alert(err.message);
    }
  }
}

function bindReplyEvents() {
  $("#reply-open").addEventListener("click", () => toggleReplyPicker());
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
  $("#reply-manage").addEventListener("click", openRepliesDialog);
  $("#menu-replies").addEventListener("click", () => {
    $("#user-menu").hidden = true;
    openRepliesDialog();
  });
  $("#reply-form").addEventListener("submit", submitReplyForm);
  $("#rf-cancel").addEventListener("click", resetReplyForm);
  $("#replies-list").addEventListener("click", onRepliesListClick);
  attachReplyShortcuts($("#draft-text"), $("#reply-suggest"));
  loadSavedReplies().catch(() => { /* se reintenta al abrir el selector */ });
}
