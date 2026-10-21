// Chispa, la mascota de ayuda: sigue el puntero con la mirada y pone cara de pensar mientras responde.
// Solo presentación: flotar, parpadear, saltar y el destello están en styles.css.

const CHISPA_REACH = 260; // a esta distancia del puntero (px) ya mira del todo hacia él

function lookAt(mascot, x, y) {
  mascot.style.setProperty("--look-x", x.toFixed(3));
  mascot.style.setProperty("--look-y", y.toFixed(3));
}

function bindChispa() {
  const mascot = $("#mascot");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let frame = 0;
  document.addEventListener("pointermove", (e) => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const r = mascot.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2);
      const dy = e.clientY - (r.top + r.height * 0.45);
      const dist = Math.hypot(dx, dy) || 1;
      const reach = Math.min(dist / CHISPA_REACH, 1);
      lookAt(mascot, (dx / dist) * reach, (dy / dist) * reach);
    });
  }, { passive: true });
  // Si el puntero sale de la ventana, vuelve a mirar al frente
  document.documentElement.addEventListener("mouseleave", () => lookAt(mascot, 0, 0));
}

// Mientras la ayuda prepara la respuesta, los ojos se vuelven tres puntos «escribiendo…»
function setChispaThinking(thinking) {
  $("#mascot").classList.toggle("thinking", thinking);
}
