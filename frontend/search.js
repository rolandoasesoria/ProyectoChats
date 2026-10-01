// Buscador de la pestaña Mensajes: por palabras (índice de texto) o ✨ por significado (IA).

function highlight(snippet) {
  // El servidor marca las coincidencias con ⟦ ⟧; se escapa todo y luego se convierten en <mark>.
  return escapeHtml(snippet).replace(/⟦/g, "<mark>").replace(/⟧/g, "</mark>");
}

function scopeLabel() {
  return state.scope === "team" ? "en todo el historial del cliente" : "solo en tus conversaciones";
}

function renderResults(html) {
  const box = $("#msg-results");
  box.innerHTML = `<div class="msg-results-head"><span class="muted small" id="msg-results-title"></span>
    <button class="icon-link" id="msg-results-close" title="Cerrar resultados">×</button></div>${html}`;
  box.hidden = false;
}

function resultItem(r, { reason = "", text = "" } = {}) {
  if (r.kind === "document") {
    return `<li class="result" data-attachment="${r.attachment_id}">
      <div class="result-meta">📄 ${escapeHtml(r.filename)} · ${formatDate(r.sent_at)}</div>
      ${reason ? `<div class="result-reason">${escapeHtml(reason)}</div>` : ""}
      <div class="result-text">${text}</div></li>`;
  }
  return `<li class="result" data-message="${r.message_id}">
    <div class="result-meta">${badge(r.channel)} ${escapeHtml(r.sender)} · ${formatDate(r.sent_at)}${r.owner && r.owner !== currentUser.name ? ` · <span class="owner-tag">la lleva ${escapeHtml(r.owner)}</span>` : ""}</div>
    ${reason ? `<div class="result-reason">${escapeHtml(reason)}</div>` : ""}
    <div class="result-text">${text}</div></li>`;
}

async function keywordSearch(e) {
  e.preventDefault();
  const q = $("#msg-search").value.trim();
  if (!q) return;
  const params = new URLSearchParams({ q, scope: state.scope, client_id: state.clientId });
  try {
    const results = await api(`/api/search?${params}`);
    renderResults(results.length
      ? `<ul class="results">${results.map((r) => resultItem(r, { text: highlight(r.snippet) })).join("")}</ul>`
      : `<p class="muted small">Nada con esas palabras. Prueba «✨ Por significado» o desmarca «Solo mis conversaciones».</p>`);
    $("#msg-results-title").textContent = `${results.length} resultado${results.length === 1 ? "" : "s"} ${scopeLabel()}`;
  } catch (err) {
    alert(err.message);
  }
}

async function smartSearch() {
  const q = $("#msg-search").value.trim();
  if (q.length < 2) {
    $("#msg-search").focus();
    return;
  }
  const btn = $("#msg-smart-btn");
  btn.disabled = true;
  btn.textContent = "✨ Buscando…";
  const clientId = state.clientId;
  try {
    const res = await api("/api/smart-search", {
      method: "POST", body: JSON.stringify({ question: q, scope: state.scope, client_id: clientId }),
    });
    if (state.clientId !== clientId) return;
    renderResults((res.results.length
      ? `<ul class="results">${res.results.map((r) => resultItem(r, { reason: r.reason, text: escapeHtml(r.text) })).join("")}</ul>`
      : `<p class="muted small">No he encontrado nada que responda a eso ${scopeLabel()}.</p>`) +
      `<p class="muted small keywords">Palabras buscadas: ${res.keywords.map(escapeHtml).join(", ")}</p>`);
    $("#msg-results-title").textContent = `✨ ${res.results.length} resultado${res.results.length === 1 ? "" : "s"} relevantes ${scopeLabel()}`;
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ Por significado";
  }
}

function closeResults() {
  $("#msg-results").hidden = true;
  $("#msg-results").replaceChildren();
}

function bindSearchEvents() {
  $("#msg-search-form").addEventListener("submit", keywordSearch);
  $("#msg-smart-btn").addEventListener("click", smartSearch);
  $("#msg-results").addEventListener("click", (e) => {
    if (e.target.closest("#msg-results-close")) return closeResults();
    const item = e.target.closest(".result");
    if (!item) return;
    if (item.dataset.attachment) window.open(attachmentUrl(item.dataset.attachment), "_blank", "noopener");
    else showSourceMessage(Number(item.dataset.message));
  });
}
