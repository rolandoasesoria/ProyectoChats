"""Dependencias comunes de las rutas: usuario autenticado, administrador, cliente existente y errores de Claude."""
from contextlib import contextmanager
from typing import Annotated

import anthropic
from fastapi import Depends

from .. import agent, auth, clients
from ..errors import ExternalServiceError, NotFound, ServiceUnavailable, TooManyAttempts

CurrentUser = Annotated[dict, Depends(auth.current_user)]


def admin_user(user: CurrentUser) -> dict:
    return auth.require_admin(user)


AdminUser = Annotated[dict, Depends(admin_user)]


@contextmanager
def claude_errors():
    """Traduce los errores de la API de Claude a respuestas HTTP con mensaje en español."""
    try:
        yield
    except anthropic.AuthenticationError:
        raise ServiceUnavailable("Clave de API de Claude inválida o ausente (revisa backend/.env).")
    except anthropic.RateLimitError:
        raise TooManyAttempts("Límite de uso de la API alcanzado. Inténtalo en unos segundos.")
    except anthropic.APIConnectionError:
        raise ExternalServiceError("No se pudo conectar con la API de Claude.")
    except anthropic.APIStatusError as exc:
        raise ExternalServiceError(f"Error de la API de Claude: {exc.message}")
    except agent.MissingCredentialsError:
        raise ServiceUnavailable("El asistente no está disponible: falta configurar ANTHROPIC_API_KEY en backend/.env.")


def client_or_404(client_id: int | None) -> dict | None:
    if client_id is None:
        return None
    client = clients.get_basic(client_id)
    if not client:
        raise NotFound("Cliente no encontrado")
    return client
