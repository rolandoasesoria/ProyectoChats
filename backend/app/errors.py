"""Errores de la lógica de la app, independientes de HTTP.

Los módulos de negocio lanzan estos errores con un mensaje para el usuario; la capa web (main.py) los traduce
a la respuesta HTTP que corresponda. Así la lógica se puede usar igual desde la API, la consola (manage.py) o
las tareas en segundo plano.
"""


class AppError(Exception):
    """Error esperado: se muestra al usuario tal cual."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidInput(AppError):
    """Datos que faltan o no son válidos."""


class NotAuthenticated(AppError):
    """No hay sesión iniciada, o ha caducado, o las credenciales no son correctas."""


class Forbidden(AppError):
    """Hay sesión, pero no permiso para hacer esto."""


class NotFound(AppError):
    """Lo pedido no existe (o no es visible para quien lo pide)."""


class Conflict(AppError):
    """Choca con datos que ya existen o que han cambiado mientras tanto."""


class TooManyAttempts(AppError):
    """Demasiados intentos seguidos: hay que esperar."""


class ExternalServiceError(AppError):
    """Un servicio externo (correo, Telegram, WhatsApp, Claude) ha fallado."""


class ServiceUnavailable(AppError):
    """La función no está disponible ahora mismo (p. ej. falta configurarla)."""
