"""Documentos y adjuntos."""
import base64
import binascii

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import attachments
from ..db import get_conn
from ..errors import Forbidden, InvalidInput, NotFound
from .deps import CurrentUser, claude_errors, client_or_404

router = APIRouter()


class FileUpload(BaseModel):
    filename: str = Field(max_length=255)
    data: str  # contenido del archivo en base64


@router.get("/api/clients/{client_id}/documents")
def list_documents(client_id: int, _: CurrentUser):
    client_or_404(client_id)
    return attachments.list_for_client(client_id)


@router.post("/api/clients/{client_id}/documents")
def upload_document(client_id: int, req: FileUpload, user: CurrentUser):
    """Sube un documento a la ficha del cliente (presupuesto firmado, factura, foto...)."""
    client_or_404(client_id)
    try:
        data = base64.b64decode(req.data, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidInput("No se pudo leer el archivo.")
    with get_conn() as conn:
        att_id = attachments.save(conn, client_id, req.filename, data, uploaded_by=user["id"])
    return attachments.get(att_id) | {"path": None, "extracted_text": None}


def _attachment_or_404(attachment_id: int) -> dict:
    att = attachments.get(attachment_id)
    if not att:
        raise NotFound("Documento no encontrado")
    return att


@router.get("/api/attachments/{attachment_id}/file")
def attachment_file(attachment_id: int, _: CurrentUser, download: bool = False):
    att = _attachment_or_404(attachment_id)
    path = attachments.file_path(att)
    if not path.exists():
        raise NotFound("El archivo ya no está en el servidor.")
    # Imágenes y PDF se abren en el navegador; el resto se descarga. Nunca se sirve HTML "en línea".
    inline = not download and (att["mime"] in attachments.AI_IMAGE_TYPES or att["mime"] == "application/pdf")
    return FileResponse(path, media_type=att["mime"], filename=att["filename"],
                        content_disposition_type="inline" if inline else "attachment")


@router.get("/api/attachments/{attachment_id}/text")
def attachment_text(attachment_id: int, _: CurrentUser):
    att = _attachment_or_404(attachment_id)
    return {"filename": att["filename"], "extracted_by": att["extracted_by"], "text": att["extracted_text"]}


@router.post("/api/attachments/{attachment_id}/read")
def read_attachment(attachment_id: int, _: CurrentUser):
    """Lee una imagen o PDF con IA y guarda el texto para buscarlo."""
    _attachment_or_404(attachment_id)
    with claude_errors():
        att = attachments.read_with_ai(attachment_id)
    return att | {"path": None}


@router.delete("/api/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, user: CurrentUser):
    with get_conn() as conn:
        row = conn.execute("SELECT uploaded_by, message_id FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not row:
        raise NotFound("Documento no encontrado")
    if row["uploaded_by"] != user["id"] and user["role"] != "admin":
        raise Forbidden("Solo quien lo subió (o un administrador) puede borrarlo.")
    attachments.delete(attachment_id)
    return {"ok": True}
