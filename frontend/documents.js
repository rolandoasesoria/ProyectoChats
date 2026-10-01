// Documentos y adjuntos: lista en la ficha, subida, lectura con IA, ver texto y borrar; adjuntos en los mensajes.

const AI_READABLE = ["application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"];

function fileIcon(mime) {
  if (mime === "application/pdf") return "PDF";
  if (mime.startsWith("image/")) return "IMG";
  return "DOC";
}

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("No se pudo leer el archivo."));
    reader.readAsDataURL(file);
  });
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
}

function attachmentUrl(id, download = false) {
  return `/api/attachments/${id}/file${download ? "?download=true" : ""}`;
}

// Chips de adjuntos bajo un mensaje de la línea de tiempo.
function attachmentChips(list) {
  if (!list || !list.length) return "";
  return `<div class="att-chips">${list.map((a) =>
    `<a class="att-chip" href="${attachmentUrl(a.id)}" target="_blank" rel="noopener" title="${escapeHtml(a.filename)} · ${formatSize(a.size)}">${escapeHtml(a.filename)}</a>`).join("")}</div>`;
}

async function loadDocuments(clientId) {
  const docs = await api(`/api/clients/${clientId}/documents`);
  if (state.clientId !== clientId) return;
  $("#documents").innerHTML = docs.length ? docs.map((d) => {
    const when = d.message_sent_at ? formatDate(d.message_sent_at) : timeAgo(d.created_at);
    const origin = d.message_id ? `adjunto de ${IDENTITY_LABELS[d.channel] || d.channel}` : `subido por ${escapeHtml(d.uploaded_by || "—")}`;
    const canRead = AI_READABLE.includes(d.mime);
    const textState = d.text_length
      ? `<button class="link small" data-show-text title="${d.extracted_by === "ai" ? "Leído con IA" : "Texto del documento"}">${d.extracted_by === "ai" ? "✨ " : ""}Ver texto</button>`
      : canRead ? `<button class="link small" data-read-ai title="La IA lo lee (también fotos y PDF escaneados) para poder buscar en él">✨ Leer con IA</button>` : "";
    const canDelete = !d.message_id && (d.uploaded_by === currentUser.name || currentUser.role === "admin");
    return `
      <li class="document" data-doc="${d.id}">
        <span class="doc-icon">${fileIcon(d.mime)}</span>
        <div class="doc-body">
          <a href="${attachmentUrl(d.id)}" target="_blank" rel="noopener" class="doc-name">${escapeHtml(d.filename)}</a>
          <span class="doc-meta">${formatSize(d.size)} · ${when} · ${origin} ${textState}</span>
          <pre class="doc-text" hidden></pre>
        </div>
        <a class="icon-link" href="${attachmentUrl(d.id, true)}" title="Descargar">⤓</a>
        ${canDelete ? `<button class="icon-link" data-delete-doc title="Borrar">×</button>` : ""}
      </li>`;
  }).join("") : `<li class="muted small">Sin documentos. Los adjuntos que lleguen por correo, WhatsApp o Telegram aparecerán aquí.</li>`;
}

async function onDocumentsClick(e) {
  const li = e.target.closest("li[data-doc]");
  if (!li) return;
  const id = li.dataset.doc;
  try {
    if (e.target.closest("[data-read-ai]")) {
      const btn = e.target.closest("[data-read-ai]");
      btn.disabled = true;
      btn.textContent = "✨ Leyendo…";
      await api(`/api/attachments/${id}/read`, { method: "POST" });
      await loadDocuments(state.clientId);
      // La lista se ha vuelto a dibujar: se busca el elemento nuevo para mostrar el texto leído.
      document.querySelector(`#documents li[data-doc="${id}"] [data-show-text]`)?.click();
    } else if (e.target.closest("[data-show-text]")) {
      const pre = li.querySelector(".doc-text");
      if (pre.hidden) pre.textContent = (await api(`/api/attachments/${id}/text`)).text || "";
      pre.hidden = !pre.hidden;
    } else if (e.target.closest("[data-delete-doc]")) {
      if (!confirm("¿Borrar este documento?")) return;
      await api(`/api/attachments/${id}`, { method: "DELETE" });
      await loadDocuments(state.clientId);
    }
  } catch (err) {
    alert(err.message);
    loadDocuments(state.clientId);
  }
}

async function uploadDocument(file) {
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) {
    alert("El archivo supera el máximo de 20 MB.");
    return;
  }
  const clientId = state.clientId;
  try {
    const data = await readAsBase64(file);
    await api(`/api/clients/${clientId}/documents`, { method: "POST", body: JSON.stringify({ filename: file.name, data }) });
    await loadDocuments(clientId);
  } catch (err) {
    alert(err.message);
  } finally {
    $("#doc-upload").value = "";
  }
}

function bindDocumentEvents() {
  $("#documents").addEventListener("click", onDocumentsClick);
  $("#doc-upload").addEventListener("change", (e) => uploadDocument(e.target.files[0]));
}
