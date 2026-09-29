"""Búsqueda por significado: Claude amplía la pregunta en palabras clave, se busca con el índice de texto
y Claude ordena los candidatos por lo bien que responden a la pregunta. No necesita otro proveedor."""
import json

from . import agent, attachments, search

MAX_CANDIDATES = 40

EXPAND_SCHEMA = {
    "type": "object",
    "properties": {"keywords": {"type": "array", "items": {"type": "string"}}},
    "required": ["keywords"], "additionalProperties": False,
}

RANK_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"ref": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["ref", "reason"], "additionalProperties": False,
    }}},
    "required": ["results"], "additionalProperties": False,
}


class SmartSearchError(Exception):
    pass


def _structured(system: str, content: str, schema: dict) -> dict:
    response = agent._create(system=system, messages=[{"role": "user", "content": content}],
                             output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}})
    if response.stop_reason in ("refusal", "max_tokens"):
        raise SmartSearchError("La IA no ha podido completar la búsqueda.")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def expand(question: str) -> list[str]:
    data = _structured(
        "Conviertes una pregunta sobre conversaciones con clientes (email, WhatsApp, Telegram) en palabras clave "
        "para un buscador de texto que NO entiende sinónimos. Devuelve de 6 a 15 palabras sueltas o expresiones "
        "de 2 palabras: las de la pregunta, sinónimos, otras formas (singular/plural, verbos conjugados), cómo lo "
        "escribiría un cliente de forma coloquial y términos relacionados que aparecerían en la respuesta "
        "(p. ej. para '¿cuándo le viene bien la entrega?': entrega, entregar, llevar, recoger, mañana, tarde, "
        "horario, día, semana). En el idioma de la pregunta. Sin palabras vacías.",
        question, EXPAND_SCHEMA)
    seen, result = set(), []
    for k in data["keywords"]:
        k = k.strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            result.append(k)
    return result[:15]


def smart_search(question: str, user_id: int, scope: str, client_id: int | None = None) -> dict:
    keywords = expand(question)
    fts_text = " ".join(keywords)
    messages = search.search_messages(fts_text, user_id, scope, client_id=client_id, limit=MAX_CANDIDATES,
                                      markers=("", ""))
    fts = search._fts_query(fts_text)
    docs = attachments.search(fts, user_id, scope, client_id=client_id, limit=10) if fts else []
    candidates = {f"m{m['message_id']}": m for m in messages} | {f"d{d['documento_id']}": d for d in docs}
    if not candidates:
        return {"keywords": keywords, "results": []}

    lines = []
    for ref, c in candidates.items():
        if ref.startswith("m"):
            who = f"{c['sender']} (cliente)" if c["direction"] == "in" else f"{c['sender']} (equipo)"
            lines.append(f"[{ref}] {c['sent_at'][:10]} · {c['channel']} · {c['client']} · {who}: {c['snippet']}")
        else:
            lines.append(f"[{ref}] documento «{c['filename']}» de {c['client']}: {c['snippet']}")
    ranked = _structured(
        "Ordenas resultados de búsqueda por lo bien que responden a la pregunta del usuario. Devuelve solo los "
        "que de verdad son relevantes (como mucho 8), del más al menos útil, con su referencia exacta (p. ej. m12 o "
        "d3) y en 'reason' una frase corta en español que diga qué aporta (p. ej. 'Indica que prefiere entregas por "
        "la mañana'). Si ninguno responde, devuelve una lista vacía.",
        f"Pregunta: {question}\n\nResultados:\n" + "\n".join(lines), RANK_SCHEMA)

    results = []
    for r in ranked["results"]:
        c = candidates.get(r["ref"].strip())
        if c is None:
            continue  # referencia inventada o mal escrita: se ignora
        if r["ref"].startswith("m"):
            results.append({"kind": "message", "message_id": c["message_id"], "client_id": c["client_id"],
                            "client": c["client"], "channel": c["channel"], "sender": c["sender"],
                            "direction": c["direction"], "sent_at": c["sent_at"], "owner": c["owner"],
                            "text": c["snippet"], "reason": r["reason"]})
        else:
            results.append({"kind": "document", "attachment_id": c["documento_id"], "client_id": c["client_id"],
                            "client": c["client"], "filename": c["filename"], "sent_at": c["fecha"],
                            "text": c["snippet"], "reason": r["reason"]})
    return {"keywords": keywords, "results": results}
