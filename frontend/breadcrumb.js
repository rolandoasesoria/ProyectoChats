// Ruta de navegación sobre las tarjetas: «Empresa › Sección › contacto › pestaña» (o la plantilla abierta). La
// empresa abre su menú; los demás niveles, menos el último, llevan a ese punto: la sección vuelve a su lista y el
// contacto, a su conversación. El nombre de la empresa lo pone un administrador en «Datos de la empresa»
// (company.js); mientras no lo haya, un administrador ve el enlace para ponerlo.

const CRUMB_SEP = `<svg class="crumb-sep" viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 6l6 6-6 6"/></svg>`;

// El icono de la sección es el mismo de la barra lateral.
function sectionIcon(view) {
  const svg = document.querySelector(`.sidebar [data-view="${view === "client" ? "contacts" : view}"] svg`);
  return svg ? svg.outerHTML.replace("<svg", '<svg class="crumb-icon"') : "";
}

// Avatar en miniatura del contacto (las iniciales van como adorno: el texto del nivel es solo su nombre).
function contactCrumbAvatar(name) {
  return `<span class="crumb-avatar chat-avatar ${avatarClass(name)}" data-initials="${escapeHtml(initialsOf(name))}" aria-hidden="true"></span>`;
}

// Niveles de la vista de contacto: la sección y, si hay un contacto abierto, su nombre y la pestaña (salvo en la
// conversación, que es la de partida).
function contactCrumbs(section, back) {
  const icon = sectionIcon(currentView());
  const name = chatState.clientId ? chatState.data?.name : null;
  if (!name) return [{ label: section, icon, action: chatState.origin === "contacts" ? back : null }];
  const contact = { label: name, icon: contactCrumbAvatar(name) };
  if (chatState.tab === "conversation") return [{ label: section, icon, action: back }, contact];
  return [{ label: section, icon, action: back }, { ...contact, action: () => showDetailTab("conversation") },
          { label: CONTACT_TABS[chatState.tab] }];
}

// Cada nivel: { label, action } (sin action, no se puede pulsar).
function breadcrumbParts(view) {
  if (view === "chats") return contactCrumbs("Mis Chats", closeChat);
  if (view === "client") return contactCrumbs("Contactos", () => showView("contacts"));
  if (view === "mail") {
    const parts = [{ label: "Correo", icon: sectionIcon("mail") },
                   { label: MAIL_FOLDERS[mailState.folder], action: mailState.open ? closeMail : null }];
    return mailState.open ? [...parts, { label: mailState.open.subject || "(sin asunto)" }] : parts;
  }
  if (view === "templates") {
    const open = tplState.selected?.name || (!$("#tpl-form").hidden ? "Nueva plantilla" : null);
    const icon = sectionIcon("templates");
    return open ? [{ label: "Plantillas de WhatsApp", icon, action: closeTemplate }, { label: open }]
      : [{ label: "Plantillas de WhatsApp", icon }];
  }
  const label = { contacts: "Contactos", tasks: "Tareas", assistant: "Asistente", ai: "Respuestas con IA",
                  dashboard: "Panel de actividad" }[view];
  return label ? [{ label, icon: sectionIcon(view) }] : [];
}

function updateBreadcrumb() {
  const nav = $("#breadcrumb");
  const parts = breadcrumbParts(currentView());
  nav.hidden = !parts.length;
  if (!parts.length) return;
  const crumbs = [];
  if (companyName) {
    crumbs.push(`<button type="button" class="crumb link-crumb company" data-crumb="company"
      title="Menú de la empresa">${companyCrumbMark()}${escapeHtml(companyName)}</button>`);
  } else if (currentUser?.role === "admin") {
    crumbs.push(`<button type="button" class="crumb link-crumb setup" data-crumb="company-setup"
      title="Datos de la empresa">+ Nombre de la empresa</button>`);
  }
  parts.forEach((p, i) => {
    const last = i === parts.length - 1;
    const inner = `${p.icon || ""}${escapeHtml(p.label)}`;
    crumbs.push(p.action && (!last || parts.length === 1)
      ? `<button type="button" class="crumb link-crumb" data-crumb="${i === 0 ? "section" : `level-${i}`}" data-i="${i}">${inner}</button>`
      : `<span class="crumb${last ? " current" : ""}">${inner}</span>`);
  });
  nav.innerHTML = crumbs.join(CRUMB_SEP);
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
