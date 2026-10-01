// Bandeja "Sin responder" y novedades desde la última visita a un cliente.

let inboxScope = "mine";
let slaHours = 24; // plazo de respuesta del equipo (lo fija un administrador); se carga al arrancar
const SLA_WARNING = 0.75; // a partir del 75 % del plazo se avisa de que está a punto de vencer

// Tiempo transcurrido desde un mensaje (hora local): «40 min», «5 h», «3 días».
function elapsed(sentAt) {
  const hours = (Date.now() - new Date(sentAt)) / 3600000;
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} días`;
}

function waitHours(sentAt) {
  return (Date.now() - new Date(sentAt)) / 3600000;
}

// Tiempo de espera con el plazo de respuesta: normal, «vence en…» (ámbar) o fuera de plazo (rojo).
function waitLabel(sentAt) {
  const hours = waitHours(sentAt);
  const title = `Esperando respuesta desde ${formatDate(sentAt)} · plazo de respuesta: ${slaHours} h`;
  if (hours >= slaHours) return `<span class="wait late" title="Fuera de plazo · ${title}">${elapsed(sentAt)}</span>`;
  if (hours >= slaHours * SLA_WARNING) {
    const left = slaHours - hours;
    const leftText = left < 1 ? `${Math.max(1, Math.round(left * 60))} min` : `${Math.round(left)} h`;
    return `<span class="wait soon" title="${title}">vence en ${leftText}</span>`;
  }
  return `<span class="wait" title="${title}">${elapsed(sentAt)}</span>`;
}

// Número de conversaciones en cada lado del selector «Mías · Todo el equipo».
async function loadInboxCounts() {
  const c = await api("/api/inbox/counts");
  $("#inbox-count-mine").textContent = c.mine;
  $("#inbox-count-team").textContent = c.team;
}

// Fecha de «Posponer…» (hora local del navegador).
function snoozeDate(option) {
  const d = new Date();
  if (option === "3h") return new Date(d.getTime() + 3 * 3600000);
  const at9 = (days) => { const x = new Date(d); x.setDate(x.getDate() + days); x.setHours(9, 0, 0, 0); return x; };
  if (option === "tomorrow") return at9(1);
  if (option === "monday") return at9(((8 - d.getDay()) % 7) || 7);
  if (option === "week") return at9(7);
  return null;
}

const SNOOZE_SELECT = `<select class="small-select" data-snooze title="Quitarla de la bandeja hasta…">
  <option value="">Posponer…</option><option value="3h">3 horas</option><option value="tomorrow">Mañana a las 9</option>
  <option value="monday">El lunes a las 9</option><option value="week">En una semana</option></select>`;

function followUpItem(f) {
  return `
    <li class="inbox-item follow-up" data-client="${f.client_id}" data-message="${f.message_id}" data-conversation="${f.conversation_id}" data-follow-up="${f.id}">
      <div class="inbox-top">
        <strong>${escapeHtml(f.client)}</strong>
        <span class="wait late" title="Le escribiste el ${formatDate(f.sent_at)}">sin contestar · ${elapsed(f.sent_at)}</span>
      </div>
      <div class="inbox-snippet">${badge(f.channel)} Tú: ${escapeHtml(f.body.length > 120 ? `${f.body.slice(0, 120)}…` : f.body)}</div>
      <div class="inbox-bottom">
        <span class="muted small">Seguimiento</span>
        <span>
          <button class="link small" data-reply title="Escribirle de nuevo">Escribir</button>
          <button class="link small" data-follow-up-done title="Quitar el aviso">✓ Hecho</button>
        </span>
      </div>
    </li>`;
}

async function loadInbox() {
  const scope = inboxScope;
  const [items, followUps, snoozed] = await Promise.all([
    api(`/api/inbox?scope=${scope}`),
    scope === "mine" ? api("/api/follow-ups") : Promise.resolve([]),
    api(`/api/inbox?scope=${scope}&snoozed=true`),
    loadInboxCounts(),
  ]);
  if (scope !== inboxScope) return;
  if (scope === "mine") setInboxCount(items, followUps);
  const followHtml = followUps.length
    ? `<li class="inbox-group">Seguimientos: no han contestado</li>${followUps.map(followUpItem).join("")}
       ${items.length ? `<li class="inbox-group">Esperan respuesta</li>` : ""}`
    : "";
  const snoozedHtml = snoozed.length ? `
    <li class="inbox-snoozed"><details>
      <summary>Pospuestas (${snoozed.length})</summary>
      <ul class="inbox-list">${snoozed.map((i) => `
        <li class="inbox-item snoozed" data-client="${i.client_id}" data-message="${i.message_id}" data-conversation="${i.conversation_id}">
          <div class="inbox-top"><strong>${escapeHtml(i.client)}</strong>
            <span class="wait" title="Vuelve a la bandeja entonces, o antes si el cliente escribe">hasta ${formatDate(i.snoozed_until + "Z")}</span></div>
          <div class="inbox-snippet">${badge(i.channel)} ${escapeHtml(i.body.length > 100 ? `${i.body.slice(0, 100)}…` : i.body)}</div>
          <div class="inbox-bottom"><span></span><button class="link small" data-unsnooze>Volver ahora</button></div>
        </li>`).join("")}</ul>
    </details></li>` : "";
  $("#inbox-list").innerHTML = followHtml + (items.length ? items.map((i) => `
    <li class="inbox-item" data-client="${i.client_id}" data-message="${i.message_id}" data-conversation="${i.conversation_id}">
      <div class="inbox-top">
        <strong>${escapeHtml(i.client)}</strong>
        ${waitLabel(i.sent_at)}
      </div>
      <div class="inbox-snippet">${badge(i.channel)} ${escapeHtml(i.body.length > 140 ? `${i.body.slice(0, 140)}…` : i.body)}</div>
      <div class="inbox-bottom">
        <span class="muted small">${i.is_mine ? "La llevas tú" : `La lleva ${escapeHtml(i.owner)}`}</span>
        <span>
          <button class="link small" data-reply title="Redactar la respuesta con IA">Responder</button>
          <button class="link small" data-dismiss title="Quitar de la bandeja: no necesita respuesta">✓ Atendido</button>
          ${SNOOZE_SELECT}
        </span>
      </div>
    </li>`).join("")
    : followUps.length ? "" : `<li class="muted small empty-tasks">${scope === "mine" ? "Nadie espera tu respuesta." : "Nadie espera respuesta del equipo."}</li>`) + snoozedHtml;
}

function setInboxCount(items, followUps = []) {
  const late = items.filter((i) => waitHours(i.sent_at) >= slaHours).length + followUps.length;
  const total = items.length + followUps.length;
  const count = $("#inbox-count");
  count.textContent = total;
  count.hidden = !total;
  count.classList.toggle("alert", late > 0);
  count.title = late ? `${late} fuera de plazo (${slaHours} h) o sin contestar` : "";
}

async function loadSettings() {
  try {
    slaHours = (await api("/api/settings")).sla_hours;
  } catch { /* se queda el plazo por defecto */ }
}

async function refreshInboxCount() {
  try {
    const [items, followUps] = await Promise.all([api("/api/inbox?scope=mine"), api("/api/follow-ups")]);
    setInboxCount(items, followUps);
    if (!$("#side-inbox").hidden) loadInbox();
  } catch { /* no crítico */ }
}

async function onInboxClick(e) {
  const li = e.target.closest(".inbox-item");
  if (!li || e.target.closest("[data-snooze], summary")) return;
  if (e.target.closest("[data-follow-up-done]") || e.target.closest("[data-unsnooze]")) {
    try {
      await api(li.dataset.followUp ? `/api/follow-ups/${li.dataset.followUp}` : `/api/conversations/${li.dataset.conversation}/snooze`,
        { method: "DELETE" });
      await Promise.all([loadInbox(), refreshInboxCount()]);
    } catch (err) {
      alert(err.message);
    }
    return;
  }
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

async function onInboxSnooze(e) {
  const select = e.target.closest("[data-snooze]");
  const until = select && snoozeDate(select.value);
  if (!until) return;
  const li = select.closest(".inbox-item");
  try {
    await api(`/api/conversations/${li.dataset.conversation}/snooze`, {
      method: "POST", body: JSON.stringify({ until: until.toISOString(), message_id: Number(li.dataset.message) }),
    });
    await Promise.all([loadInbox(), refreshInboxCount()]);
  } catch (err) {
    alert(err.message);
    select.value = "";
  }
}

function bindInboxEvents() {
  $("#inbox-list").addEventListener("click", onInboxClick);
  $("#inbox-list").addEventListener("change", onInboxSnooze);
  document.querySelectorAll("#inbox-scope [data-inbox-scope]").forEach((b) => b.addEventListener("click", () => {
    inboxScope = b.dataset.inboxScope;
    document.querySelectorAll("#inbox-scope [data-inbox-scope]").forEach((x) => x.classList.toggle("active", x === b));
    loadInbox();
  }));
  $("#whats-new-btn").addEventListener("click", summarizeWhatsNew);
  // La bandeja se revisa cada minuto (p. ej. mensajes que entran por importaciones de otros compañeros).
  setInterval(refreshInboxCount, 60000);
}
