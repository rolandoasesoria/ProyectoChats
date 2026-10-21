// Chat al estilo de WhatsApp: responder citando un mensaje, reaccionar con un emoji, el selector de emojis de la caja
// de escribir, el visor de fotos y saltar al mensaje citado. Cómo se pinta cada mensaje está en app.js (timelineHtml).

const QUICK_REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"];
const EMOJIS = ("😀 😃 😄 😁 😊 🙂 😉 😍 🥰 😘 😎 🤗 🤔 😅 😂 🤣 😇 🙃 😌 😴 😮 😯 😢 😭 😤 😡 🥳 🤩 🙄 😬 "
  + "👍 👎 👏 🙌 👌 ✌️ 🤞 🤝 💪 👋 ✋ 🙏 👀 ❤️ 🧡 💛 💚 💙 💜 🤍 🔥 ✨ ⭐ 🎉 🎁 🎂 ✅ ☑️ ❌ ⚠️ ❗ ❓ "
  + "📌 📎 📄 📝 📅 ⏰ 📞 📧 💬 🏠 🏢 🚚 📦 💶 💳 🛒 🔑 🔒").split(" ");

function firstLine(text) {
  return (text || "").split("\n").find((line) => line.trim()) || "";
}

// Coloca un menú flotante encima de `anchor` (o debajo si no cabe), dentro de la ventana.
function placeNear(el, anchor) {
  const r = anchor.getBoundingClientRect();
  const left = Math.min(Math.max(8, r.left + r.width / 2 - el.offsetWidth / 2), window.innerWidth - el.offsetWidth - 8);
  const top = r.top - el.offsetHeight - 8 >= 8 ? r.top - el.offsetHeight - 8 : r.bottom + 8;
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

function insertAtCursor(textarea, text) {
  const { selectionStart: start, selectionEnd: end, value } = textarea;
  textarea.value = value.slice(0, start) + text + value.slice(end);
  textarea.selectionStart = textarea.selectionEnd = start + text.length;
  textarea.focus();
  textarea.dispatchEvent(new Event("input", { bubbles: true })); // ajusta la altura y avisa de que estás escribiendo
}

/* ---------- Responder citando ---------- */

// Se cita un mensaje de la conversación por la que se responde; si es de otro canal tuyo, se pasa a ese canal.
async function startReply(id, retried = false) {
  const m = chatState.messagesById?.get(id);
  if (!m) return;
  if (m.conversation_id !== chatState.conversationId) {
    if (retried || m.channel === chatState.channel) return alert("Desde aquí no se puede responder en esa conversación.");
    chatState.channel = m.channel;
    setActiveChannelTab($("#chat-tabs"), m.channel);
    await loadChatConversation();
    return startReply(id, true);
  }
  chatState.replyTo = { id: m.id, conversationId: m.conversation_id };
  $("#chat-reply-sender").textContent = m.direction === "out" ? `${m.sender} · equipo` : m.sender;
  $("#chat-reply-text").textContent = firstLine(m.body) || "📎 Archivo";
  $("#chat-reply").hidden = false;
  $("#chat-text").focus();
}

function clearReply() {
  chatState.replyTo = null;
  $("#chat-reply").hidden = true;
}

// Ir al mensaje citado: si está en la conversación que se ve, se resalta; si no, se busca en todo el historial.
function jumpToMessage(id) {
  const li = document.querySelector(`#chat-timeline li[data-id="${id}"]`);
  if (!li) return showSourceMessage(id);
  li.scrollIntoView({ block: "center", behavior: "smooth" });
  li.classList.remove("flash");
  void li.offsetWidth; // reinicia la animación si ya estaba resaltado
  li.classList.add("flash");
  setTimeout(() => li.classList.remove("flash"), 2500);
}

/* ---------- Reacciones ---------- */

let reactTarget = null; // mensaje al que se reacciona
let reactAnchor = null; // botón desde el que se abrió (para el selector de emojis)

function openReactTray(button, id) {
  const tray = $("#react-tray");
  const team = chatState.messagesById?.get(id)?.reactions?.find((r) => r.side === "team");
  reactTarget = id;
  reactAnchor = button;
  tray.querySelectorAll("[data-emoji]:not([data-emoji-remove])").forEach((b) =>
    b.classList.toggle("selected", b.dataset.emoji === team?.emoji));
  tray.querySelector("[data-emoji-remove]").hidden = !team;
  tray.hidden = false;
  placeNear(tray, button);
}

function closeReactTray(keepTarget = false) {
  $("#react-tray").hidden = true;
  if (!keepTarget) reactTarget = null;
}

async function sendReaction(emoji) {
  const id = reactTarget;
  closeReactTray();
  if (!id) return;
  try {
    await api(`/api/messages/${id}/reaction`, { method: "POST", body: JSON.stringify({ emoji }) });
    await loadChatConversation(true);
  } catch (err) {
    alert(err.message);
  }
}

/* ---------- Selector de emojis (en la caja de escribir o para reaccionar) ---------- */

let emojiMode = "compose";

function openEmojiPicker(anchor, mode) {
  emojiMode = mode;
  const picker = $("#emoji-picker");
  picker.hidden = false;
  placeNear(picker, anchor);
}

function closeEmojiPicker() {
  $("#emoji-picker").hidden = true;
}

function pickEmoji(emoji) {
  closeEmojiPicker();
  if (emojiMode === "react") return sendReaction(emoji);
  insertAtCursor($("#chat-text"), emoji);
}

/* ---------- Visor de fotos ---------- */

function openMediaViewer(url, name) {
  $("#media-viewer-img").src = url;
  $("#media-viewer-img").alt = name;
  $("#media-viewer-name").textContent = name;
  $("#media-viewer-download").href = `${url}?download=true`;
  $("#media-viewer").showModal();
}

/* ---------- Eventos ---------- */

function bindChatActions() {
  $("#react-tray").insertAdjacentHTML("afterbegin", QUICK_REACTIONS.map((e) =>
    `<button type="button" data-emoji="${e}" aria-label="Reaccionar con ${e}">${e}</button>`).join(""));
  $("#emoji-grid").innerHTML = EMOJIS.map((e) => `<button type="button" data-pick="${e}" aria-label="${e}">${e}</button>`).join("");

  $("#chat-timeline").addEventListener("click", (e) => {
    const jump = e.target.closest("[data-jump]");
    const media = e.target.closest("[data-viewer]");
    const quote = e.target.closest("[data-quote-reply]");
    const react = e.target.closest("[data-react]");
    if (jump) jumpToMessage(Number(jump.dataset.jump));
    else if (media) openMediaViewer(media.dataset.viewer, media.dataset.name);
    else if (quote) startReply(Number(quote.dataset.quoteReply));
    else if (react) {
      e.stopPropagation();
      if (!$("#react-tray").hidden && reactTarget === Number(react.dataset.react)) closeReactTray();
      else openReactTray(react, Number(react.dataset.react));
    }
  });
  $("#chat-timeline").addEventListener("scroll", () => closeReactTray(), { passive: true });
  $("#react-tray").addEventListener("click", (e) => {
    if (e.target.closest("[data-emoji-more]")) {
      e.stopPropagation();
      closeReactTray(true);
      return openEmojiPicker(reactAnchor, "react");
    }
    const b = e.target.closest("[data-emoji]");
    if (b) sendReaction(b.dataset.emoji);
  });
  $("#chat-emoji").addEventListener("click", (e) => {
    e.stopPropagation();
    if ($("#emoji-picker").hidden) openEmojiPicker(e.currentTarget, "compose");
    else closeEmojiPicker();
  });
  $("#emoji-grid").addEventListener("click", (e) => {
    const b = e.target.closest("[data-pick]");
    if (b) pickEmoji(b.dataset.pick);
  });
  $("#chat-reply-cancel").addEventListener("click", clearReply);
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#react-tray")) closeReactTray();
    if (!e.target.closest("#emoji-picker")) closeEmojiPicker();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeReactTray();
      closeEmojiPicker();
    }
  });
}
