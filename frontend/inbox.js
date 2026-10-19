// Bandeja "Sin responder" y novedades desde la última visita a un cliente.

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

const SNOOZE_SELECT = `<select class="small-select chat-act" data-snooze title="Quitarla de la bandeja hasta…">
  <option value="">Posponer…</option><option value="3h">3 horas</option><option value="tomorrow">Mañana a las 9</option>
  <option value="monday">El lunes a las 9</option><option value="week">En una semana</option></select>`;

// Quién lleva al cliente: su responsable (uno solo), aunque hayan hablado con él varias personas.
function responsibleLabel(assigneeId, assignee) {
  if (!assigneeId) return "Sin responsable";
  return assigneeId === currentUser.id ? "Responsable: tú" : `Responsable: ${escapeHtml(assignee)}`;
}

// Un elemento de la bandeja con el mismo aspecto que los de Todos y No leídos: en lugar de la hora, cuánto lleva
// esperando (ámbar a punto de vencer, rojo fuera de plazo); debajo, el canal y el responsable; y, al pasar el ratón,
// sus acciones. `kind`: waiting (espera respuesta), followup (no ha contestado) o snoozed (pospuesta).
function inboxItemHtml(i, kind = "waiting") {
  const body = i.body.length > 140 ? `${i.body.slice(0, 140)}…` : i.body;
  const when = kind === "followup"
    ? `<span class="wait late" title="Le escribiste el ${escapeHtml(formatDate(i.sent_at))}">sin contestar · ${elapsed(i.sent_at)}</span>`
    : kind === "snoozed"
      ? `<span class="wait" title="Vuelve a la bandeja entonces, o antes si el cliente escribe">hasta ${escapeHtml(formatDate(`${i.snoozed_until}Z`))}</span>`
      : waitLabel(i.sent_at);
  const actions = kind === "followup"
    ? `<button type="button" class="chat-act" data-reply title="Escribirle de nuevo">Escribir</button>
       <button type="button" class="chat-act" data-follow-up-done title="Quitar el aviso">✓ Hecho</button>`
    : kind === "snoozed"
      ? `<button type="button" class="chat-act" data-unsnooze title="Devolverla ya a la bandeja">Volver ahora</button>`
      : `<button type="button" class="chat-act" data-reply title="Escribir la respuesta">Responder</button>
         <button type="button" class="chat-act" data-dismiss title="Quitar de la bandeja: no necesita respuesta">✓ Atendido</button>
         ${SNOOZE_SELECT}`;
  return `
    <li class="inbox-item ${kind}${i.client_id === chatState.clientId ? " active" : ""}" data-client="${i.client_id}"
        data-message="${i.message_id}" data-conversation="${i.conversation_id}"${kind === "followup" ? ` data-follow-up="${i.id}"` : ""}>
      <span class="chat-avatar ${avatarClass(i.client)}">${escapeHtml(initialsOf(i.client))}</span>
      <div class="chat-item-body">
        <div class="chat-item-top"><strong>${escapeHtml(i.client)}</strong>${when}</div>
        <div class="chat-item-bottom"><span class="chat-preview">${kind === "followup" ? "↪ " : ""}${escapeHtml(body)}</span></div>
        <div class="chat-item-meta">${badge(i.channel)}${kind === "waiting" ? priorityChips(i) : ""}
          <span class="inbox-resp">${kind === "followup" ? "Seguimiento" : responsibleLabel(i.assignee_id, i.assignee)}</span></div>
      </div>
      <div class="chat-actions">${actions}</div>
    </li>`;
}

// «Sin responder» en Mis Chats: en la misma lista, con el mismo buscador y el mismo «Mis chats / Todo el equipo».
async function loadInbox() {
  const scope = chatState.scope;
  const [items, followUps, snoozed] = await Promise.all([
    api(`/api/inbox?scope=${scope}`),
    scope === "mine" ? api("/api/follow-ups") : Promise.resolve([]),
    api(`/api/inbox?scope=${scope}&snoozed=true`),
  ]);
  if (scope !== chatState.scope || chatState.filter !== "inbox") return;
  if (scope === "mine") setInboxCount(items, followUps);
  const q = normText(chatState.query.trim());
  const match = (i) => !q || normText(i.client).includes(q);
  const [waiting, follow, later] = [items.filter(match), followUps.filter(match), snoozed.filter(match)];
  const group = (title) => `<li class="chats-group">${title}</li>`;
  const html = (follow.length ? group("Seguimientos: no han contestado") + follow.map((f) => inboxItemHtml(f, "followup")).join("")
    + (waiting.length ? group("Esperan respuesta") : "") : "")
    + waiting.map((i) => inboxItemHtml(i)).join("")
    + (later.length ? `<li class="inbox-snoozed"><details><summary>Pospuestas (${later.length})</summary>
        <ul class="chats-list">${later.map((i) => inboxItemHtml(i, "snoozed")).join("")}</ul></details></li>` : "");
  $("#chats-list").innerHTML = html || `<li class="chats-empty muted small">${q ? "Nadie que espere respuesta coincide con la búsqueda."
    : scope === "mine" ? "Nadie espera tu respuesta." : "Nadie espera respuesta del equipo."}</li>`;
}

function setInboxCount(items, followUps = []) {
  const late = items.filter((i) => waitHours(i.sent_at) >= slaHours).length + followUps.length;
  const total = items.length + followUps.length;
  const count = $("#inbox-count");
  count.textContent = total;
  count.hidden = !total;
  count.classList.toggle("alert", late > 0);
  count.title = late ? `${late} fuera de plazo (${slaHours} h) o sin contestar` : "";
  setNavInbox(total, late);
}

async function loadSettings() {
  try {
    const s = await api("/api/settings");
    slaHours = s.sla_hours;
    setCompany(s);
  } catch { /* se queda el plazo por defecto */ }
}

async function refreshInboxCount() {
  try {
    const [items, followUps] = await Promise.all([api("/api/inbox?scope=mine"), api("/api/follow-ups")]);
    setInboxCount(items, followUps);
    if (chatState.filter === "inbox" && currentView() === "chats") loadInbox();
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
  refreshNavCounts(); // ya no cuenta como chat sin leer
  if (state.clientId !== clientId) return;
  // Ya visto: se quita el contador de no leídos de las listas.
  document.querySelectorAll(`#chats-list li[data-client="${clientId}"], #contacts-mini li[data-client="${clientId}"]`)
    .forEach((li) => { li.classList.remove("has-unread"); li.querySelector(".unread")?.remove(); });
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
  $("#chats-list").addEventListener("click", onInboxClick);
  $("#chats-list").addEventListener("change", onInboxSnooze);
  $("#whats-new-btn").addEventListener("click", summarizeWhatsNew);
  // La bandeja se revisa cada minuto (mensajes que entran por las integraciones).
  setInterval(refreshInboxCount, 60000);
}
