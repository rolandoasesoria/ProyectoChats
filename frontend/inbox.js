// Bandeja "Sin responder" y novedades desde la última visita a un cliente.

let inboxScope = "mine";
const WAIT_ALERT_HOURS = 24; // a partir de aquí la espera se marca en rojo

function waitLabel(sentAt) {
  const hours = (Date.now() - new Date(sentAt)) / 3600000;
  let text;
  if (hours < 1) text = `${Math.max(1, Math.round(hours * 60))} min`;
  else if (hours < 48) text = `${Math.round(hours)} h`;
  else text = `${Math.round(hours / 24)} días`;
  return `<span class="wait ${hours >= WAIT_ALERT_HOURS ? "late" : ""}" title="Esperando respuesta desde ${formatDate(sentAt)}">⏱ ${text}</span>`;
}

// Número de conversaciones en cada lado del selector «Mías · Todo el equipo».
async function loadInboxCounts() {
  const c = await api("/api/inbox/counts");
  $("#inbox-count-mine").textContent = c.mine;
  $("#inbox-count-team").textContent = c.team;
}

async function loadInbox() {
  const [items] = await Promise.all([api(`/api/inbox?scope=${inboxScope}`), loadInboxCounts()]);
  if (inboxScope === "mine") setInboxCount(items);
  $("#inbox-list").innerHTML = items.length ? items.map((i) => `
    <li class="inbox-item" data-client="${i.client_id}" data-message="${i.message_id}" data-conversation="${i.conversation_id}">
      <div class="inbox-top">
        <strong>${escapeHtml(i.client)}</strong>
        ${waitLabel(i.sent_at)}
      </div>
      <div class="inbox-snippet">${badge(i.channel)} ${escapeHtml(i.body.length > 140 ? `${i.body.slice(0, 140)}…` : i.body)}</div>
      <div class="inbox-bottom">
        <span class="muted small">${i.is_mine ? "La llevas tú" : `La lleva ${escapeHtml(i.owner)}`}</span>
        <span>
          <button class="link small" data-reply title="Redactar la respuesta con IA">✍️ Responder</button>
          <button class="link small" data-dismiss title="Quitar de la bandeja: no necesita respuesta">✓ Atendido</button>
        </span>
      </div>
    </li>`).join("")
    : `<li class="muted small empty-tasks">${inboxScope === "mine" ? "Nadie espera tu respuesta. 🎉" : "Nadie espera respuesta del equipo. 🎉"}</li>`;
}

function setInboxCount(items) {
  const late = items.filter((i) => (Date.now() - new Date(i.sent_at)) / 3600000 >= WAIT_ALERT_HOURS).length;
  const count = $("#inbox-count");
  count.textContent = items.length;
  count.hidden = !items.length;
  count.classList.toggle("alert", late > 0);
  count.title = late ? `${late} esperando más de ${WAIT_ALERT_HOURS} h` : "";
}

async function refreshInboxCount() {
  try {
    setInboxCount(await api("/api/inbox?scope=mine"));
    if (!$("#side-inbox").hidden) loadInbox();
  } catch { /* no crítico */ }
}

async function onInboxClick(e) {
  const li = e.target.closest(".inbox-item");
  if (!li) return;
  if (e.target.closest("[data-dismiss]")) {
    try {
      await api(`/api/conversations/${li.dataset.conversation}/dismiss`, {
        method: "POST", body: JSON.stringify({ message_id: Number(li.dataset.message) }),
      });
      await Promise.all([loadInbox(), refreshInboxCount()]);
    } catch (err) {
      alert(err.message);
    }
    return;
  }
  if (e.target.closest("[data-reply]")) {
    await replyFromInbox(Number(li.dataset.client), Number(li.dataset.conversation));
    return;
  }
  await selectClient(Number(li.dataset.client));
  await showSourceMessage(Number(li.dataset.message));
}

/* ---------- Novedades desde la última visita ---------- */

let whatsNewSince = null;

async function recordVisit(clientId) {
  const box = $("#whats-new");
  box.hidden = true;
  $("#whats-new-summary").hidden = true;
  const v = await api(`/api/clients/${clientId}/visit`, { method: "POST" });
  if (state.clientId !== clientId) return;
  // Ya visto: se quita el contador de no leídos de la lista.
  document.querySelector(`#client-list li[data-id="${clientId}"] .unread`)?.remove();
  if (!v.previous_visit_at || !v.new_messages) return;
  whatsNewSince = v.since_message_id;
  $("#whats-new-text").textContent =
    `${v.new_messages} mensaje${v.new_messages === 1 ? "" : "s"} nuevo${v.new_messages === 1 ? "" : "s"} desde tu última visita (${timeAgo(v.previous_visit_at)})`;
  $("#whats-new-btn").hidden = false;
  box.hidden = false;
}

async function summarizeWhatsNew() {
  const clientId = state.clientId;
  const btn = $("#whats-new-btn");
  btn.disabled = true;
  btn.textContent = "✨ Resumiendo…";
  try {
    const res = await api(`/api/clients/${clientId}/whats-new`, {
      method: "POST", body: JSON.stringify({ since_message_id: whatsNewSince }),
    });
    if (state.clientId !== clientId) return;
    $("#whats-new-summary").innerHTML = renderMarkdown(res.summary);
    $("#whats-new-summary").hidden = false;
    btn.hidden = true;
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ Resumir novedades";
  }
}

function bindInboxEvents() {
  $("#inbox-list").addEventListener("click", onInboxClick);
  document.querySelectorAll("#inbox-scope [data-inbox-scope]").forEach((b) => b.addEventListener("click", () => {
    inboxScope = b.dataset.inboxScope;
    document.querySelectorAll("#inbox-scope [data-inbox-scope]").forEach((x) => x.classList.toggle("active", x === b));
    loadInbox();
  }));
  $("#whats-new-btn").addEventListener("click", summarizeWhatsNew);
  // La bandeja se revisa cada minuto (p. ej. mensajes que entran por importaciones de otros compañeros).
  setInterval(refreshInboxCount, 60000);
}
