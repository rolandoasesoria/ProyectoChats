// Cuenta del usuario: menú, tema, cambio de contraseña y administración de usuarios.

let currentUser = null;

function initAccount(user) {
  currentUser = user;
  $("#user-name").textContent = user.name;
  $("#user-avatar").textContent = user.name.trim().charAt(0).toUpperCase();
  $("#menu-name").textContent = user.name;
  $("#menu-role").textContent = user.role === "admin" ? "Administrador" : "Usuario";
  $("#menu-admin").hidden = user.role !== "admin";
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
  if (tab === "integrations") loadIntegrations();
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

async function loadUsersTable() {
  const users = await api("/api/admin/users");
  $("#users-tbody").innerHTML = users.map((u) => `
    <tr class="${u.active ? "" : "inactive"}">
      <td>${escapeHtml(u.username || "—")}</td>
      <td>${escapeHtml(u.name)}</td>
      <td>${escapeHtml(u.email || "")}</td>
      <td>${u.role === "admin" ? "Administrador" : "Usuario"}</td>
      <td>${u.active ? "Activo" : "Desactivado"}</td>
      <td class="row-actions">
        <button class="link" data-edit="${u.id}">Editar</button>
        ${u.id === currentUser.id ? "" : `<button class="link" data-toggle="${u.id}" data-active="${u.active}">${u.active ? "Desactivar" : "Activar"}</button>`}
      </td>
    </tr>`).join("");
  $("#users-tbody").dataset.users = JSON.stringify(users);
}

function resetUserForm() {
  editingUserId = null;
  $("#user-form").reset();
  $("#user-form-title").textContent = "Nueva cuenta";
  $("#uf-submit").textContent = "Crear cuenta";
  $("#uf-username").disabled = false;
  $("#uf-password").required = true;
  $("#uf-password-hint").textContent = "(mínimo 8)";
  $("#uf-cancel").hidden = true;
  showError($("#uf-error"), "");
}

function startEditUser(id) {
  const user = JSON.parse($("#users-tbody").dataset.users).find((u) => u.id === id);
  if (!user) return;
  editingUserId = id;
  $("#user-form-title").textContent = `Editar a ${user.name}`;
  $("#uf-submit").textContent = "Guardar cambios";
  $("#uf-username").value = user.username || "";
  $("#uf-username").disabled = true; // el nombre de usuario no se cambia
  $("#uf-name").value = user.name;
  $("#uf-email").value = user.email || "";
  $("#uf-role").value = user.role;
  $("#uf-role").disabled = id === currentUser.id;
  $("#uf-password").value = "";
  $("#uf-password").required = false;
  $("#uf-password-hint").textContent = "(déjala vacía para no cambiarla)";
  $("#uf-cancel").hidden = false;
  showError($("#uf-error"), "");
  $("#uf-name").focus();
}

async function submitUserForm(e) {
  e.preventDefault();
  const body = {
    name: $("#uf-name").value.trim(),
    email: $("#uf-email").value.trim() || null,
    role: $("#uf-role").value,
  };
  const password = $("#uf-password").value;
  try {
    if (editingUserId) {
      if (password) body.password = password;
      if (editingUserId === currentUser.id) delete body.role;
      await api(`/api/admin/users/${editingUserId}`, { method: "PATCH", body: JSON.stringify(body) });
    } else {
      await api("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({ ...body, username: $("#uf-username").value.trim(), password }),
      });
    }
    $("#uf-role").disabled = false;
    resetUserForm();
    await loadUsersTable();
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

function bindAccountEvents() {
  $("#theme-toggle").addEventListener("click", toggleTheme);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", updateThemeButton);

  $("#user-menu-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(); });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".user-menu")) toggleMenu(false);
  });
  $("#user-menu").addEventListener("click", (e) => { if (e.target.closest("button")) toggleMenu(false); });
  $("#menu-tour").addEventListener("click", () => startTour());
  $("#menu-password").addEventListener("click", openPasswordDialog);
  $("#menu-admin").addEventListener("click", openAdminDialog);
  $("#menu-logout").addEventListener("click", logout);

  document.querySelectorAll("[data-admin-tab]").forEach((b) =>
    b.addEventListener("click", () => showAdminTab(b.dataset.adminTab)));
  ["#audit-user", "#audit-action"].forEach((sel) => $(sel).addEventListener("change", loadAudit));
  $("#password-form").addEventListener("submit", submitPassword);
  $("#user-form").addEventListener("submit", submitUserForm);
  $("#uf-cancel").addEventListener("click", () => { $("#uf-role").disabled = false; resetUserForm(); });
  $("#users-tbody").addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit]");
    const toggle = e.target.closest("[data-toggle]");
    if (edit) startEditUser(Number(edit.dataset.edit));
    if (toggle) toggleUserActive(Number(toggle.dataset.toggle), toggle.dataset.active === "1");
  });
  document.querySelectorAll("dialog [data-close]").forEach((btn) =>
    btn.addEventListener("click", () => btn.closest("dialog").close()));
}
