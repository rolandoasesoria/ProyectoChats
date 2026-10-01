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
