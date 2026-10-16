// Presencia: avisa de qué compañeros tienen abierto el mismo cliente y de quién está respondiendo,
// para no contestar dos veces. La interfaz da un «latido» al cambiar de cliente, al empezar o dejar de escribir
// en la caja de la conversación y cada 15 segundos.

const PRESENCE_INTERVAL = 15000;

async function heartbeat() {
  const clientId = state.clientId;
  try {
    const others = await api("/api/presence", {
      method: "POST", body: JSON.stringify({ client_id: clientId, composing: !!clientId && chatState.composing }),
    });
    if (state.clientId === clientId) renderPresence(others);
  } catch { /* no crítico: se reintenta en el siguiente latido */ }
}

function renderPresence(others) {
  const bar = $("#presence-bar");
  const writing = others.filter((o) => o.composing).map((o) => o.name);
  const viewing = others.filter((o) => !o.composing).map((o) => o.name);
  const list = (names) => names.length > 1 ? `${names.slice(0, -1).join(", ")} y ${names.at(-1)}` : names[0];
  const parts = [];
  if (writing.length) parts.push(`${list(writing)} ${writing.length > 1 ? "están" : "está"} respondiendo a este cliente`);
  if (viewing.length) parts.push(`${list(viewing)} también ${viewing.length > 1 ? "lo tienen" : "lo tiene"} abierto`);
  bar.textContent = parts.join(" · ");
  bar.classList.toggle("writing", writing.length > 0);
  bar.hidden = !parts.length;
}

function bindPresenceEvents() {
  setInterval(() => { if (!document.hidden) heartbeat(); }, PRESENCE_INTERVAL);
  // Al cerrar la pestaña deja de figurar en el cliente (si el navegador no lo envía, caduca solo).
  window.addEventListener("pagehide", () => {
    navigator.sendBeacon?.("/api/presence", new Blob([JSON.stringify({ client_id: null })], { type: "application/json" }));
  });
}
