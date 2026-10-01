# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado semántico.
Cómo se mantiene: [`docs/CONTROL_DE_VERSIONES.md`](docs/CONTROL_DE_VERSIONES.md).

## [Sin publicar]

### Cambiado
- **La base de datos pasa de SQLite a PostgreSQL**: pool de conexiones, esquema con tipos propios e índices GIN.
  `scripts/postgres.ps1` instala PostgreSQL portable para desarrollo (sin permisos de administrador).
- Búsqueda de texto en español: sin tildes y por raíz de palabra («entregas» encuentra «entrega» y «entreguen»).
  La búsqueda de clientes ya no distingue mayúsculas ni tildes.
- Las pruebas usan su propia base de datos (`TEST_DATABASE_URL`) y se niegan a vaciar una que no sea de pruebas.
- Aspecto más sobrio y minimalista: paneles a sangre separados por líneas, colores neutros, etiquetas de canal
  con un punto de color, controles más finos y Chispa más discreta. Solo queda el emoji ✨ para marcar lo que
  hace la IA.
- Tutorial más breve: 12 pasos de una o dos frases (versión 14).

### Añadido
- Respuestas guardadas para todo el equipo, con variables ({nombre}, {empresa}, {dato:CIF}…) y atajos: en el
  borrador se insertan con un botón o escribiendo /atajo. Con acciones (estado, etiqueta, marcar atendida)
  funcionan como macros.
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
