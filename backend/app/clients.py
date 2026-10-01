"""Gestión de clientes: datos básicos, estado, responsable, etiquetas, identificadores y unión de duplicados."""
import re
import unicodedata

from . import notes
from .db import get_conn
from .errors import Conflict, InvalidInput, NotFound
from .repositories import clients as clients_repo
from .repositories import messages as messages_repo

STATUSES = {"lead": "Potencial", "active": "Activo", "issue": "Incidencia", "inactive": "Inactivo"}
CHANNELS = ("email", "whatsapp", "telegram", "phone", "other")


def _norm_name(name: str) -> str:
    text = unicodedata.normalize("NFD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _digits(handle: str) -> str:
    """Últimos 9 dígitos de un teléfono (ignora prefijo de país, espacios y guiones)."""
    d = re.sub(r"\D", "", handle or "")
    return d[-9:] if len(d) >= 9 else ""


def create_client(name: str, company: str | None, user_id: int) -> int:
    with get_conn() as conn:
        return clients_repo.insert(conn, name.strip(), (company or "").strip() or None, user_id)


def get_basic(client_id: int) -> dict | None:
    """Id y nombre del cliente (None si no existe)."""
    with get_conn() as conn:
        return clients_repo.get_basic(conn, client_id)


def update_client(client_id: int, fields: dict, user_id: int | None = None) -> None:
    """Cambia datos del cliente. Un cambio de estado hecho por una persona (user_id) queda como manual: la IA no lo
    toca hasta que lleguen mensajes nuevos."""
    allowed = {"name", "company", "status", "assignee_user_id"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if "status" in fields and fields["status"] not in STATUSES:
        raise InvalidInput("Estado no válido.")
    if "name" in fields and not (fields["name"] or "").strip():
        raise InvalidInput("El nombre es obligatorio.")
    if not fields:
        return
    with get_conn() as conn:
        manual_status = None
        if "status" in fields:
            current = clients_repo.get_status(conn, client_id)
            if current and current["status"] != fields["status"]:
                manual_status = {"by": user_id, "last_message_id": messages_repo.last_id_for_client(conn, client_id)}
        clients_repo.update(conn, client_id, fields, manual_status)


def notify_assigned(client_id: int, client_name: str, assignee_id: int, actor: dict) -> None:
    """Avisa a quien pasa a ser responsable del cliente."""
    with get_conn() as conn:
        notes.notify(conn, [assignee_id], "client_assigned",
                     f"{actor['name']} te ha hecho responsable de {client_name}", client_id, actor["id"])


def release_status(client_id: int) -> None:
    """Deshace el «fijado a mano»: el estado se queda como está hasta que lo decida la IA o la regla de inactividad."""
    with get_conn() as conn:
        clients_repo.release_status(conn, client_id)


def set_auto_status(conn, client_id: int, status: str, reason: str) -> str | None:
    """Estado decidido por la IA o por la regla de inactividad. No pisa un cambio manual mientras no haya mensajes
    nuevos desde entonces. Devuelve el estado anterior si ha cambiado (None si no)."""
    row = clients_repo.get_status(conn, client_id)
    if not row or status not in STATUSES:
        return None
    last = messages_repo.last_id_for_client(conn, client_id)
    if row["status_source"] == "manual" and last <= (row["status_last_message_id"] or 0):
        return None
    clients_repo.set_auto_status(conn, client_id, status, reason or None, last)
    return row["status"] if row["status"] != status else None


def reactivate(client_id: int, days: int) -> bool:
    """Sin IA: un cliente inactivo que vuelve a escribir (en los últimos `days` días) pasa a Activo."""
    with get_conn() as conn:
        recent = clients_repo.is_inactive_with_recent_message(conn, client_id, int(days or 90))
        return bool(recent and set_auto_status(conn, client_id, "active", "Ha vuelto a escribir"))


def mark_inactive(days: int) -> int:
    """Regla diaria (sin IA): pasa a Inactivo a los clientes sin mensajes en `days` días. Devuelve cuántos."""
    if not days:
        return 0
    changed = 0
    with get_conn() as conn:
        for client_id in clients_repo.stale_ids(conn, int(days)):
            if set_auto_status(conn, client_id, "inactive", f"Sin mensajes en los últimos {days} días"):
                changed += 1
    return changed


def set_tags(client_id: int, tags: list[str]) -> list[str]:
    clean = []
    for t in tags:
        t = " ".join(t.split())[:40]
        if t and t.lower() not in {c.lower() for c in clean}:
            clean.append(t)
    with get_conn() as conn:
        clients_repo.replace_tags(conn, client_id, clean[:20])
    return clean[:20]


def all_tags() -> list[dict]:
    with get_conn() as conn:
        return clients_repo.all_tags(conn)


def add_identity(client_id: int, channel: str, handle: str) -> dict:
    handle = handle.strip()
    if channel not in CHANNELS:
        raise InvalidInput("Canal no válido.")
    if not handle:
        raise InvalidInput("El identificador es obligatorio.")
    if channel == "email":
        handle = handle.lower()
    with get_conn() as conn:
        other = clients_repo.identity_owner(conn, channel, handle)
        if other:
            if other["id"] == client_id:
                raise Conflict("Este cliente ya tiene ese identificador.")
            raise Conflict(f"Ese identificador ya pertenece a «{other['name']}». "
                           "Si es la misma persona, usa «Unir con otro cliente».")
        ident_id = clients_repo.insert_identity(conn, client_id, channel, handle)
    return {"id": ident_id, "channel": channel, "handle": handle}


def delete_identity(identity_id: int) -> None:
    with get_conn() as conn:
        if not clients_repo.delete_identity(conn, identity_id):
            raise NotFound("Identificador no encontrado.")


def possible_duplicates(client_id: int) -> list[dict]:
    """Otros clientes que probablemente son la misma persona: mismo nombre, mismo email o mismo teléfono."""
    with get_conn() as conn:
        me = clients_repo.get_basic(conn, client_id)
        if not me:
            return []
        all_clients = clients_repo.list_others(conn, client_id)
        idents = clients_repo.all_identities(conn)
    mine = [i for i in idents if i["client_id"] == client_id]
    my_emails = {i["handle"].lower() for i in mine if "@" in i["handle"] and not i["handle"].startswith("@")}
    my_phones = {_digits(i["handle"]) for i in mine} - {""}
    my_name = _norm_name(me["name"])
    result = []
    for c in all_clients:
        theirs = [i for i in idents if i["client_id"] == c["id"]]
        reasons = []
        if my_name and _norm_name(c["name"]) == my_name:
            reasons.append("mismo nombre")
        if my_emails & {i["handle"].lower() for i in theirs}:
            reasons.append("mismo email")
        if my_phones & ({_digits(i["handle"]) for i in theirs} - {""}):
            reasons.append("mismo teléfono")
        if reasons:
            result.append({**c, "reasons": reasons})
    return result


def merge_clients(source_id: int, target_id: int) -> dict:
    """Mueve todo lo del cliente `source` al `target` y borra `source`. No se puede deshacer."""
    if source_id == target_id:
        raise InvalidInput("No se puede unir un cliente consigo mismo.")
    with get_conn() as conn:
        src = clients_repo.get(conn, source_id)
        dst = clients_repo.get(conn, target_id)
        if not src or not dst:
            raise NotFound("Cliente no encontrado.")
        moved = clients_repo.move_related(conn, source_id, target_id)
        clients_repo.copy_tags(conn, source_id, target_id)
        clients_repo.merge_visits(conn, source_id, target_id)
        clients_repo.archive_assistant_chats(conn, source_id, target_id)
        # El resumen de IA del que se queda deja de estar al día: se fuerza a mostrar mensajes nuevos.
        clients_repo.reset_analysis(conn, target_id)
        clients_repo.fill_missing(conn, target_id, src["company"], src["notes"], src["assignee_user_id"])
        clients_repo.delete(conn, source_id)
    return {"client_id": target_id, "moved_conversations": moved["conversations"],
            "moved_identities": moved["client_identities"]}
