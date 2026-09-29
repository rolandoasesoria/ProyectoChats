// Borradores de respuesta con IA (pestaña Mensajes de la ficha y botón "Responder" de la bandeja).


function fillDraftConversations(conversations, selectedId) {
  $("#draft-conversation").innerHTML = conversations.map((c) => {
    const last = c.last_at ? new Date(c.last_at).toLocaleDateString("es-ES", { day: "numeric", month: "short" }) : "";
    const label = [CHANNEL_LABELS[c.channel] || c.channel, c.subject, c.is_mine ? "tuya" : `de ${c.owner}`, last && `último ${last}`]
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
  $("#draft-instructions").value = "";
  $("#draft-panel").hidden = false;
  $("#draft-open").hidden = true;
  $("#draft-instructions").focus();
}

function closeDraftPanel() {
  $("#draft-panel").hidden = true;
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

async function copyDraft() {
  const text = $("#draft-text").value;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    $("#draft-text").select();
    document.execCommand("copy");
  }
  const btn = $("#draft-copy");
  btn.textContent = "✓ Copiado";
  setTimeout(() => { btn.textContent = "📋 Copiar"; }, 2000);
}

// Desde la bandeja: abrir el cliente directamente en el borrador de esa conversación.
async function replyFromInbox(clientId, conversationId) {
  await selectClient(clientId);
  showDetailTab("messages");
  openDraftPanel(conversationId);
}

function bindDraftEvents() {
  $("#draft-open").addEventListener("click", () => openDraftPanel());
  $("#draft-close").addEventListener("click", closeDraftPanel);
  $("#draft-generate").addEventListener("click", generateDraft);
  $("#draft-copy").addEventListener("click", copyDraft);
  $("#draft-instructions").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); generateDraft(); }
  });
}
