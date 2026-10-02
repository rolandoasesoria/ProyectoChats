# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado semántico.
Cómo se mantiene: [`docs/CONTROL_DE_VERSIONES.md`](docs/CONTROL_DE_VERSIONES.md).

## [Sin publicar]

### Añadido
- WhatsApp: «Conectar y probar» pregunta a Meta por el número y dice si el access token, el Phone number ID y el app
  secret son correctos; después se comprueba sola cada 6 horas («↻ Comprobar ahora» para hacerlo al momento).
- Si un servicio deja de aceptar las credenciales (token de WhatsApp o de Telegram caducado o revocado, contraseña de
  correo cambiada), la cuenta queda marcada con el motivo y su dueño recibe un aviso en la campana, una sola vez.
- Ancho ajustable de las zonas: se arrastra la línea entre clientes, ficha y asistente (o con Tab y las flechas;
  doble clic la restablece). Cada navegador recuerda el ancho elegido.
- Identidad de color propia: paleta lavanda (#F8EBF6, #E7D7EA, #DBD1EC, #CECFEB, #B2BFDE) en fondos, columna de
  clientes, conversación, selecciones y bordes, con un índigo de la misma familia (#4F4E96) para botones y
  enlaces (contraste AA). Franja con la paleta en la barra superior, marca en degradado y pantalla de entrada
  a juego. El tema oscuro usa el azul pervinca como color principal.
- Barra superior en índigo profundo con la franja de la paleta como borde, y el asistente con fondo pervinca
  suave y respuestas en burbujas blancas, para distinguir cada zona. Email pasa a naranja y Telegram a azul.

### Seguridad
- Conexión a la base de datos cifrada con TLS 1.3 y certificado verificado (`DB_SSLMODE=verify-full`). PostgreSQL
  solo acepta conexiones cifradas y con contraseña SCRAM; con un servidor remoto, la app se niega a conectarse
  sin cifrar.
- Usuarios separados: la app trabaja con `proyectochats_app`, que solo lee y escribe datos; el dueño del
  esquema (`DATABASE_ADMIN_URL`) solo se usa para migrar. `scripts/postgres.ps1 asegurar` lo aplica a una
  instalación existente y cambia las contraseñas (aleatorias, generadas con un generador criptográfico).
- Tiempos límite de conexión y de consulta. `backend/.env`, la contraseña del superusuario y las claves privadas
  quedan legibles solo por el usuario de Windows.

### Cambiado
- Si una foto o un documento de WhatsApp no se puede descargar, el mensaje se guarda igualmente con una nota (antes
  se perdía el mensaje entero).
- Un administrador que conecta o edita la cuenta de otra persona también la prueba al momento.
- Con la ventana estrecha se mantienen siempre las tres zonas (antes se ocultaba el asistente y se apilaban).
- El esquema de la base de datos sale del código Python a migraciones SQL versionadas
  (`backend/database/migrations`), con control de cambios (`schema_migrations`) y los comandos
  `python -m app.manage migrate` y `db-status`.
- Toda la configuración se lee en un único módulo (`backend/app/config.py`).
- Código organizado por capas (Clean Code / SOLID): rutas HTTP por área en `backend/app/api/`, reglas de negocio
  en los servicios y todo el SQL en `backend/app/repositories/`. `main.py` pasa de ~1.150 a ~110 líneas.
- La lógica lanza errores de dominio (`backend/app/errors.py`) y un único traductor los convierte en respuestas
  HTTP; ya no depende de FastAPI y se puede usar igual desde la consola.
- Ninguna consulta mete valores en el texto SQL (plazos e intervalos van como parámetros) y las actualizaciones
  dinámicas solo aceptan columnas de una lista permitida.
- Comprobación de estilo con `ruff` (`backend/ruff.toml`).
- Se quita la importación de chats exportados (botón «Importar»): los mensajes entran solo por las
  integraciones, en tiempo real. La lectura de correos pasa a `backend/app/emails.py`.
- Pestaña «Mensajes» al estilo de un chat: burbujas del cliente a la izquierda y del equipo a la derecha,
  separadores por día, mensajes seguidos agrupados y la caja de respuesta debajo de la conversación.
- La ficha del cliente y sus mensajes pasan al centro y el asistente a la columna derecha; Chispa se mueve
  abajo a la izquierda para no tapar el botón de enviar.
- **La base de datos pasa de SQLite a PostgreSQL**: pool de conexiones, esquema con tipos propios e índices GIN.
  `scripts/postgres.ps1` instala PostgreSQL portable para desarrollo (sin permisos de administrador).
- Búsqueda de texto en español: sin tildes y por raíz de palabra («entregas» encuentra «entrega» y «entreguen»).
  La búsqueda de clientes ya no distingue mayúsculas ni tildes.
- Las pruebas usan su propia base de datos (`TEST_DATABASE_URL`) y se niegan a vaciar una que no sea de pruebas.
- Las pruebas nunca llaman a la API de Claude aunque `backend/.env` tenga clave (`DISABLE_AI=true`).
- Aspecto más sobrio y minimalista: paneles a sangre separados por líneas, colores neutros, etiquetas de canal
  con un punto de color, controles más finos y Chispa más discreta. Solo queda el emoji ✨ para marcar lo que
  hace la IA.
- Tutorial más breve: 12 pasos de una o dos frases (versión 14).

### Añadido
- «Mis cuentas» (menú de usuario): cada persona conecta su correo, su bot de Telegram o su WhatsApp Business;
  la cuenta se prueba al conectarla y el correo se configura eligiendo el proveedor (Gmail, Outlook, Yahoo,
  iCloud…). Sustituye a la pestaña de administración «Integraciones» (los administradores ven «Todo el equipo»).
- Etiquetas en «Editar cliente» con desplegable (las básicas y las que ya usa el equipo) y la opción de
  escribir una nueva.
- El estado del cliente lo decide la IA al analizarlo (también automáticamente cuando entran mensajes por una
  integración), con su motivo y aviso al responsable si hay una incidencia. Se puede cambiar a mano pulsando el
  estado; el cambio manual se respeta hasta que haya mensajes nuevos. Sin IA, regla diaria de inactividad
  (Ajustes, 90 días) y reactivación al volver a escribir.
- Respuestas guardadas para todo el equipo, con variables ({nombre}, {empresa}, {dato:CIF}…) y atajos: en el
  borrador se insertan con un botón o escribiendo /atajo. Con acciones (estado, etiqueta, marcar atendida)
  funcionan como macros.
- Aviso de colisión: quién más tiene abierto el cliente o le está respondiendo, y aviso al enviar o copiar si
  ha llegado algo nuevo a la conversación mientras escribías.
- Protección de datos: buscar y ocultar IBAN, DNI/NIE y tarjetas en los mensajes de un cliente, y plazo de
  conservación de mensajes (Ajustes) con vista previa de lo que se borraría.
- La IA detecta la prioridad (alta, media, baja) y el tono del cliente al analizarlo; se ve en la ficha y en
  «Sin responder».
- Plazo de respuesta (Administración > Ajustes): «vence en…» en la bandeja, rojo al pasarse y «Respondidas en
  plazo» en el panel, también por persona.
- Paleta de comandos (Ctrl+K) para abrir clientes y lanzar acciones, y atajos de teclado (j/k, r, g c/s/t, ?).
- Posponer conversaciones de «Sin responder» (vuelven en la fecha elegida o si el cliente escribe) y
  seguimientos: «avísame si no contesta en X días» al enviar o copiar una respuesta.
- «✨ Retocar» en el borrador: más formal, más cercano, más corto, corregir ortografía o traducir, con «Deshacer».
- `scripts/arrancar.ps1`: arranca PostgreSQL y la app sin ventanas, y opcionalmente al iniciar sesión en Windows.
- Datos de prueba abundantes (`python -m app.seed --reset`): ~85 clientes, 6 personas, ~1.500 mensajes de los
  últimos seis meses, presupuestos en PDF, tareas, notas con menciones y clientes duplicados para practicar.
- Guía de control de versiones: un cambio lógico por commit, Conventional Commits en español, ramas por
  funcionalidad y versionado semántico.
- Hooks de git (`.githooks/`): formato del mensaje, bloqueo de secretos y datos, aviso y límite de tamaño.
  Se activan con `scripts/instalar-hooks.ps1`.
- Plantilla de mensaje de commit (`.gitmessage`) y fines de línea uniformes (`.gitattributes`).
- Pruebas dentro del repositorio (`tests/`), con `tests/run_tests.ps1` y dependencias en
  `backend/requirements-dev.txt`.
- Bandeja «Sin responder»: «Mías · Todo el equipo» con el número de cada lado, y cada conversación
  dice quién la lleva.

### Corregido
- Tras actualizar la app, recargar con F5 podía mezclar archivos viejos y nuevos y dejar la lista de clientes
  vacía: ahora el navegador comprueba siempre si hay versión nueva de la interfaz.
- La lista de clientes mostraba como mucho 50.
- En la pestaña «Tareas» de la columna izquierda las casillas se estiraban y el texto quedaba fuera de la vista.
- En «Sin responder», al elegir «Equipo» el selector desaparecía.
- Pestaña «Mensajes»: el selector «Mías/Equipo», confuso junto al de la bandeja, se sustituye por el historial
  completo (con «la lleva…» en lo de los compañeros) y la casilla «Solo mis conversaciones». Ver el historial
  completo solo se anota en el registro de accesos si contiene conversaciones de otras personas.

## [0.2.0] - 2026-09-29

Commit `6e8d047`. Agrupa todo el trabajo siguiente, anterior a la guía de control de versiones:

### Añadido
- Inicio de sesión con usuario y contraseña, administración de cuentas y comando `python -m app.manage`.
- Conversaciones con el asistente guardadas por usuario y cliente; una conversación por cliente.
- Chispa, la mascota de ayuda sobre el uso de la app.
- Tema claro y oscuro guardado en el perfil; tutorial de bienvenida versionado (versión 12).
- Importar exportaciones de WhatsApp (.txt/.zip), Telegram (.json) y email (.eml/.mbox).
- Ficha del cliente con IA (resumen, datos clave con su mensaje de origen) y tareas detectadas.
- Bandeja «Sin responder», no leídos y resumen de novedades.
- Borradores de respuesta con IA.
- Notas internas con @menciones y campana de avisos.
- Gestión de clientes: estado, responsable, etiquetas, filtros, identificadores y unir duplicados.
- Protección de datos: registro de accesos, exportar y borrar los datos de un cliente.
- Panel de actividad con gráficos.
- Documentos y adjuntos (texto de PDF, lectura de imágenes con IA).
- Buscador por palabras y por significado.
- Integraciones: email (IMAP/SMTP), bot de Telegram y WhatsApp Business, con envío desde la app.

### Seguridad
- Bloqueo por intentos fallidos, cabeceras de seguridad (CSP, HSTS…), protección CSRF, límites de tamaño.
- Preparado para HTTPS (Caddy o certificado propio); secretos de integraciones cifrados.

## [0.1.0] - 2026-09-29

Commit `c360944`. Base del proyecto:

### Añadido
- Backend FastAPI con SQLite y búsqueda de texto completo (FTS5).
- Clientes unificados con identidades por canal y conversaciones de cada miembro del equipo.
- Asistente con Claude y herramientas de búsqueda, con alcance «mías» o «equipo» aplicado en el servidor.
- Interfaz en tres columnas (clientes, asistente, línea de tiempo) y datos de ejemplo.

[Sin publicar]: https://github.com/rolandoasesoria/ProyectoChats/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/rolandoasesoria/ProyectoChats/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rolandoasesoria/ProyectoChats/releases/tag/v0.1.0
