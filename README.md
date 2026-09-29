# ProyectoChats

Asistente IA para equipos que atienden clientes por varios canales. Unifica las conversaciones de un
mismo cliente (email, WhatsApp, Telegram…) y permite preguntar por un dato concreto sin leer los hilos.

- **Frontend:** HTML + CSS + JavaScript sin frameworks (`frontend/`).
- **Backend:** Python + FastAPI (`backend/`).
- **Base de datos:** SQLite con índice de texto completo FTS5 (ignora tildes).
- **IA:** Claude (API de Anthropic) con herramientas de búsqueda sobre la base de datos.

## Puesta en marcha (Windows)

1. Instala Python 3.12 o superior: `winget install Python.Python.3.12` (o desde python.org).
2. En una terminal, dentro de `backend/`:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   copy .env.example .env      # y pon tu ANTHROPIC_API_KEY
   python -m app.seed          # datos de demostración (opcional)
   uvicorn app.main:app --reload
   ```

3. Abre http://localhost:8000

## Cómo funciona

```
frontend (navegador) ──HTTP──▶ FastAPI ──▶ SQLite (clientes, conversaciones, mensajes + FTS5)
                                   │
                                   └──▶ Claude  ◀─ herramientas: buscar_cliente, resumen_cliente,
                                                                buscar_mensajes, leer_contexto
```

- **Cliente unificado:** un cliente tiene varias *identidades* (email, número, @usuario). Todas las
  conversaciones de esas identidades cuelgan del mismo cliente, sea cual sea el canal.
- **Uso compartido:** cada conversación pertenece a un usuario del equipo. Por defecto el agente busca
  solo en las tuyas; si le pides explícitamente buscar en las del equipo, usa el alcance `equipo`.
  El filtro se aplica en el servidor (`backend/app/search.py`), no depende del modelo.
- **Trazabilidad:** cada respuesta muestra qué búsquedas hizo el agente y si salió de tus conversaciones
  o de las del equipo.

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/users` | Usuarios del equipo |
| GET | `/api/clients?q=` | Buscar clientes |
| GET | `/api/clients/{id}` | Ficha: identidades y conversaciones |
| GET | `/api/clients/{id}/timeline?scope=mine\|team&channel=` | Mensajes unificados en orden cronológico |
| GET | `/api/search?q=&scope=&client_id=` | Búsqueda directa de texto |
| POST | `/api/import` | Importar una conversación (base para integraciones) |
| POST | `/api/chat` | Hablar con el agente |

Todas (salvo `/api/users` y `/api/clients`) requieren la cabecera `X-User-Id` — identificación
provisional hasta que haya login.

## Limitaciones actuales / siguientes pasos

- Autenticación real (login, contraseñas o SSO) en lugar de la cabecera `X-User-Id`.
- Las sesiones de chat del agente viven en memoria: se pierden al reiniciar el servidor.
- Integraciones reales de canales (IMAP/Gmail, WhatsApp Business API, bot de Telegram) usando `/api/import`.
- Búsqueda semántica (embeddings) además de FTS, para preguntas sin palabras clave exactas.
- Fusión manual de clientes duplicados y detección automática de identidades del mismo cliente.
- Respuestas en streaming en el chat.
