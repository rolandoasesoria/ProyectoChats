// Gestión de clientes: filtros de la lista, cabecera de la ficha, edición, identificadores, duplicados y unir.

const STATUS_LABELS = { lead: "Potencial", active: "Activo", issue: "Incidencia", inactive: "Inactivo" };
const IDENTITY_LABELS = { email: "Email", whatsapp: "WhatsApp", telegram: "Telegram", phone: "Teléfono", other: "Otro" };

let clientDialogMode = "edit";

/* ---------- Filtros de la lista ---------- */

function clientFilterParams() {
  const params = new URLSearchParams();
  if ($("#filter-status").value) params.set("status", $("#filter-status").value);
  if ($("#filter-tag").value) params.set("tag", $("#filter-tag").value);
  if ($("#filter-mine").checked) params.set("mine", "true");
  return params;
}

async function loadTagOptions() {
  const tags = await api("/api/tags");
  const current = $("#filter-tag").value;
  $("#filter-tag").innerHTML = `<option value="">Etiquetas</option>` +
    tags.map((t) => `<option value="${escapeHtml(t.tag)}">${escapeHtml(t.tag)} (${t.clients})</option>`).join("");
  $("#filter-tag").value = tags.some((t) => t.tag === current) ? current : "";
  knownTags = tags;
}

/* ---------- Selector de etiquetas (editar cliente) ----------
   Desplegable con las etiquetas básicas y las que ya usa el equipo; también se puede escribir una nueva. */

const BASIC_TAGS = ["VIP", "Mayorista", "Minorista", "Nuevo", "Habitual", "Paga tarde", "Presupuesto enviado", "Urgente"];
let knownTags = [];      // [{tag, clients}] de /api/tags
let editorTags = [];     // etiquetas elegidas en el diálogo
let tagActive = 0;

function tagOptions() {
  const typed = $("#tag-input").value.trim();
  const q = normText(typed);
  const chosen = new Set(editorTags.map(normText));
  const seen = new Map(); // sin distinguir mayúsculas ni tildes; manda cómo la escribe ya el equipo
  knownTags.forEach((t) => seen.set(normText(t.tag), { tag: t.tag, clients: t.clients }));
  BASIC_TAGS.forEach((t) => { if (!seen.has(normText(t))) seen.set(normText(t), { tag: t, clients: 0 }); });
  const list = [...seen.entries()].filter(([k]) => !chosen.has(k) && (!q || k.includes(q))).map(([, v]) => v)
    .sort((a, b) => b.clients - a.clients || a.tag.localeCompare(b.tag, "es"));
  if (typed && !seen.has(q) && !chosen.has(q)) list.unshift({ tag: typed, clients: 0, isNew: true });
  return list;
}

function renderTagEditor() {
  $("#tag-editor-chips").innerHTML = editorTags.map((t, i) =>
    `<span class="chip-tag removable">${escapeHtml(t)}<button type="button" data-remove-tag="${i}" aria-label="Quitar ${escapeHtml(t)}">×</button></span>`).join("");
}

function renderTagOptions(open = true) {
  const menu = $("#tag-options");
  const opts = tagOptions();
  tagActive = Math.min(tagActive, Math.max(0, opts.length - 1));
  menu.innerHTML = opts.map((o, i) => `
    <li role="option" class="${i === tagActive ? "active" : ""}" data-i="${i}">
      <span>${o.isNew ? `Crear «${escapeHtml(o.tag)}»` : escapeHtml(o.tag)}</span>
      ${o.clients ? `<span class="muted small">${o.clients}</span>` : ""}
    </li>`).join("");
  menu.hidden = !open || !opts.length;
  $("#tag-input").setAttribute("aria-expanded", String(!menu.hidden));
}

function addTag(tag) {
  const t = tag.trim().split(/\s+/).join(" ").slice(0, 40);
  if (t && !editorTags.some((x) => normText(x) === normText(t))) editorTags.push(t);
  $("#tag-input").value = "";
  tagActive = 0;
  renderTagEditor();
  renderTagOptions(document.activeElement === $("#tag-input"));
}

function setEditorTags(tags) {
  editorTags = [...tags];
  $("#tag-input").value = "";
  $("#tag-options").hidden = true;
  renderTagEditor();
}

function onTagKey(e) {
  const opts = tagOptions();
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!opts.length) return;
    tagActive = (tagActive + (e.key === "ArrowDown" ? 1 : opts.length - 1)) % opts.length;
    renderTagOptions();
  } else if (e.key === "Enter" || e.key === ",") {
    e.preventDefault();
    const typed = $("#tag-input").value.trim();
    if (!$("#tag-options").hidden && opts[tagActive]) addTag(opts[tagActive].tag);
    else if (typed) addTag(typed);
  } else if (e.key === "Backspace" && !$("#tag-input").value && editorTags.length) {
    editorTags.pop();
    renderTagEditor();
    renderTagOptions();
  } else if (e.key === "Escape" && !$("#tag-options").hidden) {
    e.preventDefault(); // cierra el desplegable, no el diálogo
    $("#tag-options").hidden = true;
  }
}

function bindTagEditor() {
  const input = $("#tag-input");
  input.addEventListener("focus", () => renderTagOptions());
  input.addEventListener("click", () => renderTagOptions());
  input.addEventListener("input", () => { tagActive = 0; renderTagOptions(); });
  input.addEventListener("keydown", onTagKey);
  input.addEventListener("blur", () => setTimeout(() => {
    if (document.activeElement !== input) $("#tag-options").hidden = true;
  }, 150));
  $("#tag-options").addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-i]");
    if (!li) return;
    e.preventDefault(); // el campo no pierde el foco: se pueden elegir varias seguidas
    addTag(tagOptions()[Number(li.dataset.i)].tag);
  });
  $("#tag-editor-chips").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove-tag]");
    if (!btn) return;
    editorTags.splice(Number(btn.dataset.removeTag), 1);
    renderTagEditor();
    input.focus();
  });
  $("#tag-editor").addEventListener("click", (e) => { if (e.target.id === "tag-editor") input.focus(); });
}

function statusDot(status) {
  return `<span class="status-dot ${status}" title="${STATUS_LABELS[status] || ""}"></span>`;
}

function tagChips(tags, max = Infinity) {
  const shown = tags.slice(0, max).map((t) => `<span class="chip-tag">${escapeHtml(t)}</span>`).join("");
  return shown + (tags.length > max ? `<span class="chip-tag more">+${tags.length - max}</span>` : "");
}

/* ---------- Cabecera de la ficha ---------- */

// Quién decidió el estado: la IA (o la regla de inactividad) con su motivo, o una persona a mano.
function statusNote(data) {
  const label = STATUS_LABELS[data.status] || "";
  if (data.status_source === "manual") {
    return `${label}: puesto a mano${data.status_updated_by ? ` por ${data.status_updated_by}` : ""}`
      + `${data.status_updated_at ? ` ${timeAgo(data.status_updated_at)}` : ""}. La IA lo volverá a decidir cuando haya mensajes nuevos.`;
  }
  return data.status_reason ? `${label} (decidido automáticamente): ${data.status_reason}` : "";
}

function renderClientHeader(data) {
  $("#detail-name").textContent = data.name;
  const statusEl = $("#detail-status");
  statusEl.textContent = STATUS_LABELS[data.status] || "";
  // ✨ (por CSS) cuando lo decide la IA; sin marca cuando lo ha puesto una persona.
  statusEl.className = `status-badge ${data.status} ${data.status_source === "manual" ? "manual" : "auto"}`;
  statusEl.title = data.status_source === "manual" ? "Puesto a mano · pulsa para cambiarlo" : "Lo decide la IA · pulsa para cambiarlo a mano";
  const note = statusNote(data);
  $("#status-note").textContent = note;
  $("#status-note").hidden = !note;
  $("#status-menu").hidden = true;
  $("#detail-company").textContent = [data.company, data.assignee && `Responsable: ${data.assignee}`].filter(Boolean).join(" · ");
  $("#detail-tags").innerHTML = tagChips(data.tags);
  $("#detail-identities").innerHTML = data.identities
    .map((i) => `<div>${badge(i.channel)} ${escapeHtml(i.handle)}</div>`).join("");
}


async function loadDuplicates(clientId) {
  const box = $("#duplicates");
  box.hidden = true;
  const dups = await api(`/api/clients/${clientId}/duplicates`);
  if (state.clientId !== clientId || !dups.length) return;
  box.innerHTML = dups.map((d) => `
    <div class="duplicate" data-duplicate="${d.id}">
      <span>¿Es la misma persona que <button class="link" data-open-duplicate>${escapeHtml(d.name)}</button>?
        <span class="muted">(${escapeHtml(d.reasons.join(", "))})</span></span>
      <button class="ghost small-btn" data-merge-duplicate title="Pasar todo lo de ${escapeHtml(d.name)} a este cliente">Unir aquí</button>
    </div>`).join("");
  box.hidden = false;
}

async function onDuplicatesClick(e) {
  const row = e.target.closest("[data-duplicate]");
  if (!row) return;
  const dupId = Number(row.dataset.duplicate);
  if (e.target.closest("[data-open-duplicate]")) {
    selectClient(dupId);
  } else if (e.target.closest("[data-merge-duplicate]")) {
    const name = row.querySelector("[data-open-duplicate]").textContent;
    await mergeInto(dupId, state.clientId, `Se pasará todo lo de «${name}» a «${state.clientData.name}» y «${name}» desaparecerá. ¿Continuar?`);
  }
}

/* ---------- Unir clientes ---------- */

async function mergeInto(sourceId, targetId, question) {
  if (!confirm(question)) return;
  try {
    await api(`/api/clients/${sourceId}/merge`, { method: "POST", body: JSON.stringify({ into_client_id: targetId }) });
    // La conversación con el asistente del cliente que desaparece queda archivada en el otro.
    const thread = state.threads.get(sourceId);
    thread?.el.remove();
    state.threads.delete(sourceId);
    state.convClients.delete(sourceId);
    $("#client-dialog").close();
    await Promise.all([loadClients($("#client-search").value), loadTagOptions()]);
    await selectClient(targetId);
  } catch (err) {
    alert(err.message);
  }
}

/* ---------- Diálogo de crear / editar ---------- */

async function openClientDialog(mode) {
  clientDialogMode = mode;
  const dialog = $("#client-dialog");
  dialog.classList.toggle("create-mode", mode === "create");
  dialog.classList.toggle("is-admin", currentUser.role === "admin");
  $("#client-dialog-title").textContent = mode === "create" ? "Nuevo cliente" : "Editar cliente";
  $("#cf-submit").textContent = mode === "create" ? "Crear" : "Guardar";
  showError($("#cf-error"), "");
  $("#client-form").reset();
  if (mode === "edit") {
    const c = state.clientData;
    $("#cf-name").value = c.name;
    $("#cf-company").value = c.company || "";
    $("#cf-status").value = c.status;
    $("#cf-assignee").innerHTML = assigneeOptions(c.assignee_user_id);
    setEditorTags(c.tags);
    renderIdentities(c.identities);
    $("#sensitive-list").hidden = true;
    const all = await api("/api/clients");
    $("#merge-target").innerHTML = `<option value="">Elige el cliente con el que unir…</option>` +
      all.filter((x) => x.id !== c.id).map((x) => `<option value="${x.id}">${escapeHtml(x.name)}${x.company ? ` (${escapeHtml(x.company)})` : ""}</option>`).join("");
  }
  dialog.showModal();
  $("#cf-name").focus();
}

/* ---------- Cambiar el estado desde la cabecera ---------- */

function toggleStatusMenu() {
  const menu = $("#status-menu");
  if (!menu.hidden) { menu.hidden = true; return; }
  const c = state.clientData;
  menu.innerHTML = Object.entries(STATUS_LABELS).map(([value, label]) =>
    `<button role="menuitem" data-status="${value}" class="${value === c.status ? "current" : ""}">${statusDot(value)}${label}</button>`).join("")
    + (c.status_source === "manual" ? `<button role="menuitem" data-status-auto>✨ Que lo decida la IA</button>` : "");
  menu.hidden = false;
}

async function onStatusMenuClick(e) {
  const btn = e.target.closest("button");
  if (!btn) return;
  const clientId = state.clientId;
  const body = btn.dataset.statusAuto !== undefined ? { status_auto: true } : { status: btn.dataset.status };
  $("#status-menu").hidden = true;
  try {
    const data = await api(`/api/clients/${clientId}`, { method: "PATCH", body: JSON.stringify(body) });
    if (state.clientId !== clientId) return;
    state.clientData = { ...state.clientData, ...data };
    renderClientHeader(state.clientData);
    const dot = document.querySelector(`#client-list li[data-id="${clientId}"] .status-dot`);
    if (dot) dot.className = `status-dot ${data.status}`;
  } catch (err) {
    alert(err.message);
  }
}

/* ---------- Protección de datos (administradores) ---------- */

async function loadSensitive() {
  const list = $("#sensitive-list");
  const items = await api(`/api/clients/${state.clientId}/sensitive`);
  list.innerHTML = items.length ? items.map((m) => `
    <li data-message="${m.id}">
      <div class="muted small">${badge(m.channel)} ${escapeHtml(m.sender)} · ${formatDate(m.sent_at)} ·
        ${m.found.map((f) => `<strong>${escapeHtml(f.kind)}</strong>`).join(", ")}</div>
      <div class="sensitive-body">${escapeHtml(m.body)}</div>
      <button class="ghost small-btn" type="button" data-redact>Ocultar</button>
    </li>`).join("") : `<li class="muted small">No se han encontrado IBAN, DNI/NIE ni números de tarjeta.</li>`;
  list.hidden = false;
}

async function onSensitiveClick(e) {
  const li = e.target.closest("li[data-message]");
  if (!li || !e.target.closest("[data-redact]")) return;
  if (!confirm("Se sustituirán por «[… oculto]». El dato original no se podrá recuperar. ¿Continuar?")) return;
  try {
    await api(`/api/messages/${li.dataset.message}/redact`, { method: "POST", body: JSON.stringify({}) });
    await Promise.all([loadSensitive(), loadTimeline()]);
  } catch (err) {
    alert(err.message);
  }
}

async function exportClient() {
  const c = state.clientData;
  try {
    const res = await fetch(`/api/clients/${c.id}/export`, { credentials: "same-origin" });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `${c.name.replace(/[^\wÀ-ÿ -]/g, "").trim() || "cliente"} - datos.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    alert(err.message);
  }
}

async function deleteClient() {
  const c = state.clientData;
  const typed = prompt(`Se borrarán «${c.name}» y TODOS sus datos: conversaciones, mensajes, datos clave, tareas, notas y avisos. `
    + "No se puede deshacer.\n\nPara confirmar, escribe el nombre del cliente:");
  if (typed === null) return;
  try {
    const res = await api(`/api/clients/${c.id}?confirm=${encodeURIComponent(typed)}`, { method: "DELETE" });
    $("#client-dialog").close();
    const thread = state.threads.get(c.id);
    thread?.el.remove();
    state.threads.delete(c.id);
    alert(`Cliente borrado (${res.conversations} conversaciones y ${res.messages} mensajes).`);
    await Promise.all([loadClients($("#client-search").value), loadTagOptions(), refreshMyTasksCount(), refreshInboxCount()]);
    await selectClient(null);
  } catch (err) {
    alert(err.message);
  }
}

function renderIdentities(identities) {
  $("#cf-identities").innerHTML = identities.length ? identities.map((i) => `
    <li data-identity="${i.id}">${badge(i.channel)} <span>${escapeHtml(i.handle)}</span>
      <button class="icon-link" data-delete-identity title="Quitar este identificador">×</button></li>`).join("")
    : `<li class="muted small">Sin identificadores.</li>`;
}

async function refreshCurrentClient() {
  const data = await api(`/api/clients/${state.clientId}`);
  state.clientData = data;
  renderClientHeader(data);
  return data;
}

async function submitClientForm(e) {
  e.preventDefault();
  showError($("#cf-error"), "");
  try {
    if (clientDialogMode === "create") {
      const { id } = await api("/api/clients", {
        method: "POST", body: JSON.stringify({ name: $("#cf-name").value.trim(), company: $("#cf-company").value.trim() || null }),
      });
      $("#client-dialog").close();
      await loadClients($("#client-search").value);
      await selectClient(id);
      return;
    }
    const id = state.clientId;
    await api(`/api/clients/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: $("#cf-name").value.trim(), company: $("#cf-company").value.trim() || null,
        status: $("#cf-status").value, assignee_user_id: Number($("#cf-assignee").value) || null,
      }),
    });
    if ($("#tag-input").value.trim()) addTag($("#tag-input").value); // lo escrito sin confirmar también cuenta
    const tags = [...editorTags];
    await api(`/api/clients/${id}/tags`, { method: "PUT", body: JSON.stringify({ tags }) });
    $("#client-dialog").close();
    await Promise.all([refreshCurrentClient(), loadClients($("#client-search").value), loadTagOptions()]);
  } catch (err) {
    showError($("#cf-error"), err.message);
  }
}

async function onIdentitiesClick(e) {
  const li = e.target.closest("li[data-identity]");
  if (!li || !e.target.closest("[data-delete-identity]")) return;
  try {
    await api(`/api/identities/${li.dataset.identity}`, { method: "DELETE" });
    renderIdentities((await refreshCurrentClient()).identities);
  } catch (err) {
    alert(err.message);
  }
}

async function submitIdentity(e) {
  e.preventDefault();
  try {
    await api(`/api/clients/${state.clientId}/identities`, {
      method: "POST", body: JSON.stringify({ channel: $("#id-channel").value, handle: $("#id-handle").value.trim() }),
    });
    $("#id-handle").value = "";
    renderIdentities((await refreshCurrentClient()).identities);
    loadDuplicates(state.clientId);
  } catch (err) {
    alert(err.message);
  }
}

function bindClientEvents() {
  ["#filter-status", "#filter-tag", "#filter-mine"].forEach((sel) =>
    $(sel).addEventListener("change", () => loadClients($("#client-search").value)));
  $("#new-client-btn").addEventListener("click", () => openClientDialog("create"));
  $("#edit-client-btn").addEventListener("click", () => openClientDialog("edit"));
  $("#client-form").addEventListener("submit", submitClientForm);
  $("#cf-identities").addEventListener("click", onIdentitiesClick);
  $("#identity-form").addEventListener("submit", submitIdentity);
  $("#duplicates").addEventListener("click", onDuplicatesClick);
  $("#export-client-btn").addEventListener("click", exportClient);
  $("#delete-client-btn").addEventListener("click", deleteClient);
  $("#sensitive-btn").addEventListener("click", () => loadSensitive().catch((err) => alert(err.message)));
  $("#sensitive-list").addEventListener("click", onSensitiveClick);
  $("#detail-status").addEventListener("click", toggleStatusMenu);
  bindTagEditor();
  $("#status-menu").addEventListener("click", onStatusMenuClick);
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".status-wrap")) $("#status-menu").hidden = true;
  });
  $("#merge-btn").addEventListener("click", () => {
    const target = Number($("#merge-target").value);
    if (!target) return;
    const targetName = $("#merge-target").selectedOptions[0].textContent;
    mergeInto(state.clientId, target,
      `Se pasará todo lo de «${state.clientData.name}» a «${targetName}» y «${state.clientData.name}» desaparecerá. ¿Continuar?`);
  });
}
