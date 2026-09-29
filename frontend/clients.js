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
  $("#tag-suggestions").innerHTML = tags.map((t) => `<option value="${escapeHtml(t.tag)}">`).join("");
}

function statusDot(status) {
  return `<span class="status-dot ${status}" title="${STATUS_LABELS[status] || ""}"></span>`;
}

function tagChips(tags, max = Infinity) {
  const shown = tags.slice(0, max).map((t) => `<span class="chip-tag">${escapeHtml(t)}</span>`).join("");
  return shown + (tags.length > max ? `<span class="chip-tag more">+${tags.length - max}</span>` : "");
}

/* ---------- Cabecera de la ficha ---------- */

function renderClientHeader(data) {
  $("#detail-name").textContent = data.name;
  const statusEl = $("#detail-status");
  statusEl.textContent = STATUS_LABELS[data.status] || "";
  statusEl.className = `status-badge ${data.status}`;
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
    $("#cf-tags").value = c.tags.join(", ");
    renderIdentities(c.identities);
    const all = await api("/api/clients");
    $("#merge-target").innerHTML = `<option value="">Elige el cliente con el que unir…</option>` +
      all.filter((x) => x.id !== c.id).map((x) => `<option value="${x.id}">${escapeHtml(x.name)}${x.company ? ` (${escapeHtml(x.company)})` : ""}</option>`).join("");
  }
  dialog.showModal();
  $("#cf-name").focus();
}

/* ---------- Protección de datos (administradores) ---------- */

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
    const tags = $("#cf-tags").value.split(",").map((t) => t.trim()).filter(Boolean);
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
  $("#merge-btn").addEventListener("click", () => {
    const target = Number($("#merge-target").value);
    if (!target) return;
    const targetName = $("#merge-target").selectedOptions[0].textContent;
    mergeInto(state.clientId, target,
      `Se pasará todo lo de «${state.clientData.name}» a «${targetName}» y «${state.clientData.name}» desaparecerá. ¿Continuar?`);
  });
}
