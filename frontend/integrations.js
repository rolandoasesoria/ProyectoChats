// Cuentas conectadas («Mis cuentas»: correo, bot de Telegram, WhatsApp Business) y envío de respuestas desde el
// borrador. Cada persona gestiona las suyas; un administrador puede ver y gestionar las de todo el equipo.

const KIND_LABELS = { email: "Correo", telegram: "Telegram", whatsapp: "WhatsApp Business" };
const KIND_HELP = {
  email: "Escribe tu dirección y una «contraseña de aplicación» (no la contraseña normal): se crea en la seguridad de "
    + "tu cuenta con la verificación en dos pasos activada. Los boletines y correos automáticos se descartan.",
  telegram: "Crea un bot hablando con @BotFather en Telegram (/newbot) y pega aquí su token. Entrarán los mensajes que "
    + "los clientes escriban a ese bot y podrás responderles desde la app. Telegram no deja que un bot lea tus chats personales.",
  whatsapp: "Necesitas un número de WhatsApp Business Platform (Meta for Developers) y que la app sea accesible por HTTPS "
    + "desde internet. Tras conectar, copia la URL del webhook y el verify token en Meta y suscríbete a «messages». "
    + "Meta solo permite respuestas libres durante las 24 h siguientes al último mensaje del cliente.",
};
// Servidores de los proveedores de correo más habituales (se rellenan solos al elegir el proveedor).
const EMAIL_PROVIDERS = {
  gmail: { imap_host: "imap.gmail.com", imap_port: "993", smtp_host: "smtp.gmail.com", smtp_port: "465", sent_folder: "[Gmail]/Enviados",
    help: "Contraseña de aplicación: myaccount.google.com → Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones. Si tu Gmail está en inglés, la carpeta de enviados es «[Gmail]/Sent Mail»." },
  outlook: { imap_host: "outlook.office365.com", imap_port: "993", smtp_host: "smtp.office365.com", smtp_port: "587", sent_folder: "Elementos enviados",
    help: "Ojo: Microsoft está desactivando el acceso con contraseña (IMAP/SMTP básico) en Outlook.com y en muchas empresas con Microsoft 365. Si falla, tu administrador de Microsoft 365 tiene que permitirlo." },
  yahoo: { imap_host: "imap.mail.yahoo.com", imap_port: "993", smtp_host: "smtp.mail.yahoo.com", smtp_port: "465", sent_folder: "Sent",
    help: "Contraseña de aplicación: Información de la cuenta → Seguridad de la cuenta → Generar contraseña de aplicación." },
  icloud: { imap_host: "imap.mail.me.com", imap_port: "993", smtp_host: "smtp.mail.me.com", smtp_port: "587", sent_folder: "Sent Messages",
    help: "Contraseña específica de app: appleid.apple.com → Inicio de sesión y seguridad → Contraseñas específicas de apps." },
  other: { help: "Pide a quien gestione el correo de tu empresa los servidores IMAP y SMTP, sus puertos y el nombre de la carpeta de enviados." },
};

let integrationFields = {};
let editingIntegration = null;
let accountsScope = "mine"; // mine: mis cuentas · team: todas (solo administradores)

function accountsApi(path = "") {
  return accountsScope === "team" ? `/api/admin/integrations${path}` : `/api/me/integrations${path}`;
}

async function openAccountsDialog() {
  $("#user-menu").hidden = true;
  const isAdmin = currentUser.role === "admin";
  $("#accounts-scope").hidden = !isAdmin;
  accountsScope = "mine";
  document.querySelectorAll("#accounts-scope [data-accounts-scope]").forEach((b) =>
    b.classList.toggle("active", b.dataset.accountsScope === "mine"));
  resetIntegrationForm();
  $("#accounts-dialog").showModal();
  try {
    await loadIntegrations();
  } catch (err) {
    alert(err.message);
  }
}

async function loadIntegrations() {
  const { fields, items } = await api(accountsApi());
  integrationFields = fields;
  $("#if-owner-label").hidden = accountsScope !== "team";
  if (accountsScope === "team" && !$("#if-owner").options.length) {
    const people = await api("/api/team");
    $("#if-owner").innerHTML = people.map((u) => `<option value="${u.id}">${escapeHtml(u.name)}</option>`).join("");
  }
  $("#integrations-list").innerHTML = items.length ? items.map((i) => {
    const status = i.last_error
      ? `<span class="int-status error" title="${escapeHtml(i.last_error)}">⚠ No conecta: ${escapeHtml(i.last_error.slice(0, 120))}</span>`
      : i.kind === "whatsapp" ? `<span class="int-status">Recibe por webhook</span>`
      : i.last_sync_at ? `<span class="int-status ok">✓ Conectada · revisada ${timeAgo(i.last_sync_at)}</span>`
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
          ${accountsScope === "team" ? `<span class="muted small">de ${escapeHtml(i.owner)}</span>` : ""}
          <span class="spacer"></span>
          <label class="check"><input type="checkbox" data-toggle-integration ${i.enabled ? "checked" : ""}> Activa</label>
        </div>
        <div class="int-body">${status}${i.kind === "email" ? ` · ${escapeHtml(i.config.address)}` : ""}</div>
        ${webhook}
        <div class="draft-actions">
          ${i.kind !== "whatsapp" ? `<button class="ghost small-btn" data-sync-integration>↻ Revisar ahora</button>` : ""}
          <button class="link small" data-edit-integration>Editar</button>
          <button class="link small danger" data-delete-integration>Desconectar</button>
        </div>
      </li>`;
  }).join("") : `<li class="muted small">${accountsScope === "team" ? "Nadie ha conectado cuentas todavía." : "Todavía no has conectado ninguna cuenta."}</li>`;
  $("#integrations-list").dataset.items = JSON.stringify(items);
  if (!editingIntegration) renderIntegrationFields();
}

// Datos técnicos del correo: se rellenan con el proveedor y quedan plegados salvo en «Otro».
const EMAIL_ADVANCED = ["username", "imap_host", "imap_port", "smtp_host", "smtp_port", "sent_folder", "sync_minutes", "first_sync_days"];

function applyEmailProvider() {
  const preset = EMAIL_PROVIDERS[$("#if-provider").value] || {};
  const advanced = $("#if-advanced");
  if (advanced) advanced.open = $("#if-provider").value === "other";
  Object.entries(preset).forEach(([key, value]) => {
    const input = $(`#if-fields input[name="${key}"]`);
    if (input) input.value = value;
  });
  $("#if-help").textContent = `${KIND_HELP.email} ${preset.help || ""}`;
}

function renderIntegrationFields(values = {}) {
  const kind = $("#if-kind").value;
  $("#if-provider-label").hidden = kind !== "email";
  $("#if-help").textContent = KIND_HELP[kind];
  const field = (f) => `
    <label><span>${escapeHtml(f.label)}${f.required ? "" : ` <span class="muted">(opcional)</span>`}</span>
      <input name="${f.key}" ${f.secret ? 'type="password" autocomplete="new-password"' : 'autocomplete="off"'}
             placeholder="${escapeHtml(f.placeholder || f.default || (f.secret && editingIntegration ? "Déjalo vacío para no cambiarlo" : ""))}"
             value="${escapeHtml(values[f.key] && !f.secret ? values[f.key] : "")}">
    </label>`;
  const all = integrationFields[kind] || [];
  const isAdvanced = (f) => kind === "email" && EMAIL_ADVANCED.includes(f.key);
  const advanced = all.filter(isAdvanced);
  $("#if-fields").innerHTML = all.filter((f) => !isAdvanced(f)).map(field).join("") + (advanced.length ? `
    <details class="if-advanced" id="if-advanced" ${editingIntegration ? "open" : ""}>
      <summary>Ajustes avanzados (servidores, puertos, carpeta de enviados…)</summary>
      <div class="form-grid">${advanced.map(field).join("")}</div>
    </details>` : "");
  if (kind === "email" && !editingIntegration) applyEmailProvider();
}

function resetIntegrationForm() {
  editingIntegration = null;
  $("#integration-form").reset();
  $("#if-kind").disabled = false;
  $("#if-title").textContent = "Conectar una cuenta";
  $("#if-submit").textContent = "Conectar y probar";
  $("#if-cancel").hidden = true;
  $("#if-result").hidden = true;
  showError($("#if-error"), "");
  renderIntegrationFields();
}

function connectionResult(test) {
  if (!test) return "Cambios guardados.";
  if (!test.ok) return `Guardada, pero no conecta (${test.error.replace(/\.$/, "")}). Revisa los datos y pulsa «Editar».`;
  return test.imported ? `✓ Conectada. Han entrado ${test.imported} mensajes.` : "✓ Conectada. De momento no hay mensajes nuevos.";
}

async function submitIntegration(e) {
  e.preventDefault();
  const config = {};
  $("#if-fields").querySelectorAll("input").forEach((inp) => { config[inp.name] = inp.value.trim(); });
  const body = { name: $("#if-name").value.trim(), config };
  if (accountsScope === "team") body.owner_user_id = Number($("#if-owner").value);
  const btn = $("#if-submit");
  btn.disabled = true;
  btn.textContent = "Probando la conexión…";
  try {
    const res = editingIntegration
      ? await api(accountsApi(`/${editingIntegration}`), { method: "PATCH", body: JSON.stringify(body) })
      : await api(accountsApi(), { method: "POST", body: JSON.stringify({ ...body, kind: $("#if-kind").value }) });
    resetIntegrationForm();
    $("#if-result").textContent = connectionResult(res.test);
    $("#if-result").classList.toggle("error-text", res.test ? !res.test.ok : false);
    $("#if-result").hidden = false;
    await loadIntegrations();
    if (res.test?.imported) {
      loadClients($("#client-search").value);
      refreshInboxCount();
    }
  } catch (err) {
    showError($("#if-error"), err.message);
  } finally {
    btn.disabled = false;
    if (!editingIntegration) btn.textContent = "Conectar y probar";
  }
}

async function onIntegrationsClick(e) {
  const li = e.target.closest("li[data-integration]");
  if (!li) return;
  const id = Number(li.dataset.integration);
  const item = JSON.parse($("#integrations-list").dataset.items).find((i) => i.id === id);
  try {
    if (e.target.matches("[data-toggle-integration]")) {
      await api(accountsApi(`/${id}`), { method: "PATCH", body: JSON.stringify({ enabled: e.target.checked }) });
      await loadIntegrations();
    } else if (e.target.closest("[data-sync-integration]")) {
      const btn = e.target.closest("[data-sync-integration]");
      btn.disabled = true;
      btn.textContent = "↻ Revisando…";
      try {
        const r = await api(accountsApi(`/${id}/sync`), { method: "POST" });
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
      $("#if-submit").textContent = "Guardar y probar";
      $("#if-cancel").hidden = false;
      $("#if-result").hidden = true;
      renderIntegrationFields(item.config);
      $("#if-provider-label").hidden = true;
      $("#if-name").focus();
    } else if (e.target.closest("[data-delete-integration]")) {
      if (!confirm(`¿Desconectar «${item.name}»? Dejarán de entrar sus mensajes; las conversaciones que ya entraron se conservan.`)) return;
      await api(accountsApi(`/${id}`), { method: "DELETE" });
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
  $("#menu-accounts").addEventListener("click", openAccountsDialog);
  $("#if-provider").addEventListener("change", applyEmailProvider);
  document.querySelectorAll("#accounts-scope [data-accounts-scope]").forEach((b) => b.addEventListener("click", async () => {
    accountsScope = b.dataset.accountsScope;
    document.querySelectorAll("#accounts-scope [data-accounts-scope]").forEach((x) => x.classList.toggle("active", x === b));
    resetIntegrationForm();
    await loadIntegrations();
  }));
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
