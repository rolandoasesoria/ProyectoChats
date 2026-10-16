// La empresa: su marca (logo o iniciales) arriba de la barra lateral, que abre el menú de la empresa —sus datos,
// usuarios, cuentas conectadas, ajustes, propiedades de contacto y registro de accesos—, y el diálogo «Datos de la
// empresa» (nombre y logo; solo administradores). El nombre encabeza también la ruta de navegación.

let companyName = "";
let companyLogo = ""; // huella del logo guardado («» si no hay); cambia la URL de la imagen al cambiar el logo
const COMPANY_LOGO_MAX = 256 * 1024;
const COMPANY_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 21V5l8-2v18M12 8l8 2v11M3 21h18"/>
  <path d="M8 8v.01M8 12v.01M8 16v.01M16 13v.01M16 17v.01"/></svg>`;

function setCompany(s) {
  companyName = s.company_name || "";
  companyLogo = s.company_logo || "";
  renderCompanyMarks();
  $("#company-menu-name").textContent = companyName || "Tu empresa";
  $("#company-btn").title = companyName ? `${companyName}: menú de la empresa` : "Menú de la empresa";
  $("#company-btn").setAttribute("aria-label", $("#company-btn").title);
  updateBreadcrumb();
}

// Logo (si hay), iniciales del nombre o, sin ninguno de los dos, un edificio.
function renderCompanyMarks() {
  document.querySelectorAll(".company-mark").forEach((el) => {
    el.classList.toggle("has-logo", Boolean(companyLogo));
    el.innerHTML = companyLogo
      ? `<img src="/api/company/logo?v=${encodeURIComponent(companyLogo)}" alt="">`
      : companyName ? escapeHtml(initialsOf(companyName)) : COMPANY_ICON;
  });
}

/* ---------- Menú de la empresa ---------- */

function toggleCompanyMenu(open) {
  const menu = $("#company-menu");
  const show = open ?? menu.hidden;
  menu.hidden = !show;
  $("#company-btn").setAttribute("aria-expanded", String(show));
  if (show) {
    const people = team.filter((u) => u.active !== false).length;
    $("#company-menu-meta").textContent = people ? `${people} ${people === 1 ? "usuario" : "usuarios"}` : "";
  }
}

async function openAdminTab(tab) {
  await openAdminDialog();
  showAdminTab(tab);
}

/* ---------- Datos de la empresa ---------- */

function openCompanyDialog() {
  $("#company-name").value = companyName;
  showError($("#company-error"), "");
  $("#company-saved").hidden = true;
  $("#company-logo-remove").hidden = !companyLogo;
  $("#company-dialog").showModal();
  $("#company-name").focus();
}

async function submitCompany(e) {
  e.preventDefault();
  showError($("#company-error"), "");
  try {
    const res = await api("/api/admin/settings", {
      method: "PATCH", body: JSON.stringify({ company_name: $("#company-name").value }),
    });
    setCompany(res);
    $("#company-name").value = companyName;
    $("#company-saved").hidden = false;
  } catch (err) {
    showError($("#company-error"), err.message);
  }
}

async function uploadCompanyLogo(file) {
  showError($("#company-error"), "");
  if (!file) return;
  if (file.size > COMPANY_LOGO_MAX) return showError($("#company-error"), "El logo supera el máximo de 256 KB.");
  try {
    const res = await api("/api/admin/company/logo", { method: "PUT", body: JSON.stringify({ data: await fileToBase64(file) }) });
    setCompany({ company_name: companyName, company_logo: res.company_logo });
    $("#company-logo-remove").hidden = false;
  } catch (err) {
    showError($("#company-error"), err.message);
  } finally {
    $("#company-logo-file").value = "";
  }
}

async function removeCompanyLogo() {
  if (!confirm("¿Quitar el logo de la empresa? En su lugar saldrán las iniciales.")) return;
  try {
    await api("/api/admin/company/logo", { method: "DELETE" });
    setCompany({ company_name: companyName, company_logo: "" });
    $("#company-logo-remove").hidden = true;
  } catch (err) {
    showError($("#company-error"), err.message);
  }
}

function bindCompanyEvents() {
  $("#company-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleCompanyMenu(); });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".company-menu-wrap")) toggleCompanyMenu(false);
  });
  $("#company-menu").addEventListener("click", (e) => { if (e.target.closest("button")) toggleCompanyMenu(false); });
  $("#menu-company-data").addEventListener("click", openCompanyDialog);
  $("#menu-settings").addEventListener("click", () => openAdminTab("settings"));
  $("#menu-properties").addEventListener("click", () => openAdminTab("properties"));
  $("#menu-audit").addEventListener("click", () => openAdminTab("audit"));
  $("#company-form").addEventListener("submit", submitCompany);
  $("#company-logo-file").addEventListener("change", (e) => uploadCompanyLogo(e.target.files[0]));
  $("#company-logo-remove").addEventListener("click", removeCompanyLogo);
}
