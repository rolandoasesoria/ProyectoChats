// Ancho de las zonas de cada página: ficha (clientes · ficha · asistente), Mis Chats (lista · conversación ·
// detalles) y Plantillas (lista · plantilla). Los separadores se arrastran con el ratón o se mueven con las flechas
// del teclado; doble clic vuelve al ancho inicial. El ancho elegido se recuerda en este navegador, por página.
// La zona central ocupa el resto y nunca baja de su mínimo (`minCenter`).

const LAYOUT_STEP = 16;
const LAYOUTS = [
  {
    container: ".layout", key: "pc-layout", center: ".detail", minCenter: 300,
    zones: {
      clients: { pane: ".clients", side: "left", def: 290, min: 180, max: 520 },
      chat: { pane: "#assistant", side: "right", def: 400, min: 260, max: 760 },
    },
  },
  {
    container: "#view-chats", key: "pc-layout-chats", center: ".chat-main", minCenter: 340,
    zones: {
      list: { pane: ".chats-pane", side: "left", def: 320, min: 240, max: 520 },
      details: { pane: "#chat-details", side: "right", def: 400, min: 260, max: 760 }, // como el asistente de la ficha
    },
  },
  {
    container: "#view-templates", key: "pc-layout-templates", center: ".tpl-main", minCenter: 340,
    zones: { list: { pane: ".tpl-pane", side: "left", def: 300, min: 220, max: 560 } },
  },
];

function loadLayoutWidths(layout) {
  const defaults = Object.fromEntries(Object.entries(layout.zones).map(([zone, z]) => [zone, z.def]));
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(layout.key) || "{}") };
  } catch {
    return defaults;
  }
}

function saveLayoutWidths(layout, widths) {
  try { localStorage.setItem(layout.key, JSON.stringify(widths)); } catch { /* almacenamiento no disponible */ }
}

function applyLayoutWidths(layout, widths) {
  const container = $(layout.container);
  for (const [zone, z] of Object.entries(layout.zones)) {
    container.style.setProperty(`--w-${zone}`, `${widths[zone]}px`);
    const handle = container.querySelector(`:scope > .resizer[data-zone="${zone}"]`);
    handle.setAttribute("aria-valuenow", widths[zone]);
    handle.setAttribute("aria-valuemin", z.min);
    handle.setAttribute("aria-valuemax", z.max);
  }
}

// Lo más que puede crecer la zona ahora: lo que la zona central tiene por encima de su mínimo.
function zoneRoom(layout, zone) {
  const center = $(layout.center).getBoundingClientRect().width;
  const pane = $(layout.zones[zone].pane).getBoundingClientRect().width;
  return pane + Math.max(0, center - layout.minCenter);
}

function bindLayout(layout) {
  const container = $(layout.container);
  const widths = loadLayoutWidths(layout);
  applyLayoutWidths(layout, widths);

  const setZone = (zone, width, room = zoneRoom(layout, zone)) => {
    const z = layout.zones[zone];
    widths[zone] = Math.round(Math.max(z.min, Math.min(width, z.max, room)));
    applyLayoutWidths(layout, widths);
  };

  for (const handle of container.querySelectorAll(":scope > .resizer")) {
    const zone = handle.dataset.zone;
    const z = layout.zones[zone];

    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("resizing");
      // El ancho se mide desde el borde exterior de la zona; el separador está en medio del hueco entre tarjetas.
      const gap = parseFloat(getComputedStyle(container).columnGap) || 0;
      const rect = $(z.pane).getBoundingClientRect();
      const room = zoneRoom(layout, zone);
      const onMove = (e) => setZone(zone, z.side === "left" ? e.clientX - rect.left - gap : rect.right - e.clientX - gap, room);
      const onUp = () => {
        handle.removeEventListener("pointermove", onMove);
        document.body.classList.remove("resizing");
        saveLayoutWidths(layout, widths);
      };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp, { once: true });
      handle.addEventListener("pointercancel", onUp, { once: true });
    });

    handle.addEventListener("dblclick", () => {
      setZone(zone, z.def);
      saveLayoutWidths(layout, widths);
    });

    // Teclado: la flecha mueve el separador en su dirección (las zonas de la derecha crecen hacia la izquierda).
    handle.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const towardsRight = event.key === "ArrowRight";
      const grows = z.side === "left" ? towardsRight : !towardsRight;
      setZone(zone, widths[zone] + (grows ? LAYOUT_STEP : -LAYOUT_STEP));
      saveLayoutWidths(layout, widths);
    });
  }
}

function bindLayoutEvents() {
  LAYOUTS.forEach(bindLayout);
}
