"""Sección Contactos: la tabla de clientes con sus datos de contacto, etiquetas, responsable, actividad y propiedades."""
from collections import defaultdict

from . import search
from .db import get_conn
from .repositories import clients as clients_repo
from .repositories import properties as properties_repo

PHONE_CHANNELS = ("whatsapp", "phone")
DEFAULT_DIRECTIONS = {"name": "asc", "company": "asc", "agent": "asc", "status": "asc", "activity": "desc",
                      "created": "desc", "unread": "desc"}


def list_contacts(user_id: int, query: str = "", status: str | None = None, tag: str | None = None,
                  assignee_id: int | None = None, channel: str | None = None, unread_only: bool = False,
                  limit: int = 500, sort: str = "name", direction: str | None = None) -> list[dict]:
    """Por defecto, por nombre. Sin sentido indicado, el natural de cada orden (A-Z; lo más reciente o con más sin leer
    primero)."""
    direction = direction or DEFAULT_DIRECTIONS[sort]
    contacts = search.find_clients(query, limit=limit, user_id=user_id, status=status, tag=tag, assignee_id=assignee_id,
                                   sort=sort, direction=direction)
    for c in contacts:
        c["channels"] = sorted(c["channels"].split(",")) if c["channels"] else []
    if channel:
        contacts = [c for c in contacts if channel in c["channels"]]
    if unread_only:
        contacts = [c for c in contacts if c["unread"]]
    ids = [c["id"] for c in contacts]
    with get_conn() as conn:
        identities = clients_repo.identities_for(conn, ids)
        values = properties_repo.values_for(conn, ids)
    handles, props = defaultdict(list), defaultdict(dict)
    for i in identities:
        handles[i["client_id"]].append(i)
    for v in values:
        props[v["client_id"]][v["property_id"]] = v["value"]
    for c in contacts:
        own = handles[c["id"]]
        c["phones"] = [i["handle"] for i in own if i["channel"] in PHONE_CHANNELS]
        c["emails"] = [i["handle"] for i in own if i["channel"] == "email"]
        c["telegram"] = [i["handle"] for i in own if i["channel"] == "telegram"]
        c["properties"] = props[c["id"]]
    return contacts
