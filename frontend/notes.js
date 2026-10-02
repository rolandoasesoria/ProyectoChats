// Notas internas del equipo con @menciones, y campana de avisos.

/* ---------- Notas ---------- */

// Resalta las @menciones de compañeros en el texto (ya escapado).
function renderNoteBody(body) {
  const html = escapeHtml(body);
  const names = [...new Set(team.flatMap((u) => [u.name, u.name.split(" ")[0]]))]
    .sort((a, b) => b.length - a.length) // primero el nombre completo, para no cortar "@Ana Ruiz" en "@Ana"
    .map((n) => escapeHtml(n).replace(/[.*+?^$(){}|[\]\\]/g, "\\$&"));
  if (!names.length) return html;
  const re = new RegExp("@(" + names.join("|") + ")(?![\\wÀ-ÿ])", "gi");
  return html.replace(re, (m) => `<span class="mention">${m}</span>`);
}

async function loadNotes(clientId) {
  const list = await api(`/api/clients/${clientId}/notes`);
  if (state.clientId !== clientId) return;
  $("#notes-list").innerHTML = list.length ? list.map((n) => `
    <li class="note" data-note="${n.id}">
      <div class="note-meta">
        <strong>${escapeHtml(n.author || "Usuario eliminado")}</strong>
        <span class="muted">${timeAgo(n.created_at)}${n.updated_at ? " · editada" : ""}</span>
        ${n.user_id === currentUser.id ? `<button class="icon-link" data-edit-note title="Editar">✎</button>` : ""}
        ${n.user_id === currentUser.id || currentUser.role === "admin" ? `<button class="icon-link" data-delete-note title="Borrar">×</button>` : ""}
      </div>
      <div class="note-body">${renderNoteBody(n.body)}</div>
    </li>`).join("") : `<li class="muted small">Todavía no hay notas sobre este cliente.</li>`;
  const count = $("#notes-count");
  count.textContent = list.length;
  count.hidden = !list.length;
  state.notes = list;
}

async function submitNote(e) {
  e.preventDefault();
  const clientId = state.clientId;
  try {
    await api(`/api/clients/${clientId}/notes`, { method: "POST", body: JSON.stringify({ body: $("#note-body").value.trim() }) });
    $("#note-body").value = "";
    await loadNotes(clientId);
  } catch (err) {
    alert(err.message);
  }
}

async function onNotesClick(e) {
  const li = e.target.closest("li[data-note]");
  if (!li) return;
  const id = Number(li.dataset.note);
  try {
    if (e.target.closest("[data-delete-note]")) {
      if (!confirm("¿Borrar esta nota?")) return;
      await api(`/api/notes/${id}`, { method: "DELETE" });
      await loadNotes(state.clientId);
    } else if (e.target.closest("[data-edit-note]")) {
      const note = state.notes.find((n) => n.id === id);
      li.querySelector(".note-body").innerHTML = `
        <form class="note-edit">
          <div class="mention-wrap">
            <textarea rows="3" maxlength="5000" required>${escapeHtml(note.body)}</textarea>
            <ul class="mention-list" role="listbox" hidden></ul>
          </div>
          <div class="draft-actions">
            <button class="ghost small-btn" type="submit">Guardar</button>
            <button class="link" type="button" data-cancel-note>Cancelar</button>
          </div>
        </form>`;
      const textarea = li.querySelector("textarea");
      attachMentions(textarea, li.querySelector(".mention-list"));
      textarea.focus();
    } else if (e.target.closest("[data-cancel-note]")) {
      await loadNotes(state.clientId);
    }
  } catch (err) {
    alert(err.message);
  }
}

async function onNotesSubmit(e) {
  e.preventDefault();
  const li = e.target.closest("li[data-note]");
  try {
    await api(`/api/notes/${li.dataset.note}`, {
      method: "PATCH", body: JSON.stringify({ body: e.target.querySelector("textarea").value.trim() }),
    });
    await loadNotes(state.clientId);
  } catch (err) {
    alert(err.message);
  }
}

/* ---------- Autocompletado de @menciones ---------- */

function attachMentions(textarea, list) {
  let matches = [];
  let active = 0;

  const close = () => { list.hidden = true; matches = []; };
  const query = () => {
    const before = textarea.value.slice(0, textarea.selectionStart);
    const m = before.match(/(^|\s)@([\wÀ-ÿ]*)$/);
    return m ? m[2] : null;
  };
  const render = () => {
    list.innerHTML = matches.map((u, i) =>
      `<li role="option" class="${i === active ? "active" : ""}" data-i="${i}">@${escapeHtml(u.name)}</li>`).join("");
    list.hidden = !matches.length;
  };
  const choose = (u) => {
    const pos = textarea.selectionStart;
    const before = textarea.value.slice(0, pos).replace(/@([\wÀ-ÿ]*)$/, `@${u.name} `);
    textarea.value = before + textarea.value.slice(pos);
    textarea.selectionStart = textarea.selectionEnd = before.length;
    close();
    textarea.focus();
  };

  textarea.addEventListener("input", () => {
    const q = query();
    if (q === null) return close();
    const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    matches = team.filter((u) => u.id !== currentUser.id && norm(u.name).split(" ").some((w) => w.startsWith(norm(q))));
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
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-i]");
    if (li) { e.preventDefault(); choose(matches[Number(li.dataset.i)]); }
  });
  textarea.addEventListener("blur", () => setTimeout(close, 150));
}

/* ---------- Campana de avisos ---------- */

let bellItems = [];

async function loadNotifications() {
  try {
    const data = await api("/api/notifications");
    renderNotifications(data);
  } catch { /* no crítico */ }
}

function renderNotifications({ unread, items }) {
  bellItems = items;
  const count = $("#bell-count");
  count.textContent = unread > 9 ? "9+" : unread;
  count.hidden = !unread;
  $("#bell").title = unread ? `${unread} aviso${unread === 1 ? "" : "s"} sin leer` : "Avisos";
  $("#bell-read-all").hidden = !unread;
  $("#bell-list").innerHTML = items.length ? items.map((n) => `
    <li class="bell-item ${n.read_at ? "" : "unread-item"}" data-notification="${n.id}" data-client="${n.client_id || ""}" data-kind="${n.kind}">
      <span class="bell-icon"></span>
      <span class="bell-text">${escapeHtml(n.text)}<span class="muted small">${timeAgo(n.created_at)}</span></span>
    </li>`).join("") : `<li class="muted small bell-empty">No tienes avisos.</li>`;
}

function toggleBell(open) {
  const menu = $("#bell-menu");
  const show = open ?? menu.hidden;
  menu.hidden = !show;
  $("#bell").setAttribute("aria-expanded", String(show));
}

async function onBellClick(e) {
  const li = e.target.closest("li[data-notification]");
  if (!li) return;
  toggleBell(false);
  try {
    renderNotifications(await api("/api/notifications/read", {
      method: "POST", body: JSON.stringify({ ids: [Number(li.dataset.notification)] }),
    }));
  } catch { /* se abre igualmente */ }
  if (li.dataset.kind === "integration_error") {
    openAccountsDialog();  // una cuenta conectada necesita atención (token caducado, contraseña cambiada...)
  } else if (li.dataset.client) {
    await selectClient(Number(li.dataset.client));
    showDetailTab({ mention: "notes", task_assigned: "tasks" }[li.dataset.kind] || "profile");
  }
}

function bindNotesEvents() {
  $("#note-form").addEventListener("submit", submitNote);
  $("#note-body").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("#note-form").requestSubmit();
  });
  attachMentions($("#note-body"), $("#mention-list"));
  $("#notes-list").addEventListener("click", onNotesClick);
  $("#notes-list").addEventListener("submit", onNotesSubmit);

  $("#bell").addEventListener("click", (e) => { e.stopPropagation(); toggleBell(); });
  document.addEventListener("click", (e) => { if (!e.target.closest(".bell-wrap")) toggleBell(false); });
  $("#bell-list").addEventListener("click", onBellClick);
  $("#bell-read-all").addEventListener("click", async () => {
    renderNotifications(await api("/api/notifications/read", { method: "POST", body: JSON.stringify({}) }));
  });
  setInterval(loadNotifications, 60000);
}
