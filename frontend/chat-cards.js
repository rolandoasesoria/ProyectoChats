// Chat al estilo de WhatsApp, lo que se ve dentro de cada mensaje: tarjetas de ubicación y de contacto, el reproductor
// de audios y notas de voz, la vista previa de los enlaces e «Info del mensaje». Cómo se pinta cada mensaje está en
// app.js (timelineHtml); lo que se envía desde la caja de escribir, en chat-compose.js.

const ICON_INFO = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5v.5"/></svg>';
const ICON_PIN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.4"/></svg>';
const ICON_MIC = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/></svg>';
const ICON_MUSIC = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/></svg>';
const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="solid" d="M8 5.5v13l10.5-6.5z"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="solid" d="M7.5 5h3.2v14H7.5zM13.3 5h3.2v14h-3.2z"/></svg>';

// «1:05» a partir de segundos
function clock(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/* ---------- Ubicación y tarjetas de contacto ---------- */

function mapsUrl(lat, lng) {
  return `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
}

function locationCardHtml(p) {
  const lat = Number(p.latitude);
  const lng = Number(p.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return "";
  const coords = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  const title = p.name || p.address || "Ubicación";
  const detail = p.name && p.address ? p.address : coords;
  return `<a class="place-card" href="${escapeHtml(mapsUrl(lat, lng))}" target="_blank" rel="noopener noreferrer" title="Abrir en Google Maps">
    <span class="place-map" aria-hidden="true">${ICON_PIN}</span>
    <span class="place-body"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span>
      <span class="place-open">Abrir en Google Maps ↗</span></span></a>`;
}

function contactCardHtml(c) {
  const phones = (c.phones || []).filter(Boolean);
  const emails = (c.emails || []).filter(Boolean);
  const copy = [c.name, c.org, ...phones, ...emails].filter(Boolean).join("\n");
  return `<div class="contact-card">
    <span class="chat-avatar contact-card-avatar ${avatarClass(c.name)}" aria-hidden="true">${escapeHtml(initialsOf(c.name || "?"))}</span>
    <span class="contact-card-body">
      <strong>${escapeHtml(c.name || "Contacto")}</strong>${c.org ? `<span class="muted">${escapeHtml(c.org)}</span>` : ""}
      ${phones.map((t) => `<a href="tel:${escapeHtml(t.replace(/[^\d+]/g, ""))}">${escapeHtml(t)}</a>`).join("")}
      ${emails.map((e) => `<span>${escapeHtml(e)}</span>`).join("")}
    </span>
    <button type="button" class="icon-btn contact-card-copy" data-copy="${escapeHtml(copy)}" aria-label="Copiar los datos del contacto" title="Copiar los datos">${COPY_ICON}</button>
  </div>`;
}

// La tarjeta de lo que se compartió (ubicación o contactos), o «» si el mensaje es texto.
function payloadHtml(m) {
  const p = m.payload;
  if (p?.type === "location") return locationCardHtml(p);
  if (p?.type === "contacts") return (p.contacts || []).map(contactCardHtml).join("");
  return "";
}

// El texto que se generó al recibirlo o enviarlo («📍 Ubicación: …», «🎤 Nota de voz (0:05)», «📎 foto.jpg»): con la
// tarjeta o el reproductor a la vista, sobra.
function bodyIsAutomatic(m, inline) {
  const kind = m.payload?.type;
  if ((kind === "location" || kind === "contacts") && payloadHtml(m)) return true;
  if (!inline.length) return false;
  if (kind === "voice") return true;
  return inline.some((a) => m.body === `📎 ${a.filename}`) || /^(🎤 Nota de voz|🎵 Audio)( \(\d+:\d\d\))?$/u.test(m.body);
}

/* ---------- Audios y notas de voz ---------- */

const VOICE_RATES = [1, 1.5, 2];
let voiceRate = 1; // la velocidad elegida vale para todos los audios, como en WhatsApp

function voiceNoteHtml(a, m) {
  const isVoice = m.payload?.type === "voice" || (m.body || "").startsWith("🎤");
  const seconds = m.payload?.seconds || 0;
  return `<div class="voice-note${isVoice ? " is-voice" : ""}" data-voice data-seconds="${seconds}">
    <button type="button" class="voice-play" data-voice-play aria-label="Reproducir">${ICON_PLAY}</button>
    <span class="voice-track">
      <input type="range" class="voice-seek" data-voice-seek min="0" max="1000" value="0" aria-label="Posición del audio">
      <span class="voice-info"><span data-voice-time>${seconds ? clock(seconds) : "0:00"}</span>
        <button type="button" class="voice-speed" data-voice-speed title="Velocidad de reproducción">${voiceRate}×</button></span>
    </span>
    <span class="voice-avatar" aria-hidden="true">${isVoice ? ICON_MIC : ICON_MUSIC}</span>
    <audio src="${attachmentUrl(a.id)}" preload="metadata"></audio>
  </div>`;
}

// Parado se ve lo que dura; sonando (o en pausa a medias), por dónde va.
function syncVoice(audio, icon = false) {
  const box = audio.closest("[data-voice]");
  if (!box) return;
  const duration = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : Number(box.dataset.seconds) || 0;
  const playing = !audio.paused && !audio.ended;
  if (duration) box.querySelector("[data-voice-seek]").value = String(Math.round((audio.currentTime / duration) * 1000));
  box.querySelector("[data-voice-time]").textContent = clock(playing || audio.currentTime > 0 ? audio.currentTime : duration);
  if (!icon) return;
  box.classList.toggle("playing", playing);
  const btn = box.querySelector("[data-voice-play]");
  btn.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
  btn.setAttribute("aria-label", playing ? "Pausar" : "Reproducir");
}

function toggleVoice(box) {
  const audio = box.querySelector("audio");
  if (!audio.paused) return audio.pause();
  document.querySelectorAll("[data-voice] audio").forEach((other) => { if (other !== audio) other.pause(); });
  audio.playbackRate = voiceRate;
  audio.play().catch(() => alert("No se ha podido reproducir el audio."));
}

function nextVoiceRate() {
  voiceRate = VOICE_RATES[(VOICE_RATES.indexOf(voiceRate) + 1) % VOICE_RATES.length];
  document.querySelectorAll("[data-voice-speed]").forEach((b) => { b.textContent = `${voiceRate}×`; });
  document.querySelectorAll("[data-voice] audio").forEach((a) => { a.playbackRate = voiceRate; });
}

/* ---------- Vista previa de los enlaces (título, descripción e imagen, como en WhatsApp) ---------- */

const linkPreviews = new Map(); // enlace → su vista previa (o null si no tiene), para no volver a pedirla
const previewRequests = new Map(); // enlace → petición en curso
const previewQueue = [];
let previewSlots = 3; // peticiones a la vez

const RAW_URL = /https?:\/\/[^\s<>"']+/;

function firstUrl(text) {
  const found = (text || "").match(RAW_URL);
  return found ? found[0].replace(/[.,;:!?)\]]+$/, "") : null;
}

function siteOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function linkCardHtml(url, p) {
  if (!p) return "";
  const image = p.image?.startsWith("data:image/") ? p.image : "";
  return `<a class="link-card${image ? " has-image" : ""}" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">
    ${image ? `<img class="link-card-img" src="${image}" alt="">` : ""}
    <span class="link-card-body">${p.title ? `<strong>${escapeHtml(p.title)}</strong>` : ""}${p.description ? `<span class="link-card-desc">${escapeHtml(p.description)}</span>` : ""}<span class="link-card-site">${escapeHtml(p.site || siteOf(url))}</span></span></a>`;
}

// En WhatsApp y Telegram, el primer enlace del mensaje: su tarjeta si ya se tiene o un hueco que se rellena luego.
function linkPreviewHtml(m) {
  if ((m.channel !== "whatsapp" && m.channel !== "telegram") || m.payload) return "";
  const url = firstUrl(m.body);
  if (!url) return "";
  if (linkPreviews.has(url)) return linkCardHtml(url, linkPreviews.get(url));
  return `<div class="link-slot" data-preview-url="${escapeHtml(url)}" hidden></div>`;
}

function queuedPreview(url) {
  return new Promise((resolve) => {
    const run = () => {
      previewSlots--;
      api(`/api/link-preview?${new URLSearchParams({ url })}`).then((r) => r.preview, () => null).then((p) => {
        previewSlots++;
        previewQueue.shift()?.();
        resolve(p);
      });
    };
    if (previewSlots > 0) run();
    else previewQueue.push(run);
  });
}

function fetchPreview(url) {
  if (!previewRequests.has(url)) {
    previewRequests.set(url, queuedPreview(url).then((p) => {
      linkPreviews.set(url, p);
      previewRequests.delete(url);
      return p;
    }));
  }
  return previewRequests.get(url);
}

// Rellena los huecos de vista previa de la conversación (sin mover la vista si se estaba al final).
function hydrateLinkPreviews(root) {
  const urls = new Set([...root.querySelectorAll("[data-preview-url]")].map((slot) => slot.dataset.previewUrl));
  for (const url of urls) {
    fetchPreview(url).then((p) => {
      const list = $("#chat-timeline");
      const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
      document.querySelectorAll(`[data-preview-url="${CSS.escape(url)}"]`).forEach((slot) => { slot.outerHTML = linkCardHtml(url, p); });
      if (p && atBottom) list.scrollTop = list.scrollHeight;
    });
  }
}

/* ---------- Info del mensaje ---------- */

function infoDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const day = dayLabel(d);
  return `${day.charAt(0).toUpperCase()}${day.slice(1)}, ${d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}`;
}

function infoRow(label, value, extra = "") {
  return `<div class="msg-info-row${extra}"><dt>${label}</dt><dd>${value}</dd></div>`;
}

const TICK_READ = '<span class="ticks read" aria-hidden="true"><svg viewBox="0 0 16 12"><path d="M1 6.5l3 3 6.5-7"/><path d="M7.5 8.5l1 1 6.5-7"/></svg></span>';
const TICK_DELIVERED = '<span class="ticks delivered" aria-hidden="true"><svg viewBox="0 0 16 12"><path d="M1 6.5l3 3 6.5-7"/><path d="M7.5 8.5l1 1 6.5-7"/></svg></span>';
const TICK_SENT = '<span class="ticks sent" aria-hidden="true"><svg viewBox="0 0 16 12"><path d="M3 6.5l3 3 6.5-7"/></svg></span>';

function messageInfoHtml(m) {
  const rows = [];
  const out = m.direction === "out";
  if (out && m.status === "failed") {
    rows.push(infoRow("No entregado", escapeHtml(m.status_error || "WhatsApp no pudo entregarlo."), " failed"));
  } else if (out && m.status) {
    rows.push(infoRow(`${TICK_READ} Leído`, escapeHtml(infoDate(m.read_at))));
    rows.push(infoRow(`${TICK_DELIVERED} Entregado`, escapeHtml(infoDate(m.delivered_at || m.read_at))));
  }
  rows.push(infoRow(out ? `${TICK_SENT} Enviado` : "Recibido", escapeHtml(infoDate(m.sent_at))));
  rows.push(infoRow(out ? "Enviado por" : "De", escapeHtml(m.sender) + (m.by_ai ? ' <span class="ai-mark">🤖 escrito por la IA</span>' : "")));
  rows.push(infoRow("Canal", `${escapeHtml(IDENTITY_LABELS[m.channel] || m.channel)} · cuenta de ${escapeHtml(m.owner)}`));
  if (m.reply_to_id) {
    rows.push(infoRow("En respuesta a", `${escapeHtml(m.reply_sender || "Mensaje")}: ${escapeHtml(firstLine(m.reply_body) || "📎 Archivo")}`));
  }
  if (m.attachments?.length) {
    rows.push(infoRow("Archivos", m.attachments.map((a) =>
      `<a href="${attachmentUrl(a.id, true)}">${escapeHtml(a.filename)}</a> <span class="muted">${formatSize(a.size)}</span>`).join("<br>")));
  }
  if (m.reactions?.length) {
    rows.push(infoRow("Reacciones", m.reactions.map((r) =>
      `${escapeHtml(r.emoji)} ${r.side === "client" ? "del cliente" : `de ${escapeHtml(r.user || "el equipo (desde el móvil)")}`}`).join("<br>")));
  }
  return rows.join("");
}

function openMessageInfo(id) {
  const m = chatState.messagesById?.get(id);
  const li = document.querySelector(`#chat-timeline li[data-id="${id}"]`);
  if (!m || !li) return;
  // El mensaje tal cual se ve en la conversación (sin las acciones ni las reacciones flotantes)
  const preview = $("#msg-info-preview");
  preview.className = `msg-info-preview msg-row ${m.direction} ${m.channel}`;
  preview.innerHTML = li.querySelector(".bubble").outerHTML;
  preview.querySelectorAll(".bubble-reactions, audio").forEach((x) => x.remove());
  preview.querySelectorAll("[data-voice]").forEach((x) => x.classList.add("static"));
  $("#msg-info-list").innerHTML = messageInfoHtml(m);
  $("#msg-info-dialog").showModal();
}

/* ---------- Eventos ---------- */

function bindChatCards() {
  document.addEventListener("click", (e) => {
    const play = e.target.closest("[data-voice-play]");
    const speed = e.target.closest("[data-voice-speed]");
    const info = e.target.closest("[data-info]");
    const copy = e.target.closest("[data-copy]");
    if (play && !play.closest(".static")) toggleVoice(play.closest("[data-voice]"));
    else if (speed) nextVoiceRate();
    else if (info) openMessageInfo(Number(info.dataset.info));
    else if (copy) {
      navigator.clipboard.writeText(copy.dataset.copy).then(() => toast("Datos del contacto copiados.", "success"),
        () => alert("No se han podido copiar."));
    }
  });
  document.addEventListener("input", (e) => {
    const seek = e.target.closest?.("[data-voice-seek]");
    const audio = seek?.closest("[data-voice]")?.querySelector("audio");
    if (!audio) return;
    const duration = Number.isFinite(audio.duration) ? audio.duration : Number(seek.closest("[data-voice]").dataset.seconds);
    if (duration) audio.currentTime = (Number(seek.value) / 1000) * duration;
  });
  // Los eventos del audio no suben: se escuchan en la fase de captura.
  for (const type of ["play", "pause", "ended"]) {
    document.addEventListener(type, (e) => {
      if (e.target.tagName !== "AUDIO") return;
      if (type === "ended") e.target.currentTime = 0;
      syncVoice(e.target, true);
    }, true);
  }
  for (const type of ["timeupdate", "loadedmetadata", "durationchange"]) {
    document.addEventListener(type, (e) => { if (e.target.tagName === "AUDIO") syncVoice(e.target); }, true);
  }
  // Vista previa con una imagen pequeña (un logo): en miniatura al lado del texto, como en WhatsApp
  document.addEventListener("load", (e) => {
    if (e.target.classList?.contains("link-card-img") && e.target.naturalWidth < 400) e.target.closest(".link-card").classList.add("compact");
  }, true);
}
