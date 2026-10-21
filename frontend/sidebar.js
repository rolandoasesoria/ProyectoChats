// Barra lateral: al pasar el ratón (o con el teclado) cada icono se despliega con su nombre y un detalle en vivo
// («12 sin leer · 3 esperan respuesta»), y lleva un contador. Los contadores se refrescan cada 30 s y cuando cambia
// algo: al abrir un chat, al decidir una propuesta de la IA, al cambiar la bandeja o las tareas.

const NAV_REFRESH = 30000;
const navState = { unreadChats: 0, unreadMail: 0, waiting: 0, late: 0, aiPending: 0, aiEnabled: false };

function setNavBadge(view, n, alert = false) {
  const badge = document.querySelector(`.sidebar [data-view="${view}"] .nav-count`);
  if (!badge) return;
  badge.textContent = n > 99 ? "99+" : n;
  badge.hidden = !n;
  badge.classList.toggle("alert", alert);
}

function setNavDetail(view, text) {
  const detail = document.querySelector(`.sidebar [data-view="${view}"] .nav-detail`);
  if (!detail) return;
  detail.textContent = text || "";
  detail.hidden = !text;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function renderNav() {
  const s = navState;
  setNavBadge("chats", s.unreadChats, s.late > 0);
  setNavDetail("chats", [s.unreadChats && plural(s.unreadChats, "sin leer", "sin leer"),
    s.waiting && `${plural(s.waiting, "espera", "esperan")} respuesta${s.late ? ` (${s.late} fuera de plazo)` : ""}`]
    .filter(Boolean).join(" · ") || "Todo al día");
  setNavBadge("mail", s.unreadMail);
  setNavDetail("mail", s.unreadMail ? plural(s.unreadMail, "correo sin leer", "correos sin leer") : "Todo leído");
  setNavBadge("ai", s.aiPending);
  setNavDetail("ai", s.aiEnabled
    ? `Activada${s.aiPending ? ` · ${plural(s.aiPending, "propuesta", "propuestas")} por revisar` : ""}` : "Desactivada");
}

// La bandeja «Sin responder» (inbox.js) avisa de cuántas esperan y cuántas están fuera de plazo.
function setNavInbox(waiting, late) {
  navState.waiting = waiting;
  navState.late = late;
  renderNav();
  setTopbarToday({ inbox: waiting, late });
}

// Las tareas (profile.js) avisan de cuántas tiene la persona y cuántas vencen hoy o ya vencieron.
function setNavTasks(open, overdue) {
  setTopbarToday({ tasks: overdue });
  setNavDetail("tasks", open ? `${plural(open, "pendiente", "pendientes")}${overdue ? ` · ${overdue} para hoy o vencidas` : ""}`
    : "Ninguna pendiente");
}

async function refreshNavCounts() {
  try {
    const c = await api("/api/me/counts");
    navState.unreadChats = c.unread_chats;
    navState.unreadMail = c.unread_mail;
    navState.aiPending = c.ai_pending;
    navState.aiEnabled = c.ai_enabled;
    renderNav();
  } catch { /* no crítico: se reintenta en la siguiente vuelta */ }
}

function bindSidebarEvents() {
  setInterval(() => { if (!document.hidden) refreshNavCounts(); }, NAV_REFRESH);
  refreshNavCounts();
}
