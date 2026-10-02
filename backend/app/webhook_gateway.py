"""Puerta pública solo para los webhooks: python -m app.webhook_gateway

Meta tiene que poder avisar a la app por HTTPS desde internet cuando llega un WhatsApp, pero el resto de la app
(inicio de sesión, clientes, datos) debe seguir solo en la red de la oficina. Este proceso escucha en este equipo
(127.0.0.1, WEBHOOK_PORT, 8010 por defecto) y SOLO atiende /api/webhooks/whatsapp/{id}: cualquier otra ruta
devuelve 404. El túnel (scripts/webhook-publico.ps1) publica este puerto, nunca el de la app.
"""
import uvicorn
from fastapi import FastAPI

from .api import integrations as integrations_api
from .config import config
from .errors import AppError
from .main import app_error

gateway = FastAPI(title="ProyectoChats · webhooks", docs_url=None, redoc_url=None, openapi_url=None)
gateway.add_exception_handler(AppError, app_error)
gateway.add_api_route("/api/webhooks/whatsapp/{integration_id}", integrations_api.whatsapp_verify, methods=["GET"])
gateway.add_api_route("/api/webhooks/whatsapp/{integration_id}", integrations_api.whatsapp_webhook, methods=["POST"])


def main() -> None:
    uvicorn.run(gateway, host="127.0.0.1", port=config.server.webhook_port, server_header=False, proxy_headers=False)


if __name__ == "__main__":
    main()
