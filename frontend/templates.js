// Sección Plantillas: las plantillas de mensaje de una cuenta de WhatsApp (lista con estado, vista previa, crear y
// borrar) y la ventana para enviar una plantilla aprobada desde el chat, rellenando sus variables.

const TEMPLATE_STATUS = { APPROVED: "✓ Aprobada", PENDING: "En revisión", REJECTED: "✗ Rechazada", PAUSED: "En pausa", DISABLED: "Desactivada" };
const TEMPLATE_CATEGORY = { UTILITY: "Servicio", MARKETING: "Marketing", AUTHENTICATION: "Autenticación" };
const TEMPLATE_ACCOUNT_KEY = "pc-tpl-account";
const TEMPLATE_VARIABLE = /\{\{(\d+)\}\}/g;
const tplState = { accounts: [], account: null, items: [], selected: null }; // selected: {name, language}
let tplSendItems = [];

/* ---------- Vista previa al estilo WhatsApp ---------- */

function templateVariables(body) {
  return Math.max(0, ...[...(body || "").matchAll(TEMPLATE_VARIABLE)].map((m) => Number(m[1])));
}

// El texto con cada {{n}} sustituido por su valor; las que aún no tienen valor se ven resaltadas.
function templatePreviewHtml(body, values = []) {
  return escapeHtml(body || "").replace(TEMPLATE_VARIABLE, (_, n) => {
    const value = (values[Number(n) - 1] || "").trim();
    return value ? `<strong>${escapeHtml(value)}</strong>` : `<span class="tpl-var">{{${n}}}</span>`;
  });
}

function previewBubble(body, values) {
  return `<div class="tpl-bubble">${templatePreviewHtml(body, values) || `<span class="muted">El texto aparecerá aquí.</span>`}</div>`;
}

/* ---------- Cuentas y lista ---------- */

// Una entrada por cuenta de WhatsApp Business de Meta (WABA): todos sus números comparten las plantillas, que se
// consultan con uno de ellos. Un número sin el identificador de su cuenta va aparte.
async function loadTemplateAccounts() {
  const whatsapp = (items) => items.filter((i) => i.kind === "whatsapp");
  const mine = whatsapp((await api("/api/me/integrations")).items).map((i) => ({ ...i, base: "/api/me/integrations" }));
  let others = [];
  if (currentUser.role === "admin") {
    others = whatsapp((await api("/api/admin/integrations")).items).filter((i) => !mine.some((m) => m.id === i.id))
      .map((i) => ({ ...i, base: "/api/admin/integrations" }));
  }
  const groups = new Map();
  for (const i of [...mine, ...others]) {
    const key = i.waba_id || `numero-${i.id}`;
    if (!groups.has(key)) {
      groups.set(key, { id: i.id, base: i.base, waba: i.waba_id, ids: [], numbers: [], other: i.waba_other,
                        main: i.waba_main, sharedWith: i.waba_shared_with || [] });
    }
    const g = groups.get(key);
    g.ids.push(i.id);
    g.numbers.push(`${i.name} (${i.owner})`);
  }
  tplState.accounts = [...groups.values()].map((g) => {
    // Los números que comparten sus plantillas: los que se ven aquí y los de los compañeros (quien no es administrador
    // solo tiene los suyos).
    const shared = [...new Set([...g.numbers, ...g.sharedWith])];
    const label = g.waba ? `Cuenta ${g.waba} · ${shared.length} ${shared.length === 1 ? "número" : "números"}`
      : `${g.numbers[0]} · sin cuenta de Meta`;
    return { ...g, shared, label };
  });
  $("#tpl-account").innerHTML = tplState.accounts.length
    ? tplState.accounts.map((a) => `<option value="${a.id}">${escapeHtml(a.label)}</option>`).join("")
    : `<option value="">Sin cuentas de WhatsApp</option>`;
}

function chooseTemplateAccount(id) {
  let saved = null;
  try { saved = Number(localStorage.getItem(TEMPLATE_ACCOUNT_KEY)); } catch { /* sin preferencia guardada */ }
  const wanted = id ?? saved;
  tplState.account = tplState.accounts.find((a) => a.ids.includes(wanted)) || tplState.accounts[0] || null;
  if (tplState.account) {
    $("#tpl-account").value = tplState.account.id;
    try { localStorage.setItem(TEMPLATE_ACCOUNT_KEY, tplState.account.id); } catch { /* almacenamiento no disponible */ }
  }
  renderTemplateAccountInfo();
}

// Bajo el selector: qué números comparten estas plantillas, o qué falta para usarlas.
function renderTemplateAccountInfo() {
  const a = tplState.account;
  const info = $("#tpl-account-info");
  info.hidden = !a;
  if (!a) return;
  info.classList.toggle("error-text", !!a.other);
  info.textContent = !a.waba
    ? "Este número no tiene el identificador de su cuenta de WhatsApp Business: añádelo en «Mis cuentas» → «Editar» para usar plantillas."
    : `${a.shared.length > 1 ? "Comparten estas plantillas" : "Usa estas plantillas"}: ${a.shared.join(", ")}.`
      + (a.other ? ` ⚠ Esta cuenta de Meta es distinta de la del resto del equipo (${a.main}): sus plantillas son otras.` : "");
}

// Al entrar en la sección (o desde «Mis cuentas» → «Plantillas» de una cuenta concreta).
async function openTemplatesView(accountId = null) {
  if ($("#view-templates").hidden) showView("templates");
  try {
    await loadTemplateAccounts();
    chooseTemplateAccount(accountId);
    showTemplatePane(null);
    await loadTemplateList();
  } catch (err) {
    $("#tpl-list").innerHTML = `<li class="form-error">${escapeHtml(err.message)}</li>`;
  }
}

// Crear y borrar plantillas es cosa de un administrador (son de la empresa); los demás las ven y las envían.
function canManageTemplates() {
  return currentUser.role === "admin";
}

async function loadTemplateList() {
  const list = $("#tpl-list");
  $("#tpl-new").disabled = !tplState.account || !canManageTemplates();
  $("#tpl-new").hidden = !canManageTemplates();
  $("#tpl-admin-note").hidden = canManageTemplates();
  if (!tplState.account) {
    tplState.items = [];
    list.innerHTML = `<li class="muted small tpl-hint">Conecta una cuenta de WhatsApp Business en «Mis cuentas» para crear y usar plantillas.</li>`;
    return;
  }
  list.innerHTML = `<li class="muted small tpl-hint">Consultando a Meta…</li>`;
  try {
    const { items } = await api(`${tplState.account.base}/${tplState.account.id}/templates`);
    tplState.items = items;
    renderTemplateList();
  } catch (err) {
    tplState.items = [];
    list.innerHTML = `<li class="form-error">${escapeHtml(err.message)}</li>`;
  }
}

function renderTemplateList() {
  const q = $("#tpl-search").value.trim().toLowerCase();
  const items = tplState.items.filter((t) => !q || t.name.toLowerCase().includes(q) || (t.body || "").toLowerCase().includes(q));
  const sel = tplState.selected;
  $("#tpl-list").innerHTML = items.length ? items.map((t) => `
    <li data-name="${escapeHtml(t.name)}" data-language="${escapeHtml(t.language)}"
        class="${sel && sel.name === t.name && sel.language === t.language ? "active" : ""}">
      <div class="tpl-item-top"><strong>${escapeHtml(t.name)}</strong><span class="tpl-status ${escapeHtml((t.status || "").toLowerCase())}"
        title="${escapeHtml(TEMPLATE_STATUS[t.status] || t.status || "")}">${t.status === "APPROVED" ? "✓" : t.status === "REJECTED" ? "✗" : "…"}</span></div>
      <span class="muted small">${escapeHtml(TEMPLATE_CATEGORY[t.category] || t.category || "")} · ${escapeHtml(t.language || "")}</span>
    </li>`).join("")
    : `<li class="muted small tpl-hint">${tplState.items.length ? "Ninguna plantilla coincide." : "Esta cuenta todavía no tiene plantillas: pulsa «Crear»."}</li>`;
}

/* ---------- Plantilla elegida y editor ---------- */

// Qué se ve a la derecha: nada, una plantilla (detalle) o el editor de una nueva («create»).
function showTemplatePane(mode) {
  $("#tpl-empty").hidden = mode !== null;
  $("#tpl-detail").hidden = mode !== "detail";
  $("#tpl-form").hidden = mode !== "create";
  $("#tpl-preview-box").hidden = mode !== "create";
  updateBreadcrumb();
}

// Vuelve a la lista de plantillas sin ninguna abierta (desde la ruta de navegación).
function closeTemplate() {
  tplState.selected = null;
  renderTemplateList();
  showTemplatePane(null);
}

function selectTemplate(name, language) {
  const t = tplState.items.find((x) => x.name === name && x.language === language);
  if (!t) return;
  tplState.selected = { name, language };
  renderTemplateList();
  const rejected = t.status === "REJECTED" && t.rejected_reason && t.rejected_reason !== "NONE";
  $("#tpl-detail").innerHTML = `
    <div class="tpl-detail-head">
      <div>
        <h2>${escapeHtml(t.name)}</h2>
        <span class="muted small">${escapeHtml(TEMPLATE_CATEGORY[t.category] || t.category || "")} · ${escapeHtml(t.language || "")}</span>
      </div>
      <span class="spacer"></span>
      <span class="int-status ${t.status === "APPROVED" ? "ok" : t.status === "REJECTED" ? "error" : ""}">${escapeHtml(TEMPLATE_STATUS[t.status] || t.status || "")}</span>
      ${canManageTemplates() ? `<button type="button" class="link small danger" id="tpl-delete">Borrar</button>` : ""}
    </div>
    ${rejected ? `<p class="form-error">Meta la ha rechazado: ${escapeHtml(t.rejected_reason)}</p>` : ""}
    ${t.status === "PENDING" ? `<p class="muted small">Meta la está revisando. Podrás enviarla desde el chat cuando esté aprobada.</p>` : ""}
    <div class="tpl-preview">${previewBubble(t.body)}</div>
    ${templateVariables(t.body) ? `<p class="muted small">Las partes {{1}}, {{2}}… se rellenan al enviarla desde el chat.</p>` : ""}`;
  showTemplatePane("detail");
}

async function deleteSelectedTemplate() {
  const sel = tplState.selected;
  if (!sel || !(await appConfirm(`¿Borrar la plantilla «${sel.name}» en Meta? Se borra en todos sus idiomas y no se puede deshacer.`, { ok: "Borrar", danger: true }))) return;
  try {
    await api(`${tplState.account.base}/${tplState.account.id}/templates/${encodeURIComponent(sel.name)}`, { method: "DELETE" });
    tplState.selected = null;
    showTemplatePane(null);
    await loadTemplateList();
  } catch (err) {
    alert(err.message);
  }
}

function startNewTemplate() {
  tplState.selected = null;
  renderTemplateList();
  $("#tpl-form").reset();
  showError($("#tpl-error"), "");
  $("#tpl-result").hidden = true;
  renderTemplateExamples();
  showTemplatePane("create");
  $("#tpl-name").focus();
}

// Un campo de ejemplo por cada variable {{n}} del texto (Meta los exige para revisar la plantilla).
function renderTemplateExamples() {
  const box = $("#tpl-examples");
  const previous = [...box.querySelectorAll("input")].map((i) => i.value);
  const count = templateVariables($("#tpl-body").value);
  box.innerHTML = Array.from({ length: count }, (_, n) => `
    <label>Ejemplo de {{${n + 1}}} <input data-example maxlength="200" required value="${escapeHtml(previous[n] || "")}"
      placeholder="${n === 0 ? "Ej. Laura" : n === 1 ? "Ej. 14 de octubre a las 10:00" : ""}"></label>`).join("");
  renderEditorPreview();
}

function renderEditorPreview() {
  const values = [...$("#tpl-examples").querySelectorAll("input")].map((i) => i.value);
  $("#tpl-preview").innerHTML = previewBubble($("#tpl-body").value, values);
}

async function submitTemplate(e) {
  e.preventDefault();
  const btn = $("#tpl-submit");
  btn.disabled = true;
  showError($("#tpl-error"), "");
  try {
    const res = await api(`${tplState.account.base}/${tplState.account.id}/templates`, {
      method: "POST",
      body: JSON.stringify({
        name: $("#tpl-name").value.trim(), category: $("#tpl-category").value, language: $("#tpl-language").value,
        body: $("#tpl-body").value, examples: [...$("#tpl-examples").querySelectorAll("input")].map((i) => i.value),
      }),
    });
    await loadTemplateList();
    const created = tplState.items.find((t) => t.name === res.name);
    if (created) selectTemplate(created.name, created.language);
    else showTemplatePane(null);
  } catch (err) {
    showError($("#tpl-error"), err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---------- Enviar una plantilla desde el chat ---------- */

async function openTemplateSend() {
  const convId = chatState.conversationId;
  if (!convId) return;
  showError($("#tpl-send-error"), "");
  $("#tpl-send-select").innerHTML = `<option value="">Consultando a Meta…</option>`;
  $("#tpl-send-vars").innerHTML = "";
  $("#tpl-send-preview").innerHTML = "";
  $("#tpl-send-dialog").showModal();
  try {
    tplSendItems = (await api(`/api/conversations/${convId}/templates`)).items;
    $("#tpl-send-select").innerHTML = tplSendItems.length
      ? tplSendItems.map((t, i) => `<option value="${i}">${escapeHtml(t.name)} · ${escapeHtml(t.language)}</option>`).join("")
      : `<option value="">No hay plantillas aprobadas: créalas en la sección Plantillas</option>`;
    renderTemplateSendVars();
  } catch (err) {
    $("#tpl-send-select").innerHTML = "";
    showError($("#tpl-send-error"), err.message);
  }
}

function renderTemplateSendVars() {
  const t = tplSendItems[Number($("#tpl-send-select").value)];
  $("#tpl-send-submit").disabled = !t;
  if (!t) { $("#tpl-send-vars").innerHTML = ""; $("#tpl-send-preview").innerHTML = ""; return; }
  const firstName = (chatState.data?.name || "").split(/\s+/)[0];
  $("#tpl-send-vars").innerHTML = Array.from({ length: t.variables }, (_, n) => `
    <label>Valor de {{${n + 1}}} <input data-var maxlength="200" required value="${n === 0 ? escapeHtml(firstName) : ""}"></label>`).join("");
  renderTemplateSendPreview();
}

function renderTemplateSendPreview() {
  const t = tplSendItems[Number($("#tpl-send-select").value)];
  if (!t) return;
  const values = [...$("#tpl-send-vars").querySelectorAll("input")].map((i) => i.value);
  $("#tpl-send-preview").innerHTML = previewBubble(t.body, values);
}

async function submitTemplateSend(e) {
  e.preventDefault();
  const t = tplSendItems[Number($("#tpl-send-select").value)];
  if (!t || !chatState.conversationId) return;
  const btn = $("#tpl-send-submit");
  btn.disabled = true;
  showError($("#tpl-send-error"), "");
  try {
    await api(`/api/conversations/${chatState.conversationId}/send-template`, {
      method: "POST",
      body: JSON.stringify({ name: t.name, language: t.language,
                             params: [...$("#tpl-send-vars").querySelectorAll("input")].map((i) => i.value) }),
    });
    $("#tpl-send-dialog").close();
    await loadChatConversation();
    loadChats();
  } catch (err) {
    showError($("#tpl-send-error"), err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---------- Eventos ---------- */

function bindTemplatesEvents() {
  $("#tpl-account").addEventListener("change", (e) => {
    chooseTemplateAccount(Number(e.target.value));
    tplState.selected = null;
    showTemplatePane(null);
    loadTemplateList();
  });
  $("#tpl-search").addEventListener("input", renderTemplateList);
  $("#tpl-list").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-name]");
    if (li) selectTemplate(li.dataset.name, li.dataset.language);
  });
  $("#tpl-new").addEventListener("click", startNewTemplate);
  $("#tpl-cancel").addEventListener("click", () => showTemplatePane(null));
  $("#tpl-detail").addEventListener("click", (e) => { if (e.target.closest("#tpl-delete")) deleteSelectedTemplate(); });
  $("#tpl-body").addEventListener("input", renderTemplateExamples);
  $("#tpl-examples").addEventListener("input", renderEditorPreview);
  $("#tpl-form").addEventListener("submit", submitTemplate);
  $("#chat-template").addEventListener("click", openTemplateSend);
  $("#tpl-send-select").addEventListener("change", renderTemplateSendVars);
  $("#tpl-send-vars").addEventListener("input", renderTemplateSendPreview);
  $("#tpl-send-form").addEventListener("submit", submitTemplateSend);
}
