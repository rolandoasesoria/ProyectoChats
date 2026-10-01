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

env_file = dotenv_values(BACKEND / ".env")
url = os.environ.get("TEST_DATABASE_URL") or env_file.get("TEST_DATABASE_URL")
admin_url = os.environ.get("TEST_DATABASE_ADMIN_URL") or env_file.get("TEST_DATABASE_ADMIN_URL") or ""
for u in filter(None, (url, admin_url)):
    if "test" not in u.split("?", 1)[0].rsplit("/", 1)[-1]:
        sys.exit("Las bases de datos de pruebas (TEST_DATABASE_URL, TEST_DATABASE_ADMIN_URL) deben tener 'test' "
                 "en el nombre.")
if not url:
    sys.exit("Falta TEST_DATABASE_URL en backend/.env. Ejecuta scripts/postgres.ps1 instalar.")
os.environ["DATABASE_URL"] = url
os.environ["DATABASE_ADMIN_URL"] = admin_url  # usuario dueño: vaciar y migrar la base de datos de pruebas
os.environ.setdefault("DATA_DIR", str(TMP))
os.environ["DISABLE_SYNC"] = "true"
os.environ["DISABLE_AI"] = "true"  # las pruebas nunca llaman a la API de Claude de verdad
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
