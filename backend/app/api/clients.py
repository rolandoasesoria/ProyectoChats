"""Clientes: datos, etiquetas, identificadores, duplicados, visitas y mensajes."""
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import audit, auth, clients, contacts, insights, message_actions, search
from ..errors import Forbidden, NotFound
from .deps import CurrentUser, client_or_404

router = APIRouter()


@router.get("/api/clients")
def list_clients(user: CurrentUser, q: str = "", status: Literal["lead", "active", "issue", "inactive"] | None = None,
                 tag: str | None = None, mine: bool = False):
    # La lista de la interfaz muestra hasta 500 clientes (el buscador y los filtros acotan el resto).
    return search.find_clients(q, limit=500, user_id=user["id"], status=status, tag=tag or None,
                               assignee_id=user["id"] if mine else None)


@router.get("/api/chats")
def list_chats(user: CurrentUser, q: str = "", scope: Literal["mine", "team"] = "mine", unread: bool = False):
    """Sección Chats: un elemento por cliente con su último mensaje y los no leídos."""
    if scope == "team":
        if not auth.can_view_team_chats(user):
            raise Forbidden("Para ver los chats de todo el equipo hace falta que un administrador te dé permiso.")
        audit.log(user["id"], "team_chats", throttle=True)
    return search.chat_list(user["id"], scope, q, unread)


@router.get("/api/contacts")
def list_contacts(user: CurrentUser, q: str = "", status: Literal["lead", "active", "issue", "inactive"] | None = None,
                  tag: str | None = None, assignee: int | None = None,
                  channel: Literal["email", "whatsapp", "telegram", "phone"] | None = None, unread: bool = False,
                  sort: Literal["name", "company", "activity", "status", "agent", "created", "unread"] = "name",
                  order: Literal["asc", "desc"] | None = None):
    """Sección Contactos: la tabla con datos de contacto, etiquetas, responsable, actividad y propiedades, ordenada
    por nombre (o como se pida)."""
    return contacts.list_contacts(user["id"], q, status, tag or None, assignee, channel, unread, sort=sort,
                                  direction=order)


class NewClient(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(None, max_length=200)


@router.post("/api/clients")
def create_client(req: NewClient, user: CurrentUser):
    """Cliente creado a mano (p. ej. tras una llamada). Queda asignado a quien lo crea."""
    return {"id": clients.create_client(req.name, req.company, user["id"])}


class ClientUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    company: str | None = Field(None, max_length=200)
    status: Literal["lead", "active", "issue", "inactive"] | None = None
    status_auto: bool | None = None  # true: que el estado lo vuelva a decidir la IA
    assignee_user_id: int | None = None


@router.patch("/api/clients/{client_id}")
def update_client(client_id: int, req: ClientUpdate, user: CurrentUser):
    clients.edit(client_id, {k: getattr(req, k) for k in req.model_fields_set}, user)
    return search.client_overview(client_id, user["id"])


class TagsIn(BaseModel):
    tags: list[Annotated[str, Field(max_length=40)]] = Field(max_length=20)


@router.put("/api/clients/{client_id}/tags")
def set_tags(client_id: int, req: TagsIn, _: CurrentUser):
    client_or_404(client_id)
    return {"tags": clients.set_tags(client_id, req.tags)}


@router.get("/api/tags")
def tags(_: CurrentUser):
    return clients.all_tags()


class IdentityIn(BaseModel):
    channel: Literal["email", "whatsapp", "telegram", "phone", "other"]
    handle: str = Field(min_length=1, max_length=200)


@router.post("/api/clients/{client_id}/identities")
def add_identity(client_id: int, req: IdentityIn, _: CurrentUser):
    client_or_404(client_id)
    return clients.add_identity(client_id, req.channel, req.handle)


@router.delete("/api/identities/{identity_id}")
def delete_identity(identity_id: int, _: CurrentUser):
    clients.delete_identity(identity_id)
    return {"ok": True}


@router.get("/api/clients/{client_id}/duplicates")
def duplicates(client_id: int, _: CurrentUser):
    client_or_404(client_id)
    return clients.possible_duplicates(client_id)


class MergeRequest(BaseModel):
    into_client_id: int


@router.post("/api/clients/{client_id}/merge")
def merge(client_id: int, req: MergeRequest, user: CurrentUser):
    """Une este cliente con otro: todo pasa a `into_client_id` y este se borra."""
    source = client_or_404(client_id)
    result = clients.merge_clients(client_id, req.into_client_id)
    audit.log(user["id"], "client_merge", req.into_client_id, detail=f"«{source['name']}» (id {client_id}) unido a este cliente")
    return result


@router.post("/api/clients/{client_id}/visit")
def visit_client(client_id: int, user: CurrentUser):
    """El usuario abre la ficha: devuelve cuántos mensajes han llegado desde su visita anterior. Lo que le escribió el
    cliente por WhatsApp queda leído (él ve los checks azules), en segundo plano."""
    client_or_404(client_id)
    result = search.record_visit(user["id"], client_id)
    message_actions.mark_read_later(client_id, user)
    return result


class WhatsNewRequest(BaseModel):
    since_message_id: int


@router.post("/api/clients/{client_id}/whats-new")
def whats_new(client_id: int, req: WhatsNewRequest, _: CurrentUser):
    """Resumen con IA de los mensajes llegados desde un punto (la visita anterior)."""
    client = client_or_404(client_id)
    messages = search.messages_since(client_id, req.since_message_id)
    if not messages:
        return {"summary": "No hay mensajes nuevos."}
    return {"summary": insights.summarize_new_messages(client["name"], messages)}


@router.get("/api/clients/{client_id}")
def client_detail(client_id: int, user: CurrentUser):
    data = search.client_overview(client_id, user["id"])
    if not data:
        raise NotFound("Cliente no encontrado")
    return data


@router.get("/api/clients/{client_id}/timeline")
def client_timeline(client_id: int, user: CurrentUser, scope: Literal["mine", "team"] = "mine",
                    channel: str | None = None):
    messages = search.timeline(client_id, user["id"], scope, channel)
    # Solo cuenta como acceso al equipo si de verdad se muestran conversaciones de compañeros.
    if scope == "team" and any(m["owner_id"] != user["id"] for m in messages):
        audit.log(user["id"], "team_messages", client_id, throttle=True)
    return messages
