"""Conectar un WhatsApp Business con el registro insertado de Meta, en modo coexistencia.

La persona pulsa «Conectar con WhatsApp Business» en «Mis cuentas», inicia sesión con Facebook, elige su cuenta y
escanea un código desde la app WhatsApp Business del móvil. El navegador recibe un código de un solo uso (válido
30 segundos) y el identificador de la cuenta de WhatsApp Business (WABA); con eso, aquí:

1. se canjea el código por el token de la empresa (no caduca y no hay que pegarlo a mano);
2. se localiza el número de la cuenta y se comprueba que el token tiene acceso a él;
3. se suscribe la app a los avisos de esa cuenta (mensajes, envíos desde el móvil, historial, contactos);
4. se guarda la integración (cifrada), de la persona que la conecta;
5. se pide a Meta la sincronización de contactos y del historial (hay 24 h para hacerlo tras el alta).

El número NO se registra con /register: en la coexistencia ya está registrado en la app del móvil, que sigue
funcionando igual.
"""
import urllib.parse

from . import integrations
from .config import config
from .errors import Conflict, ExternalServiceError, InvalidInput, ServiceUnavailable

SYNC_TYPES = {"contacts": "smb_app_state_sync", "history": "history"}


def settings_for(user: dict) -> dict:
    """Lo que necesita el navegador para abrir el registro insertado (nada secreto) y, para administradores, los
    datos del webhook de la app que hay que poner una vez en Meta."""
    meta = config.meta
    result = {"ready": meta.embedded_signup_ready, "app_id": meta.app_id, "config_id": meta.config_id,
              "graph_version": config.integrations.graph_api.rstrip("/").rsplit("/", 1)[-1]}
    if user["role"] == "admin":
        base = integrations.webhook_base_url()
        result["webhook"] = {"url": f"{base}/api/webhooks/whatsapp" if base else None,
                             "verify_token": meta.webhook_verify_token}
    return result


def _graph(method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    try:
        return integrations.graph_request(method, path, token, body=body, timeout=20) or {}
    except integrations.IntegrationError as exc:
        error = exc.error.get("message") or str(exc)
        raise ExternalServiceError(f"Meta ha rechazado la conexión: {error}") from exc


def _exchange_code(code: str) -> str:
    query = urllib.parse.urlencode({"client_id": config.meta.app_id, "client_secret": config.meta.app_secret,
                                    "code": code})
    try:
        token = _graph("GET", f"/oauth/access_token?{query}").get("access_token")
    except ExternalServiceError as exc:
        raise ExternalServiceError(f"{exc} (el código del alta dura 30 segundos: vuelve a pulsar «Conectar»).") from exc
    if not token:
        raise ExternalServiceError("Meta no ha devuelto el token de la empresa. Vuelve a intentarlo.")
    return token


def _account_from_token(token: str) -> str:
    """Si el navegador no recibió el identificador de la cuenta, se saca de los permisos concedidos al token."""
    app_token = f"{config.meta.app_id}|{config.meta.app_secret}"
    query = urllib.parse.urlencode({"input_token": token, "access_token": app_token})
    scopes = _graph("GET", f"/debug_token?{query}").get("data", {}).get("granular_scopes", [])
    for scope in scopes:
        if scope.get("scope") in ("whatsapp_business_management", "whatsapp_business_messaging") and scope.get("target_ids"):
            return scope["target_ids"][0]
    raise ExternalServiceError("No se ha podido saber qué cuenta de WhatsApp Business se ha conectado. Vuelve a intentarlo.")


def _pick_number(token: str, waba_id: str, phone_number_id: str | None) -> dict:
    numbers = _graph("GET", f"/{waba_id}/phone_numbers?fields=id,display_phone_number,verified_name", token)
    numbers = numbers.get("data", [])
    if phone_number_id:
        numbers = [n for n in numbers if n.get("id") == phone_number_id]
    if not numbers:
        raise ExternalServiceError("La cuenta de WhatsApp Business conectada no tiene ese número.")
    return numbers[0]


def _start_sync(token: str, phone_number_id: str) -> dict:
    """Pide los contactos y el historial a la app del móvil. Un fallo aquí no impide usar la cuenta."""
    result = {}
    for name, sync_type in SYNC_TYPES.items():
        try:
            _graph("POST", f"/{phone_number_id}/smb_app_data", token,
                   {"messaging_product": "whatsapp", "sync_type": sync_type})
            result[name] = "solicitado"
        except ExternalServiceError as exc:
            result[name] = str(exc)
    return result


def connect(user: dict, code: str, waba_id: str = "", phone_number_id: str = "", name: str = "") -> dict:
    """Da de alta (o renueva) el WhatsApp Business de la persona en modo coexistencia."""
    if not config.meta.embedded_signup_ready:
        raise ServiceUnavailable("Falta configurar la app de Meta (META_APP_ID, META_APP_SECRET y META_CONFIG_ID).")
    if not code:
        raise InvalidInput("Meta no ha devuelto el código del alta. Vuelve a intentarlo.")
    token = _exchange_code(code)
    waba_id = waba_id or _account_from_token(token)
    number = _pick_number(token, waba_id, phone_number_id or None)
    _graph("POST", f"/{waba_id}/subscribed_apps", token)

    cfg = {"phone_number_id": number["id"], "access_token": token, "app_secret": config.meta.app_secret,
           "verify_token": config.meta.webhook_verify_token, "waba_id": waba_id}
    existing = integrations.find_whatsapp(number["id"])
    if existing and existing["owner_user_id"] != user["id"] and user["role"] != "admin":
        raise Conflict("Ese número de WhatsApp ya lo tiene conectado otra persona del equipo.")
    label = name.strip() or f"WhatsApp {number.get('display_phone_number', '')}".strip()
    if existing:
        integration_id = existing["id"]
        integrations.update(integration_id, label, None, True, cfg)
    else:
        integration_id = integrations.create("whatsapp", label, user["id"], cfg)
    sync = _start_sync(token, number["id"])
    integrations.set_state_fields(integration_id, coexistence=True,
                                  history="solicitado" if sync["history"] == "solicitado" else "no disponible")
    return {"id": integration_id, "number": number, "sync": sync, "test": integrations.check_connection(integration_id)}
