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
| API | `test_*_api.py`, `test_drafts.py`, `test_integrations.py` | Servidor de pruebas en el puerto 8001 con BD nueva por archivo |
| Interfaz | `test_ui.py` | Edge invisible controlado por DevTools: login, tutorial, pantallas; capturas en `tests/.tmp/shots` |

- **Nunca llaman a la API de Claude**: las respuestas se simulan (no gastan ni necesitan clave).
- Las integraciones se prueban con IMAP/SMTP falsos, API de Telegram simulada y webhook de WhatsApp firmado.
- Todo lo temporal (bases de datos, capturas, perfil del navegador) va a `tests/.tmp/`, ignorado por git.
- Las cifras del panel dependen de las fechas de los datos de ejemplo (julio-septiembre de 2026): la prueba
  usa el periodo de 1 año, válido hasta mediados de 2027. Después habrá que mover las fechas de `seed.py`.

## Añadir pruebas con cada cambio

Cada funcionalidad nueva llega con su archivo o sus comprobaciones (commit `test(...)`, ver
`docs/CONTROL_DE_VERSIONES.md`). Si cambia la interfaz, actualiza también `test_ui.py`.
