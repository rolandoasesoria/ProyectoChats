// Ficha del cliente (resumen y datos clave), tareas y pestañas de los paneles.

let team = [];              // miembros del equipo (para asignar tareas)

/* ---------- Pestañas ---------- */

function showDetailTab(tab) {
  document.querySelectorAll(".detail-tabs [data-tab]").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tab);
    $(`#tab-${b.dataset.tab}`).hidden = b.dataset.tab !== tab;
  });
}

function showSideTab(side) {
  document.querySelectorAll(".side-tabs [data-side]").forEach((b) => {
    b.classList.toggle("active", b.dataset.side === side);
    $(`#side-${b.dataset.side}`).hidden = b.dataset.side !== side;
  });
  if (side === "tasks") loadMyTasks();
  if (side === "inbox") loadInbox();
}

/* ---------- Utilidades de fechas ---------- */

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dueLabel(due) {
  if (!due) return "";
  const today = todayIso();
  const sameYear = due.slice(0, 4) === today.slice(0, 4);
  const text = new Date(`${due}T12:00:00`).toLocaleDateString("es-ES",
    sameYear ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
  if (due < today) return `<span class="due overdue" title="Vencida">⚠ ${text}</span>`;
  if (due === today) return `<span class="due today">Hoy</span>`;
  return `<span class="due">${text}</span>`;
}

function timeAgo(isoUtc) {
  const then = new Date(`${isoUtc.replace(" ", "T")}Z`);
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "ahora mismo";
  if (mins < 60) return `hace ${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `hace ${hours} h`;
  return then.toLocaleDateString("es-ES", { day: "numeric", month: "short" });
}

function sourceLink(messageId) {
  return messageId
    ? `<button class="icon-link" data-source="${messageId}" title="Ver el mensaje de donde sale">↗</button>` : "";
}

/* ---------- Ficha ---------- */

async function loadProfile(clientId) {
  const data = await api(`/api/clients/${clientId}/profile`);
  if (state.clientId === clientId) renderProfile(data);
  return data;
}

// Prioridad y tono que la IA dedujo en el último análisis (solo se muestra lo que pide atención).
function priorityChips(p) {
  const reason = p.priority_reason ? ` title="${escapeHtml(p.priority_reason)}"` : "";
  return [
    p.priority === "alta" ? `<span class="prio-chip high"${reason}>Prioridad alta</span>` : "",
    p.priority === "media" ? `<span class="prio-chip medium"${reason}>Prioridad media</span>` : "",
    p.mood === "molesto" ? `<span class="prio-chip upset" title="Tono del cliente en sus últimos mensajes">Molesto</span>` : "",
  ].join("");
}

function renderProfile(p) {
  $("#summary-text").textContent = p.summary
    || "Todavía no hay resumen. Pulsa «Actualizar con IA» para que lea las conversaciones y rellene la ficha y las tareas.";
  $("#summary-text").classList.toggle("muted", !p.summary);
  const meta = [];
  if (p.analyzed_at) meta.push(`Actualizado ${timeAgo(p.analyzed_at)}`);
  if (p.analyzed_at && p.new_messages_since_analysis) {
    meta.push(`${p.new_messages_since_analysis} mensaje${p.new_messages_since_analysis === 1 ? "" : "s"} nuevo${p.new_messages_since_analysis === 1 ? "" : "s"} desde entonces`);
  }
  $("#summary-meta").textContent = meta.join(" · ");
  const chips = priorityChips(p);
  $("#summary-priority").innerHTML = chips ? `${chips}${p.priority_reason ? `<span class="muted small">${escapeHtml(p.priority_reason)}</span>` : ""}` : "";
  $("#summary-priority").hidden = !chips;

  $("#facts").innerHTML = p.facts.length ? p.facts.map((f) => `
    <li data-fact="${f.id}">
      <span class="fact-label">${escapeHtml(f.label)}</span>
      <span class="fact-value">${escapeHtml(f.value)}</span>
      <span class="fact-actions">
        ${f.origin === "ai" ? `<span class="ai-badge" title="Extraído por la IA">IA</span>` : `<span class="muted small" title="Confirmado por ${escapeHtml(f.updated_by || "una persona")}">✓</span>`}
        ${sourceLink(f.source_message_id)}
        <button class="icon-link" data-edit-fact="${f.id}" title="Editar">✎</button>
        <button class="icon-link" data-delete-fact="${f.id}" title="${f.origin === "ai" ? "Descartar (la IA no lo volverá a proponer)" : "Borrar"}">×</button>
      </span>
    </li>`).join("") : `<li class="muted small">Sin datos todavía.</li>`;
}

async function analyzeClient() {
  const clientId = state.clientId;
  const btn = $("#analyze-btn");
  btn.disabled = true;
  btn.textContent = "✨ Analizando…";
  try {
    const res = await api(`/api/clients/${clientId}/analyze`, { method: "POST" });
    if (state.clientId !== clientId) return;
    renderProfile(res);
    const c = res.changes;
    const parts = [];
    if (c.facts) parts.push(`${c.facts} dato${c.facts === 1 ? "" : "s"}`);
    if (c.new_tasks) parts.push(`${c.new_tasks} tarea${c.new_tasks === 1 ? "" : "s"} nueva${c.new_tasks === 1 ? "" : "s"}`);
    if (c.completed_tasks) parts.push(`${c.completed_tasks} tarea${c.completed_tasks === 1 ? "" : "s"} completada${c.completed_tasks === 1 ? "" : "s"}`);
    $("#summary-meta").textContent += parts.length ? ` · ${parts.join(", ")}` : "";
    await Promise.all([loadClientTasks(clientId), refreshMyTasksCount()]);
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ Actualizar con IA";
  }
}

async function submitFact(e) {
  e.preventDefault();
  try {
    renderProfile(await api(`/api/clients/${state.clientId}/facts`, {
      method: "POST", body: JSON.stringify({ label: $("#fact-label").value.trim(), value: $("#fact-value").value.trim() }),
    }));
    $("#fact-form").reset();
    $("#fact-label").focus();
  } catch (err) {
    alert(err.message);
  }
}

function startEditFact(li) {
  const label = li.querySelector(".fact-label").textContent;
  const value = li.querySelector(".fact-value").textContent;
  li.innerHTML = `
    <form class="inline-form fact-edit">
      <input name="label" maxlength="100" required value="${escapeHtml(label)}">
      <input name="value" maxlength="2000" required value="${escapeHtml(value)}">
      <button class="ghost small-btn" type="submit">Guardar</button>
      <button class="link" type="button" data-cancel>Cancelar</button>
    </form>`;
  li.querySelector('[name="value"]').focus();
}

async function onFactsClick(e) {
  const li = e.target.closest("li[data-fact]");
  if (!li) return;
  const id = li.dataset.fact;
  try {
    if (e.target.closest("[data-edit-fact]")) startEditFact(li);
    else if (e.target.closest("[data-cancel]")) loadProfile(state.clientId);
    else if (e.target.closest("[data-delete-fact]")) {
      renderProfile(await api(`/api/facts/${id}`, { method: "DELETE" }));
    }
  } catch (err) {
    alert(err.message);
  }
}

async function onFactsSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const id = form.closest("li[data-fact]").dataset.fact;
  try {
    renderProfile(await api(`/api/facts/${id}`, {
      method: "PATCH", body: JSON.stringify({ label: form.elements.label.value.trim(), value: form.elements.value.value.trim() }),
    }));
  } catch (err) {
    alert(err.message);
  }
}

/* ---------- Tareas ---------- */

function assigneeOptions(selected) {
  return `<option value="">Sin responsable</option>` + team.map((u) =>
    `<option value="${u.id}" ${u.id === selected ? "selected" : ""}>${escapeHtml(u.name)}</option>`).join("");
}

function taskItem(t, { showClient = false } = {}) {
  return `
    <li class="task ${t.status}" data-task="${t.id}" data-client="${t.client_id}">
      <input type="checkbox" data-toggle-task ${t.status === "done" ? "checked" : ""} title="${t.status === "done" ? "Marcar como pendiente" : "Marcar como hecha"}">
      <div class="task-body">
        <span class="task-title">${escapeHtml(t.title)}</span>
        <span class="task-meta">
          ${showClient ? `<button class="link client-link" data-open-client="${t.client_id}">${escapeHtml(t.client)}</button>` : ""}
          ${dueLabel(t.due_date)}
          ${showClient ? "" : `<span class="muted">${escapeHtml(t.assignee || "Sin responsable")}</span>`}
          ${t.origin === "ai" ? `<span class="ai-badge" title="Detectada por la IA en las conversaciones">IA</span>` : ""}
          ${showClient ? "" : sourceLink(t.source_message_id)}
        </span>
      </div>
      ${showClient ? "" : `<button class="icon-link" data-edit-task title="Editar">✎</button>
      <button class="icon-link" data-delete-task title="Borrar">×</button>`}
    </li>`;
}

async function loadClientTasks(clientId) {
  const tasks = await api(`/api/tasks?scope=all&status=all&client_id=${clientId}`);
  if (state.clientId !== clientId) return;
  const open = tasks.filter((t) => t.status === "open");
  const done = tasks.filter((t) => t.status === "done");
  $("#client-tasks").innerHTML = open.length ? open.map((t) => taskItem(t)).join("")
    : `<li class="muted small">No hay tareas pendientes con este cliente.</li>`;
  $("#client-done-tasks").innerHTML = done.map((t) => taskItem(t)).join("");
  $("#done-count").textContent = done.length;
  $("#done-tasks").hidden = !done.length;
  const count = $("#client-tasks-count");
  count.textContent = open.length;
  count.hidden = !open.length;
}

async function loadMyTasks() {
  const tasks = await api("/api/tasks?scope=mine&status=open");
  setMyTasksCount(tasks);
  const today = todayIso();
  const groups = [
    ["Vencidas", tasks.filter((t) => t.due_date && t.due_date < today)],
    ["Hoy", tasks.filter((t) => t.due_date === today)],
    ["Próximas", tasks.filter((t) => t.due_date && t.due_date > today)],
    ["Sin fecha", tasks.filter((t) => !t.due_date)],
  ].filter(([, list]) => list.length);
  $("#my-tasks").innerHTML = groups.length
    ? groups.map(([title, list]) => `<li class="task-group">${title}</li>` + list.map((t) => taskItem(t, { showClient: true })).join("")).join("")
    : `<li class="muted small empty-tasks">No tienes tareas pendientes.</li>`;
}

function setMyTasksCount(tasks) {
  const overdue = tasks.filter((t) => t.due_date && t.due_date <= todayIso()).length;
  const count = $("#my-tasks-count");
  count.textContent = tasks.length;
  count.hidden = !tasks.length;
  count.classList.toggle("alert", overdue > 0);
  count.title = overdue ? `${overdue} vencida${overdue === 1 ? "" : "s"} o para hoy` : "";
}

async function refreshMyTasksCount() {
  try {
    const tasks = await api("/api/tasks?scope=mine&status=open");
    setMyTasksCount(tasks);
    if (!$("#side-tasks").hidden) loadMyTasks();
  } catch { /* no crítico */ }
}

async function refreshTasksEverywhere(clientId) {
  await Promise.all([
    state.clientId === clientId ? loadClientTasks(clientId) : null,
    refreshMyTasksCount(),
  ]);
}

async function submitTask(e) {
  e.preventDefault();
  const clientId = state.clientId;
  try {
    await api(`/api/clients/${clientId}/tasks`, {
      method: "POST",
      body: JSON.stringify({
        title: $("#task-title").value.trim(),
        due_date: $("#task-due").value || null,
        assignee_user_id: Number($("#task-assignee").value) || null,
      }),
    });
    $("#task-title").value = "";
    $("#task-due").value = "";
    await refreshTasksEverywhere(clientId);
  } catch (err) {
    alert(err.message);
  }
}

function startEditTask(li, task) {
  li.innerHTML = `
    <form class="task-form task-edit">
      <input name="title" maxlength="300" required value="${escapeHtml(task.title)}">
      <div class="task-form-row">
        <input name="due" type="date" value="${task.due_date || ""}">
        <select name="assignee">${assigneeOptions(task.assignee_user_id)}</select>
        <button class="ghost small-btn" type="submit">Guardar</button>
        <button class="link" type="button" data-cancel>Cancelar</button>
      </div>
    </form>`;
  li.querySelector('[name="title"]').focus();
}

async function onTaskClick(e) {
  const li = e.target.closest("li[data-task]");
  if (!li) return;
  const id = li.dataset.task;
  const clientId = Number(li.dataset.client);
  try {
    if (e.target.closest("[data-open-client]")) {
      await selectClient(clientId);
      showDetailTab("tasks");
    } else if (e.target.matches("[data-toggle-task]")) {
      await api(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ status: e.target.checked ? "done" : "open" }) });
      await refreshTasksEverywhere(clientId);
    } else if (e.target.closest("[data-delete-task]")) {
      if (!confirm("¿Borrar esta tarea?")) return;
      await api(`/api/tasks/${id}`, { method: "DELETE" });
      await refreshTasksEverywhere(clientId);
    } else if (e.target.closest("[data-edit-task]")) {
      const tasks = await api(`/api/tasks?scope=all&status=all&client_id=${clientId}`);
      const task = tasks.find((t) => String(t.id) === id);
      if (task) startEditTask(li, task);
    } else if (e.target.closest("[data-cancel]")) {
      await loadClientTasks(clientId);
    }
  } catch (err) {
    alert(err.message);
  }
}

async function onTaskSubmit(e) {
  if (!e.target.classList.contains("task-edit")) return;
  e.preventDefault();
  const form = e.target;
  const li = form.closest("li[data-task]");
  try {
    await api(`/api/tasks/${li.dataset.task}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: form.elements.title.value.trim(), due_date: form.elements.due.value || null,
        assignee_user_id: Number(form.elements.assignee.value) || null,
      }),
    });
    await refreshTasksEverywhere(Number(li.dataset.client));
  } catch (err) {
    alert(err.message);
  }
}

/* ---------- Ir al mensaje de origen ---------- */

async function showSourceMessage(messageId) {
  showDetailTab("messages");
  // El mensaje puede ser de la conversación de un compañero: se muestra todo el historial.
  state.scope = "team";
  $("#only-mine").checked = false;
  state.channel = "";
  $("#channel-filter").value = "";
  await loadTimeline();
  const li = document.querySelector(`#timeline li[data-id="${messageId}"]`);
  if (li) {
    li.scrollIntoView({ block: "center", behavior: "smooth" });
    li.classList.add("flash");
    setTimeout(() => li.classList.remove("flash"), 2500);
  }
}

/* ---------- Al abrir un cliente ---------- */

async function openClientDetail(clientId) {
  $("#task-assignee").innerHTML = assigneeOptions(currentUser.id);
  await Promise.all([loadProfile(clientId), loadClientTasks(clientId), loadNotes(clientId), loadDocuments(clientId)]);
}

function bindProfileEvents() {
  document.querySelectorAll(".detail-tabs [data-tab]").forEach((b) =>
    b.addEventListener("click", () => showDetailTab(b.dataset.tab)));
  document.querySelectorAll(".side-tabs [data-side]").forEach((b) =>
    b.addEventListener("click", () => showSideTab(b.dataset.side)));
  $("#analyze-btn").addEventListener("click", analyzeClient);
  $("#fact-form").addEventListener("submit", submitFact);
  $("#facts").addEventListener("click", onFactsClick);
  $("#facts").addEventListener("submit", onFactsSubmit);
  $("#task-form").addEventListener("submit", submitTask);
  ["#client-tasks", "#client-done-tasks", "#my-tasks"].forEach((sel) => {
    $(sel).addEventListener("click", onTaskClick);
    $(sel).addEventListener("submit", onTaskSubmit);
  });
  $("#detail").addEventListener("click", (e) => {
    const src = e.target.closest("[data-source]");
    if (src) showSourceMessage(Number(src.dataset.source));
  });
}

async function initProfile() {
  team = await api("/api/team");
  await refreshMyTasksCount();
}
