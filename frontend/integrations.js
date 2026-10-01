// Integraciones con los canales (Administración → Integraciones) y envío de respuestas desde el borrador.

const KIND_LABELS = { email: "Email", telegram: "Telegram", whatsapp: "WhatsApp Business" };
const KIND_HELP = {
  email: "Gmail y Outlook exigen una «contraseña de aplicación» (con la verificación en dos pasos activada). "
    + "Gmail: imap.gmail.com / smtp.gmail.com, carpeta de enviados «[Gmail]/Enviados» (o «[Gmail]/Sent Mail» en inglés). "
    + "Outlook: outlook.office365.com / smtp.office365.com, puerto SMTP 587. Los boletines y correos automáticos se descartan.",
  telegram: "Crea un bot hablando con @BotFather en Telegram y pega aquí su token. Entrarán los mensajes que los "
    + "clientes escriban al bot (Telegram no permite a un bot leer tus chats personales) y podrás responderles desde la app.",
  whatsapp: "Necesitas una cuenta de WhatsApp Business Platform (Meta for Developers) y la app publicada con HTTPS. "
    + "Tras guardar, copia la URL del webhook y el verify token en la configuración de Meta y suscríbete a «messages». "
    + "Meta solo permite respuestas libres durante las 24 h siguientes al último mensaje del cliente.",
};

let integrationFields = {};
let editingIntegration = null;

async function loadIntegrations() {
  const { fields, items } = await api("/api/admin/integrations");
  integrationFields = fields;
  const users = JSON.parse($("#users-tbody").dataset.users || "[]").filter((u) => u.active);
  $("#if-owner").innerHTML = users.map((u) => `<option value="${u.id}">${escapeHtml(u.name)}</option>`).join("");
  $("#integrations-list").innerHTML = items.length ? items.map((i) => {
    const status = i.last_error
      ? `<span class="int-status error" title="${escapeHtml(i.last_error)}">⚠ Error: ${escapeHtml(i.last_error.slice(0, 90))}</span>`
      : i.kind === "whatsapp" ? `<span class="int-status">Recibe por webhook</span>`
      : i.last_sync_at ? `<span class="int-status ok">✓ Sincronizado ${timeAgo(i.last_sync_at)}</span>`
      : `<span class="int-status">Pendiente de la primera sincronización</span>`;
    const webhook = i.kind === "whatsapp" ? `
      <div class="webhook-info">
        <span class="muted small">URL del webhook</span><code>${escapeHtml(`${location.origin}/api/webhooks/whatsapp/${i.id}`)}</code>
        <span class="muted small">Verify token</span><code>${escapeHtml(i.config.verify_token)}</code>
      </div>` : "";
    return `
      <li class="integration ${i.enabled ? "" : "disabled"}" data-integration="${i.id}">
        <div class="int-head">
          ${badge(i.kind)} <strong>${escapeHtml(i.name)}</strong>
          <span class="muted small">→ conversaciones de ${escapeHtml(i.owner)}</span>
          <span class="spacer"></span>
          <label class="check"><input type="checkbox" data-toggle-integration ${i.enabled ? "checked" : ""}> Activa</label>
        </div>
        <div class="int-body">${status}${i.kind === "email" ? ` · ${escapeHtml(i.config.address)}` : ""}</div>
        ${webhook}
        <div class="draft-actions">
          ${i.kind !== "whatsapp" ? `<button class="ghost small-btn" data-sync-integration>↻ Sincronizar ahora</button>` : ""}
          <button class="link small" data-edit-integration>Editar</button>
          <button class="link small danger" data-delete-integration>Borrar</button>
        </div>
      </li>`;
  }).join("") : `<li class="muted small">Todavía no hay canales conectados.</li>`;
  $("#integrations-list").dataset.items = JSON.stringify(items);
  if (!editingIntegration) renderIntegrationFields();
}

function renderIntegrationFields(values = {}) {
  const kind = $("#if-kind").value;
  $("#if-help").textContent = KIND_HELP[kind];
  $("#if-fields").innerHTML = (integrationFields[kind] || []).map((f) => `
    <label>${escapeHtml(f.label)}${f.required ? "" : ` <span class="muted">(opcional)</span>`}
      <input name="${f.key}" ${f.secret ? 'type="password" autocomplete="new-password"' : 'autocomplete="off"'}
             placeholder="${escapeHtml(f.placeholder || f.default || (f.secret && editingIntegration ? "Déjalo vacío para no cambiarlo" : ""))}"
             value="${escapeHtml(values[f.key] && !f.secret ? values[f.key] : "")}">
    </label>`).join("");
}

function resetIntegrationForm() {
  editingIntegration = null;
  $("#integration-form").reset();
  $("#if-kind").disabled = false;
  $("#if-title").textContent = "Nueva integración";
  $("#if-submit").textContent = "Conectar";
  $("#if-cancel").hidden = true;
  showError($("#if-error"), "");
  renderIntegrationFields();
}

async function submitIntegration(e) {
  e.preventDefault();
  const config = {};
  $("#if-fields").querySelectorAll("input").forEach((inp) => { config[inp.name] = inp.value.trim(); });
  const body = { name: $("#if-name").value.trim(), owner_user_id: Number($("#if-owner").value), config };
  try {
    if (editingIntegration) {
      await api(`/api/admin/integrations/${editingIntegration}`, { method: "PATCH", body: JSON.stringify(body) });
    } else {
      await api("/api/admin/integrations", { method: "POST", body: JSON.stringify({ ...body, kind: $("#if-kind").value }) });
    }
    resetIntegrationForm();
    await loadIntegrations();
  } catch (err) {
    showError($("#if-error"), err.message);
  }
}

async function onIntegrationsClick(e) {
  const li = e.target.closest("li[data-integration]");
  if (!li) return;
  const id = Number(li.dataset.integration);
  const item = JSON.parse($("#integrations-list").dataset.items).find((i) => i.id === id);
  try {
    if (e.target.matches("[data-toggle-integration]")) {
      await api(`/api/admin/integrations/${id}`, { method: "PATCH", body: JSON.stringify({ enabled: e.target.checked }) });
      await loadIntegrations();
    } else if (e.target.closest("[data-sync-integration]")) {
      const btn = e.target.closest("[data-sync-integration]");
      btn.disabled = true;
      btn.textContent = "↻ Sincronizando…";
      try {
        const r = await api(`/api/admin/integrations/${id}/sync`, { method: "POST" });
        alert(r.imported ? `${r.imported} mensaje${r.imported === 1 ? "" : "s"} nuevo${r.imported === 1 ? "" : "s"}.` : "No hay mensajes nuevos.");
        loadClients($("#client-search").value);
        refreshInboxCount();
      } finally {
        await loadIntegrations();
      }
    } else if (e.target.closest("[data-edit-integration]")) {
      editingIntegration = id;
      $("#if-kind").value = item.kind;
      $("#if-kind").disabled = true;
      $("#if-name").value = item.name;
      $("#if-owner").value = String(item.owner_user_id);
      $("#if-title").textContent = `Editar «${item.name}»`;
      $("#if-submit").textContent = "Guardar cambios";
      $("#if-cancel").hidden = false;
      renderIntegrationFields(item.config);
      $("#if-name").focus();
    } else if (e.target.closest("[data-delete-integration]")) {
      if (!confirm(`¿Borrar la integración «${item.name}»? Las conversaciones ya importadas se conservan.`)) return;
      await api(`/api/admin/integrations/${id}`, { method: "DELETE" });
      if (editingIntegration === id) resetIntegrationForm();
      await loadIntegrations();
    }
  } catch (err) {
    alert(err.message);
    loadIntegrations();
  }
}

/* ---------- Enviar desde el borrador ---------- */

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

function bindIntegrationEvents() {
  $("#if-kind").addEventListener("change", () => renderIntegrationFields());
  $("#integration-form").addEventListener("submit", submitIntegration);
  $("#if-cancel").addEventListener("click", resetIntegrationForm);
  $("#integrations-list").addEventListener("click", onIntegrationsClick);
  $("#draft-conversation").addEventListener("change", updateSendButton);
  $("#draft-send").addEventListener("click", sendDraft);
  $("#draft-write").addEventListener("click", () => {
    $("#draft-text").hidden = false;
    $("#draft-result-actions").hidden = false;
    $("#draft-text").focus();
  });
}
