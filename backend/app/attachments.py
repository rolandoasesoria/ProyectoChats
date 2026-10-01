"""Adjuntos y documentos: guardar archivos, extraer su texto, leerlos con IA y buscarlos."""
import base64
import io
import mimetypes
import re
import uuid

from fastapi import HTTPException

from . import agent
from .config import config
from .db import TS_CONFIG, get_conn, rows

STORAGE = config.data_dir / "attachments"
MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 100_000          # texto extraído que se guarda por archivo
AI_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
AI_IMAGE_MAX_BYTES = 5 * 1024 * 1024   # límite de la API de Claude por imagen
FIELDS = """a.id, a.client_id, a.message_id, a.filename, a.mime, a.size, a.extracted_by,
            length(a.extracted_text) AS text_length, a.created_at, u.name AS uploaded_by"""


def _guess_mime(filename: str, mime: str | None) -> str:
    if mime and mime != "application/octet-stream":
        return mime
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _safe_name(filename: str) -> str:
    name = re.sub(r"[^\w.\- ]", "_", filename).strip() or "archivo"
    return name[-120:]


def extract_text(data: bytes, mime: str) -> tuple[str | None, str | None]:
    """Texto legible sin IA: PDFs con capa de texto y archivos de texto. (texto, método) o (None, None)."""
    if mime == "application/pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception:  # noqa: BLE001 - PDF dañado o cifrado: se podrá leer con IA
            return None, None
        # Un PDF escaneado no tiene texto: se deja para leerlo con IA.
        return (text[:MAX_TEXT], "pdf") if len(text) > 20 else (None, None)
    if mime.startswith("text/") or mime in ("application/json", "text/csv"):
        return data.decode("utf-8", errors="replace")[:MAX_TEXT], "text"
    return None, None


def save(conn, client_id: int, filename: str, data: bytes, mime: str | None = None,
         message_id: int | None = None, uploaded_by: int | None = None) -> int:
    """Guarda el archivo en disco y su fila (usa la conexión de quien llama, dentro de su transacción)."""
    if len(data) > MAX_BYTES:
        raise HTTPException(400, f"«{filename}» supera el máximo de 20 MB.")
    mime = _guess_mime(filename, mime)
    STORAGE.mkdir(parents=True, exist_ok=True)
    path = STORAGE / f"{uuid.uuid4().hex}_{_safe_name(filename)}"
    path.write_bytes(data)
    text, method = extract_text(data, mime)
    return conn.execute(
        """INSERT INTO attachments (client_id, message_id, filename, mime, size, path, extracted_text,
                                    extracted_by, uploaded_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           RETURNING id""",
        (client_id, message_id, filename, mime, len(data), path.name, text, method, uploaded_by)).lastrowid


def get(attachment_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(f"""SELECT {FIELDS}, a.path, a.extracted_text FROM attachments a
                               LEFT JOIN users u ON u.id = a.uploaded_by WHERE a.id = ?""", (attachment_id,)).fetchone()
    return dict(row) if row else None


def file_path(att: dict):
    return STORAGE / att["path"]


def list_for_client(client_id: int) -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute(
            f"""SELECT {FIELDS}, m.sent_at AS message_sent_at, c.channel
                  FROM attachments a LEFT JOIN users u ON u.id = a.uploaded_by
                  LEFT JOIN messages m ON m.id = a.message_id
                  LEFT JOIN conversations c ON c.id = m.conversation_id
                 WHERE a.client_id = ? ORDER BY coalesce(m.sent_at, a.created_at) DESC""", (client_id,)))


def by_message(message_ids: list[int]) -> dict[int, list[dict]]:
    if not message_ids:
        return {}
    marks = ",".join("?" * len(message_ids))
    with get_conn() as conn:
        found = rows(conn.execute(
            f"SELECT id, message_id, filename, mime, size FROM attachments WHERE message_id IN ({marks})", message_ids))
    result: dict[int, list[dict]] = {}
    for a in found:
        result.setdefault(a["message_id"], []).append(a)
    return result


def delete(attachment_id: int) -> None:
    att = get(attachment_id)
    if not att:
        raise HTTPException(404, "Documento no encontrado")
    with get_conn() as conn:
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    file_path(att).unlink(missing_ok=True)


def delete_files_for_client(client_id: int) -> None:
    """Antes de borrar un cliente: sus archivos en disco (las filas se borran en cascada)."""
    with get_conn() as conn:
        paths = [r["path"] for r in conn.execute("SELECT path FROM attachments WHERE client_id = ?", (client_id,))]
    for p in paths:
        (STORAGE / p).unlink(missing_ok=True)


def read_with_ai(attachment_id: int) -> dict:
    """Lee una imagen o un PDF (también escaneado) con Claude y guarda el texto para poder buscarlo."""
    att = get(attachment_id)
    if not att:
        raise HTTPException(404, "Documento no encontrado")
    data = file_path(att).read_bytes()
    b64 = base64.standard_b64encode(data).decode()
    if att["mime"] in AI_IMAGE_TYPES:
        if len(data) > AI_IMAGE_MAX_BYTES:
            raise HTTPException(400, "La imagen supera los 5 MB que admite la IA.")
        block = {"type": "image", "source": {"type": "base64", "media_type": att["mime"], "data": b64}}
    elif att["mime"] == "application/pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    else:
        raise HTTPException(400, "La IA solo puede leer imágenes (PNG, JPG, GIF, WEBP) y PDF.")
    response = agent._create(
        system="Extraes el contenido de documentos e imágenes que los clientes envían a una empresa, para poder "
               "buscarlo después. Transcribe todo el texto legible tal cual (importes, fechas, referencias, "
               "direcciones). Si es una foto sin texto relevante, descríbela en 1-2 frases (qué es, estado, "
               "detalles útiles). Responde solo con el contenido, en el idioma del documento, sin comentarios.",
        messages=[{"role": "user", "content": [block, {"type": "text", "text": f"Archivo: {att['filename']}"}]}],
        output_config={"effort": "low"},
    )
    if response.stop_reason == "refusal":
        raise HTTPException(400, "La IA no ha podido leer este archivo.")
    text = "\n".join(b.text for b in response.content if b.type == "text").strip()[:MAX_TEXT]
    with get_conn() as conn:
        conn.execute("UPDATE attachments SET extracted_text = ?, extracted_by = 'ai' WHERE id = ?", (text, attachment_id))
    return get(attachment_id)


def search(query_fts: str, user_id: int, scope: str, client_id: int | None = None, limit: int = 15) -> list[dict]:
    """Busca en el nombre y el contenido de los documentos. Los adjuntos de mensajes respetan el alcance
    (solo conversaciones propias con 'mine'); los documentos subidos a la ficha son del equipo."""
    sql = f"""SELECT a.id AS documento_id, a.filename, a.client_id, cl.name AS client, a.extracted_by,
                    ts_headline('{TS_CONFIG}', coalesce(a.extracted_text, a.filename), q, 'StartSel=⟦, StopSel=⟧, MaxWords=35, MinWords=12, ShortWord=2, MaxFragments=2, FragmentDelimiter=" … "') AS snippet,
                    coalesce(m.sent_at, a.created_at) AS fecha, c.channel, u.name AS owner
               FROM attachments a
               CROSS JOIN to_tsquery('{TS_CONFIG}', ?) AS q
               JOIN clients cl ON cl.id = a.client_id
               LEFT JOIN messages m ON m.id = a.message_id
               LEFT JOIN conversations c ON c.id = m.conversation_id
               LEFT JOIN users u ON u.id = c.owner_user_id
              WHERE a.tsv @@ q"""
    args: list = [query_fts]
    if scope == "mine":
        sql += " AND (a.message_id IS NULL OR c.owner_user_id = ?)"
        args.append(user_id)
    if client_id:
        sql += " AND a.client_id = ?"
        args.append(client_id)
    sql += " ORDER BY ts_rank(a.tsv, q) DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        found = rows(conn.execute(sql, args))
    for f in found:
        f["snippet"] = (f["snippet"] or "").replace("⟦", "[").replace("⟧", "]")
    return found


def texts_for_client(client_id: int, max_chars: int = 3000) -> list[dict]:
    """Contenido de los documentos del cliente para el análisis con IA (recortado)."""
    with get_conn() as conn:
        found = rows(conn.execute(
            """SELECT a.filename, a.message_id, substr(a.extracted_text, 1, ?) AS text FROM attachments a
                WHERE a.client_id = ? AND a.extracted_text IS NOT NULL ORDER BY a.id DESC LIMIT 20""",
            (max_chars, client_id)))
    return found
