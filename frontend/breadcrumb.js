// Ruta de navegación sobre las tarjetas: «Empresa › Sección › lo que está abierto» (un chat, un contacto, una
// plantilla). La empresa abre su menú y la sección vuelve a su lista. El nombre de la empresa lo pone un
// administrador en «Datos de la empresa» (company.js); mientras no lo haya, un administrador ve el enlace para ponerlo.

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
  if (view === "ai") return ["Respuestas con IA", null, null];
  if (view === "dashboard") return ["Panel de actividad", null, null];
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
  if (companyName) {
    crumbs.push(`<button type="button" class="crumb link-crumb company" data-crumb="company"
      title="Menú de la empresa">${escapeHtml(companyName)}</button>`);
  } else if (currentUser?.role === "admin") {
    crumbs.push(`<button type="button" class="crumb link-crumb muted" data-crumb="company-setup"
      title="Datos de la empresa">+ Nombre de la empresa</button>`);
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
    if (crumb.dataset.crumb === "company-setup") openCompanyDialog();
    if (crumb.dataset.crumb === "company") {
      e.stopPropagation(); // si no, el clic fuera del menú lo cerraría al momento
      toggleCompanyMenu(true);
    }
  });
}
