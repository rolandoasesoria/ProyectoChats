from pathlib import Path

from dotenv import load_dotenv

# Carga backend/.env antes de que cualquier módulo lea variables de entorno.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
