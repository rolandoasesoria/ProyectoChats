"""Aplicación web: crea la app, aplica la seguridad HTTP, traduce los errores y reúne las rutas (app/api).

Las rutas de cada área están en app/api/*.py; la lógica, en los módulos de app/; el esquema de la base de datos,
en backend/database/migrations.
"""
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import integrations, privacy
from .api import (assistants, auth, clients, dashboard, documents, drafts, inbox, messaging, notes, profile,
                  replies, search, settings, tasks, users)
from .api import integrations as integrations_api
from .api import privacy as privacy_api
from .config import config
from .db import init_db
from .errors import (AppError, Conflict, ExternalServiceError, Forbidden, InvalidInput, NotAuthenticated, NotFound,
                     ServiceUnavailable, TooManyAttempts)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

# FORCE_HTTPS=true: redirige HTTP a HTTPS y activa HSTS. Detrás de un proxy (Caddy, Nginx)
# arranca con `python -m app.serve`, que confía en las cabeceras X-Forwarded-* del proxy.
FORCE_HTTPS = config.security.force_https
# La documentación interactiva de la API (/docs) solo se publica si se pide expresamente.
ENABLE_DOCS = config.security.enable_docs


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Al arrancar: esquema de la base de datos al día y tareas periódicas (salvo DISABLE_SYNC=true, en pruebas)."""
    init_db()
    if not config.integrations.sync_disabled:
        integrations.start_scheduler()  # buzones y bots conectados
        privacy.start_daily_jobs()  # retención de mensajes y clientes inactivos, una vez al día
    yield


app = FastAPI(
    title="ProyectoChats",
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
    lifespan=lifespan,
)

# Errores de la lógica de la app -> código HTTP (el más específico de su jerarquía).
ERROR_STATUS = {InvalidInput: 400, NotAuthenticated: 401, Forbidden: 403, NotFound: 404, Conflict: 409,
                TooManyAttempts: 429, ExternalServiceError: 502, ServiceUnavailable: 503, AppError: 400}


@app.exception_handler(AppError)
def app_error(_: Request, exc: AppError) -> JSONResponse:
    status = next(ERROR_STATUS[c] for c in type(exc).__mro__ if c in ERROR_STATUS)
    return JSONResponse({"detail": exc.message}, status_code=status)


SECURITY_HEADERS = {
    # Solo se ejecutan scripts y estilos servidos por la propia app; la página no se puede incrustar en otra web.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FILE_ROUTE = re.compile(r"^/api/attachments/\d+/file$")


@app.middleware("http")
async def security(request: Request, call_next):
    if FORCE_HTTPS and request.url.scheme != "https":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)

    # Protección CSRF adicional a la cookie SameSite: las peticiones que modifican datos
    # deben venir de la propia app (mismo origen).
    if request.method in UNSAFE_METHODS:
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlsplit(origin).netloc != request.url.netloc:
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)

    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if FILE_ROUTE.match(request.url.path):
        # Los archivos adjuntos se abren en su propia pestaña (visor de PDF o imagen del navegador), que la
        # CSP de la app bloquearía. Solo se sirven en línea PDF e imágenes; lo demás se descarga.
        del response.headers["Content-Security-Policy"]
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        # HTML, JS y CSS: el navegador puede guardarlos, pero debe preguntar siempre si han cambiado (responde
        # 304 si no). Sin esto, tras una actualización podía mezclar archivos viejos y nuevos y la app fallaba.
        response.headers["Cache-Control"] = "no-cache"
    return response


# Rutas por área. El orden importa solo si dos rutas pudieran coincidir.
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(settings.router)
app.include_router(integrations_api.router)
app.include_router(messaging.router)
app.include_router(dashboard.router)
app.include_router(privacy_api.router)
app.include_router(clients.router)
app.include_router(drafts.router)
app.include_router(replies.router)
app.include_router(inbox.router)
app.include_router(search.router)
app.include_router(documents.router)
app.include_router(profile.router)
app.include_router(notes.router)
app.include_router(tasks.router)
app.include_router(assistants.router)

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
