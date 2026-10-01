// Tutorial de bienvenida: recorre los apartados de la app la primera vez que se entra.
//
// ⚠️ MANTENER AL DÍA: cada vez que se añada, quite o cambie un apartado de la interfaz:
//   1. Actualiza TOUR_STEPS (un paso por apartado, en el orden en que se recorre la pantalla).
//   2. Sube TOUR_VERSION: así quienes ya vieron el tutorial lo verán de nuevo con los cambios.
//   3. Actualiza también HELP_SYSTEM_PROMPT (la mascota Chispa) en backend/app/agent.py.
//
// Cada paso: { target: selector CSS o null (tarjeta centrada), title, text, when?: () => boolean }.
// Los pasos cuyo elemento no esté visible (p. ej. en pantallas pequeñas) se saltan solos.

const TOUR_VERSION = 15;

const TOUR_STEPS = [
  {
    target: null,
    title: "Bienvenido a ProyectoChats",
    text: "Todas las conversaciones con tus clientes —email, WhatsApp, Telegram— en un solo sitio, y una IA que encuentra los datos por ti. Un recorrido de un minuto.",
  },
  {
    target: ".clients",
    title: "Clientes",
    text: "Busca por nombre, empresa, email o teléfono, y filtra por estado, etiqueta o responsable. El número azul indica mensajes nuevos. «Consulta general» pregunta sobre todos los clientes a la vez.",
  },
  {
    target: "#import-btn",
    title: "Importar",
    text: "Sube un chat exportado de WhatsApp (.txt/.zip), Telegram (.json) o correo (.eml/.mbox). Si lo vuelves a importar, solo se añaden los mensajes nuevos.",
  },
  {
    target: ".chat",
    title: "Asistente",
    text: "Pregunta cualquier dato: «¿qué CIF nos dio?». Cada cliente tiene su propia conversación. Busca en las tuyas; si quieres que mire las de tus compañeros, pídeselo.",
  },
  {
    target: ".detail",
    title: "Ficha del cliente",
    text: "«Ficha»: resumen, datos clave y documentos. «Tareas» pendientes. «Notas» internas (con @ avisas a un compañero). «Mensajes»: todo el historial, con buscador y «Redactar respuesta» (con IA o con respuestas guardadas: escribe /), que la IA puede retocar. Con ✎ editas estado, responsable y etiquetas.",
  },
  {
    target: "#side-inbox-tab",
    title: "Sin responder",
    text: "Quién espera respuesta, de más a menos tiempo. Elige «Mías» o «Todo el equipo»; «Atendido» quita lo que no necesita respuesta y «Posponer» la aparta hasta más tarde. Arriba verás también a quien no te ha contestado, si lo pediste al responder.",
  },
  {
    target: "#side-tasks-tab",
    title: "Tareas",
    text: "Tus tareas de todos los clientes. El número se pone en rojo si alguna vence hoy o ya ha vencido.",
  },
  {
    target: "#dashboard-btn",
    title: "Panel",
    text: "Mensajes, tiempo de respuesta, tareas y clientes por estado en el periodo que elijas.",
  },
  {
    target: "#bell",
    title: "Avisos",
    text: "Te avisa cuando te mencionan en una nota o te asignan una tarea.",
  },
  {
    target: "#user-menu-btn",
    title: "Tu cuenta",
    text: "Contraseña, este tutorial y cerrar sesión. El botón de al lado cambia entre tema claro y oscuro.",
  },
  {
    target: "#user-menu-btn",
    title: "Administración",
    text: "En este menú gestionas cuentas, conectas canales en «Integraciones» y consultas el «Registro de accesos». Desde ✎ en cada cliente puedes exportar o borrar sus datos.",
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
  const steps = TOUR_STEPS.filter((s) =>
    (!s.when || s.when()) && (!s.target || isVisible(document.querySelector(s.target))));
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
