// Tutorial de bienvenida: recorre los apartados de la app la primera vez que se entra.
//
// ⚠️ MANTENER AL DÍA: cada vez que se añada, quite o cambie un apartado de la interfaz:
//   1. Actualiza TOUR_STEPS (un paso por apartado, en el orden en que se recorre la pantalla).
//   2. Sube TOUR_VERSION: así quienes ya vieron el tutorial lo verán de nuevo con los cambios.
//   3. Actualiza también HELP_SYSTEM_PROMPT (la mascota Chispa) en backend/app/agent.py.
//
// Cada paso: { target: selector CSS o null (tarjeta centrada), title, text, when?: () => boolean,
//              view?: sección de la barra lateral que se abre para enseñarlo ("chats" o "clients") }.
// Los pasos cuyo elemento no esté visible (p. ej. en pantallas pequeñas) se saltan solos.

const TOUR_VERSION = 27;

const TOUR_STEPS = [
  {
    target: null,
    title: "Bienvenido a Hilvana Chat",
    text: "Todas las conversaciones con tus clientes —email, WhatsApp, Telegram— en un solo sitio, y una IA que encuentra los datos por ti. A la izquierda, la barra con las secciones: Chats, para conversar, y Clientes, con la ficha y el asistente. Un recorrido de un minuto.",
  },
  {
    target: ".chats-pane",
    view: "chats",
    title: "Chats",
    text: "Tus conversaciones, la más reciente arriba, con el último mensaje y los no leídos. «No leídos» deja solo las que tienen mensajes nuevos. Busca por nombre, empresa o teléfono.",
  },
  {
    target: ".chat-main",
    view: "chats",
    title: "La conversación",
    text: "Al elegir un chat, sus mensajes salen separados por canal (WhatsApp, Email, Telegram) en pestañas. Escribe abajo y pulsa Intro para enviar por tu cuenta conectada, o «✨ Redactar con IA» para que te proponga la respuesta. A la derecha, los detalles del contacto; «Abrir ficha» te lleva a todo lo demás.",
  },
  {
    target: "#nav-clients",
    title: "Clientes",
    text: "La ficha completa de cada cliente: datos, tareas, notas, todo el historial y el asistente que encuentra cualquier dato. Te lo enseño.",
  },
  {
    target: ".clients",
    view: "clients",
    title: "Lista de clientes",
    text: "Busca por nombre, empresa, email o teléfono, y filtra por estado, etiqueta o responsable. El número azul indica mensajes nuevos. «Consulta general» pregunta sobre todos los clientes a la vez.",
  },
  {
    target: ".detail",
    view: "clients",
    title: "Ficha del cliente",
    text: "«Ficha»: resumen (con la prioridad que detecta la IA), datos clave y documentos. «Tareas» pendientes. «Notas» internas (con @ avisas a un compañero). «Mensajes»: todo el historial, con buscador y «Redactar respuesta» (con IA o con respuestas guardadas: escribe /), que la IA puede retocar. El estado (Potencial, Activo, Incidencia, Inactivo) lo decide la IA ✨; púlsalo para cambiarlo a mano. Con ✎ editas responsable y etiquetas. Si un compañero está respondiendo al mismo cliente, te lo avisaré aquí.",
  },
  {
    target: ".chat",
    view: "clients",
    title: "Asistente",
    text: "Pregunta cualquier dato: «¿qué CIF nos dio?». Cada cliente tiene su propia conversación. Busca en las tuyas; si quieres que mire las de tus compañeros, pídeselo.",
  },
  {
    target: "#side-inbox-tab",
    view: "clients",
    title: "Sin responder",
    text: "Quién espera respuesta, de más a menos tiempo; avisa cuando está a punto de vencer el plazo. Elige «Mías» o «Todo el equipo»; «Atendido» quita lo que no necesita respuesta y «Posponer» la aparta hasta más tarde. Arriba verás también a quien no te ha contestado, si lo pediste al responder.",
  },
  {
    target: "#side-tasks-tab",
    view: "clients",
    title: "Tareas",
    text: "Tus tareas de todos los clientes. El número se pone en rojo si alguna vence hoy o ya ha vencido.",
  },
  {
    target: "#palette-btn",
    title: "Buscar o ir a… (Ctrl+K)",
    text: "Abre cualquier cliente o acción escribiendo. Con ? ves los atajos de teclado: j/k para cambiar de cliente, r para responder…",
  },
  {
    target: ".sidebar",
    title: "Barra lateral",
    text: "Tus secciones: Inicio (el panel de actividad) y Chats, la vista en la que estás. Abajo: Mis cuentas, Respuestas guardadas y, si eres administrador, Administración. Pasa el ratón por cada icono para ver su nombre.",
  },
  {
    target: "#dashboard-btn",
    title: "Inicio: el panel",
    text: "Mensajes, tiempo de respuesta y cuántas se responden en plazo, tareas y clientes por estado en el periodo que elijas.",
  },
  {
    target: "#bell",
    title: "Avisos",
    text: "Te avisa cuando te mencionan en una nota, te asignan una tarea o una de tus cuentas conectadas deja de funcionar (por ejemplo, un token caducado).",
  },
  {
    target: "#menu-accounts",
    title: "Mis cuentas",
    text: "Conecta tu correo, tu bot de Telegram o el WhatsApp Business de tu móvil (sigue funcionando en el móvil) para que tus mensajes entren solos, y crea las plantillas de WhatsApp. Debajo, tus respuestas guardadas.",
  },
  {
    target: "#user-menu-btn",
    title: "Tu cuenta",
    text: "Tu contraseña, este tutorial y cerrar sesión. El botón de al lado cambia el tema.",
  },
  {
    target: "#menu-admin",
    title: "Administración",
    text: "Aquí gestionas los usuarios y consultas el «Registro de accesos»; en «Mis cuentas» ves también las de todo el equipo. En «Ajustes» fijas el plazo de respuesta y si la IA analiza sola a los clientes. Desde ✎ en cada cliente puedes exportar o borrar sus datos y ocultar IBAN o DNI de sus mensajes.",
    when: () => currentUser?.role === "admin",
  },
  {
    target: "#mascot",
    title: "¿Dudas? Pregunta a Chispa",
    text: "Chispa te explica cómo funciona la app. Ya puedes empezar: elige un cliente y pregúntale al asistente.",
  },
];

/* ---------- Motor del tutorial ---------- */

let tour = null; // { steps, index, els }

function isVisible(el) {
  return el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
}

function startTour() {
  // Los pasos de otra sección cuentan aunque ahora no se vean: al llegar a ellos se abre su sección.
  const steps = TOUR_STEPS.filter((s) =>
    (!s.when || s.when()) && (!s.target || s.view || isVisible(document.querySelector(s.target))));
  if (!steps.length) return;
  endTour(false);
  const backdrop = document.createElement("div");
  backdrop.className = "tour-backdrop";
  const spot = document.createElement("div");
  spot.className = "tour-spot";
  const card = document.createElement("div");
  card.className = "tour-card";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-live", "polite");
  document.body.append(backdrop, spot, card);
  tour = { steps, index: 0, els: { backdrop, spot, card } };
  card.addEventListener("click", onTourClick);
  window.addEventListener("resize", positionTour);
  document.addEventListener("keydown", onTourKey);
  renderTourStep();
}

function renderTourStep() {
  const { steps, index, els } = tour;
  const step = steps[index];
  const last = index === steps.length - 1;
  if (step.view) showView(step.view);
  els.card.innerHTML = `
    <div class="tour-progress">${index + 1} / ${steps.length}</div>
    <h3>${escapeHtml(step.title)}</h3>
    <p>${escapeHtml(step.text)}</p>
    <div class="tour-actions">
      ${last ? "" : `<button class="link" data-tour="skip">Saltar</button>`}
      <span class="spacer"></span>
      ${index > 0 ? `<button class="ghost" data-tour="prev">Anterior</button>` : ""}
      <button class="primary" data-tour="next">${last ? "Empezar" : "Siguiente"}</button>
    </div>`;
  positionTour();
  els.card.querySelector('[data-tour="next"]').focus();
}

function positionTour() {
  if (!tour) return;
  const { steps, index, els } = tour;
  const step = steps[index];
  const target = step.target && document.querySelector(step.target);
  const margin = 12;
  const pad = 6;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  if (!target) {
    Object.assign(els.spot.style, { top: `${vh / 2}px`, left: `${vw / 2}px`, width: "0px", height: "0px" });
    const c = els.card.getBoundingClientRect();
    Object.assign(els.card.style, { top: `${(vh - c.height) / 2}px`, left: `${(vw - c.width) / 2}px` });
    return;
  }

  target.scrollIntoView({ block: "nearest" });
  const r = target.getBoundingClientRect();
  Object.assign(els.spot.style, {
    top: `${r.top - pad}px`, left: `${r.left - pad}px`,
    width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px`,
  });

  // Coloca la tarjeta donde haya sitio: debajo, encima, a la derecha o a la izquierda del elemento.
  const c = els.card.getBoundingClientRect();
  let top;
  let left;
  if (r.bottom + margin + c.height <= vh) {
    top = r.bottom + margin;
    left = r.left + r.width / 2 - c.width / 2;
  } else if (r.top - margin - c.height >= 0) {
    top = r.top - margin - c.height;
    left = r.left + r.width / 2 - c.width / 2;
  } else if (r.right + margin + c.width <= vw) {
    top = r.top + r.height / 2 - c.height / 2;
    left = r.right + margin;
  } else {
    top = r.top + r.height / 2 - c.height / 2;
    left = r.left - margin - c.width;
  }
  top = Math.min(Math.max(top, margin), vh - c.height - margin);
  left = Math.min(Math.max(left, margin), vw - c.width - margin);
  Object.assign(els.card.style, { top: `${top}px`, left: `${left}px` });
}

function onTourClick(e) {
  const action = e.target.closest("[data-tour]")?.dataset.tour;
  if (action === "next") {
    if (tour.index === tour.steps.length - 1) endTour(true);
    else { tour.index += 1; renderTourStep(); }
  } else if (action === "prev") {
    tour.index -= 1;
    renderTourStep();
  } else if (action === "skip") {
    endTour(true);
  }
}

function onTourKey(e) {
  if (!tour) return;
  if (e.key === "Escape") endTour(true);
  else if (e.key === "ArrowRight") tour.els.card.querySelector('[data-tour="next"]')?.click();
  else if (e.key === "ArrowLeft") tour.els.card.querySelector('[data-tour="prev"]')?.click();
}

function endTour(markSeen) {
  if (!tour) return;
  Object.values(tour.els).forEach((el) => el.remove());
  window.removeEventListener("resize", positionTour);
  document.removeEventListener("keydown", onTourKey);
  tour = null;
  if (markSeen && currentUser && currentUser.tour_version < TOUR_VERSION) {
    currentUser.tour_version = TOUR_VERSION;
    api("/api/me", { method: "PATCH", body: JSON.stringify({ tour_version: TOUR_VERSION }) }).catch(() => {});
  }
}

// Se muestra solo si el usuario no ha visto la versión actual del tutorial.
function maybeStartTour() {
  if (currentUser && currentUser.tour_version < TOUR_VERSION) startTour();
}
