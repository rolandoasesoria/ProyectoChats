// Tutorial de bienvenida: recorre los apartados de la app la primera vez que se entra.
//
// ⚠️ MANTENER AL DÍA: cada vez que se añada, quite o cambie un apartado de la interfaz:
//   1. Actualiza TOUR_STEPS (un paso por apartado, en el orden en que se recorre la pantalla).
//   2. Sube TOUR_VERSION: así quienes ya vieron el tutorial lo verán de nuevo con los cambios.
//   3. Actualiza también HELP_SYSTEM_PROMPT (la mascota Chispa) en backend/app/agent.py.
//
// Cada paso: { target: selector CSS o null (tarjeta centrada), title, text, when?: () => boolean }.
// Los pasos cuyo elemento no esté visible (p. ej. en pantallas pequeñas) se saltan solos.

const TOUR_VERSION = 13;

const TOUR_STEPS = [
  {
    target: null,
    title: "¡Bienvenido a ProyectoChats! 👋",
    text: "Aquí tienes todas las conversaciones con tus clientes —email, WhatsApp, Telegram…— en un solo sitio, y un asistente de IA que busca los datos por ti. Te enseño la pantalla en un minuto.",
  },
  {
    target: ".clients",
    title: "Tus clientes",
    text: "Aquí están todos los clientes, con los canales por los que se ha hablado con cada uno. El buscador encuentra por nombre, empresa, email, teléfono o @usuario. Un número azul indica mensajes nuevos desde la última vez que abriste ese cliente, y un punto, que tienes una conversación abierta con el asistente sobre él.",
  },
  {
    target: "#client-filters",
    title: "Filtrar clientes",
    text: "Filtra la lista por estado (potencial, activo, incidencia, inactivo), por etiqueta o para ver solo los clientes de los que eres responsable. El punto de color junto a cada nombre indica su estado. Con ＋ puedes crear un cliente a mano.",
  },
  {
    target: "#import-btn",
    title: "Importar conversaciones",
    text: "Trae aquí tus chats: exporta una conversación de WhatsApp (.txt, o .zip si incluye fotos y archivos), Telegram (.json) o tus correos (.eml o .mbox, con sus adjuntos) y súbela. Te preguntaré quién es el cliente y la guardaré en su ficha. Si importas el mismo chat más tarde, solo se añaden los mensajes nuevos.",
  },
  {
    target: "#client-list li.general",
    title: "Consulta general",
    text: "Si no sabes de qué cliente se trata, o quieres preguntar por varios a la vez, usa la consulta general: puede buscar en todos los clientes.",
  },
  {
    target: ".chat",
    title: "El asistente",
    text: "Pregúntale cualquier dato: «¿qué CIF nos dio?», «¿qué fecha de entrega acordamos?». Cada cliente tiene su propia conversación, que se guarda en tu perfil. Por defecto busca solo en TUS conversaciones; si quieres que mire también las de tus compañeros, pídeselo («busca también en las del equipo»).",
  },
  {
    target: "#new-chat",
    title: "Nueva conversación",
    text: "Empieza de cero la conversación con el asistente sobre el cliente actual.",
  },
  {
    target: ".detail",
    title: "Ficha, tareas y mensajes del cliente",
    text: "Al elegir un cliente verás arriba su estado, responsable y etiquetas; con ✎ los cambias, añades identificadores (email, teléfono…) o lo unes con otro cliente si es la misma persona (y si la app detecta un posible duplicado, te lo propone). Debajo hay cuatro pestañas. «Ficha»: un resumen de cómo va todo y sus datos clave (dirección, CIF, forma de pago…), que la IA saca de las conversaciones; puedes corregirlos, añadir los tuyos o descartar los que sobren, y con ↗ ves el mensaje de donde sale cada uno. Debajo están sus «Documentos»: adjuntos de correos y WhatsApp y los que subas tú; la IA puede leer fotos y PDF para que también se pueda buscar en ellos. «Tareas»: lo que hay pendiente con ese cliente, incluidos los compromisos que la IA detecta («te mando el presupuesto el lunes»). «Notas»: comentarios internos del equipo que el cliente nunca ve; escribe @ y el nombre de un compañero para avisarle. «Mensajes»: todo el historial del cliente en todos los canales, también lo que hablaron tus compañeros (verás «la lleva…» en esas conversaciones; marca «Solo mis conversaciones» para ver solo las tuyas), con un buscador por palabras o ✨ por significado (entiende la pregunta aunque el mensaje use otras palabras), y el botón «✍️ Redactar respuesta» para que la IA te prepare la contestación (o escribirla tú); si el canal está conectado, la envías desde aquí con «📤 Enviar», y si no, la copias. Si han llegado mensajes desde tu última visita, te lo avisaré arriba y podrás pedir un resumen de las novedades.",
  },
  {
    target: "#side-inbox-tab",
    title: "Sin responder",
    text: "Clientes que te han escrito y esperan respuesta, del que más tiempo lleva esperando al que menos (en rojo si pasan de 24 h). Pulsa uno para ir directo a su mensaje. Con «✍️ Responder» la IA te prepara un borrador. Si un mensaje no necesita respuesta (un «¡gracias!»), márcalo como «Atendido». Arriba eliges «Mías» o «Todo el equipo» (con el número de cada lado); en las de tus compañeros verás quién la lleva.",
  },
  {
    target: "#side-tasks-tab",
    title: "Tus tareas",
    text: "Aquí tienes todas tus tareas pendientes de todos los clientes, ordenadas: vencidas, para hoy, próximas y sin fecha. El número se pone en rojo si alguna vence hoy o ya ha vencido.",
  },
  {
    target: "#dashboard-btn",
    title: "Panel de actividad",
    text: "Cifras del equipo en el periodo que elijas: mensajes recibidos y enviados, clientes con actividad, tiempo de primera respuesta, tareas y clientes por estado. Los administradores ven además el desglose por persona.",
  },
  {
    target: "#bell",
    title: "Avisos",
    text: "La campana te avisa cuando un compañero te menciona en una nota o te asigna una tarea. Pulsa un aviso para ir directo al cliente.",
  },
  {
    target: "#theme-toggle",
    title: "Tema claro u oscuro",
    text: "Cambia entre tema claro y oscuro. Se guarda en tu perfil, así que lo tendrás igual en cualquier dispositivo.",
  },
  {
    target: "#user-menu-btn",
    title: "Tu cuenta",
    text: "Desde aquí puedes volver a ver este tutorial, cambiar tu contraseña y cerrar sesión.",
  },
  {
    target: "#user-menu-btn",
    title: "Administración",
    text: "Como administrador, en este mismo menú tienes «Administración»: crear cuentas, cambiar roles, restablecer contraseñas y desactivar cuentas; «Integraciones», para conectar el correo, un bot de Telegram o WhatsApp Business y que los mensajes entren solos; y el «Registro de accesos», que muestra quién ha consultado conversaciones de compañeros y quién ha exportado, borrado o unido clientes. Además, en ✎ de cada cliente puedes descargar todos sus datos o borrarlo por completo si lo pide (protección de datos).",
    when: () => currentUser?.role === "admin",
  },
  {
    target: "#mascot",
    title: "Chispa, tu ayudante",
    text: "¿Dudas sobre cómo funciona algo? Pulsa aquí y pregúntale a Chispa. Ella sabe todo sobre la app (pero no ve los datos de los clientes: para eso está el asistente).",
  },
  {
    target: null,
    title: "¡Listo!",
    text: "Ya puedes empezar. Elige un cliente de la lista y pregúntale al asistente lo que necesites.",
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
