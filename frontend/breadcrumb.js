// Ruta de navegación sobre las tarjetas: «Empresa › Sección › lo que está abierto» (un chat, un contacto, una
// plantilla). La sección se puede pulsar para volver a su lista. El nombre de la empresa lo pone un administrador
// en Administración → Ajustes; mientras no lo haya, un administrador ve el enlace para ponerlo.

let companyName = "";

function setCompanyName(name) {
  companyName = name || "";
  updateBreadcrumb();
}

function currentView() {
  return Object.keys(VIEWS).find((v) => !$(VIEWS[v]).hidden) || null;
}

// [sección, acción al pulsarla (o null), elemento abierto (o null)]
function breadcrumbParts(view) {
  if (view === "chats") {
    return ["Mis Chats", chatState.data ? closeChat : null, chatState.data?.name || null];
  }
  if (view === "contacts") return ["Contactos", null, null];
  if (view === "client") {
    const name = state.clientId === null ? "Consulta general" : state.clientData?.id === state.clientId ? state.clientData.name : null;
    return ["Contactos", () => showView("contacts"), name];
  }
  if (view === "templates") {
    const open = tplState.selected?.name || (!$("#tpl-form").hidden ? "Nueva plantilla" : null);
    return ["Plantillas de WhatsApp", open ? closeTemplate : null, open];
  }
  if (view === "ai") return ["IA que responde", null, null];
  return [null, null, null];
}

function updateBreadcrumb() {
  const nav = $("#breadcrumb");
  const view = currentView();
  const [section, back, open] = breadcrumbParts(view);
  if (!section) {
    nav.hidden = true;
    return;
  }
  nav.hidden = false;
  const crumbs = [];
  if (companyName) crumbs.push(`<span class="crumb company">${escapeHtml(companyName)}</span>`);
  else if (currentUser?.role === "admin") {
    crumbs.push(`<button type="button" class="crumb link-crumb muted" data-crumb="company"
      title="Administración → Ajustes">+ Nombre de la empresa</button>`);
  }
  crumbs.push(back
    ? `<button type="button" class="crumb link-crumb" data-crumb="section">${escapeHtml(section)}</button>`
    : `<span class="crumb${open ? "" : " current"}">${escapeHtml(section)}</span>`);
  if (open) crumbs.push(`<span class="crumb current">${escapeHtml(open)}</span>`);
  nav.innerHTML = crumbs.join(`<span class="crumb-sep" aria-hidden="true">›</span>`);
  nav._back = back;
}

function bindBreadcrumbEvents() {
  $("#breadcrumb").addEventListener("click", (e) => {
    const crumb = e.target.closest("[data-crumb]");
    if (!crumb) return;
    if (crumb.dataset.crumb === "section") $("#breadcrumb")._back?.();
    if (crumb.dataset.crumb === "company") openAdminDialog().then(() => showAdminTab("settings"));
  });
}
