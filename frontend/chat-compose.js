// Caja de escribir del chat, lo que va más allá del texto: el menú de adjuntar (archivo, ubicación o contacto), pegar o
// arrastrar archivos al chat y grabar notas de voz. Cómo se ve lo enviado está en chat-cards.js.

const LAST_LOCATION_KEY = "hilvana.ubicacion"; // la última ubicación enviada (suele ser la de la oficina)
const VOICE_TYPES = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
const VOICE_MAX_SECONDS = 15 * 60;

/* ---------- Qué se puede enviar en la conversación abierta ---------- */

// Con cuenta para enviar se puede adjuntar un archivo; la ubicación, los contactos y las notas de voz van en una
// conversación (no en un correo nuevo).
function syncComposerTools() {
  const canAttach = !$("#chat-file").disabled;
  const inThread = canAttach && !chatState.newEmail && Boolean(chatState.conversationId);
  $("#chat-attach").disabled = !canAttach;
  $("#attach-location").hidden = !inThread;
  $("#attach-contact").hidden = !inThread;
  $("#chat-voice").hidden = chatState.newEmail;
  $("#chat-voice").disabled = !inThread;
  if (!canAttach) toggleAttachMenu(false);
}

function toggleAttachMenu(open = $("#attach-menu").hidden) {
  $("#attach-menu").hidden = !open;
  $("#chat-attach").setAttribute("aria-expanded", String(open));
}

// Tras enviar algo desde aquí: la conversación (si sigue abierta), la lista de chats y la bandeja.
function afterComposerSend(clientId) {
  if (chatState.clientId === clientId) loadChatConversation();
  loadChats();
  refreshInboxCount();
}

async function sendFromComposer(path, body, button) {
  const conversationId = chatState.conversationId;
  const clientId = chatState.clientId;
  if (!conversationId) return false;
  button.disabled = true;
  try {
    await api(`/api/conversations/${conversationId}/${path}`, { method: "POST", body: JSON.stringify(body) });
  } finally {
    button.disabled = false;
  }
  afterComposerSend(clientId);
  return true;
}

function showFormError(el, message) {
  el.textContent = message;
  el.hidden = !message;
}

/* ---------- Pegar o arrastrar archivos ---------- */

// Las capturas pegadas llegan como «image.png»: se les pone la fecha y la hora para reconocerlas.
function namedFile(file) {
  if (!/^image\.\w+$/.test(file.name)) return file;
  const stamp = new Date().toLocaleString("sv-SE").replace(" ", "_").replaceAll(":", ".");
  return new File([file], `captura-${stamp}.${file.name.split(".").pop()}`, { type: file.type });
}

function attachFiles(files) {
  if (!files.length) return;
  if ($("#chat-file").disabled) return alert($("#chat-send-note").textContent || "Desde aquí no se pueden enviar archivos.");
  if (files.length > 1) toast(`Se adjunta un archivo por mensaje: «${files[0].name}».`);
  setChatFile(namedFile(files[0]));
  $("#chat-text").focus();
}

// Pegar una captura o un archivo copiado lo adjunta. Si también hay texto (p. ej. celdas de Excel, que llevan además
// su imagen), se pega el texto.
function onComposerPaste(e) {
  const files = [...(e.clipboardData?.files || [])];
  if (!files.length || e.clipboardData.getData("text/plain")) return;
  e.preventDefault();
  attachFiles(files);
}

let dragDepth = 0;

function draggingFiles(e) {
  return [...(e.dataTransfer?.types || [])].includes("Files");
}

function showDropZone(on) {
  const can = !$("#chat-file").disabled;
  const zone = $("#chat-drop");
  zone.hidden = !on;
  zone.classList.toggle("blocked", !can);
  $("#chat-drop-title").textContent = can ? "Suelta el archivo para adjuntarlo" : "Aquí no se pueden enviar archivos";
  $("#chat-drop-text").textContent = can ? "Se enviará con tu próximo mensaje"
    : $("#chat-send-note").textContent || "Conecta tu cuenta en «Mis cuentas» para enviar archivos.";
}

function bindDropZone() {
  const pane = $("#tab-conversation");
  pane.addEventListener("dragenter", (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    if (dragDepth++ === 0) showDropZone(true);
  });
  pane.addEventListener("dragover", (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = $("#chat-file").disabled ? "none" : "copy";
  });
  pane.addEventListener("dragleave", (e) => {
    if (!draggingFiles(e) || --dragDepth > 0) return;
    dragDepth = 0;
    showDropZone(false);
  });
  pane.addEventListener("drop", (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    showDropZone(false);
    attachFiles([...e.dataTransfer.files]);
  });
  // Fuera de la conversación, soltar un archivo no hace nada (el navegador lo abriría y se saldría de la app).
  window.addEventListener("dragover", (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    if (!e.target.closest?.("#tab-conversation")) e.dataTransfer.dropEffect = "none";
  });
  window.addEventListener("drop", (e) => { if (draggingFiles(e)) e.preventDefault(); });
}

/* ---------- Notas de voz ---------- */

let voice = null; // la grabación en curso: { recorder, stream, chunks, started, conversationId, clientId, … }

async function startVoice() {
  if (voice || !chatState.conversationId || $("#chat-voice").disabled) return;
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    return alert("Este navegador no puede grabar audio.");
  }
  const conversationId = chatState.conversationId;
  const clientId = chatState.clientId;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (err) {
    return alert(err.name === "NotAllowedError"
      ? "Para grabar notas de voz, permite el micrófono (en el candado de la barra de direcciones del navegador)."
      : "No se ha encontrado ningún micrófono.");
  }
  if (chatState.conversationId !== conversationId) return stream.getTracks().forEach((t) => t.stop());
  const mimeType = VOICE_TYPES.find((t) => MediaRecorder.isTypeSupported(t));
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType, audioBitsPerSecond: 32000 } : {});
  voice = { recorder, stream, chunks: [], started: Date.now(), conversationId, clientId };
  const current = voice;
  recorder.ondataavailable = (e) => { if (e.data.size) current.chunks.push(e.data); };
  recorder.start(250);
  current.timer = setInterval(() => {
    const seconds = (Date.now() - current.started) / 1000;
    $("#voice-time").textContent = clock(Math.floor(seconds));
    if (seconds >= VOICE_MAX_SECONDS) finishVoice(true);
  }, 250);
  $("#chat-composer").classList.add("recording");
  $("#voice-bar").hidden = false;
  $("#voice-time").textContent = "0:00";
  startVoiceMeter(current);
  $("#voice-send").focus();
}

// El nivel del micrófono, como barras que avanzan (si el navegador no deja medirlo, se graba igual).
function startVoiceMeter(v) {
  try {
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    ctx.createMediaStreamSource(v.stream).connect(analyser);
    v.ctx = ctx;
    const canvas = $("#voice-level");
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(canvas.clientWidth * ratio);
    canvas.height = Math.round(canvas.clientHeight * ratio);
    const g = canvas.getContext("2d");
    const samples = new Uint8Array(analyser.fftSize);
    const levels = [];
    let last = 0;
    const draw = (t) => {
      if (voice !== v) return;
      requestAnimationFrame(draw);
      if (t - last < 80) return;
      last = t;
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const x of samples) sum += (x - 128) ** 2;
      levels.push(Math.min(1, (Math.sqrt(sum / samples.length) / 128) * 4));
      const bar = 3 * ratio;
      const gap = 2 * ratio;
      const count = Math.floor(canvas.width / (bar + gap));
      levels.splice(0, Math.max(0, levels.length - count));
      g.clearRect(0, 0, canvas.width, canvas.height);
      g.fillStyle = getComputedStyle(canvas).color;
      levels.forEach((level, i) => {
        const h = Math.max(bar, level * canvas.height);
        g.fillRect(canvas.width - (levels.length - i) * (bar + gap), (canvas.height - h) / 2, bar, h);
      });
    };
    requestAnimationFrame(draw);
  } catch {
    /* sin medidor */
  }
}

function stopRecorder(v) {
  return new Promise((resolve) => {
    if (v.recorder.state === "inactive") return resolve();
    v.recorder.addEventListener("stop", () => resolve(), { once: true });
    v.recorder.stop();
  });
}

// Termina la grabación y la envía (send = true) o la descarta.
async function finishVoice(send) {
  const v = voice;
  if (!v) return;
  voice = null;
  clearInterval(v.timer);
  const seconds = Math.round((Date.now() - v.started) / 1000);
  await stopRecorder(v);
  v.stream.getTracks().forEach((t) => t.stop());
  v.ctx?.close().catch(() => {});
  $("#chat-composer").classList.remove("recording");
  $("#voice-bar").hidden = true;
  if (!send) return;
  if (seconds < 1 || !v.chunks.length) return toast("La nota de voz es demasiado corta: mantén la grabación al menos un segundo.");
  const blob = new Blob(v.chunks, { type: v.recorder.mimeType });
  const button = $("#chat-voice");
  button.disabled = true;
  button.classList.add("sending");
  try {
    const data = await fileToBase64(blob);
    await api(`/api/conversations/${v.conversationId}/send-voice`, {
      method: "POST", body: JSON.stringify({ data, mime: v.recorder.mimeType, seconds: Math.min(seconds, VOICE_MAX_SECONDS) }),
    });
    afterComposerSend(v.clientId);
  } catch (err) {
    alert(err.message);
  } finally {
    button.classList.remove("sending");
    syncComposerTools();
  }
}

// Al cambiar de chat no se envía nada que no se haya confirmado: la grabación se descarta.
function discardVoice() {
  if (!voice) return;
  finishVoice(false);
  toast("Nota de voz descartada al cambiar de chat.");
}

/* ---------- Enviar una ubicación ---------- */

let locationPrefill = null; // lo rellenado con la última ubicación enviada

function lastLocation() {
  try {
    return JSON.parse(localStorage.getItem(LAST_LOCATION_KEY) || "null");
  } catch {
    return null;
  }
}

// «40.4168, -3.7038», «40,4168 -3,7038» o un enlace de Google Maps (…/@40.41,-3.70,17z o …?q=40.41,-3.70).
function parseCoords(text) {
  let t = text.trim();
  try {
    t = decodeURIComponent(t);
  } catch {
    /* tal cual */
  }
  const found = t.match(/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/)
    || t.match(/[?&](?:q|query|ll|destination)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/)
    || t.match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/)
    || t.match(/^(-?\d+(?:,\d+)?)\s*[;\s]\s*(-?\d+(?:,\d+)?)$/);
  if (!found) return null;
  const latitude = Number(found[1].replace(",", "."));
  const longitude = Number(found[2].replace(",", "."));
  if (!(Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180)) return null;
  return { latitude, longitude };
}

function updateLocationMap() {
  const coords = parseCoords($("#location-coords").value);
  const link = $("#location-map");
  link.hidden = !coords;
  if (coords) link.href = mapsUrl(coords.latitude, coords.longitude);
}

function openLocationDialog() {
  toggleAttachMenu(false);
  const last = lastLocation();
  locationPrefill = last;
  $("#location-coords").value = last ? `${last.latitude}, ${last.longitude}` : "";
  $("#location-name").value = last?.name || "";
  $("#location-address").value = last?.address || "";
  const status = $("#location-status");
  status.textContent = last ? "Rellenado con la última ubicación que enviaste." : "";
  status.hidden = !last;
  showFormError($("#location-error"), "");
  updateLocationMap();
  $("#location-dialog").showModal();
  $(last ? "#location-submit" : "#location-coords").focus();
}

function locateMe() {
  const status = $("#location-status");
  status.hidden = false;
  if (!navigator.geolocation) {
    status.textContent = "Este navegador no puede darte la ubicación: escribe las coordenadas.";
    return;
  }
  status.textContent = "Buscando tu ubicación…";
  navigator.geolocation.getCurrentPosition((pos) => {
    const { latitude, longitude, accuracy } = pos.coords;
    $("#location-coords").value = `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`;
    // El nombre y la dirección eran los de la última ubicación enviada: ya no valen
    if (locationPrefill && $("#location-name").value === (locationPrefill.name || "")) $("#location-name").value = "";
    if (locationPrefill && $("#location-address").value === (locationPrefill.address || "")) $("#location-address").value = "";
    locationPrefill = null;
    status.textContent = `Ubicación encontrada (precisión: ±${Math.round(accuracy)} m).`;
    updateLocationMap();
  }, (err) => {
    status.textContent = err.code === err.PERMISSION_DENIED
      ? "Sin permiso para ver tu ubicación: actívalo en el candado de la barra de direcciones."
      : "No se ha podido obtener tu ubicación: escribe las coordenadas.";
  }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
}

async function sendLocation(e) {
  e.preventDefault();
  const error = $("#location-error");
  const coords = parseCoords($("#location-coords").value);
  if (!coords) {
    return showFormError(error, "Escribe las coordenadas (p. ej. 40.4168, -3.7038), pega un enlace de Google Maps o usa tu ubicación actual.");
  }
  const body = { ...coords, name: $("#location-name").value.trim(), address: $("#location-address").value.trim() };
  showFormError(error, "");
  try {
    await sendFromComposer("send-location", body, $("#location-submit"));
  } catch (err) {
    return showFormError(error, err.message);
  }
  try {
    localStorage.setItem(LAST_LOCATION_KEY, JSON.stringify(body));
  } catch {
    /* sin almacenamiento: la próxima vez no se rellena */
  }
  $("#location-dialog").close();
}

/* ---------- Enviar un contacto ---------- */

let contactMatches = [];
let contactSearchTimer = null;

// Los teléfonos de WhatsApp se guardan sin el «+»: en la tarjeta van con él.
function displayPhone(phone) {
  return /^\d{10,15}$/.test(phone) ? `+${phone}` : phone;
}

function openContactDialog() {
  toggleAttachMenu(false);
  $("#contact-form").reset();
  $("#contact-results").hidden = true;
  contactMatches = [];
  showFormError($("#contact-error"), "");
  $("#contact-dialog").showModal();
  $("#contact-search").focus();
}

async function searchContacts() {
  const q = $("#contact-search").value.trim();
  const list = $("#contact-results");
  if (q.length < 2) {
    list.hidden = true;
    return;
  }
  let found;
  try {
    found = await api(`/api/contacts?${new URLSearchParams({ q })}`);
  } catch {
    return;
  }
  if ($("#contact-search").value.trim() !== q) return;
  contactMatches = found.filter((c) => c.phones?.length).slice(0, 6);
  list.innerHTML = contactMatches.length ? contactMatches.map((c, i) => `<li><button type="button" role="option" data-pick-contact="${i}">
      <span class="chat-avatar contact-card-avatar ${avatarClass(c.name)}" aria-hidden="true">${escapeHtml(initialsOf(c.name))}</span>
      <span class="contact-result-body"><strong>${escapeHtml(c.name)}</strong>
        <span class="muted small">${escapeHtml(displayPhone(c.phones[0]))}${c.emails?.[0] ? ` · ${escapeHtml(c.emails[0])}` : ""}</span></span>
    </button></li>`).join("")
    : `<li class="muted small contact-none">Ningún contacto con teléfono se llama así.</li>`;
  list.hidden = false;
}

function pickContact(i) {
  const c = contactMatches[i];
  if (!c) return;
  $("#contact-name").value = c.name;
  $("#contact-phone").value = displayPhone(c.phones[0]);
  $("#contact-email").value = c.emails?.[0] || "";
  $("#contact-results").hidden = true;
  $("#contact-submit").focus();
}

async function sendContact(e) {
  e.preventDefault();
  const error = $("#contact-error");
  const body = { name: $("#contact-name").value.trim(), phone: $("#contact-phone").value.trim(), email: $("#contact-email").value.trim() };
  if (!body.name) return showFormError(error, "Escribe el nombre del contacto (o búscalo en Contactos).");
  if (body.phone.replace(/\D/g, "").length < 6) return showFormError(error, "Escribe un teléfono válido, con prefijo si es de otro país.");
  if (body.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email)) return showFormError(error, "Ese email no parece válido.");
  showFormError(error, "");
  try {
    await sendFromComposer("send-contact", body, $("#contact-submit"));
  } catch (err) {
    return showFormError(error, err.message);
  }
  $("#contact-dialog").close();
}

/* ---------- Eventos ---------- */

function bindChatCompose() {
  $("#chat-attach").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleAttachMenu();
  });
  $("#chat-file").addEventListener("change", () => toggleAttachMenu(false));
  $("#attach-location").addEventListener("click", openLocationDialog);
  $("#attach-contact").addEventListener("click", openContactDialog);
  document.addEventListener("click", (e) => { if (!e.target.closest(".attach-wrap")) toggleAttachMenu(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleAttachMenu(false); });

  $("#chat-text").addEventListener("paste", onComposerPaste);
  bindDropZone();

  $("#chat-voice").addEventListener("click", startVoice);
  $("#voice-send").addEventListener("click", () => finishVoice(true));
  $("#voice-cancel").addEventListener("click", () => finishVoice(false));

  $("#location-here").addEventListener("click", locateMe);
  $("#location-coords").addEventListener("input", updateLocationMap);
  $("#location-form").addEventListener("submit", sendLocation);

  $("#contact-search").addEventListener("input", () => {
    clearTimeout(contactSearchTimer);
    contactSearchTimer = setTimeout(searchContacts, 250);
  });
  $("#contact-results").addEventListener("click", (e) => {
    const b = e.target.closest("[data-pick-contact]");
    if (b) pickContact(Number(b.dataset.pickContact));
  });
  $("#contact-form").addEventListener("submit", sendContact);
}
