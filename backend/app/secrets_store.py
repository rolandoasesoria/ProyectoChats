"""Cifrado de secretos (contraseñas de correo, tokens de bots y de WhatsApp) antes de guardarlos.

La clave sale de SECRET_KEY en backend/.env; si no está, se genera una la primera vez y se guarda en
data/secret.key. Sin esa clave no se pueden descifrar las integraciones: haz copia de seguridad de ella
junto con la base de datos (y no la subas a un repositorio).
"""
import json
import os

from cryptography.fernet import Fernet, InvalidToken

from .db import DATA_DIR

KEY_FILE = DATA_DIR / "secret.key"
_fernet: Fernet | None = None


def _get() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.getenv("SECRET_KEY", "").strip()
        if not key:
            if KEY_FILE.exists():
                key = KEY_FILE.read_text().strip()
            else:
                KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
                key = Fernet.generate_key().decode()
                KEY_FILE.write_text(key)
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt(data: dict) -> str:
    return _get().encrypt(json.dumps(data).encode()).decode()


def decrypt(token: str) -> dict:
    try:
        return json.loads(_get().decrypt(token.encode()))
    except InvalidToken as exc:
        raise RuntimeError("No se pueden descifrar los datos de la integración: la clave SECRET_KEY ha cambiado.") from exc
