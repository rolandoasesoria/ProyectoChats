// IA que responde por WhatsApp: la sección «Respuestas con IA» (configuración y «Probar la IA») y, en cada chat, el interruptor para
// pausarla en esa conversación y la propuesta de respuesta del modo supervisado.

const AI_DAYS = [[1, "L"], [2, "M"], [3, "X"], [4, "J"], [5, "V"], [6, "S"], [7, "D"]];
const aiState = { settings: null, conversation: null }; // conversation: estado de la IA en el chat abierto

/* ---------- Sección IA ---------- */

function setSegment(groupSel, attr, value) {
  document.querySelectorAll(`${groupSel} [data-${attr}]`).forEach((b) =>
    b.classList.toggle("active", b.dataset[attr] === String(value)));
}

function segmentValue(groupSel, attr) {
  return document.querySelector(`${groupSel} [data-${attr}].active`)?.dataset[attr];
}

function renderAISettings(s) {
  $("#ai-enabled").checked = s.enabled;
  setSegment("#ai-mode", "mode", s.mode);
  setSegment("#ai-inactivity", "hours", s.inactivity_hours);
  $("#ai-schedule").value = s.schedule;
  const [start, end] = s.hours.split("-");
  $("#ai-hours-start").value = start;
  $("#ai-hours-end").value = end;
  $("#ai-days").innerHTML = AI_DAYS.map(([n, label]) =>
    `<label class="check day-check"><input type="checkbox" value="${n}" ${s.days.includes(n) ? "checked" : ""}>${label}</label>`).join("");
  $("#ai-hours-box").hidden = s.schedule !== "out_of_hours";
  $("#ai-instructions").value = s.instructions;
  const admin = currentUser.role === "admin";
  $("#ai-readonly").hidden = admin;
  $("#ai-test").hidden = !admin;
  document.querySelectorAll("#view-ai input, #view-ai select, #view-ai textarea, #view-ai button").forEach((el) => {
    if (!el.closest("#ai-test")) el.disabled = !admin;
  });
}

async function loadAISettings() {
  aiState.settings = await api("/api/ai-reply/settings");
  renderAISettings(aiState.settings);
}

function aiFormValues() {
  return {
    enabled: $("#ai-enabled").checked,
    mode: segmentValue("#ai-mode", "mode"),
    inactivity_hours: Number(segmentValue("#ai-inactivity", "hours")),
    schedule: $("#ai-schedule").value,
    hours: `${$("#ai-hours-start").value || "09:00"}-${$("#ai-hours-end").value || "18:00"}`,
    days: [...$("#ai-days").querySelectorAll("input:checked")].map((i) => Number(i.value)),
    instructions: $("#ai-instructions").value,
  };
}

async function saveAISettings(e) {
  e?.preventDefault();
  showError($("#ai-error"), "");
  $("#ai-saved").hidden = true;
  try {
    aiState.settings = await api("/api/admin/ai-reply/settings", { method: "PUT", body: JSON.stringify(aiFormValues()) });
    renderAISettings(aiState.settings);
    $("#ai-saved").hidden = false;
  } catch (err) {
    showError($("#ai-error"), err.message);
    renderAISettings(aiState.settings); // p. ej. no se puede activar sin instrucciones: vuelve a como estaba
  }
}

async function testAI() {
  const message = $("#ai-test-message").value.trim();
  if (!message) return;
  const box = $("#ai-test-result");
  const btn = $("#ai-test-btn");
  btn.disabled = true;
  box.hidden = false;
  box.innerHTML = `<span class="muted small">Pensando…</span>`;
  try {
    const r = await api("/api/admin/ai-reply/test", {
      method: "POST", body: JSON.stringify({ message, instructions: $("#ai-instructions").value }),
    });
    box.innerHTML = r.action === "reply"
      ? `<span class="muted small">Respondería:</span><div class="tpl-bubble">${escapeHtml(r.message)}</div>`
      : `<span class="muted small">No respondería: pasaría el chat a una persona.</span><p>${escapeHtml(r.reason)}</p>`;
  } catch (err) {
    box.innerHTML = `<p class="form-error">${escapeHtml(err.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
}

/* ---------- En el chat ---------- */

// Estado de la IA en la conversación abierta (WhatsApp): interruptor de pausa y propuesta pendiente.
async function loadChatAI(conversationId) {
  const toggle = $("#chat-ai-toggle");
  const box = $("#chat-ai-suggestion");
  const shownId = aiState.conversation?.pending?.id; // propuesta que ya se ve (quizá editada a medias)
  toggle.hidden = true;
  box.hidden = true;
  aiState.conversation = null;
  if (!conversationId) return;
  try {
    const state = await api(`/api/conversations/${conversationId}/ai`);
    if (chatState.conversationId !== conversationId || !state.available) return;
    aiState.conversation = { id: conversationId, ...state };
    toggle.hidden = !state.enabled;
    toggle.textContent = state.paused ? "🤖 IA en pausa" : "🤖 IA activa";
    toggle.classList.toggle("paused", state.paused);
    toggle.setAttribute("aria-pressed", String(!state.paused));
    if (state.pending) {
      // Al refrescarse el chat no se pisa lo que se está editando: el texto solo cambia con una propuesta nueva.
      if (state.pending.id !== shownId) $("#chat-ai-text").value = state.pending.text;
      box.hidden = false;
    }
  } catch { /* sin IA en este chat */ }
}

async function toggleChatAI() {
  const c = aiState.conversation;
  if (!c) return;
  try {
    await api(`/api/conversations/${c.id}/ai`, { method: "PUT", body: JSON.stringify({ paused: !c.paused }) });
    await loadChatAI(c.id);
  } catch (err) {
    alert(err.message);
  }
}

async function decideSuggestion(send) {
  const pending = aiState.conversation?.pending;
  if (!pending) return;
  const buttons = [$("#chat-ai-send"), $("#chat-ai-discard")];
  buttons.forEach((b) => { b.disabled = true; });
  try {
    if (send) {
      await api(`/api/ai-replies/${pending.id}/send`, { method: "POST", body: JSON.stringify({ text: $("#chat-ai-text").value }) });
    } else {
      await api(`/api/ai-replies/${pending.id}/discard`, { method: "POST" });
    }
    await loadChatConversation();
    loadChats();
  } catch (err) {
    alert(err.message);
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}

/* ---------- Eventos ---------- */

function bindAIEvents() {
  $("#ai-form").addEventListener("submit", saveAISettings);
  $("#ai-enabled").addEventListener("change", () => saveAISettings());
  ["#ai-mode", "#ai-inactivity"].forEach((sel) => $(sel).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    $(sel).querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
  }));
  $("#ai-schedule").addEventListener("change", (e) => { $("#ai-hours-box").hidden = e.target.value !== "out_of_hours"; });
  $("#ai-test-btn").addEventListener("click", testAI);
  $("#ai-test-message").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); testAI(); } });
  $("#chat-ai-toggle").addEventListener("click", toggleChatAI);
  $("#chat-ai-send").addEventListener("click", () => decideSuggestion(true));
  $("#chat-ai-discard").addEventListener("click", () => decideSuggestion(false));
}
