# Pruebas

Scripts de Python sin framework: cada uno imprime `OK`/`FAIL` por comprobación y termina con código 1 si algo falla.

```powershell
# Una vez: dependencias de desarrollo
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

# Antes de cada commit: pruebas rápidas (~2 min)
powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1

# Antes de integrar en main: todo, incluido el recorrido en el navegador (Edge en modo invisible)
powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1 -Todas

# Solo algunas
powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1 test_notes_api.py
```

| Tipo | Archivos | Cómo |
|---|---|---|
| Sin servidor | `check_js.py`, `test_importers.py`, `test_insights.py`, `test_agent_tools.py` | Lógica pura; Claude simulado |
| API | `test_*_api.py`, `test_drafts.py`, `test_integrations.py` | Servidor de pruebas en el puerto 8001; la base de pruebas se vacía y se recarga por archivo |
| Interfaz | `test_ui.py` | Edge invisible controlado por DevTools: login, tutorial, pantallas; capturas en `tests/.tmp/shots` |

- **Nunca llaman a la API de Claude**: las respuestas se simulan (no gastan ni necesitan clave).
- Las integraciones se prueban con IMAP/SMTP falsos, API de Telegram simulada y webhook de WhatsApp firmado.
- Usan la base de datos `TEST_DATABASE_URL` de `backend/.env` (la crea `scripts/postgres.ps1 instalar`), que se
  **vacía** en cada archivo: por seguridad, las pruebas se niegan a arrancar si su nombre no contiene «test».
  PostgreSQL tiene que estar en marcha (`scripts/postgres.ps1 iniciar`).
- Todo lo temporal (adjuntos, capturas, perfil del navegador) va a `tests/.tmp/`, ignorado por git.
- Las cifras del panel dependen de las fechas de los datos de ejemplo (julio-septiembre de 2026): la prueba
  usa el periodo de 1 año, válido hasta mediados de 2027. Después habrá que mover las fechas de los datos básicos de `seed.py` (los abundantes ya se generan según hoy).

## Añadir pruebas con cada cambio

Cada funcionalidad nueva llega con su archivo o sus comprobaciones (commit `test(...)`, ver
`docs/CONTROL_DE_VERSIONES.md`). Si cambia la interfaz, actualiza también `test_ui.py`.
