// Cuenta del usuario: menú, tema, cambio de contraseña y administración de usuarios.

let currentUser = null;

function initAccount(user) {
  currentUser = user;
  $("#user-name").textContent = user.name;
  $("#user-avatar").textContent = user.name.trim().charAt(0).toUpperCase();
  $("#menu-name").textContent = user.name;
  $("#menu-role").textContent = user.role === "admin" ? "Administrador" : "Usuario";
  document.querySelectorAll("[data-admin-only]").forEach((el) => { el.hidden = user.role !== "admin"; });
  applyTheme(user.theme);
  updateThemeButton();
}

/* ---------- Tema ---------- */

function updateThemeButton() {
  const dark = effectiveTheme() === "dark";
  const btn = $("#theme-toggle");
  btn.classList.toggle("is-dark", dark);
  btn.title = dark ? "Cambiar a tema claro" : "Cambiar a tema oscuro";
}

async function toggleTheme() {
  const next = effectiveTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  updateThemeButton();
  try {
    await api("/api/me", { method: "PATCH", body: JSON.stringify({ theme: next }) });
  } catch { /* si falla, el tema queda aplicado en este navegador */ }
}

/* ---------- Menú de usuario ---------- */

function toggleMenu(open) {
  const menu = $("#user-menu");
  const show = open ?? menu.hidden;
  menu.hidden = !show;
  $("#user-menu-btn").setAttribute("aria-expanded", String(show));
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* se redirige igualmente */ }
  window.location.href = "/login.html";
}

/* ---------- Diálogos ---------- */

function showError(el, message) {
  el.textContent = message;
  el.hidden = !message;
}

function openPasswordDialog() {
  $("#password-form").reset();
  showError($("#pw-error"), "");
  $("#password-dialog").showModal();
}

async function submitPassword(e) {
  e.preventDefault();
  const error = $("#pw-error");
  if ($("#pw-new").value !== $("#pw-repeat").value) {
    showError(error, "Las contraseñas nuevas no coinciden.");
    return;
  }
  try {
    await api("/api/me/password", {
      method: "POST",
      body: JSON.stringify({ current_password: $("#pw-current").value, new_password: $("#pw-new").value }),
    });
    $("#password-dialog").close();
    alert("Contraseña cambiada. Se han cerrado tus sesiones en otros dispositivos.");
  } catch (err) {
    showError(error, err.message);
  }
}

/* ---------- Administración de usuarios ---------- */

let editingUserId = null;

async function openAdminDialog() {
  resetUserForm();
  showAdminTab("users");
  $("#admin-dialog").showModal();
  await loadUsersTable();
}

function showAdminTab(tab) {
  document.querySelectorAll("[data-admin-tab]").forEach((b) => {
    b.classList.toggle("active", b.dataset.adminTab === tab);
    $(`#admin-${b.dataset.adminTab}`).hidden = b.dataset.adminTab !== tab;
  });
  if (tab === "audit") loadAudit();
  if (tab === "settings") loadSettingsForm();
  if (tab === "properties") loadPropertiesAdmin();
}

/* ---------- Ajustes del equipo ---------- */

async function loadSettingsForm() {
  $("#set-error").hidden = true;
  $("#set-saved").hidden = true;
  const s = await api("/api/settings");
  $("#set-sla").value = s.sla_hours;
  $("#set-retention").value = s.retention_months;
  $("#set-inactive").value = s.inactive_days;
  $("#set-auto-analysis").checked = Boolean(s.auto_analysis);
  $("#retention-apply").hidden = !s.retention_months;
  updateRetentionPreview();
}

// Cuántos mensajes se borrarían con el plazo escrito (antes de guardarlo).
async function updateRetentionPreview() {
  const months = Number($("#set-retention").value);
  const out = $("#retention-preview");
  out.textContent = "";
  if (!months) return;
  try {
    const p = await api(`/api/admin/retention?months=${months}`);
    if (Number($("#set-retention").value) === months) {
      out.textContent = p.messages ? `Con ${months} meses se borrarían ${p.messages} mensajes.` : `Con ${months} meses no se borraría ningún mensaje.`;
    }
  } catch { /* valor fuera de rango: lo avisará al guardar */ }
}

async function applyRetention() {
  if (!(await appConfirm("¿Borrar ya los mensajes más antiguos que el plazo guardado? No se puede deshacer.", { ok: "Borrar", danger: true }))) return;
  try {
    const r = await api("/api/admin/retention/apply", { method: "POST" });
    alert(r.messages ? `Borrados ${r.messages} mensajes y ${r.conversations} conversaciones vacías.` : "No había mensajes tan antiguos.");
    updateRetentionPreview();
  } catch (err) {
    alert(err.message);
  }
}

async function submitSettings(e) {
  e.preventDefault();
  $("#set-error").hidden = true;
  try {
    const res = await api("/api/admin/settings", {
      method: "PATCH",
      body: JSON.stringify({
        sla_hours: Number($("#set-sla").value),
        retention_months: Number($("#set-retention").value),
        inactive_days: Number($("#set-inactive").value),
        auto_analysis: $("#set-auto-analysis").checked ? 1 : 0,
      }),
    });
    slaHours = res.sla_hours;
    $("#retention-apply").hidden = !res.retention_months;
    $("#set-saved").hidden = false;
    refreshInboxCount();
  } catch (err) {
    $("#set-error").textContent = err.message;
    $("#set-error").hidden = false;
  }
}

async function loadAudit() {
  const params = new URLSearchParams();
  if ($("#audit-user").value) params.set("user_id", $("#audit-user").value);
  if ($("#audit-action").value) params.set("action", $("#audit-action").value);
  const { actions, entries } = await api(`/api/admin/audit?${params}`);
  if ($("#audit-action").options.length === 1) {
    $("#audit-action").innerHTML += Object.entries(actions)
      .map(([k, label]) => `<option value="${k}">${escapeHtml(label)}</option>`).join("");
    const users = JSON.parse($("#users-tbody").dataset.users || "[]");
    $("#audit-user").innerHTML += users.map((u) => `<option value="${u.id}">${escapeHtml(u.name)}</option>`).join("");
  }
  $("#audit-tbody").innerHTML = entries.length ? entries.map((e) => `
    <tr>
      <td>${new Date(`${e.created_at.replace(" ", "T")}Z`).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" })}</td>
      <td>${escapeHtml(e.user || "—")}</td>
      <td>${escapeHtml(e.action_label)}</td>
      <td>${escapeHtml(e.client_name || "")}</td>
      <td class="audit-detail">${escapeHtml(e.detail || "")}</td>
    </tr>`).join("") : `<tr><td colspan="5" class="muted">Sin registros.</td></tr>`;
}

// Cuentas conectadas de una persona, como fichas («⚠» si alguna no conecta; atenuada si está en pausa).
function userAccountsHtml(accounts) {
  if (!accounts.length) return `<span class="muted small">Ninguna</span>`;
  return accounts.map((a) => {
    const status = a.last_error ? `No conecta: ${a.last_error}` : a.enabled ? "Conectada" : "En pausa";
    return `<span class="acct-chip ${escapeHtml(a.kind)}${a.last_error ? " error" : ""}${a.enabled ? "" : " paused"}"
      title="${escapeHtml(status)}">${a.last_error ? "⚠ " : ""}${escapeHtml(KIND_LABELS[a.kind] || a.kind)} · ${escapeHtml(a.name)}</span>`;
  }).join("");
}

async function loadUsersTable() {
  const [users, accounts] = await Promise.all([
    api("/api/admin/users"),
    api("/api/admin/integrations").then((r) => r.items).catch(() => []),
  ]);
  $("#users-tbody").innerHTML = users.map((u) => `
    <tr class="${u.active ? "" : "inactive"}">
      <td>${escapeHtml(u.username || "—")}</td>
      <td>${escapeHtml(u.name)}</td>
      <td>${escapeHtml(u.email || "")}</td>
      <td>${u.role === "admin" ? "Administrador" : "Usuario"}${u.role !== "admin" && u.can_view_team_chats
        ? `<span class="perm-chip" title="Puede ver en Mis Chats los chats de todo el equipo">Chats del equipo</span>` : ""}</td>
      <td>${u.active ? "Activo" : "Desactivado"}</td>
      <td><div class="user-accounts">${userAccountsHtml(accounts.filter((a) => a.owner_user_id === u.id))}</div></td>
      <td class="row-actions">
        <button class="link" data-edit="${u.id}">Editar</button>
        <button class="link" data-accounts="${u.id}" title="Ver, añadir o quitar sus cuentas conectadas">Cuentas</button>
        ${u.id === currentUser.id ? "" : `<button class="link" data-toggle="${u.id}" data-active="${u.active}">${u.active ? "Desactivar" : "Activar"}</button>`}
      </td>
    </tr>`).join("");
  $("#users-tbody").dataset.users = JSON.stringify(users);
}

function resetUserForm() {
  editingUserId = null;
  $("#user-form").reset();
  delete $("#uf-team-chats").dataset.userValue;
  $("#user-form-title").textContent = "Nuevo usuario";
  $("#uf-submit").textContent = "Crear usuario";
  $("#uf-submit").className = "ghost";
  $("#uf-submit-accounts").hidden = false;
  $("#uf-accounts-hint").hidden = false;
  $("#uf-username").disabled = false;
  $("#uf-password").required = true;
  $("#uf-password-hint").textContent = "(mínimo 8)";
  $("#uf-cancel").hidden = true;
  syncTeamChatsCheck();
  showError($("#uf-error"), "");
}

// Permiso de ver los chats de todo el equipo: los administradores lo tienen siempre (casilla marcada y fija).
function syncTeamChatsCheck() {
  const admin = $("#uf-role").value === "admin";
  const box = $("#uf-team-chats");
  // Al volver a «Usuario», lo que tenía (o desmarcado, si es nuevo).
  box.checked = admin || box.dataset.userValue === "1";
  box.disabled = admin;
  $("#uf-team-chats-hint").textContent = admin ? "(los administradores pueden siempre)"
    : "(en Mis Chats, «Todo el equipo»; queda en el registro de accesos)";
}

function startEditUser(id) {
  const user = JSON.parse($("#users-tbody").dataset.users).find((u) => u.id === id);
  if (!user) return;
  editingUserId = id;
  $("#user-form-title").textContent = `Editar a ${user.name}`;
  $("#uf-submit").textContent = "Guardar cambios";
  $("#uf-submit").className = "primary";
  $("#uf-submit-accounts").hidden = true;
  $("#uf-done").hidden = true;
  $("#uf-username").value = user.username || "";
  $("#uf-username").disabled = true; // el nombre de usuario no se cambia
  $("#uf-name").value = user.name;
  $("#uf-email").value = user.email || "";
  $("#uf-role").value = user.role;
  $("#uf-role").disabled = id === currentUser.id;
  $("#uf-team-chats").dataset.userValue = user.can_view_team_chats ? "1" : "0";
  $("#uf-team-chats").checked = !!user.can_view_team_chats;
  syncTeamChatsCheck();
  $("#uf-password").value = "";
  $("#uf-password").required = false;
  $("#uf-password-hint").textContent = "(déjala vacía para no cambiarla)";
  $("#uf-cancel").hidden = false;
  $("#uf-accounts-hint").hidden = true;
  showError($("#uf-error"), "");
  $("#uf-name").focus();
}

// Dos botones al crear: «Crear usuario» solo lo crea; «Crear y añadir cuentas» abre después sus cuentas.
async function submitUserForm(e) {
  e.preventDefault();
  const withAccounts = e.submitter?.id === "uf-submit-accounts";
  $("#uf-done").hidden = true;
  const body = {
    name: $("#uf-name").value.trim(),
    email: $("#uf-email").value.trim() || null,
    role: $("#uf-role").value,
    can_view_team_chats: $("#uf-role").value === "admin" ? false : $("#uf-team-chats").checked,
  };
  const password = $("#uf-password").value;
  let created = null;
  try {
    if (editingUserId) {
      if (password) body.password = password;
      if (editingUserId === currentUser.id) delete body.role;
      await api(`/api/admin/users/${editingUserId}`, { method: "PATCH", body: JSON.stringify(body) });
    } else {
      created = await api("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({ ...body, username: $("#uf-username").value.trim(), password }),
      });
    }
    $("#uf-role").disabled = false;
    resetUserForm();
    await loadUsersTable();
    if (created && withAccounts) await openAccountsDialog({ id: created.id, name: created.name });
    else if (created) {
      $("#uf-done").textContent = `✓ Usuario «${created.name}» creado.`;
      $("#uf-done").hidden = false;
    }
  } catch (err) {
    showError($("#uf-error"), err.message);
  }
}

async function toggleUserActive(id, active) {
  try {
    await api(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify({ active: !active }) });
    await loadUsersTable();
  } catch (err) {
    showError($("#uf-error"), err.message);
  }
}

/* ---------- Eventos ---------- */

/* ---------- Ventanas (diálogos) ---------- */

// La ventana abierta cuyo fondo oscuro se ha pulsado (fuera de la caja), o null. En una ventana modal, el clic en el
// fondo llega a la propia <dialog>, igual que en su margen interior: se distingue por la posición.
function backdropDialog(e) {
  const dialog = e.target;
  if (dialog?.tagName !== "DIALOG" || !dialog.open) return null;
  const r = dialog.getBoundingClientRect();
  const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  return inside ? null : dialog;
}

// Clic fuera de una ventana la cierra, como Esc. Solo si el clic empezó también fuera: así no se cierra al
// seleccionar texto dentro y soltar el ratón fuera.
function bindDialogBackdrops() {
  let pressed = null;
  document.addEventListener("pointerdown", (e) => { pressed = backdropDialog(e); });
  document.addEventListener("click", (e) => {
    const dialog = backdropDialog(e);
    if (dialog && dialog === pressed) dialog.close();
    pressed = null;
  });
}

function bindAccountEvents() {
  $("#theme-toggle").addEventListener("click", toggleTheme);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", updateThemeButton);

  $("#user-menu-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(); });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".user-menu")) toggleMenu(false);
  });
  $("#user-menu").addEventListener("click", (e) => { if (e.target.closest("button")) toggleMenu(false); });
  $("#menu-tour").hidden = !TOUR_ENABLED;
  $("#menu-tour").addEventListener("click", () => startTour());
  $("#menu-password").addEventListener("click", openPasswordDialog);
  $("#menu-admin").addEventListener("click", openAdminDialog);
  $("#menu-logout").addEventListener("click", logout);

  document.querySelectorAll("[data-admin-tab]").forEach((b) =>
    b.addEventListener("click", () => showAdminTab(b.dataset.adminTab)));
  ["#audit-user", "#audit-action"].forEach((sel) => $(sel).addEventListener("change", loadAudit));
  $("#settings-form").addEventListener("submit", submitSettings);
  $("#set-retention").addEventListener("input", updateRetentionPreview);
  $("#retention-apply").addEventListener("click", applyRetention);
  $("#password-form").addEventListener("submit", submitPassword);
  $("#user-form").addEventListener("submit", submitUserForm);
  $("#uf-cancel").addEventListener("click", () => { $("#uf-role").disabled = false; resetUserForm(); });
  $("#uf-role").addEventListener("change", syncTeamChatsCheck);
  $("#uf-team-chats").addEventListener("change", (e) => { e.target.dataset.userValue = e.target.checked ? "1" : "0"; });
  $("#users-tbody").addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit]");
    const toggle = e.target.closest("[data-toggle]");
    const accounts = e.target.closest("[data-accounts]");
    if (edit) startEditUser(Number(edit.dataset.edit));
    if (accounts) {
      const user = JSON.parse($("#users-tbody").dataset.users).find((u) => u.id === Number(accounts.dataset.accounts));
      if (user) openAccountsDialog({ id: user.id, name: user.name });
    }
    if (toggle) toggleUserActive(Number(toggle.dataset.toggle), toggle.dataset.active === "1");
  });
  document.querySelectorAll("dialog [data-close]").forEach((btn) =>
    btn.addEventListener("click", () => btn.closest("dialog").close()));
  bindDialogBackdrops();
}
