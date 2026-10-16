// Sección Contactos: la tabla de contactos (filtros, columnas a elegir, nuevo contacto), las propiedades de contacto
// en la ficha y su gestión en Administración → «Propiedades de contacto».

const CONTACT_COLUMNS_KEY = "pc-contact-columns";
const CONTACT_BASE_COLUMNS = [
  { key: "company", label: "Empresa", value: (c) => escapeHtml(c.company || "") },
  { key: "phone", label: "Teléfono", value: (c) => cellList(c.phones) },
  { key: "email", label: "Email", value: (c) => cellList(c.emails) },
  { key: "channels", label: "Canales", value: (c) => c.channels.map(badge).join(" ") },
  { key: "tags", label: "Etiquetas", value: (c) => cellList(c.tags, (t) => tagChips([t])) },
  { key: "agent", label: "Agente", value: (c) => escapeHtml(team.find((u) => u.id === c.assignee_user_id)?.name || "") },
  { key: "status", label: "Estado", value: (c) => `${statusDot(c.status)} ${escapeHtml(STATUS_LABELS[c.status] || "")}` },
  { key: "activity", label: "Última actividad", value: (c) => c.last_message_at ? escapeHtml(chatTime(c.last_message_at)) : "" },
];
const CONTACT_DEFAULT_COLUMNS = ["phone", "email", "channels", "tags", "agent", "activity"];
const PROPERTY_KINDS = { text: "Texto", number: "Número", date: "Fecha", select: "Lista de opciones" };

let contactProps = null; // propiedades de contacto definidas (caché; se recarga al cambiarlas)
let contactsSearchTimer = null;

async function loadContactProps(force = false) {
  if (!contactProps || force) contactProps = await api("/api/properties");
  return contactProps;
}

/* ---------- Tabla ---------- */

function contactColumns() {
  const props = (contactProps || []).map((p) => ({
    key: `prop:${p.id}`, label: p.label, value: (c) => escapeHtml(propertyText(p, c.properties[p.id])),
  }));
  return [...CONTACT_BASE_COLUMNS, ...props];
}

function visibleColumnKeys() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONTACT_COLUMNS_KEY) || "null");
    if (Array.isArray(saved)) return saved;
  } catch { /* sin preferencia guardada */ }
  return CONTACT_DEFAULT_COLUMNS;
}

function saveColumnKeys(keys) {
  try { localStorage.setItem(CONTACT_COLUMNS_KEY, JSON.stringify(keys)); } catch { /* almacenamiento no disponible */ }
}

function propertyText(prop, value) {
  if (!value) return "";
  return prop.kind === "date" ? new Date(`${value}T00:00:00`).toLocaleDateString("es-ES") : value;
}

function contactsQuery() {
  const params = new URLSearchParams({ q: $("#contacts-search").value });
  for (const [key, sel] of [["status", "#contacts-status"], ["tag", "#contacts-tag"], ["assignee", "#contacts-agent"],
    ["channel", "#contacts-channel"]]) {
    if ($(sel).value) params.set(key, $(sel).value);
  }
  if ($("#contacts-unread").checked) params.set("unread", "true");
  return params;
}

// Etiquetas y agentes de los filtros (se rellenan al entrar, conservando lo elegido).
async function fillContactFilters() {
  const keep = (sel, html) => { const v = $(sel).value; $(sel).innerHTML = html; $(sel).value = v; };
  const tags = await api("/api/tags");
  keep("#contacts-tag", `<option value="">Etiquetas</option>` +
    tags.map((t) => `<option value="${escapeHtml(t.tag)}">${escapeHtml(t.tag)}</option>`).join(""));
  keep("#contacts-agent", `<option value="">Agentes</option>` +
    team.map((u) => `<option value="${u.id}">${escapeHtml(u.name)}</option>`).join(""));
}

async function loadContacts() {
  try {
    await Promise.all([loadContactProps(), fillContactFilters()]);
    const contacts = await api(`/api/contacts?${contactsQuery()}`);
    renderContacts(contacts);
  } catch (err) {
    $("#contacts-body").innerHTML = `<tr><td class="form-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

// Celda con varios valores (emails, teléfonos, etiquetas): una sola línea con el primero y «+N», que despliega
// el resto, para que la fila no crezca. Los textos largos se cortan con «…».
function cellList(values, render = escapeHtml) {
  if (values.length <= 1) return `<span class="cell-text">${values.length ? render(values[0]) : ""}</span>`;
  return `<div class="cell-multi">
      <span class="cell-text">${render(values[0])}</span>
      <details class="cell-more">
        <summary title="Ver los ${values.length}">+${values.length - 1}</summary>
        <ul>${values.map((v) => `<li>${render(v)}</li>`).join("")}</ul>
      </details>
    </div>`;
}

function closeCellLists(except = null) {
  document.querySelectorAll("#contacts-body details.cell-more[open]").forEach((d) => { if (d !== except) d.open = false; });
}

function renderContacts(contacts) {
  const keys = visibleColumnKeys();
  const columns = contactColumns().filter((col) => keys.includes(col.key));
  $("#contacts-count").textContent = `· ${contacts.length}`;
  $("#contacts-head").innerHTML = `<tr><th>Nombre</th>${columns.map((col) => `<th>${escapeHtml(col.label)}</th>`).join("")}</tr>`;
  $("#contacts-body").innerHTML = contacts.length ? contacts.map((c) => `
    <tr data-client="${c.id}" tabindex="0">
      <td class="contact-name">
        <span class="chat-avatar small">${escapeHtml(initialsOf(c.name))}</span>
        <span>${escapeHtml(c.name)}</span>
        ${c.unread ? `<span class="unread" title="Mensajes sin leer">${c.unread > 99 ? "99+" : c.unread}</span>` : ""}
      </td>
      ${columns.map((col) => `<td>${col.value(c)}</td>`).join("")}
    </tr>`).join("")
    : `<tr><td colspan="${columns.length + 1}" class="muted contacts-empty">Ningún contacto coincide con los filtros.</td></tr>`;
}

function renderColumnsMenu() {
  const keys = visibleColumnKeys();
  $("#contacts-columns").innerHTML = `<div class="menu-head"><strong>Columnas</strong></div>` + contactColumns().map((col) => `
    <label class="check"><input type="checkbox" data-column="${escapeHtml(col.key)}" ${keys.includes(col.key) ? "checked" : ""}>
      ${escapeHtml(col.label)}</label>`).join("");
}

function toggleColumnsMenu(open) {
  const menu = $("#contacts-columns");
  const show = open ?? menu.hidden;
  if (show) renderColumnsMenu();
  menu.hidden = !show;
  $("#contacts-columns-btn").setAttribute("aria-expanded", String(show));
}

/* ---------- Propiedades en la ficha ---------- */

function propertyInput(prop, value) {
  const attrs = `data-prop="${prop.id}" aria-label="${escapeHtml(prop.label)}"`;
  if (prop.kind === "select") {
    return `<select ${attrs}><option value="">—</option>${prop.options.map((o) =>
      `<option ${o === value ? "selected" : ""}>${escapeHtml(o)}</option>`).join("")}</select>`;
  }
  const type = { number: "number", date: "date" }[prop.kind] || "text";
  return `<input ${attrs} type="${type}" ${type === "number" ? 'step="any"' : 'maxlength="500"'} value="${escapeHtml(value || "")}" placeholder="Sin valor">`;
}

async function loadClientProperties(clientId) {
  const box = $("#client-props");
  const [props, { values }] = await Promise.all([loadContactProps(), api(`/api/clients/${clientId}/properties`)]);
  if (state.clientId !== clientId) return;
  box.dataset.client = clientId;
  box.innerHTML = props.length ? props.map((p) => `
    <label class="prop-field"><span class="muted small">${escapeHtml(p.label)}</span>${propertyInput(p, values[p.id])}</label>`).join("")
    : `<p class="muted small">${currentUser.role === "admin"
      ? "Aún no hay propiedades. Créalas en Administración → «Propiedades de contacto»."
      : "Aún no hay propiedades: las crea un administrador."}</p>`;
}

async function saveClientProperty(e) {
  const field = e.target.closest("[data-prop]");
  if (!field) return;
  const clientId = Number($("#client-props").dataset.client);
  field.classList.remove("saved", "invalid");
  try {
    const { values } = await api(`/api/clients/${clientId}/properties`, {
      method: "PUT", body: JSON.stringify({ values: { [field.dataset.prop]: field.value } }),
    });
    if (field.tagName === "INPUT" && field.type !== "date") field.value = values[field.dataset.prop] || "";
    field.classList.add("saved");
    setTimeout(() => field.classList.remove("saved"), 1200);
  } catch (err) {
    field.classList.add("invalid");
    alert(err.message);
  }
}

/* ---------- Administración: propiedades de contacto ---------- */

async function loadPropertiesAdmin() {
  const props = await loadContactProps(true);
  $("#props-admin-list").innerHTML = props.length ? props.map((p, i) => `
    <li data-prop-id="${p.id}">
      <div><strong>${escapeHtml(p.label)}</strong> <span class="muted small">· ${escapeHtml(PROPERTY_KINDS[p.kind])}${p.options.length
        ? `: ${escapeHtml(p.options.join(", "))}` : ""}</span></div>
      <span class="spacer"></span>
      <button class="icon-btn" data-prop-move="-1" title="Subir" ${i === 0 ? "disabled" : ""}>↑</button>
      <button class="icon-btn" data-prop-move="1" title="Bajar" ${i === props.length - 1 ? "disabled" : ""}>↓</button>
      <button class="link small" data-prop-edit>Editar</button>
      <button class="link small danger" data-prop-delete>Borrar</button>
    </li>`).join("") : `<li class="muted small">Todavía no hay propiedades.</li>`;
}

async function onPropertiesAdminClick(e) {
  const li = e.target.closest("li[data-prop-id]");
  if (!li) return;
  const id = Number(li.dataset.propId);
  const prop = contactProps.find((p) => p.id === id);
  try {
    if (e.target.closest("[data-prop-move]")) {
      const ids = contactProps.map((p) => p.id);
      const from = ids.indexOf(id);
      const to = from + Number(e.target.closest("[data-prop-move]").dataset.propMove);
      [ids[from], ids[to]] = [ids[to], ids[from]];
      await api("/api/admin/properties/order", { method: "PUT", body: JSON.stringify({ ids }) });
    } else if (e.target.closest("[data-prop-edit]")) {
      const label = prompt("Nombre de la propiedad:", prop.label);
      if (label === null) return;
      let options = prop.options;
      if (prop.kind === "select") {
        const text = prompt("Opciones, separadas por comas:", prop.options.join(", "));
        if (text === null) return;
        options = text.split(",");
      }
      await api(`/api/admin/properties/${id}`, { method: "PATCH", body: JSON.stringify({ label, options }) });
    } else if (e.target.closest("[data-prop-delete]")) {
      if (!confirm(`¿Borrar la propiedad «${prop.label}»? Se borrará su valor en todos los contactos.`)) return;
      await api(`/api/admin/properties/${id}`, { method: "DELETE" });
    } else {
      return;
    }
    await loadPropertiesAdmin();
  } catch (err) {
    alert(err.message);
  }
}

async function submitProperty(e) {
  e.preventDefault();
  showError($("#prop-error"), "");
  const kind = $("#prop-kind").value;
  try {
    await api("/api/admin/properties", {
      method: "POST",
      body: JSON.stringify({ label: $("#prop-label").value.trim(), kind,
                             options: kind === "select" ? $("#prop-options").value.split(",") : [] }),
    });
    $("#prop-form").reset();
    $("#prop-options").hidden = true;
    await loadPropertiesAdmin();
  } catch (err) {
    showError($("#prop-error"), err.message);
  }
}

/* ---------- Eventos ---------- */

function bindContactsEvents() {
  $("#contacts-search").addEventListener("input", () => {
    clearTimeout(contactsSearchTimer);
    contactsSearchTimer = setTimeout(loadContacts, 200);
  });
  ["#contacts-status", "#contacts-tag", "#contacts-agent", "#contacts-channel", "#contacts-unread"].forEach((sel) =>
    $(sel).addEventListener("change", loadContacts));
  $("#contacts-body").addEventListener("click", (e) => {
    // El desplegable «+N» de una celda no abre la ficha (y solo queda abierto uno)
    const more = e.target.closest("details.cell-more");
    if (more) return closeCellLists(more);
    closeCellLists();
    const row = e.target.closest("tr[data-client]");
    if (row) selectClient(Number(row.dataset.client)).catch((err) => alert(err.message));
  });
  $("#contacts-body").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("tr[data-client]")) e.target.click();
  });
  $("#contacts-columns-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleColumnsMenu(); });
  $("#contacts-columns").addEventListener("click", (e) => e.stopPropagation());
  $("#contacts-columns").addEventListener("change", (e) => {
    const keys = [...$("#contacts-columns").querySelectorAll("input:checked")].map((i) => i.dataset.column);
    saveColumnKeys(keys);
    loadContacts();
  });
  document.addEventListener("click", (e) => {
    if (!$("#contacts-columns").hidden) toggleColumnsMenu(false);
    if (!e.target.closest("#contacts-body")) closeCellLists();
  });
  $("#contacts-new").addEventListener("click", () => openClientDialog("create"));
  $("#client-props").addEventListener("change", saveClientProperty);
  $("#props-admin-list").addEventListener("click", onPropertiesAdminClick);
  $("#prop-form").addEventListener("submit", submitProperty);
  $("#prop-kind").addEventListener("change", (e) => { $("#prop-options").hidden = e.target.value !== "select"; });
}
