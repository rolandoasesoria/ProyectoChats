"""Configura las pruebas para usar la base de datos de pruebas (TEST_DATABASE_URL de backend/.env) y la
carpeta tests/.tmp para los archivos. Se importa antes que el código de la app.

Salvaguarda: si la base de datos no parece de pruebas (su nombre no contiene "test"), aborta, para no borrar
nunca los datos reales (las pruebas vacían la base de datos).
"""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TMP = Path(__file__).resolve().parent / ".tmp"
TMP.mkdir(exist_ok=True)

url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(BACKEND / ".env").get("TEST_DATABASE_URL")
if not url or "test" not in url.rsplit("/", 1)[-1]:
    sys.exit("Falta TEST_DATABASE_URL (una base de datos cuyo nombre contenga 'test') en backend/.env. "
             "Ejecuta scripts/postgres.ps1 instalar.")
os.environ["DATABASE_URL"] = url
os.environ.setdefault("DATA_DIR", str(TMP))
os.environ["DISABLE_SYNC"] = "true"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
