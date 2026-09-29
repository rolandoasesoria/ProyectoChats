"""API HTTP + servidor del frontend estático."""
from pathlib import Path
from typing import Literal

import anthropic
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, search
from .db import get_conn, init_db

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="ProyectoChats")
init_db()


def current_user(user_id: int | None) -> dict:
    """Identificación provisional por cabecera X-User-Id (se sustituirá por login real)."""
    if user_id is None:
        raise HTTPException(401, "Falta la cabecera X-User-Id")
    with get_conn() as conn:
        row = conn.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(401, "Usuario desconocido")
    return dict(row)


@app.get("/api/users")
def users():
    return search.list_users()


@app.get("/api/clients")
def clients(q: str = ""):
    return search.find_clients(q)


@app.get("/api/clients/{client_id}")
def client_detail(client_id: int, x_user_id: int | None = Header(None)):
    user = current_user(x_user_id)
    data = search.client_overview(client_id, user["id"])
    if not data:
        raise HTTPException(404, "Cliente no encontrado")
    return data


@app.get("/api/clients/{client_id}/timeline")
def client_timeline(client_id: int, scope: Literal["mine", "team"] = "mine",
                    channel: str | None = None, x_user_id: int | None = Header(None)):
    user = current_user(x_user_id)
    return search.timeline(client_id, user["id"], scope, channel)


@app.get("/api/search")
def search_endpoint(q: str, scope: Literal["mine", "team"] = "mine",
                    client_id: int | None = None, x_user_id: int | None = Header(None)):
    user = current_user(x_user_id)
    return search.search_messages(q, user["id"], scope, client_id=client_id)


class ImportMessage(BaseModel):
    direction: Literal["in", "out"]
    sender: str
    body: str
    sent_at: str


class ImportPayload(BaseModel):
    channel: str
    handle: str
    client_name: str | None = None
    client_id: int | None = None
    subject: str | None = None
    messages: list[ImportMessage]


@app.post("/api/import")
def import_conversation(payload: ImportPayload, x_user_id: int | None = Header(None)):
    """Punto de entrada para integraciones (email, WhatsApp, Telegram...) o importaciones manuales."""
    user = current_user(x_user_id)
    data = payload.model_dump()
    data["owner_user_id"] = user["id"]
    return search.import_conversation(data)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    client_id: int | None = None


@app.post("/api/chat")
def chat(req: ChatRequest, x_user_id: int | None = Header(None)):
    user = current_user(x_user_id)
    client = None
    if req.client_id:
        with get_conn() as conn:
            row = conn.execute("SELECT id, name FROM clients WHERE id = ?", (req.client_id,)).fetchone()
        client = dict(row) if row else None
    session = agent.get_session(req.session_id, user["id"])
    try:
        result = agent.chat(session, user, req.message, client)
    except anthropic.AuthenticationError:
        raise HTTPException(500, "Clave de API de Claude inválida o ausente (revisa backend/.env).")
    except anthropic.RateLimitError:
        raise HTTPException(429, "Límite de uso de la API alcanzado. Inténtalo en unos segundos.")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "No se pudo conectar con la API de Claude.")
    except anthropic.APIStatusError as exc:
        raise HTTPException(502, f"Error de la API de Claude: {exc.message}")
    except agent.MissingCredentialsError:
        raise HTTPException(503, "El asistente no está disponible: falta configurar ANTHROPIC_API_KEY en backend/.env.")
    return {"session_id": session.id, **result}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
