// Ancho de las tres zonas (clientes · ficha · asistente). Los separadores se arrastran con el ratón o se mueven
// con las flechas del teclado; doble clic vuelve al ancho inicial. El ancho elegido se recuerda en este navegador.
// La ficha (centro) ocupa el resto y nunca baja de LAYOUT_MIN_DETAIL.

const LAYOUT_KEY = "pc-layout";
const LAYOUT_DEFAULTS = { clients: 290, chat: 400 };
const LAYOUT_LIMITS = { clients: [180, 520], chat: [260, 760] };
const LAYOUT_MIN_DETAIL = 300;
const LAYOUT_STEP = 16;

function loadLayoutWidths() {
  try {
    const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}");
    return { ...LAYOUT_DEFAULTS, ...saved };
  } catch {
    return { ...LAYOUT_DEFAULTS };
  }
}

function saveLayoutWidths(widths) {
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(widths)); } catch { /* almacenamiento no disponible */ }
}

// Límite de la zona, sin dejar la ficha por debajo de su mínimo con el ancho actual de la ventana.
function clampZone(zone, width, widths) {
  const [min, max] = LAYOUT_LIMITS[zone];
  const other = zone === "clients" ? widths.chat : widths.clients;
  const room = $(".layout").clientWidth - other - LAYOUT_MIN_DETAIL;
  return Math.round(Math.max(min, Math.min(width, max, room)));
}

function applyLayoutWidths(widths) {
  const layout = $(".layout");
  for (const zone of ["clients", "chat"]) {
    layout.style.setProperty(`--w-${zone}`, `${widths[zone]}px`);
    const handle = $(`.resizer[data-zone="${zone}"]`);
    handle.setAttribute("aria-valuenow", widths[zone]);
    handle.setAttribute("aria-valuemin", LAYOUT_LIMITS[zone][0]);
    handle.setAttribute("aria-valuemax", LAYOUT_LIMITS[zone][1]);
  }
}

function bindLayoutEvents() {
  const widths = loadLayoutWidths();
  applyLayoutWidths(widths);

  const setZone = (zone, width) => {
    widths[zone] = clampZone(zone, width, widths);
    applyLayoutWidths(widths);
  };

  for (const handle of document.querySelectorAll(".resizer")) {
    const zone = handle.dataset.zone;

    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("resizing");
      const box = $(".layout").getBoundingClientRect();
      const onMove = (e) => setZone(zone, zone === "clients" ? e.clientX - box.left : box.right - e.clientX);
      const onUp = () => {
        handle.removeEventListener("pointermove", onMove);
        document.body.classList.remove("resizing");
        saveLayoutWidths(widths);
      };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp, { once: true });
      handle.addEventListener("pointercancel", onUp, { once: true });
    });

    handle.addEventListener("dblclick", () => {
      setZone(zone, LAYOUT_DEFAULTS[zone]);
      saveLayoutWidths(widths);
    });

    // Teclado: la flecha mueve el separador en su dirección (el asistente crece hacia la izquierda).
    handle.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const towardsRight = event.key === "ArrowRight";
      const grows = zone === "clients" ? towardsRight : !towardsRight;
      setZone(zone, widths[zone] + (grows ? LAYOUT_STEP : -LAYOUT_STEP));
      saveLayoutWidths(widths);
    });
  }
}
