"""Configuración de la app, leída UNA vez de las variables de entorno (backend/.env).

Es el único módulo que lee el entorno: el resto recibe valores ya validados y con tipo. Así un error de
configuración se detecta al arrancar, y no a mitad de una petición.
"""
import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class ConfigError(RuntimeError):
    """Configuración incompleta o insegura: la app no debe arrancar así."""


def _text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _flag(name: str, default: bool = False) -> bool:
    return _text(name, "true" if default else "false").lower() in ("1", "true", "yes", "si", "sí")


def _int(name: str, default: int) -> int:
    value = _text(name, str(default))
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} debe ser un número entero (vale «{value}»).") from exc


def _path(name: str, default: str) -> Path:
    path = Path(_text(name, default))
    return path if path.is_absolute() else BACKEND_DIR / path


@dataclass(frozen=True)
class DatabaseConfig:
    url: str              # usuario de la app: solo lee y escribe datos
    admin_url: str        # usuario dueño del esquema: migraciones (vacío = el mismo que url)
    ssl_mode: str         # vacío = automático: verify-full si el servidor no es este equipo
    ssl_root_cert: str    # certificado de la autoridad que firmó el del servidor (para verify-ca/verify-full)
    auto_migrate: bool    # aplicar las migraciones pendientes al arrancar
    pool_size: int
    statement_timeout_ms: int
    connect_timeout_s: int

    @property
    def migration_url(self) -> str:
        return self.admin_url or self.url


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    ssl_certfile: str | None
    ssl_keyfile: str | None
    forwarded_allow_ips: str


@dataclass(frozen=True)
class SecurityConfig:
    force_https: bool
    cookie_secure: bool
    enable_docs: bool
    login_lock_minutes: int
    login_max_fails_per_user: int
    login_max_fails_per_ip: int
    secret_key: str


@dataclass(frozen=True)
class AIConfig:
    model: str
    disabled: bool

    @property
    def has_credentials(self) -> bool:
        return not self.disabled and bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


@dataclass(frozen=True)
class IntegrationsConfig:
    sync_disabled: bool
    telegram_api: str
    graph_api: str


@dataclass(frozen=True)
class Config:
    data_dir: Path
    database: DatabaseConfig
    server: ServerConfig
    security: SecurityConfig
    ai: AIConfig
    integrations: IntegrationsConfig


def load() -> Config:
    return Config(
        data_dir=_path("DATA_DIR", "data"),
        database=DatabaseConfig(
            url=_text("DATABASE_URL", "postgresql://proyectochats@localhost:5432/proyectochats"),
            admin_url=_text("DATABASE_ADMIN_URL"),
            ssl_mode=_text("DB_SSLMODE").lower(),
            ssl_root_cert=_text("DB_SSLROOTCERT"),
            auto_migrate=_flag("DB_AUTO_MIGRATE", True),
            pool_size=_int("DB_POOL_SIZE", 10),
            statement_timeout_ms=_int("DB_STATEMENT_TIMEOUT_MS", 30000),
            connect_timeout_s=_int("DB_CONNECT_TIMEOUT", 10),
        ),
        server=ServerConfig(
            host=_text("HOST", "127.0.0.1"),
            port=_int("PORT", 8000),
            ssl_certfile=_text("SSL_CERTFILE") or None,
            ssl_keyfile=_text("SSL_KEYFILE") or None,
            forwarded_allow_ips=_text("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        ),
        security=SecurityConfig(
            force_https=_flag("FORCE_HTTPS"),
            cookie_secure=_flag("COOKIE_SECURE"),
            enable_docs=_flag("ENABLE_DOCS"),
            login_lock_minutes=_int("LOGIN_LOCK_MINUTES", 15),
            login_max_fails_per_user=_int("LOGIN_MAX_FAILS_PER_USER", 5),
            login_max_fails_per_ip=_int("LOGIN_MAX_FAILS_PER_IP", 20),
            secret_key=_text("SECRET_KEY"),
        ),
        ai=AIConfig(model=_text("CLAUDE_MODEL", "claude-opus-5-5"), disabled=_flag("DISABLE_AI")),
        integrations=IntegrationsConfig(
            sync_disabled=_flag("DISABLE_SYNC"),
            telegram_api=_text("TELEGRAM_API", "https://api.telegram.org"),
            graph_api=_text("GRAPH_API", "https://graph.facebook.com/v21.0"),
        ),
    )


config = load()
