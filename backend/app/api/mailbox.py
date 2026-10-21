"""Correo en bandejas: Recibidos, Enviados y Destacados, el correo abierto con su hilo y «marcar todo como leído».
Responder y escribir un correo nuevo usan las rutas de siempre (/api/conversations/{id}/send y /api/clients/{id}/emails)."""
from typing import Literal

from fastapi import APIRouter, Query

from .. import mailbox
from .deps import CurrentUser

router = APIRouter()


@router.get("/api/mail")
def mail_folder(user: CurrentUser, folder: Literal["inbox", "sent", "starred"] = "inbox",
                scope: Literal["mine", "team"] = "mine", q: str = Query("", max_length=200),
                client_id: int | None = None, offset: int = Query(0, ge=0)):
    return mailbox.folder(user, folder, scope, q, client_id, offset)


@router.get("/api/mail/{message_id}")
def open_mail(message_id: int, user: CurrentUser):
    return mailbox.open_email(user, message_id)


@router.post("/api/mail/read-all")
def read_all(user: CurrentUser, scope: Literal["mine", "team"] = "mine"):
    return {"marked": mailbox.read_all(user, scope)}
