"""Agente conversacional: Claude + herramientas de búsqueda sobre las conversaciones."""
import json
import os
import threading
import uuid
from datetime import date

import anthropic

from . import search

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT = """Eres el asistente de un equipo que atiende clientes por varios canales \
(email, WhatsApp, Telegram, etc.). Tu trabajo es encontrar datos concretos dentro del historial \
de conversaciones para que el usuario no tenga que leerlas enteras.

Cómo trabajar:
- Usa las herramientas para buscar; no inventes datos. Si no encuentras algo, dilo y sugiere otra búsqueda.
- Si el usuario nombra a un cliente, localízalo con `buscar_cliente` antes de buscar mensajes.
- Prueba varias palabras clave y sinónimos cuando la primera búsqueda no dé resultados \
(p. ej. "teléfono", "móvil", "número"). Usa `leer_contexto` para confirmar un dato ambiguo.
- Alcance: por defecto busca solo en las conversaciones del usuario (alcance "mias"). \
Usa alcance "equipo" únicamente cuando el usuario lo pida de forma explícita \
(p. ej. "busca también en las de mis compañeros", "¿alguien del equipo habló de...?"). \
Si no encuentras nada en las suyas y crees que el equipo podría tenerlo, ofrécelo en vez de hacerlo.
- Al dar un dato, indica de dónde sale: canal, fecha y, si es de otra persona del equipo, quién llevaba esa conversación.
- Responde en español, breve y directo. Usa listas cuando haya varios datos."""

SCOPE_PROP = {
    "type": "string",
    "enum": ["mias", "equipo"],
    "description": "'mias' = solo conversaciones del usuario actual (por defecto). "
                   "'equipo' = también las de sus compañeros; solo si el usuario lo pidió explícitamente.",
}

TOOLS = [
    {
        "name": "buscar_cliente",
        "description": "Busca clientes por nombre, empresa o identificador de canal (email, teléfono, @usuario). "
                       "Devuelve id, nombre y canales por los que se ha hablado con cada uno.",
        "input_schema": {
            "type": "object",
            "properties": {"texto": {"type": "string", "description": "Nombre, empresa, email, teléfono..."}},
            "required": ["texto"],
        },
    },
    {
        "name": "resumen_cliente",
        "description": "Ficha de un cliente: identidades por canal y lista de conversaciones "
                       "(canal, responsable del equipo, nº de mensajes, fechas).",
        "input_schema": {
            "type": "object",
            "properties": {"cliente_id": {"type": "integer"}},
            "required": ["cliente_id"],
        },
    },
    {
        "name": "buscar_mensajes",
        "description": "Búsqueda de texto completo en los mensajes (ignora tildes, admite prefijos). "
                       "Devuelve fragmentos con el término entre corchetes, id de mensaje, canal, fecha y responsable. "
                       "Pasa palabras clave, no frases largas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "Palabras clave; se combinan con OR."},
                "cliente_id": {"type": "integer", "description": "Limita la búsqueda a un cliente."},
                "alcance": SCOPE_PROP,
                "canales": {"type": "array", "items": {"type": "string"},
                            "description": "Filtra por canal: email, whatsapp, telegram..."},
                "desde": {"type": "string", "description": "Fecha mínima ISO (YYYY-MM-DD)."},
                "hasta": {"type": "string", "description": "Fecha máxima ISO (YYYY-MM-DD)."},
                "limite": {"type": "integer", "description": "Máximo de resultados (por defecto 20, máx. 50)."},
            },
            "required": ["consulta", "alcance"],
        },
    },
    {
        "name": "leer_contexto",
        "description": "Lee los mensajes anteriores y posteriores a un mensaje concreto de la misma conversación, "
                       "para entender o confirmar un dato encontrado con buscar_mensajes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mensaje_id": {"type": "integer"},
                "alcance": SCOPE_PROP,
                "ventana": {"type": "integer", "description": "Mensajes a cada lado (por defecto 8)."},
            },
            "required": ["mensaje_id", "alcance"],
        },
    },
]

_SCOPE_MAP = {"mias": "mine", "equipo": "team"}


def _run_tool(name: str, args: dict, user_id: int) -> object:
    scope = _SCOPE_MAP.get(args.get("alcance", "mias"))
    if scope is None:
        raise ValueError("alcance debe ser 'mias' o 'equipo'")
    if name == "buscar_cliente":
        return search.find_clients(str(args["texto"]), limit=10)
    if name == "resumen_cliente":
        return search.client_overview(int(args["cliente_id"]), user_id) or {"error": "cliente no encontrado"}
    if name == "buscar_mensajes":
        results = search.search_messages(
            str(args["consulta"]), user_id, scope,
            client_id=args.get("cliente_id"), channels=args.get("canales"),
            date_from=args.get("desde"), date_to=args.get("hasta"),
            limit=int(args.get("limite", 20)),
        )
        return results or {"resultados": 0, "nota": f"Sin coincidencias en alcance '{args.get('alcance')}'."}
    if name == "leer_contexto":
        ctx = search.message_context(int(args["mensaje_id"]), user_id, scope, int(args.get("ventana", 8)))
        return ctx or {"error": "mensaje no encontrado o fuera del alcance permitido"}
    raise ValueError(f"herramienta desconocida: {name}")


class ChatSession:
    def __init__(self, user_id: int):
        self.id = uuid.uuid4().hex
        self.user_id = user_id
        self.messages: list = []
        self.lock = threading.Lock()


class MissingCredentialsError(Exception):
    """No hay clave de API ni otra credencial de Anthropic configurada."""


_sessions: dict[str, ChatSession] = {}
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def get_session(session_id: str | None, user_id: int) -> ChatSession:
    session = _sessions.get(session_id or "")
    if session is None or session.user_id != user_id:
        session = ChatSession(user_id)
        _sessions[session.id] = session
    return session


def _context_line(user: dict, client: dict | None) -> str:
    parts = [f"Fecha de hoy: {date.today().isoformat()}", f"Usuario actual: {user['name']} (id {user['id']})"]
    if client:
        parts.append(f"Cliente abierto en pantalla: {client['name']} (cliente_id {client['id']})")
    return "[Contexto: " + "; ".join(parts) + "]"


def chat(session: ChatSession, user: dict, text: str, client: dict | None = None) -> dict:
    """Envía un mensaje del usuario y ejecuta el bucle de herramientas hasta obtener respuesta.

    Devuelve {"reply": str, "tool_calls": [{"name", "input"}]}.
    """
    with session.lock:
        session.messages.append({
            "role": "user",
            "content": [{"type": "text", "text": f"{_context_line(user, client)}\n\n{text}"}],
        })
        tool_log: list[dict] = []

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = _get_client().beta.messages.create(
                    model=MODEL,
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=session.messages,
                    output_config={"effort": "medium"},
                    cache_control={"type": "ephemeral"},
                    # Si el modelo rechaza la petición, la API la reintenta con un modelo alternativo.
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            except TypeError as exc:
                # El SDK lanza TypeError (no un error de API) cuando no encuentra credenciales.
                if "authentication method" in str(exc):
                    session.messages.pop()
                    raise MissingCredentialsError() from exc
                raise
            # Se guarda el contenido completo (incluidos bloques de razonamiento) sin modificar.
            session.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return {"reply": "No puedo ayudar con esa petición.", "tool_calls": tool_log}
            if response.stop_reason != "tool_use":
                reply = "\n".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    reply += "\n\n*(Respuesta cortada por longitud.)*"
                return {"reply": reply or "(sin respuesta)", "tool_calls": tool_log}

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_log.append({"name": block.name, "input": block.input})
                try:
                    result = _run_tool(block.name, block.input, user["id"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                except (KeyError, ValueError, TypeError) as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    })
            session.messages.append({"role": "user", "content": tool_results})

        return {"reply": "La búsqueda necesitó demasiados pasos. Prueba a concretar más la pregunta.",
                "tool_calls": tool_log}
