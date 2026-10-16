// Ruta de navegación sobre las tarjetas: «Empresa › Sección › contacto › pestaña» (o la plantilla abierta). La
// empresa abre su menú; los demás niveles, menos el último, llevan a ese punto: la sección vuelve a su lista y el
// contacto, a su conversación. El nombre de la empresa lo pone un administrador en «Datos de la empresa»
// (company.js); mientras no lo haya, un administrador ve el enlace para ponerlo.

// Niveles de la vista de contacto: la sección y, si hay un contacto abierto, su nombre y la pestaña (salvo en la
// conversación, que es la de partida).
function contactCrumbs(section, back) {
  const name = chatState.clientId ? chatState.data?.name : null;
  if (!name) return [{ label: section, action: chatState.origin === "contacts" ? back : null }];
  if (chatState.tab === "conversation") return [{ label: section, action: back }, { label: name }];
  return [{ label: section, action: back }, { label: name, action: () => showDetailTab("conversation") },
          { label: CONTACT_TABS[chatState.tab] }];
}

// Cada nivel: { label, action } (sin action, no se puede pulsar).
function breadcrumbParts(view) {
  if (view === "chats") return contactCrumbs("Mis Chats", closeChat);
  if (view === "client") return contactCrumbs("Contactos", () => showView("contacts"));
  if (view === "templates") {
    const open = tplState.selected?.name || (!$("#tpl-form").hidden ? "Nueva plantilla" : null);
    return open ? [{ label: "Plantillas de WhatsApp", action: closeTemplate }, { label: open }]
      : [{ label: "Plantillas de WhatsApp" }];
  }
  const label = { contacts: "Contactos", tasks: "Tareas", assistant: "Asistente", ai: "Respuestas con IA",
                  dashboard: "Panel de actividad" }[view];
  return label ? [{ label }] : [];
}

function updateBreadcrumb() {
  const nav = $("#breadcrumb");
  const parts = breadcrumbParts(currentView());
  nav.hidden = !parts.length;
  if (!parts.length) return;
  const crumbs = [];
  if (companyName) {
    crumbs.push(`<button type="button" class="crumb link-crumb company" data-crumb="company"
      title="Menú de la empresa">${escapeHtml(companyName)}</button>`);
  } else if (currentUser?.role === "admin") {
    crumbs.push(`<button type="button" class="crumb link-crumb muted" data-crumb="company-setup"
      title="Datos de la empresa">+ Nombre de la empresa</button>`);
  }
  parts.forEach((p, i) => {
    const last = i === parts.length - 1;
    crumbs.push(p.action && (!last || parts.length === 1)
      ? `<button type="button" class="crumb link-crumb" data-crumb="${i === 0 ? "section" : `level-${i}`}" data-i="${i}">${escapeHtml(p.label)}</button>`
      : `<span class="crumb${last ? " current" : ""}">${escapeHtml(p.label)}</span>`);
  });
  nav.innerHTML = crumbs.join(`<span class="crumb-sep" aria-hidden="true">›</span>`);
  nav._actions = parts.map((p) => p.action);
}

function bindBreadcrumbEvents() {
  $("#breadcrumb").addEventListener("click", (e) => {
    const crumb = e.target.closest("[data-crumb]");
    if (!crumb) return;
    if (crumb.dataset.i !== undefined) $("#breadcrumb")._actions[Number(crumb.dataset.i)]?.();
    if (crumb.dataset.crumb === "company-setup") openCompanyDialog();
    if (crumb.dataset.crumb === "company") {
      e.stopPropagation(); // si no, el clic fuera del menú lo cerraría al momento
      toggleCompanyMenu(true);
    }
  });
}
