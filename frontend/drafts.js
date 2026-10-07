// Borradores de respuesta con IA (pestaña Mensajes de la ficha y botón "Responder" de la bandeja), y su envío
// por la cuenta conectada del canal.


function fillDraftConversations(conversations, selectedId) {
  $("#draft-conversation").innerHTML = conversations.map((c) => {
    const last = c.last_at ? new Date(c.last_at).toLocaleDateString("es-ES", { day: "numeric", month: "short" }) : "";
    const label = [IDENTITY_LABELS[c.channel] || c.channel, c.subject, c.is_mine ? "tuya" : `de ${c.owner}`, last && `último ${last}`]
      .filter(Boolean).join(" · ");
    return `<option value="${c.id}" ${c.id === selectedId ? "selected" : ""}>${escapeHtml(label)}</option>`;
  }).join("");
}

// Abre el panel. Sin conversación indicada, propone la más reciente.
function openDraftPanel(conversationId = null) {
  const conversations = state.clientData?.conversations || [];
  if (!conversations.length) {
    alert("Este cliente todavía no tiene conversaciones.");
    return;
  }
  fillDraftConversations(conversations, conversationId ?? conversations[0].id);
  updateSendButton();
  $("#draft-text").hidden = true;
  $("#draft-text").value = "";
  $("#draft-result-actions").hidden = true;
  $("#draft-applied").hidden = true;
  $("#draft-undo").hidden = true;
  $("#draft-followup").value = "";
  $("#draft-sent-note").hidden = true;
  draftBeforeRewrite = null;
  $("#reply-picker").hidden = true;
  $("#draft-instructions").value = "";
  $("#draft-panel").hidden = false;
  $("#draft-open").hidden = true;
  heartbeat();
  $("#draft-instructions").focus();
}

function closeDraftPanel() {
  const wasOpen = !$("#draft-panel").hidden;
  $("#draft-panel").hidden = true;
  if (wasOpen) heartbeat();
  $("#reply-picker").hidden = true;
  $("#draft-open").hidden = false;
}

async function generateDraft() {
  const clientId = state.clientId;
  const btn = $("#draft-generate");
  btn.disabled = true;
  btn.textContent = "✨ Redactando…";
  try {
    const res = await api(`/api/conversations/${$("#draft-conversation").value}/draft`, {
      method: "POST", body: JSON.stringify({ instructions: $("#draft-instructions").value }),
    });
    if (state.clientId !== clientId) return;
    const text = $("#draft-text");
    text.value = res.draft;
    text.hidden = false;
    $("#draft-result-actions").hidden = false;
    btn.textContent = "✨ Generar otro";
    text.focus();
  } catch (err) {
    alert(err.message);
    btn.textContent = "✨ Generar borrador";
  } finally {
    btn.disabled = false;
  }
}

// «Avísame si no contesta»: se programa al enviar o copiar la respuesta.
async function scheduleFollowUp(conversationId) {
  const days = Number($("#draft-followup").value);
  if (!days) return "";
  try {
    const f = await api(`/api/conversations/${conversationId}/follow-up`, { method: "POST", body: JSON.stringify({ days }) });
    $("#draft-followup").value = "";
    return `Te avisaré el ${new Date(`${f.due_at}Z`).toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })} si no contesta.`;
  } catch (err) {
    return `No se pudo programar el aviso: ${err.message}`;
  }
}

async function copyDraft() {
  const text = $("#draft-text").value;
  if (!(await confirmNoNews($("#draft-conversation").value))) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    $("#draft-text").select();
    document.execCommand("copy");
  }
  const note = await scheduleFollowUp($("#draft-conversation").value);
  if (note) {
    $("#draft-applied").textContent = note;
    $("#draft-applied").hidden = false;
  }
  const btn = $("#draft-copy");
  btn.textContent = "✓ Copiado";
  setTimeout(() => { btn.textContent = "Copiar"; }, 2000);
}

// Retocar con IA lo que ya está escrito; «Deshacer» recupera la versión anterior.
let draftBeforeRewrite = null;

async function rewriteDraft() {
  const select = $("#draft-rewrite");
  const [action, presetLanguage] = select.value.split(":");
  select.value = "";
  const text = $("#draft-text").value.trim();
  if (!action || !text) return;
  let language = presetLanguage || "";
  if (action === "translate" && !language) {
    language = (prompt("¿A qué idioma lo traduzco?") || "").trim();
    if (!language) return;
  }
  const clientId = state.clientId;
  const conv = (state.clientData?.conversations || []).find((c) => c.id === Number($("#draft-conversation").value));
  select.disabled = true;
  select.options[0].textContent = "✨ Retocando…";
  try {
    const res = await api("/api/drafts/rewrite", {
      method: "POST", body: JSON.stringify({ text, action, language, channel: conv?.channel || null }),
    });
    if (state.clientId !== clientId) return;
    draftBeforeRewrite = $("#draft-text").value;
    $("#draft-text").value = res.text;
    $("#draft-undo").hidden = false;
  } catch (err) {
    alert(err.message);
  } finally {
    select.disabled = false;
    select.options[0].textContent = "✨ Retocar…";
  }
}

function undoRewrite() {
  if (draftBeforeRewrite === null) return;
  $("#draft-text").value = draftBeforeRewrite;
  draftBeforeRewrite = null;
  $("#draft-undo").hidden = true;
}

// Desde la bandeja: abrir el cliente directamente en el borrador de esa conversación.
async function replyFromInbox(clientId, conversationId) {
  await selectClient(clientId);
  showDetailTab("messages");
  openDraftPanel(conversationId);
}

/* ---------- Enviar por la cuenta conectada ---------- */

// Último mensaje de la conversación al empezar a escribir: si llega otro antes de enviar, se avisa.
let draftBaseline = null;

async function updateSendButton() {
  const btn = $("#draft-send");
  btn.hidden = true;
  draftBaseline = null;
  const convId = $("#draft-conversation").value;
  if (!convId) return;
  try {
    const s = await api(`/api/conversations/${convId}/sender`);
    if ($("#draft-conversation").value !== convId) return;
    draftBaseline = s.last_message_id;
    btn.hidden = !s.can_send;
    btn.textContent = `Enviar por ${s.via || ""}`.trim();
  } catch { /* sin envío */ }
}

async function sendDraft() {
  const text = $("#draft-text").value.trim();
  const convId = $("#draft-conversation").value;
  if (!text) return;
  const option = $("#draft-conversation").selectedOptions[0]?.textContent || "";
  if (!confirm(`¿Enviar este mensaje al cliente?\n\n${option}`)) return;
  const btn = $("#draft-send");
  btn.disabled = true;
  try {
    const send = (force) => api(`/api/conversations/${convId}/send`, {
      method: "POST", body: JSON.stringify({ text, after_message_id: draftBaseline, force }),
    });
    try {
      await send(false);
    } catch (err) {
      if (err.status !== 409) throw err;
      if (!confirm(`${err.message}

¿Enviar de todos modos?`)) return;
      await send(true);
    }
    const note = await scheduleFollowUp(convId);
    closeDraftPanel();
    $("#draft-sent-note").textContent = `Enviado.${note ? ` ${note}` : ""}`;
    $("#draft-sent-note").hidden = false;
    await loadTimeline();
    refreshInboxCount();
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
  }
}

// Antes de copiar el borrador: ¿ha llegado algo a la conversación desde que se empezó a escribir?
async function confirmNoNews(conversationId) {
  if (draftBaseline === null) return true;
  try {
    const s = await api(`/api/conversations/${conversationId}/sender`);
    if (s.last_message_id > draftBaseline) {
      if (!confirm("Mientras escribías ha llegado un mensaje nuevo a esta conversación (del cliente o de un compañero).\n\n¿Copiar la respuesta igualmente?")) return false;
      draftBaseline = s.last_message_id;
    }
  } catch { /* sin comprobación */ }
  return true;
}

function bindDraftEvents() {
  $("#draft-open").addEventListener("click", () => openDraftPanel());
  $("#draft-close").addEventListener("click", closeDraftPanel);
  $("#draft-generate").addEventListener("click", generateDraft);
  $("#draft-copy").addEventListener("click", copyDraft);
  $("#draft-rewrite").addEventListener("change", rewriteDraft);
  $("#draft-undo").addEventListener("click", undoRewrite);
  $("#draft-instructions").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); generateDraft(); }
  });
  $("#draft-conversation").addEventListener("change", updateSendButton);
  $("#draft-send").addEventListener("click", sendDraft);
  $("#draft-write").addEventListener("click", () => {
    $("#draft-text").hidden = false;
    $("#draft-result-actions").hidden = false;
    $("#draft-text").focus();
  });
}
