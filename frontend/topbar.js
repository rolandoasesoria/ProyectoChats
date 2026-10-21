// Barra superior: el saludo con la fecha y el resumen del día (quién espera respuesta y las tareas para hoy).

const topbarToday = { inbox: null, late: 0, tasks: null };

function greetingFor(date) {
  const hour = date.getHours();
  if (hour >= 6 && hour < 13) return "Buenos días";
  if (hour >= 13 && hour < 21) return "Buenas tardes";
  return "Buenas noches";
}

// «Buenos días, Ana» y «martes, 21 de octubre» (hora local). Se repasa cada minuto por si cambia el tramo o el día.
function renderGreeting() {
  if (!currentUser) return;
  const now = new Date();
  $("#greeting-hello").textContent = `${greetingFor(now)}, ${currentUser.name.trim().split(/\s+/)[0]}`;
  $("#greeting-date").textContent = now.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
}

// Lo avisan la bandeja (setNavInbox) y las tareas (setNavTasks). Con todo a cero, «Todo al día».
function setTopbarToday(changes) {
  Object.assign(topbarToday, changes);
  const { inbox, late, tasks } = topbarToday;
  const inboxChip = $("#today-inbox");
  inboxChip.hidden = !inbox;
  inboxChip.textContent = `${inbox} sin responder`;
  inboxChip.classList.toggle("late", late > 0);
  inboxChip.title = late ? `${late} fuera de plazo o sin contestar` : "Conversaciones que esperan tu respuesta";
  $("#today-tasks").hidden = !tasks;
  $("#today-tasks").textContent = plural(tasks, "tarea para hoy", "tareas para hoy");
  $("#today-done").hidden = inbox !== 0 || tasks !== 0;
}

function bindTopbarEvents() {
  $("#today-inbox").addEventListener("click", () => goToSide("inbox"));
  $("#today-tasks").addEventListener("click", () => goToSide("tasks"));
  setInterval(renderGreeting, 60000);
}
