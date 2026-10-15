"""Plantillas de mensaje de una cuenta de WhatsApp Business (Graph API: /{waba_id}/message_templates).

Las plantillas son los únicos mensajes que se pueden enviar a un cliente fuera de las 24 h siguientes a su último
mensaje (recordatorios, avisos, campañas). Meta las revisa antes de aprobarlas: se crean aquí y su estado
(PENDING, APPROVED, REJECTED…) se consulta a Meta cada vez.
"""
import re
import unicodedata

from . import integrations
from .errors import ExternalServiceError, InvalidInput

CATEGORIES = {"UTILITY", "MARKETING"}
LANGUAGES = {"es", "es_ES", "en", "en_US", "ca", "fr", "pt_PT"}
VARIABLE = re.compile(r"\{\{(\d+)\}\}")


def _account(integ: dict) -> str:
    if integ["kind"] != "whatsapp":
        raise InvalidInput("Las plantillas solo existen en las cuentas de WhatsApp Business.")
    waba_id = integ["config"].get("waba_id")
    if not waba_id:
        raise InvalidInput("Falta el identificador de la cuenta de WhatsApp Business: pulsa «Editar» y cópialo de Meta "
                           "(WhatsApp → API Setup, debajo del número).")
    return waba_id


def _graph(integ: dict, method: str, path: str, body: dict | None = None) -> dict:
    try:
        return integrations.graph_request(method, path, integ["config"]["access_token"], body=body, timeout=20) or {}
    except integrations.IntegrationError as exc:
        raise ExternalServiceError(str(integrations.explain_meta(exc))) from exc


def list_templates(integ: dict) -> list[dict]:
    fields = "name,status,category,language,components,rejected_reason"
    data = _graph(integ, "GET", f"/{_account(integ)}/message_templates?fields={fields}&limit=100").get("data", [])
    return [{"id": t.get("id"), "name": t.get("name"), "status": t.get("status"), "category": t.get("category"),
             "language": t.get("language"), "rejected_reason": t.get("rejected_reason"),
             "body": next((c.get("text") for c in t.get("components", []) if c.get("type") == "BODY"), "")}
            for t in data]


def template_name(name: str) -> str:
    """Meta solo admite minúsculas, números y guiones bajos: «Recordatorio de cita» → recordatorio_de_cita."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", plain)).strip("_")[:512]


def create_template(integ: dict, name: str, category: str, language: str, body: str,
                    examples: list[str] | None = None) -> dict:
    """Envía la plantilla a revisión de Meta. Si el texto lleva variables ({{1}}, {{2}}…), Meta exige un ejemplo de
    cada una."""
    waba_id = _account(integ)
    slug = template_name(name)
    if not slug:
        raise InvalidInput("Ponle un nombre a la plantilla.")
    if category not in CATEGORIES:
        raise InvalidInput("La categoría debe ser «Servicio» (UTILITY) o «Marketing» (MARKETING).")
    if language not in LANGUAGES:
        raise InvalidInput("Idioma no admitido.")
    body = body.strip()
    if not body:
        raise InvalidInput("Escribe el texto de la plantilla.")
    variables = sorted({int(n) for n in VARIABLE.findall(body)})
    if variables != list(range(1, len(variables) + 1)):
        raise InvalidInput("Las variables deben ir numeradas seguidas: {{1}}, {{2}}, {{3}}…")
    examples = [e.strip() for e in (examples or []) if e.strip()]
    if len(examples) < len(variables):
        raise InvalidInput(f"Meta pide un ejemplo de cada variable: faltan {len(variables) - len(examples)}.")
    component = {"type": "BODY", "text": body}
    if variables:
        component["example"] = {"body_text": [examples[:len(variables)]]}
    result = _graph(integ, "POST", f"/{waba_id}/message_templates",
                    {"name": slug, "category": category, "language": language, "components": [component]})
    return {"id": result.get("id"), "name": slug, "status": result.get("status", "PENDING"),
            "category": result.get("category", category)}


def delete_template(integ: dict, name: str) -> None:
    """Borra la plantilla en Meta (en todos sus idiomas)."""
    _graph(integ, "DELETE", f"/{_account(integ)}/message_templates?name={template_name(name)}")


def variable_count(body: str) -> int:
    return max((int(n) for n in VARIABLE.findall(body or "")), default=0)


def render(body: str, params: list[str]) -> str:
    """El texto que verá el cliente: cada {{n}} sustituido por su valor."""
    return VARIABLE.sub(lambda m: params[int(m.group(1)) - 1] if int(m.group(1)) <= len(params) else m.group(0), body)


def approved_for(conversation_id: int, user: dict) -> list[dict]:
    """Plantillas aprobadas de la cuenta de WhatsApp con la que `user` responde en esta conversación."""
    integ, conv, _ = integrations.reply_target(conversation_id, user)
    if conv["channel"] != "whatsapp":
        raise InvalidInput("Las plantillas solo se envían por WhatsApp.")
    return [{**t, "variables": variable_count(t["body"])} for t in list_templates(integ) if t["status"] == "APPROVED"]


def send_template(conversation_id: int, user: dict, name: str, language: str, params: list[str]) -> dict:
    """Envía una plantilla aprobada al cliente de la conversación y la guarda con el texto ya rellenado."""
    integ, conv, idents = integrations.reply_target(conversation_id, user)
    if conv["channel"] != "whatsapp":
        raise InvalidInput("Las plantillas solo se envían por WhatsApp.")
    template = next((t for t in list_templates(integ) if t["name"] == name and t["language"] == language
                     and t["status"] == "APPROVED"), None)
    if not template:
        raise InvalidInput("Esa plantilla no existe o todavía no está aprobada por Meta.")
    params = [p.strip() for p in params]
    needed = variable_count(template["body"])
    if len(params) != needed or not all(params):
        raise InvalidInput(f"Rellena las {needed} variables de la plantilla." if needed != 1 else "Rellena la variable.")
    text = render(template["body"], params)
    return integrations.deliver(integ, conversation_id, user, text,
                                lambda: integrations.send_whatsapp_template(integ, idents[0], name, language, params))
