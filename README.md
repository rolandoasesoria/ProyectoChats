# ProyectoChats

Asistente IA para equipos que atienden clientes por varios canales. Unifica las conversaciones de un
mismo cliente (email, WhatsApp, Telegram…) y permite preguntar por un dato concreto sin leer los hilos.

- **Frontend:** HTML + CSS + JavaScript sin frameworks (`frontend/`).
- **Backend:** Python + FastAPI (`backend/`).
- **Base de datos:** PostgreSQL, con búsqueda de texto en español (sin tildes y por raíz de palabra).
- **IA:** Claude (API de Anthropic) con herramientas de búsqueda sobre la base de datos.

## Puesta en marcha (Windows)

1. Instala Python 3.12 o superior: `winget install Python.Python.3.12` (o desde python.org).
2. Instala PostgreSQL para desarrollo (versión portable, sin permisos de administrador; en la raíz del repositorio):

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 instalar   # una vez
   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 iniciar    # después de reiniciar el equipo
   ```

   Crea las bases `proyectochats` y `proyectochats_test` y guarda la conexión en `backend/.env`.
   (En producción, usa un PostgreSQL gestionado o como servicio y pon su `DATABASE_URL` en `.env`.)
3. En una terminal, dentro de `backend/`:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   # añade a .env tu ANTHROPIC_API_KEY (ver .env.example)
   python -m app.seed --reset      # datos de prueba abundantes (BORRA lo que haya)
   uvicorn app.main:app --reload   # desarrollo
   python -m app.serve             # uso real (lee HOST, PORT, HTTPS... de .env)
   ```

4. Abre http://localhost:8000 e inicia sesión.

**Arranque automático** (opcional): `powershell -ExecutionPolicy Bypass -File scripts/arrancar.ps1 -InstalarInicio`
crea un acceso directo en la carpeta de Inicio de Windows que, al iniciar sesión, arranca PostgreSQL y después la app
sin ventanas (registro en `backend/data/app.log`). `-QuitarInicio` lo desactiva; sin parámetros, arranca todo ahora.

## Usuarios y acceso

- Cada persona entra con **usuario y contraseña**. No hay registro libre: las cuentas las crea un administrador
  desde la app (menú de usuario → *Administrar usuarios*) o desde la consola del servidor.
- Datos de prueba (`python -m app.seed --reset`): `ana` (administradora), `carlos`, `marta`, `lucia`, `javier` y
  `elena`, todos con contraseña `demo1234`. Unos 85 clientes de una empresa de packaging, ~1.500 mensajes de los
  últimos seis meses por email, WhatsApp y Telegram, presupuestos en PDF, tareas (algunas vencidas), notas con
  menciones y dos pares de clientes duplicados a propósito para practicar «Unir». Se generan según la fecha de hoy
  (`backend/app/demo_data.py`). Con `--basico` solo se cargan los 3 clientes que usan las pruebas automáticas.
- Crear el primer administrador en una instalación nueva (sin datos de demostración):

  ```powershell
  python -m app.manage create-user admin "Nombre Apellido" --admin
  python -m app.manage set-password USUARIO     # restablecer una contraseña
  python -m app.manage list-users
  ```

- Contraseñas guardadas con hash scrypt; la sesión va en una cookie HttpOnly válida 30 días.
  Cambiar la contraseña o desactivar una cuenta cierra sus sesiones abiertas.

## Seguridad

- **Fuerza bruta:** tras 5 fallos seguidos un usuario queda bloqueado 15 min (y una IP tras 20).
  Un administrador lo desbloquea antes poniéndole una contraseña nueva. Configurable en `.env` (`LOGIN_*`).
- **Sin pistas a atacantes:** el login tarda lo mismo y responde igual exista o no el usuario.
- **Cabeceras de seguridad** en todas las respuestas: CSP estricta (solo scripts/estilos propios),
  anti-iframe, `nosniff`, HSTS cuando va por HTTPS; las respuestas de la API no se guardan en caché.
- **CSRF:** cookie `SameSite=Lax` + rechazo de peticiones que modifican datos desde otro origen.
- **Límites de tamaño** en mensajes al asistente (4.000 caracteres) y contraseñas (128).
- `/docs` (documentación de la API) desactivado salvo `ENABLE_DOCS=true`.

## Conectar canales (Administración → Integraciones)

Lógica en `backend/app/integrations.py`. Cada integración tiene un responsable: sus mensajes entran como
conversaciones de esa persona, que puede responder desde el borrador con **📤 Enviar**.

| Canal | Cómo entra | Cómo se responde | Requisitos |
|---|---|---|---|
| Email | IMAP cada N minutos (recibidos y enviados; boletines descartados) | SMTP, en el mismo hilo | Gmail/Outlook: contraseña de aplicación |
| Telegram | Bot (`getUpdates` cada minuto) | `sendMessage` del bot | Token de @BotFather; solo chats que escriben al bot |
| WhatsApp | Webhook `/api/webhooks/whatsapp/{id}` con firma verificada | Cloud API de Meta | Cuenta WhatsApp Business, app publicada con HTTPS; ventana de 24 h |

- Contraseñas y tokens se guardan **cifrados** (Fernet). La clave es `SECRET_KEY` en `.env` o, si no existe,
  `backend/data/secret.key` (se genera sola). **Haz copia de seguridad de esa clave junto con la base de datos.**
- La sincronización corre en segundo plano dentro del servidor; `DISABLE_SYNC=true` la desactiva.
- Es la única vía de entrada de mensajes: la app no importa chats exportados, trabaja con las conversaciones
  reales y en tiempo real.

## Protección de datos

- **Registro de accesos** (*Administración → Registro de accesos*): quién ha visto conversaciones de compañeros
  (historial «Equipo», bandeja del equipo, búsquedas propias o del asistente) y acciones delicadas
  (exportar, borrar o unir clientes, cambios en cuentas). Lógica en `backend/app/audit.py`.
- **Derecho de acceso**: exportar en JSON todos los datos de un cliente (*✎ Editar cliente*, solo administradores).
- **Derecho de supresión**: borrar un cliente y todo lo relacionado, confirmando con su nombre.

## Publicar con HTTPS

**Opción recomendada — proxy Caddy** (certificado gratuito de Let's Encrypt, renovación automática):
necesitas un dominio apuntando al servidor. Sigue los pasos de [`deploy/Caddyfile`](deploy/Caddyfile):
en `.env` pon `FORCE_HTTPS=true` y `COOKIE_SECURE=true`, arranca `python -m app.serve` y luego Caddy.

**Opción directa** (p. ej. red interna con certificado propio de la empresa): en `.env` indica
`SSL_CERTFILE` y `SSL_KEYFILE`, `PORT=443` (o el que uséis), `HOST=0.0.0.0`, `FORCE_HTTPS=true`,
`COOKIE_SECURE=true`, y arranca `python -m app.serve`.

En local (`localhost`) se puede seguir usando HTTP para desarrollar.

## Interfaz

- **Ficha del cliente con IA** (`backend/app/insights.py`): una sola llamada a Claude con salida estructurada
  extrae el resumen del estado, los datos clave (cada uno enlazado a su mensaje de origen) y los compromisos
  pendientes como tareas con fecha y responsable. Se lanza con *Actualizar con IA* o sola cuando entran mensajes nuevos.
  Lo editado por personas nunca lo sobrescribe la IA; lo descartado no se vuelve a proponer.
- **Tareas** por cliente y **Mis tareas** (todas las mías, agrupadas por vencimiento).
- **Sin responder**: bandeja de conversaciones cuyo último mensaje es del cliente, por tiempo de espera;
  se pueden marcar como atendidas (vuelven si el cliente escribe otra vez).
- **Novedades**: contador de mensajes no leídos por cliente desde tu última visita y resumen con IA
  de solo lo nuevo.
- **Gestión de clientes**: estado (potencial/activo/incidencia/inactivo), responsable, etiquetas y filtros;
  alta manual; identificadores por canal; detección de posibles duplicados y **unir clientes**.
- **Panel de actividad** (icono de gráfico): mensajes recibidos/enviados, clientes con actividad, mediana de
  primera respuesta, tareas, mensajes por semana y canal, clientes por estado y (administradores) desglose
  por persona. Gráficos en SVG propio con la paleta validada; colores de canal iguales en toda la app.
- **Notas internas** por cliente con **@menciones**, y **campana de avisos** (menciones y tareas asignadas).
- **Borradores de respuesta con IA** (pestaña Mensajes y botón *Responder* de la bandeja): usa el contexto
  de todos los canales, la ficha y las tareas; estilo según el canal; sin inventar datos (deja `[huecos]`).
- **Buscador de mensajes** (pestaña Mensajes): por palabras (índice de PostgreSQL, en español: «entregas»
  encuentra «entrega» y «entreguen»; resaltado) o **✨ por significado**
  (`backend/app/smartsearch.py`): Claude amplía la pregunta en palabras clave, se busca en mensajes y documentos
  y Claude ordena lo relevante con un motivo. Sin proveedor de *embeddings* adicional.
- **Documentos y adjuntos** (`backend/app/attachments.py`): adjuntos de correos, WhatsApp exportado con archivos
  (.zip) y subidas manuales a la ficha. Texto de PDFs al momento (pypdf); fotos y PDF escaneados con IA.
  Todo buscable (asistente con `buscar_documentos`) y usado en el análisis. Archivos en `backend/data/attachments/`.
- **Tema claro/oscuro** (botón sol/luna), guardado en el perfil de cada usuario.
- **Conversaciones con el asistente guardadas por usuario y cliente**; se conservan entre sesiones y dispositivos.
- **Tutorial de bienvenida** la primera vez que se entra (se puede repetir desde el menú de usuario).
- **Chispa**, la mascota de ayuda (esquina inferior derecha), resuelve dudas sobre el uso de la app.

> ⚠️ **Al añadir o cambiar apartados de la interfaz** hay que actualizar el tutorial
> (`TOUR_STEPS` y subir `TOUR_VERSION` en `frontend/tour.js`, para que los usuarios lo vuelvan a ver)
> y la descripción de la app que usa Chispa (`HELP_SYSTEM_PROMPT` en `backend/app/agent.py`).

## Cómo funciona

```
frontend (navegador) ──HTTP──▶ FastAPI ──▶ PostgreSQL (clientes, conversaciones, mensajes + búsqueda en español)
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
| POST | `/api/auth/login` · `/api/auth/logout` | Iniciar / cerrar sesión |
| GET · PATCH | `/api/me` | Perfil propio (tema, versión del tutorial vista) |
| POST | `/api/me/password` | Cambiar la contraseña propia |
| GET · POST | `/api/admin/users` | Listar / crear cuentas (solo administradores) |
| PATCH | `/api/admin/users/{id}` | Editar, restablecer contraseña, activar/desactivar (solo administradores) |
| GET | `/api/clients?q=` | Buscar clientes |
| GET | `/api/clients/{id}` | Ficha: identidades y conversaciones |
| GET | `/api/clients/{id}/timeline?scope=mine\|team&channel=` | Mensajes unificados en orden cronológico |
| GET | `/api/search?q=&scope=&client_id=` | Búsqueda directa de texto |
| POST | `/api/chat` | Hablar con el agente (una conversación por cliente, `client_id`) |
| POST | `/api/help` | Hablar con Chispa, la mascota de ayuda sobre el uso de la app |
| GET | `/api/conversations/{agent\|help}?client_id=` | Conversación guardada para mostrarla |
| GET | `/api/conversations/agent/clients` | Clientes con conversación abierta |
| POST | `/api/conversations/{agent\|help}/reset` | Nueva conversación (archiva la actual) |

Todas salvo el login requieren haber iniciado sesión.

## Desarrollo

- **Control de versiones**: [`docs/CONTROL_DE_VERSIONES.md`](docs/CONTROL_DE_VERSIONES.md) — commits pequeños,
  ramas por funcionalidad, versiones en [`CHANGELOG.md`](CHANGELOG.md). Al clonar, activa los hooks:
  `powershell -ExecutionPolicy Bypass -File scripts/instalar-hooks.ps1`.
- **Pruebas**: [`tests/README.md`](tests/README.md) — `powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1`.

## Limitaciones actuales / siguientes pasos

- SSO (Google / Microsoft) o verificación en dos pasos, si se necesita.
- Ver conversaciones archivadas con el asistente.
- Respuestas en streaming en el chat.
- Plantillas de WhatsApp para escribir fuera de la ventana de 24 h.
- Probar las integraciones con cuentas reales (hasta ahora verificadas con servidores simulados).
