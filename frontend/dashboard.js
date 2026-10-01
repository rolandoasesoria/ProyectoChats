// Panel de actividad: indicadores, mensajes por semana y canal, clientes por estado y desglose por persona.
// Gráficos en SVG propio (sin librerías), siguiendo la guía de visualización: barras finas, 2 px de separación,
// esquina redondeada solo en el extremo de datos, rejilla tenue, leyenda, aviso al pasar el ratón y vista en tabla.

const SVG_NS = "http://www.w3.org/2000/svg";
let dashDays = 30;

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function formatHours(h) {
  if (h === null || h === undefined) return "—";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${h < 10 ? h.toFixed(1).replace(".", ",") : Math.round(h)} h`;
  return `${Math.round(h / 24)} días`;
}

function compact(n) {
  return new Intl.NumberFormat("es-ES", { notation: n >= 10000 ? "compact" : "standard" }).format(n);
}

/* ---------- Aviso (tooltip) ---------- */

function showTooltip(evt, title, rows) {
  const tip = $("#viz-tooltip");
  tip.replaceChildren();
  const head = document.createElement("div");
  head.className = "viz-tip-title";
  head.textContent = title;
  tip.appendChild(head);
  rows.forEach(({ value, label, color }) => {
    const row = document.createElement("div");
    row.className = "viz-tip-row";
    const key = document.createElement("span");
    key.className = "viz-tip-key";
    if (color) key.style.background = color;
    const strong = document.createElement("strong");
    strong.textContent = value;
    const name = document.createElement("span");
    name.textContent = label;
    row.append(key, strong, name);
    tip.appendChild(row);
  });
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  const x = Math.min(evt.clientX + 14, window.innerWidth - r.width - 8);
  const y = Math.max(8, evt.clientY - r.height - 12);
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

function hideTooltip() {
  $("#viz-tooltip").hidden = true;
}

/* ---------- Gráfico de columnas apiladas ---------- */

function channelColor(ch) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${ch}`).trim() || "#888";
}

function weekLabel(iso, withYear = false) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("es-ES",
    withYear ? { day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" });
}

function renderWeekly(data) {
  const box = $("#dash-weekly");
  box.replaceChildren();
  const channels = data.channels;
  const weeks = data.weekly;
  const labels = { email: "Email", telegram: "Telegram", whatsapp: "WhatsApp" };

  // Leyenda (rectángulos, como las barras). Texto en tinta normal; el color va en la marca.
  $("#dash-legend").innerHTML = channels.map((ch) =>
    `<span class="viz-legend-item"><span class="viz-key ${ch}"></span>${labels[ch]}</span>`).join("");

  const W = Math.max(box.clientWidth || 700, 320);
  const H = 220;
  const m = { top: 12, right: 8, bottom: 26, left: 34 };
  const iw = W - m.left - m.right;
  const ih = H - m.top - m.bottom;
  const totals = weeks.map((w) => channels.reduce((s, ch) => s + w[ch], 0));
  const max = Math.max(4, ...totals);
  const step = max <= 5 ? 1 : Math.ceil(max / 4);
  const top = Math.ceil(max / step) * step;
  const y = (v) => m.top + ih - (v / top) * ih;
  const band = iw / weeks.length;
  const barW = Math.min(24, Math.max(4, band * 0.6));

  const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Mensajes recibidos por semana y canal" });
  // Rejilla horizontal tenue y eje Y con pocas marcas.
  for (let v = 0; v <= top; v += step) {
    svg.appendChild(svgEl("line", { x1: m.left, x2: W - m.right, y1: y(v), y2: y(v),
      class: v === 0 ? "viz-baseline" : "viz-grid" }));
    const t = svgEl("text", { x: m.left - 6, y: y(v) + 4, "text-anchor": "end", class: "viz-axis" });
    t.textContent = compact(v);
    svg.appendChild(t);
  }
  const labelEvery = Math.ceil(weeks.length / Math.floor(iw / 56));
  weeks.forEach((w, i) => {
    const cx = m.left + band * i + band / 2;
    const x = cx - barW / 2;
    let acc = 0;
    const segs = channels.filter((ch) => w[ch] > 0);
    segs.forEach((ch, si) => {
      const y0 = y(acc);
      const y1 = y(acc + w[ch]);
      acc += w[ch];
      const isTop = si === segs.length - 1;
      // 2 px de separación en color de superficie entre segmentos (se resta de la altura, no se dibuja borde).
      const h = Math.max(1, y0 - y1 - (si > 0 ? 2 : 0));
      const yTop = y1;
      const r = isTop ? Math.min(4, h, barW / 2) : 0;
      // Rectángulo con esquinas redondeadas solo arriba (extremo de datos), recto en la base.
      const d = `M${x},${yTop + h} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + barW - r} ` +
                `Q${x + barW},${yTop} ${x + barW},${yTop + r} V${yTop + h} Z`;
      svg.appendChild(svgEl("path", { d, class: `viz-seg ${ch}` }));
    });
    if (i % labelEvery === 0) {
      const t = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle", class: "viz-axis" });
      t.textContent = weekLabel(w.week);
      svg.appendChild(t);
    }
    // Zona activa: toda la franja de la semana (más grande que la barra).
    const hit = svgEl("rect", { x: m.left + band * i, y: m.top, width: band, height: ih, fill: "transparent",
      tabindex: 0, class: "viz-hit" });
    const rows = [...channels].reverse().map((ch) => ({ value: String(w[ch]), label: labels[ch], color: channelColor(ch) }));
    const title = `Semana del ${weekLabel(w.week, true)} · ${totals[i]} mensaje${totals[i] === 1 ? "" : "s"}`;
    hit.addEventListener("pointermove", (e) => showTooltip(e, title, rows));
    hit.addEventListener("pointerleave", hideTooltip);
    hit.addEventListener("focus", () => {
      const b = hit.getBoundingClientRect();
      showTooltip({ clientX: b.left + b.width / 2, clientY: b.top + 40 }, title, rows);
    });
    hit.addEventListener("blur", hideTooltip);
    svg.appendChild(hit);
  });
  box.appendChild(svg);

  // Vista en tabla (siempre accesible sin ratón).
  $("#dash-weekly-table").innerHTML =
    `<thead><tr><th>Semana</th>${channels.map((ch) => `<th>${labels[ch]}</th>`).join("")}<th>Total</th></tr></thead>` +
    `<tbody>${weeks.map((w, i) => `<tr><td>${weekLabel(w.week, true)}</td>${channels.map((ch) => `<td class="num">${w[ch]}</td>`).join("")}<td class="num">${totals[i]}</td></tr>`).join("")}</tbody>`;
}

/* ---------- Clientes por estado (barras horizontales, una sola serie) ---------- */

function renderStatus(counts) {
  const max = Math.max(1, ...Object.values(counts));
  $("#dash-status").innerHTML = Object.entries(counts).map(([status, n]) => `
    <div class="hbar">
      <span class="hbar-label">${STATUS_LABELS[status]}</span>
      <span class="hbar-track"><span class="hbar-fill" data-pct="${(n / max) * 100}"></span></span>
      <span class="hbar-value">${n}</span>
    </div>`).join("");
  // El ancho se asigna por JavaScript: la política de seguridad no permite atributos style en el HTML.
  document.querySelectorAll("#dash-status .hbar-fill").forEach((el) => { el.style.width = `${el.dataset.pct}%`; });
}

/* ---------- Carga ---------- */

async function loadDashboard() {
  const data = await api(`/api/dashboard?days=${dashDays}`);
  const t = data.totals;
  const tiles = [
    ["Mensajes recibidos", compact(t.received)],
    ["Mensajes enviados", compact(t.sent)],
    ["Clientes con actividad", compact(t.active_clients)],
    ["Primera respuesta (mediana)", formatHours(t.median_response_hours)],
    [`Respondidas en plazo (${t.sla_hours} h)`, t.within_sla_pct === null ? "—" : `${t.within_sla_pct} %`],
    ["Tareas abiertas", `${compact(t.open_tasks)}${t.overdue_tasks ? ` <span class="tile-note">⚠ ${t.overdue_tasks} vencida${t.overdue_tasks === 1 ? "" : "s"}</span>` : ""}`],
  ];
  $("#dash-tiles").innerHTML = tiles.map(([label, value]) =>
    `<div class="stat-tile"><span class="stat-label">${label}</span><span class="stat-value">${value}</span></div>`).join("");
  renderWeekly(data);
  renderStatus(data.clients_by_status);
  $("#dash-people-card").hidden = !data.people;
  if (data.people) {
    $("#dash-people").innerHTML = `<thead><tr><th>Persona</th><th title="Mediana del tiempo de primera respuesta">1.ª resp.</th><th title="Respuestas en el periodo">Resp.</th><th title="Respuestas dentro del plazo (${t.sla_hours} h)">En plazo</th><th title="Conversaciones esperando respuesta ahora">Esperan</th><th title="Tareas abiertas">Tareas</th><th>Vencidas</th><th title="Clientes de los que es responsable">Clientes</th></tr></thead>
      <tbody>${data.people.map((p) => `<tr><td>${escapeHtml(p.name)}</td><td class="num">${formatHours(p.median_response_hours)}</td>
        <td class="num">${p.responses}</td><td class="num">${p.within_sla_pct === null ? "—" : `${p.within_sla_pct} %`}</td><td class="num">${p.waiting}</td><td class="num">${p.open_tasks}</td>
        <td class="num">${p.overdue_tasks ? `⚠ ${p.overdue_tasks}` : 0}</td><td class="num">${p.clients}</td></tr>`).join("")}</tbody>`;
  }
}

async function openDashboard() {
  $("#dashboard-dialog").showModal();
  try {
    await loadDashboard();
  } catch (err) {
    alert(err.message);
  }
}

function bindDashboardEvents() {
  $("#dashboard-btn").addEventListener("click", openDashboard);
  document.querySelectorAll("#dash-range [data-days]").forEach((b) => b.addEventListener("click", () => {
    dashDays = Number(b.dataset.days);
    document.querySelectorAll("#dash-range [data-days]").forEach((x) => x.classList.toggle("active", x === b));
    loadDashboard();
  }));
  $("#dashboard-dialog").addEventListener("close", hideTooltip);
}
