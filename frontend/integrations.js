// Cuentas conectadas («Mis cuentas»: correo, bot de Telegram, WhatsApp Business) y sus plantillas de WhatsApp.
// Cada persona gestiona las suyas; un administrador puede ver y gestionar las de todo el equipo.

const KIND_LABELS = { email: "Correo", telegram: "Telegram", whatsapp: "WhatsApp Business" };
const KIND_HELP = {
  email: "Escribe tu dirección y una «contraseña de aplicación» (no la contraseña normal): se crea en la seguridad de "
    + "tu cuenta con la verificación en dos pasos activada. Los boletines y correos automáticos se descartan.",
  telegram: "Crea un bot hablando con @BotFather en Telegram (/newbot) y pega aquí su token. Entrarán los mensajes que "
    + "los clientes escriban a ese bot y podrás responderles desde la app. Telegram no deja que un bot lea tus chats personales.",
  whatsapp: "Necesitas un número de WhatsApp Business Platform (Meta for Developers) y que la app sea accesible por HTTPS "
    + "desde internet. Usa un access token permanente (Business Manager → Usuarios del sistema → Generar token, caducidad "
    + "«Nunca»): el temporal de «API Setup» caduca en 24 h. Al conectar, la app comprueba con Meta el token, el número y el "
    + "app secret. Después copia la URL del webhook y el verify token en Meta y suscríbete a «messages». Meta solo permite "
    + "respuestas libres durante las 24 h siguientes al último mensaje del cliente.",
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
let metaSignup = null; // registro insertado de Meta (coexistencia): {ready, app_id, config_id, graph_version, webhook?}
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
  $("#accounts-dialog").showModal();
  try {
    metaSignup = await api("/api/meta/whatsapp-signup").catch(() => null);
    resetIntegrationForm();
    await loadIntegrations();
  } catch (err) {
    alert(err.message);
  }
}

async function loadIntegrations() {
  const { fields, items, webhook_base: webhookBase } = await api(accountsApi());
  integrationFields = fields;
  $("#if-owner-label").hidden = accountsScope !== "team";
  if (accountsScope === "team" && !$("#if-owner").options.length) {
    const people = await api("/api/team");
    $("#if-owner").innerHTML = people.map((u) => `<option value="${u.id}">${escapeHtml(u.name)}</option>`).join("");
  }
  renderMetaWebhookInfo(webhookBase);
  $("#integrations-list").innerHTML = items.length ? items.map((i) => {
    const status = i.last_error
      ? `<span class="int-status error" title="${escapeHtml(i.last_error)}">⚠ No conecta: ${escapeHtml(i.last_error.slice(0, 240))}</span>`
      : i.kind === "whatsapp" ? `<span class="int-status ${i.last_sync_at ? "ok" : ""}">${i.last_sync_at
        ? `✓ Conectada · comprobada ${timeAgo(i.last_sync_at)} · recibe por webhook` : "Recibe por webhook"}</span>`
      : i.last_sync_at ? `<span class="int-status ok">✓ Conectada · revisada ${timeAgo(i.last_sync_at)}</span>`
      : `<span class="int-status">Pendiente de la primera sincronización</span>`;
    const coexistence = i.coexistence
      ? `<div class="muted small">Conectado con la app WhatsApp Business del móvil (coexistencia)${i.history ? ` · historial: ${escapeHtml(i.history)}` : ""}</div>`
      : "";
    const webhook = i.kind === "whatsapp" && !i.coexistence ? `
      <div class="webhook-info">
        <span class="muted small">URL del webhook</span><code>${escapeHtml(`${webhookBase || location.origin}/api/webhooks/whatsapp/${i.id}`)}</code>
        ${webhookBase ? "" : `<span></span><span class="muted small">Esta dirección solo funciona dentro de la oficina: Meta necesita la pública (scripts/webhook-publico.ps1).</span>`}
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
        ${coexistence}${webhook}
        <div class="draft-actions">
          <button class="ghost small-btn" data-sync-integration>${i.kind === "whatsapp" ? "↻ Comprobar ahora" : "↻ Revisar ahora"}</button>
          ${i.kind === "whatsapp" ? `<button class="link small" data-templates-integration>Plantillas</button>` : ""}
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
  if (kind === "whatsapp" && !editingIntegration && metaSignup?.ready) {
    $("#if-help").textContent = COEXISTENCE_HELP;
    $("#if-fields").innerHTML = `
      <div class="coex-box">
        <strong>Conecta el WhatsApp Business de tu móvil</strong>
        <p class="muted small">Sigues usando WhatsApp Business en el móvil y en el ordenador como siempre. Los mensajes que
          recibes y los que envías desde el móvil entran también aquí, con hasta 6 meses de historial si lo autorizas.</p>
        <button type="button" class="primary" id="coex-connect">Conectar con WhatsApp Business</button>
      </div>
      <details class="if-advanced" id="if-manual">
        <summary>Conexión manual (con el token y el app secret de Meta)</summary>
        <div class="form-grid">${all.map(field).join("")}</div>
      </details>`;
    // «Conectar y probar» es solo para la conexión manual: aparece al desplegarla.
    $("#if-submit").hidden = true;
    $("#if-manual").addEventListener("toggle", (e) => { $("#if-submit").hidden = !e.target.open; });
    return;
  }
  $("#if-submit").hidden = false;
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
  if (!test.ok) return `Guardada, pero no conecta: ${test.error.replace(/\.$/, "")}. Revisa los datos y pulsa «Editar».`;
  if (test.detail !== undefined) {
    return `✓ Conectada: Meta acepta las credenciales${test.detail ? ` (${test.detail})` : ""}. `
      + "Copia en Meta la URL del webhook y el verify token que ves en la lista.";
  }
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
    loadNotifications();
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
      btn.textContent = item.kind === "whatsapp" ? "↻ Comprobando…" : "↻ Revisando…";
      try {
        const r = await api(accountsApi(`/${id}/sync`), { method: "POST" });
        if (item.kind === "whatsapp") {
          alert(`✓ Meta acepta las credenciales${r.detail ? ` (${r.detail})` : ""}.`);
        } else {
          alert(r.imported ? `${r.imported} mensaje${r.imported === 1 ? "" : "s"} nuevo${r.imported === 1 ? "" : "s"}.` : "No hay mensajes nuevos.");
          loadClients($("#client-search").value);
          refreshInboxCount();
        }
        loadNotifications();
      } finally {
        await loadIntegrations();
      }
    } else if (e.target.closest("[data-templates-integration]")) {
      openTemplatesDialog(item);
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

/* ---------- Plantillas de mensaje de WhatsApp ---------- */

const TEMPLATE_STATUS = { APPROVED: "✓ Aprobada", PENDING: "En revisión", REJECTED: "✗ Rechazada", PAUSED: "En pausa", DISABLED: "Desactivada" };
const TEMPLATE_CATEGORY = { UTILITY: "Servicio", MARKETING: "Marketing", AUTHENTICATION: "Autenticación" };
let templatesIntegration = null;

async function openTemplatesDialog(item) {
  templatesIntegration = item;
  $("#tpl-title").textContent = `Plantillas de «${item.name}»`;
  $("#tpl-form").reset();
  renderTemplateExamples();
  showError($("#tpl-error"), "");
  $("#tpl-result").hidden = true;
  $("#templates-dialog").showModal();
  await loadTemplates();
}

async function loadTemplates() {
  const list = $("#tpl-list");
  list.innerHTML = `<li class="muted small">Consultando a Meta…</li>`;
  try {
    const { items } = await api(accountsApi(`/${templatesIntegration.id}/templates`));
    list.innerHTML = items.length ? items.map((t) => `
      <li class="integration">
        <div class="int-head">
          <strong>${escapeHtml(t.name)}</strong>
          <span class="muted small">${escapeHtml(TEMPLATE_CATEGORY[t.category] || t.category || "")} · ${escapeHtml(t.language || "")}</span>
          <span class="spacer"></span>
          <span class="int-status ${t.status === "APPROVED" ? "ok" : t.status === "REJECTED" ? "error" : ""}">${escapeHtml(TEMPLATE_STATUS[t.status] || t.status || "")}</span>
        </div>
        <div class="int-body tpl-text">${escapeHtml(t.body || "")}</div>
        ${t.status === "REJECTED" && t.rejected_reason && t.rejected_reason !== "NONE" ? `<div class="muted small">Motivo: ${escapeHtml(t.rejected_reason)}</div>` : ""}
      </li>`).join("") : `<li class="muted small">Esta cuenta todavía no tiene plantillas.</li>`;
  } catch (err) {
    list.innerHTML = `<li class="form-error">${escapeHtml(err.message)}</li>`;
  }
}

// Un campo de ejemplo por cada variable {{n}} del texto (Meta los exige para revisar la plantilla).
function renderTemplateExamples() {
  const box = $("#tpl-examples");
  const previous = [...box.querySelectorAll("input")].map((i) => i.value);
  const count = Math.max(0, ...[...$("#tpl-body").value.matchAll(/\{\{(\d+)\}\}/g)].map((m) => Number(m[1])));
  box.innerHTML = Array.from({ length: count }, (_, n) => `
    <label>Ejemplo de {{${n + 1}}} <input data-example maxlength="200" required value="${escapeHtml(previous[n] || "")}"
      placeholder="${n === 0 ? "Ej. Laura" : n === 1 ? "Ej. 14 de octubre a las 10:00" : ""}"></label>`).join("");
}

async function submitTemplate(e) {
  e.preventDefault();
  const btn = $("#tpl-submit");
  btn.disabled = true;
  showError($("#tpl-error"), "");
  try {
    const res = await api(accountsApi(`/${templatesIntegration.id}/templates`), {
      method: "POST",
      body: JSON.stringify({
        name: $("#tpl-name").value.trim(), category: $("#tpl-category").value, language: $("#tpl-language").value,
        body: $("#tpl-body").value, examples: [...$("#tpl-examples").querySelectorAll("input")].map((i) => i.value),
      }),
    });
    $("#tpl-form").reset();
    renderTemplateExamples();
    $("#tpl-result").textContent = `✓ «${res.name}» enviada a Meta: ${TEMPLATE_STATUS[res.status] || res.status}. El estado se actualiza al volver a abrir esta ventana.`;
    $("#tpl-result").hidden = false;
    await loadTemplates();
  } catch (err) {
    showError($("#tpl-error"), err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---------- Coexistencia: registro insertado de Meta ---------- */

const COEXISTENCE_HELP = "Pulsa el botón, inicia sesión con Facebook, elige tu cuenta de WhatsApp Business y escanea el código "
  + "que te mostrará con la app WhatsApp Business del móvil (Ajustes → Dispositivos vinculados). Hace falta la app WhatsApp "
  + "Business (no la normal) actualizada. Los grupos no se sincronizan y, mientras esté conectada, la app deja de permitir "
  + "mensajes temporales y de «ver una vez».";

// Datos del webhook de la app de Meta (solo administradores): se configuran una vez en Meta para todos los números.
function renderMetaWebhookInfo(webhookBase) {
  const box = $("#meta-webhook-info");
  const hook = metaSignup?.webhook;
  box.hidden = !(metaSignup?.ready && hook);
  if (box.hidden) return;
  const url = hook.url || `${webhookBase || location.origin}/api/webhooks/whatsapp`;
  box.innerHTML = `
    <strong>Webhook de la app de Meta</strong>
    <span class="muted"> · se pone una vez en Meta (WhatsApp → Configuración) y sirve para todos los números conectados;
      suscríbete a messages, smb_message_echoes, history, smb_app_state_sync y account_update.</span>
    <div class="webhook-info">
      <span class="muted small">URL</span><code>${escapeHtml(url)}</code>
      <span class="muted small">Verify token</span><code>${escapeHtml(hook.verify_token || "(falta META_WEBHOOK_VERIFY_TOKEN)")}</code>
    </div>
    ${hook.url ? "" : `<p class="muted small">Esta URL solo funciona dentro de la oficina: abre el túnel (scripts/webhook-publico.ps1) para que Meta pueda llegar.</p>`}`;
}

function loadFacebookSdk() {
  if (window.FB) return Promise.resolve(window.FB);
  return new Promise((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB.init({ appId: metaSignup.app_id, autoLogAppEvents: false, xfbml: false, version: metaSignup.graph_version });
      resolve(window.FB);
    };
    const script = document.createElement("script");
    script.src = "https://connect.facebook.net/es_ES/sdk.js";
    script.async = true;
    script.crossOrigin = "anonymous";
    script.onerror = () => reject(new Error("No se ha podido cargar el inicio de sesión de Facebook. Revisa la conexión a internet."));
    document.head.appendChild(script);
  });
}

async function connectCoexistence() {
  const btn = $("#coex-connect");
  const result = $("#if-result");
  btn.disabled = true;
  btn.textContent = "Abriendo Facebook…";
  showError($("#if-error"), "");
  // Meta avisa por postMessage de la cuenta elegida (o de que se ha cancelado); el código llega por FB.login.
  let session = {};
  const onMessage = (event) => {
    if (!event.origin.endsWith("facebook.com")) return;
    try {
      const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      if (data?.type === "WA_EMBEDDED_SIGNUP") session = data;
    } catch { /* otros mensajes de Facebook */ }
  };
  window.addEventListener("message", onMessage);
  try {
    const FB = await loadFacebookSdk();
    const code = await new Promise((resolve) => FB.login((response) => resolve(response.authResponse?.code || null), {
      config_id: metaSignup.config_id,
      response_type: "code",
      override_default_response_type: true,
      extras: { setup: {}, featureType: "whatsapp_business_app_onboarding", sessionInfoVersion: "3" },
    }));
    for (let i = 0; i < 20 && !session.event; i++) await new Promise((r) => setTimeout(r, 100));
    if (session.event === "ERROR") throw new Error(session.data?.error_message || "Meta ha devuelto un error en el alta.");
    if (!code || session.event === "CANCEL") throw new Error("Has cerrado la ventana de Meta sin terminar la conexión.");
    btn.textContent = "Conectando…";
    const res = await api("/api/me/integrations/whatsapp-coexistence", {
      method: "POST",
      body: JSON.stringify({ code, waba_id: session.data?.waba_id || "", phone_number_id: session.data?.phone_number_id || "",
                             name: $("#if-name").value.trim() }),
    });
    resetIntegrationForm();
    const history = res.sync?.history === "solicitado"
      ? " El historial de los últimos meses irá entrando en unos minutos."
      : " No se ha podido pedir el historial (puedes seguir usándola igual).";
    const number = [res.number?.display_phone_number, res.number?.verified_name].filter(Boolean).join(" · ");
    result.textContent = res.test?.ok
      ? `✓ Conectado tu WhatsApp Business${number ? ` (${number})` : ""}.${history}`
      : `Conectado, pero Meta no acepta las credenciales: ${res.test?.error || ""}`;
    result.classList.toggle("error-text", !res.test?.ok);
    result.hidden = false;
    await loadIntegrations();
    loadNotifications();
  } catch (err) {
    showError($("#if-error"), err.message);
  } finally {
    window.removeEventListener("message", onMessage);
    if (document.body.contains(btn)) {
      btn.disabled = false;
      btn.textContent = "Conectar con WhatsApp Business";
    }
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
  $("#if-fields").addEventListener("click", (e) => { if (e.target.closest("#coex-connect")) connectCoexistence(); });
  $("#tpl-body").addEventListener("input", renderTemplateExamples);
  $("#tpl-form").addEventListener("submit", submitTemplate);
}
