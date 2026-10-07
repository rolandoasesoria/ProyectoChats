// Utilidades compartidas por login.html e index.html. Se carga en <head> para aplicar el tema antes de pintar.

/* ---------- Tema claro / oscuro ----------
   La preferencia real se guarda en el perfil del usuario (servidor). Aquí se cachea en el navegador
   solo para aplicarla al instante al cargar la página, antes de que responda el servidor. */

const THEME_KEY = "pc-theme";

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  else delete root.dataset.theme; // "system": sigue al sistema operativo
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* almacenamiento no disponible */ }
}

function effectiveTheme() {
  const t = document.documentElement.dataset.theme;
  if (t) return t;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

(function applyCachedTheme() {
  let cached = null;
  try { cached = localStorage.getItem(THEME_KEY); } catch { /* ignorar */ }
  if (cached) applyTheme(cached);
})();

/* ---------- API ---------- */

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    window.location.href = "/login.html";
    throw new Error("Sesión no iniciada");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "Datos no válidos (revisa la longitud del texto).";
    } catch { /* sin cuerpo JSON */ }
    const error = new Error(detail);
    error.status = res.status;
    throw error;
  }
  return res.json();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const $ = (sel) => document.querySelector(sel);

// Autocompletado en un cuadro de texto: al escribir el disparador (`pattern`, cuyo grupo 2 es lo escrito tras él,
// p. ej. @nombre o /atajo) muestra en `list` las opciones de `search(texto)`; se recorren con las flechas y se eligen
// con Enter, Tab o el ratón. `render(opción, i, activa)` pinta cada <li data-i> y `choose(opción, inicio)` la aplica
// (inicio = posición del disparador en el texto).
function attachAutocomplete(textarea, list, { pattern, search, render, choose }) {
  let matches = [];
  let active = 0;
  let from = 0;

  const close = () => { list.hidden = true; matches = []; };
  const show = () => {
    list.innerHTML = matches.map((item, i) => render(item, i, active)).join("");
    list.hidden = !matches.length;
  };
  const pick = (item) => { close(); choose(item, from); };

  textarea.addEventListener("input", () => {
    const before = textarea.value.slice(0, textarea.selectionStart);
    const m = before.match(pattern);
    if (!m) return close();
    from = before.length - m[2].length - 1;
    matches = search(m[2]);
    active = 0;
    show();
  });
  textarea.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : matches.length - 1)) % matches.length;
      show();
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      pick(matches[active]);
    } else if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  });
  textarea.addEventListener("blur", () => setTimeout(close, 150));
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-i]");
    if (li) { e.preventDefault(); pick(matches[Number(li.dataset.i)]); }
  });
}
