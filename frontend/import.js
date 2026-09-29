// Importar exportaciones de WhatsApp, Telegram y email: elegir archivo → revisar → resultado.

const CHANNEL_LABELS = { whatsapp: "WhatsApp", telegram: "Telegram", email: "Email" };
const HANDLE_HINTS = {
  whatsapp: "Teléfono del cliente, p. ej. +34600111222",
  telegram: "@usuario del cliente",
  email: "Email del cliente",
};

const importState = { file: null, data: null, preview: null, resultClientId: null };

function importStep(step) {
  $("#import-step-file").hidden = step !== "file";
  $("#import-step-review").hidden = step !== "review";
  $("#import-step-done").hidden = step !== "done";
}

function openImportDialog() {
  Object.assign(importState, { file: null, data: null, preview: null, resultClientId: null });
  $("#import-file").value = "";
  showError($("#import-error"), "");
  importStep("file");
  $("#import-dialog").showModal();
}

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("No se pudo leer el archivo."));
    reader.readAsDataURL(file);
  });
}

function formatDay(iso) {
  return new Date(iso).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" });
}

async function handleImportFile(file) {
  if (!file) return;
  showError($("#import-error"), "");
  const maxMb = file.name.toLowerCase().endsWith(".zip") ? 50 : 25;
  if (file.size > maxMb * 1024 * 1024) {
    showError($("#import-error"), `El archivo es demasiado grande (máximo ${maxMb} MB).`);
    return;
  }
  $("#dropzone").classList.add("loading");
  try {
    importState.file = file;
    importState.data = await readAsBase64(file);
    importState.preview = await api("/api/import/preview", {
      method: "POST", body: JSON.stringify({ filename: file.name, data: importState.data }),
    });
    await renderImportReview();
    importStep("review");
  } catch (err) {
    showError($("#import-error"), err.message);
  } finally {
    $("#dropzone").classList.remove("loading");
  }
}

// Sugerencia: el participante que no es el usuario actual y que más escribe (o que ya es cliente).
function suggestedParticipant(p) {
  const me = [currentUser.name, currentUser.email, currentUser.username].filter(Boolean).map((s) => s.toLowerCase());
  const others = p.participants.filter((x) => !me.includes(x.key.toLowerCase()) && !me.includes(x.name.toLowerCase()));
  return others.find((x) => x.client) || others.find((x) => p.title && x.name === p.title) || others[0] || p.participants[0];
}

async function renderImportReview() {
  const p = importState.preview;
  $("#import-summary").innerHTML =
    `${badge(p.channel)} <strong>${escapeHtml(importState.file.name)}</strong> · ${p.total} mensajes · ` +
    `del ${formatDay(p.first)} al ${formatDay(p.last)}`;

  const suggested = suggestedParticipant(p);
  // En email puede haber cientos de direcciones: se muestran las 15 más frecuentes.
  $("#import-participants").innerHTML = p.participants.slice(0, 15).map((x) => `
    <label class="participant">
      <input type="radio" name="import-participant" value="${escapeHtml(x.key)}" ${x.key === suggested.key ? "checked" : ""}>
      <span><strong>${escapeHtml(x.name)}</strong>${x.name !== x.key ? ` <span class="muted">${escapeHtml(x.key)}</span>` : ""}</span>
      <span class="muted">${x.count} mensaje${x.count === 1 ? "" : "s"}</span>
      ${x.client ? `<span class="tag">ya es cliente: ${escapeHtml(x.client.name)}</span>` : ""}
    </label>`).join("");

  const clients = await api("/api/clients");
  $("#import-client").innerHTML = `<option value="">➕ Cliente nuevo</option>` +
    clients.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
  $("#import-handle").placeholder = HANDLE_HINTS[p.channel] || "";
  $("#import-handle-label").hidden = p.channel === "email"; // en email el identificador es la propia dirección
  onParticipantChange();
}

function selectedParticipant() {
  const key = document.querySelector('input[name="import-participant"]:checked')?.value;
  return importState.preview.participants.find((x) => x.key === key);
}

function onParticipantChange() {
  const part = selectedParticipant();
  if (!part) return;
  $("#import-client").value = part.client ? String(part.client.id) : "";
  $("#import-name").value = part.name;
  $("#import-handle").value = "";
  onImportClientChange();
}

function onImportClientChange() {
  const isNew = !$("#import-client").value;
  $("#import-name-label").hidden = !isNew;
  $("#import-name").required = isNew;
}

async function submitImport(e) {
  e.preventDefault();
  const part = selectedParticipant();
  if (!part) return;
  showError($("#import-error2"), "");
  $("#import-submit").disabled = true;
  try {
    const clientId = $("#import-client").value;
    const res = await api("/api/import/file", {
      method: "POST",
      body: JSON.stringify({
        filename: importState.file.name, data: importState.data, client_key: part.key,
        client_id: clientId ? Number(clientId) : null,
        client_name: $("#import-name").value.trim() || null,
        handle: $("#import-handle").value.trim() || null,
      }),
    });
    importState.resultClientId = res.client_id;
    importState.analysisStarted = res.analysis_started;
    importState.importedAt = res.imported_at;
    $("#import-result").innerHTML = res.messages
      ? `✅ Importados <strong>${res.messages}</strong> mensajes en ${res.conversations} conversación${res.conversations === 1 ? "" : "es"}` +
        (res.attachments ? ` y ${res.attachments} archivo${res.attachments === 1 ? "" : "s"} adjunto${res.attachments === 1 ? "" : "s"}` : "") +
        (res.duplicates ? ` <span class="muted">(${res.duplicates} ya estaban y se han omitido)</span>` : "") + "."
      : `No había mensajes nuevos: los ${res.duplicates} mensajes ya estaban importados.`;
    importStep("done");
    await loadClients($("#client-search").value);
    refreshInboxCount();
  } catch (err) {
    showError($("#import-error2"), err.message);
  } finally {
    $("#import-submit").disabled = false;
  }
}

function bindImportEvents() {
  $("#import-btn").addEventListener("click", openImportDialog);
  $("#import-file").addEventListener("change", (e) => handleImportFile(e.target.files[0]));
  const zone = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault();
    zone.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, () => zone.classList.remove("over")));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    handleImportFile(e.dataTransfer.files[0]);
  });
  $("#import-participants").addEventListener("change", onParticipantChange);
  $("#import-client").addEventListener("change", onImportClientChange);
  $("#import-step-review").addEventListener("submit", submitImport);
  $("#import-back").addEventListener("click", () => { $("#import-file").value = ""; importStep("file"); });
  $("#import-another").addEventListener("click", openImportDialog);
  $("#import-open").addEventListener("click", async () => {
    $("#import-dialog").close();
    const clientId = importState.resultClientId;
    if (!clientId) return;
    await selectClient(clientId);
    if (importState.analysisStarted) {
      showDetailTab("profile");
      watchBackgroundAnalysis(clientId, importState.importedAt);
    }
  });
}
