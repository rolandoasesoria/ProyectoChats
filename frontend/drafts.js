// La caja de escribir de la conversación: borrador con IA (con indicaciones opcionales), retocar con IA lo escrito,
// copiarlo para pegarlo fuera (sin cuenta conectada) y «avísame si no contesta». Las respuestas guardadas, en replies.js.

let draftBeforeRewrite = null; // texto antes de retocarlo con IA («Deshacer»)

function composerText() {
  return $("#chat-text");
}

// Pone el texto en la caja de escribir (como si se hubiera escrito: crece y avisa de que se está respondiendo).
function setComposerText(value) {
  const input = composerText();
  input.value = value;
  input.dispatchEvent(new Event("input"));
  input.focus();
}

function showComposerNote(text) {
  $("#draft-applied").textContent = text || "";
  $("#draft-applied").hidden = !text;
}

// Al cambiar de contacto (o tras enviar): fuera notas, menús y el «Deshacer» del texto anterior.
function resetComposerExtras({ keepFollowUp = false } = {}) {
  draftBeforeRewrite = null;
  $("#draft-undo").hidden = true;
  $("#draft-ai-menu").hidden = true;
  $("#reply-picker").hidden = true;
  showComposerNote("");
  if (!keepFollowUp) $("#draft-followup").value = "";
}

/* ---------- Borrador con IA ---------- */

function toggleDraftMenu(open) {
  const menu = $("#draft-ai-menu");
  const show = open ?? menu.hidden;
  menu.hidden = !show;
  if (show) $("#draft-instructions").focus();
}

async function generateDraft() {
  const clientId = state.clientId;
  const convId = chatState.conversationId;
  if (!convId) return;
  const btn = $("#chat-ai-draft");
  toggleDraftMenu(false);
  btn.disabled = true;
  btn.textContent = "✨ Redactando…";
  try {
    const res = await api(`/api/conversations/${convId}/draft`, {
      method: "POST", body: JSON.stringify({ instructions: $("#draft-instructions").value }),
    });
    if (state.clientId !== clientId) return;
    $("#draft-instructions").value = "";
    setComposerText(res.draft);
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = !chatState.conversationId;
    btn.textContent = "✨ Redactar con IA";
  }
}

/* ---------- Retocar lo escrito ---------- */

async function rewriteDraft() {
  const select = $("#draft-rewrite");
  const [action, presetLanguage] = select.value.split(":");
  select.value = "";
  const text = composerText().value.trim();
  if (!action) return;
  if (!text) {
    composerText().focus();
    return;
  }
  let language = presetLanguage || "";
  if (action === "translate" && !language) {
    language = (prompt("¿A qué idioma lo traduzco?") || "").trim();
    if (!language) return;
  }
  const clientId = state.clientId;
  select.disabled = true;
  select.options[0].textContent = "✨ Retocando…";
  try {
    const res = await api("/api/drafts/rewrite", {
      method: "POST", body: JSON.stringify({ text, action, language, channel: replyChannel() }),
    });
    if (state.clientId !== clientId) return;
    draftBeforeRewrite = composerText().value;
    setComposerText(res.text);
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
  setComposerText(draftBeforeRewrite);
  draftBeforeRewrite = null;
  $("#draft-undo").hidden = true;
}

/* ---------- Avisos de seguimiento y copiar ---------- */

// «Avísame si no contesta»: se programa al enviar o copiar la respuesta.
async function scheduleFollowUp(conversationId) {
  const days = Number($("#draft-followup").value);
  if (!days || !conversationId) return "";
  try {
    const f = await api(`/api/conversations/${conversationId}/follow-up`, { method: "POST", body: JSON.stringify({ days }) });
    $("#draft-followup").value = "";
    return `Te avisaré el ${new Date(`${f.due_at}Z`).toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })} si no contesta.`;
  } catch (err) {
    return `No se pudo programar el aviso: ${err.message}`;
  }
}

// Antes de copiar: ¿ha llegado algo a la conversación desde que se abrió?
async function confirmNoNews(conversationId) {
  if (chatState.baseline === null || !conversationId) return true;
  try {
    const s = await api(`/api/conversations/${conversationId}/sender`);
    if (s.last_message_id > chatState.baseline) {
      if (!confirm("Mientras escribías ha llegado un mensaje nuevo a esta conversación (del cliente o de un compañero).\n\n¿Copiar la respuesta igualmente?")) return false;
      chatState.baseline = s.last_message_id;
    }
  } catch { /* sin comprobación */ }
  return true;
}

// Sin cuenta conectada para enviar: se copia para pegarlo en el móvil o en el correo.
async function copyDraft() {
  const text = composerText().value;
  if (!text.trim()) return composerText().focus();
  const convId = chatState.conversationId;
  if (!(await confirmNoNews(convId))) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    composerText().select();
    document.execCommand("copy");
  }
  showComposerNote(await scheduleFollowUp(convId));
  const btn = $("#draft-copy");
  btn.textContent = "✓ Copiado";
  setTimeout(() => { btn.textContent = "Copiar"; }, 2000);
}

/* ---------- Desde la bandeja ---------- */

// «Responder» en Sin responder: abre el contacto en esa conversación, con el cursor en la caja de escribir.
async function replyFromInbox(clientId, conversationId) {
  await selectClient(clientId);
  showDetailTab("conversation");
  const conv = chatState.data?.conversations.find((c) => c.id === conversationId);
  if (conv) {
    if (!conv.is_mine && $("#only-mine").checked) {
      $("#only-mine").checked = false;
      syncScope();
    }
    chatState.channel = conv.channel;
    renderChannelTabs();
    await loadChatConversation();
  }
  composerText().focus();
}

function bindDraftEvents() {
  $("#chat-ai-draft").addEventListener("click", (e) => { e.stopPropagation(); toggleDraftMenu(); });
  $("#draft-ai-menu").addEventListener("click", (e) => e.stopPropagation());
  $("#draft-generate").addEventListener("click", generateDraft);
  $("#draft-instructions").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); generateDraft(); }
    if (e.key === "Escape") { e.stopPropagation(); toggleDraftMenu(false); }
  });
  document.addEventListener("click", () => { if (!$("#draft-ai-menu").hidden) toggleDraftMenu(false); });
  $("#draft-copy").addEventListener("click", copyDraft);
  $("#draft-rewrite").addEventListener("change", rewriteDraft);
  $("#draft-undo").addEventListener("click", undoRewrite);
}
