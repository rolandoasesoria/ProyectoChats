"""Búsqueda por palabras (API, con resaltado) y por significado (lógica con Claude simulado + API sin clave)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from apitest import Session, check, results  # noqa: E402

ana = Session("ana")
st, r = ana.get("/api/search?q=direccion&scope=mine&client_id=1")
check("por palabras: encuentra sin tilde y resalta con ⟦ ⟧", st == 200 and "⟦dirección⟧" in r[0]["snippet"], r)
check("por palabras: el alcance 'mine' no ve el CIF de Carlos", ana.get("/api/search?q=CIF&scope=mine&client_id=1")[1] == [])
check("por palabras: con 'team' sí", len(ana.get("/api/search?q=CIF&scope=team&client_id=1")[1]) == 1)
st, r = ana.post("/api/smart-search", {"question": "¿cuándo le viene bien la entrega?", "client_id": 1})
check("por significado sin clave = 503", st == 503, r)
check("pregunta demasiado corta = 422", ana.post("/api/smart-search", {"question": "a"})[0] == 422)

# Lógica con Claude simulado (mismo proceso y misma base de datos que la instancia de pruebas)
from app import agent, smartsearch  # noqa: E402

calls = []
replies = []


def fake_create(**params):
    calls.append(params)
    return SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=json.dumps(replies.pop(0)))])


agent._create = fake_create
replies[:] = [{"keywords": ["entrega", "entregar", "mañana", "tarde", "almacén", "entrega"]}, None]


def rank_reply():
    # La segunda llamada (ordenar) depende de los candidatos: se elige el de "mañana" y se añade una referencia inventada.
    prompt = calls[-1]["messages"][0]["content"] if calls else ""
    return prompt


res = None
orig_structured = smartsearch._structured


def structured(system, content, schema):
    if "keywords" in schema["properties"]:
        return {"keywords": ["entrega", "entregar", "mañana", "tarde", "almacén", "Entrega"]}
    refs = [line.split("]")[0][1:] for line in content.splitlines() if line.startswith("[")]
    target = next(r for r, line in zip(refs, [l for l in content.splitlines() if l.startswith("[")]) if "mañana" in line)
    return {"results": [{"ref": target, "reason": "Prefiere entregas por la mañana"}, {"ref": "m99999", "reason": "inventado"}]}


smartsearch._structured = structured
res = smartsearch.smart_search("¿cuándo le viene bien la entrega?", 1, "mine", client_id=1)
check("amplía la pregunta sin duplicados", res["keywords"] == ["entrega", "entregar", "mañana", "tarde", "almacén"], res["keywords"])
check("devuelve el mensaje relevante con su motivo", len(res["results"]) == 1 and "mañana" in res["results"][0]["text"]
      and res["results"][0]["reason"] == "Prefiere entregas por la mañana", res["results"])
check("ignora referencias inventadas", all(r["kind"] == "message" for r in res["results"]))
check("respeta el alcance: sin resultados de Carlos con 'mine'",
      all(r["owner"] == "Ana Ruiz" for r in res["results"]))

smartsearch._structured = orig_structured
agent._create = lambda **p: SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
    type="text", text=json.dumps({"keywords": ["zzzzqqq"]}))])
check("sin candidatos no hace la segunda llamada", smartsearch.smart_search("algo", 1, "mine", 1) == {"keywords": ["zzzzqqq"], "results": []})
agent._create = lambda **p: SimpleNamespace(stop_reason="refusal", content=[])
try:
    smartsearch.smart_search("algo", 1, "mine", 1)
    check("rechazo da error claro", False)
except smartsearch.SmartSearchError:
    check("rechazo da error claro", True)
sys.exit(0 if results["ok"] else 1)
