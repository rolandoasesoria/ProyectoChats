# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado semántico.
Cómo se mantiene: [`docs/CONTROL_DE_VERSIONES.md`](docs/CONTROL_DE_VERSIONES.md).

## [Sin publicar]

### Añadido
- **Mi perfil** (menú de usuario): cada uno cambia su foto de perfil, su nombre, su email, el tema y la
  contraseña. La foto se recorta en cuadrado al subirla y se ve arriba a la derecha, como responsable en
  Detalles, en la lista para asignar y en Administración > Usuarios.
- Test `test_ui_campos.py`: recorre con el ratón y el teclado reales los 155 desplegables, campos y casillas de
  todas las pantallas y ventanas (que abran, dejen elegir o escribir y no estén tapados). Va en `run_tests.ps1 -Todas`.
- Permiso **«Puede ver los chats de todo el equipo»**: un administrador se lo da a un usuario al crearlo o después
  (Administración → Usuarios), y ese usuario puede elegir «Todo el equipo» en Mis Chats. Migración
  `0004_permiso_chats_equipo.sql`.
- **Piezas propias en lugar de las del navegador** (`frontend/ui.js`): tooltips en burbuja, listas de los
  desplegables con teclado (flechas, Intro, Esc y escribir para saltar), avisos flotantes en lugar de `alert`, y
  confirmaciones y preguntas en ventanas de la app (botón en rojo para borrar). Casillas, interruptor, plegables y
  barras de desplazamiento con el estilo de la app.
- **Ruta de navegación más visual**: marca de la empresa, icono de la sección, avatar del contacto, separadores finos
  y el nivel actual resaltado.
- **Barra lateral más informativa**: al pasar el ratón, el icono se despliega con su nombre y un detalle en vivo;
  contadores de chats sin leer (en rojo si hay respuestas fuera de plazo), tareas y propuestas de la IA por revisar;
  secciones agrupadas por uso (trabajo, IA, textos, análisis). Ruta nueva `GET /api/me/counts`.
- **Detalles del contacto rediseñados**: identidad centrada (avatar con color propio, estado, prioridad de la IA),
  acciones rápidas por canal y «Editar», y tarjetas de Contacto (copiar con un clic), Responsable, Etiquetas,
  Datos clave y Actividad. Los avatares tienen un color por persona en toda la app.
- Plantillas por **cuenta de WhatsApp Business de Meta**: en la sección Plantillas se elige la cuenta (no el número) y
  se ve qué números comparten sus plantillas. En «Mis cuentas», cada número de WhatsApp muestra su cuenta de Meta y
  con quién comparte plantillas, y avisa si está en una cuenta distinta de la del resto del equipo.
- Las ventanas (Administración, Mis cuentas, editar cliente…) se cierran también con un clic fuera de ellas.
- Administración → Usuarios: «Crear usuario» solo lo crea y **«Crear y añadir cuentas»** abre después
  **«Cuentas de …»** para conectarle su correo, bot de
  Telegram o WhatsApp Business; la columna **«Cuentas conectadas»** muestra las de cada persona (⚠ si alguna no
  conecta) y el botón «Cuentas» de cada fila permite verlas, añadir o quitar.
- **Vista de contacto única**: al abrir un chat (Mis Chats) o un contacto (Contactos) se ve lo mismo: a la izquierda
  la lista de la que vienes (en Contactos, la de contactos con «← Volver a la tabla»), en el centro el contacto con
  las pestañas **Conversación · Ficha · Tareas · Notas** y a la derecha Detalles / Asistente IA. La ficha ya no saca
  de Mis Chats. La ruta de navegación añade la pestaña abierta.
- La caja de escribir de la conversación reúne lo que tenía el antiguo «Redactar respuesta»: «✨ Redactar con IA» con
  indicaciones, respuestas guardadas (botón o «/»), «✨ Retocar…», «Copiar» sin cuenta conectada y «⏰ Avisar si no
  contesta». El buscador de mensajes se abre con la lupa 🔍.
- Secciones nuevas en la barra lateral: **Tareas** (tus tareas de todos los clientes, con contador) y **Asistente**
  (la consulta general sobre todos los clientes).
- **Menú de la empresa**: arriba de la barra lateral, el logo o las iniciales de la empresa (en lugar de la casita)
  abren su menú: Mis cuentas y, para administradores, Datos de la empresa (nombre y logo PNG/JPG/WebP de hasta
  256 KB), Usuarios del equipo, Ajustes, Propiedades de contacto y Registro de accesos. El nombre de la empresa en la
  ruta de navegación abre el mismo menú.
- Ruta de navegación sobre cada sección: «Empresa › Sección › lo abierto» (chat, contacto o plantilla); pulsar la
  sección vuelve a su lista.
- Administración → Ajustes: **nombre de la empresa**, que encabeza la ruta de navegación.
- Pestañas de canal en «Mensajes» de la ficha (sustituyen al desplegable) y pestaña «Todos los canales» en Mis
  Chats, que junta los mensajes de todos los canales; desde ella se responde por el canal más reciente.
- Mis Chats y Plantillas: el ancho de las columnas se ajusta arrastrando los separadores (o con las flechas; doble
  clic lo restablece), como en la ficha. Se recuerda por página.
- Contactos: las celdas con varios valores (emails, teléfonos, etiquetas) muestran el primero y «+N», que despliega
  el resto; los textos largos se cortan con «…», así las filas no crecen.
- Chats, panel derecho: pestaña **«Asistente IA»** para preguntar al asistente sobre ese contacto sin abrir su ficha
  (es el mismo asistente de la ficha: mismo aspecto y misma conversación).
- Estilo de tarjetas: cada zona de las secciones (lista, conversación, detalles…) es una tarjeta con sombra suave
  sobre el fondo de la ventana; la barra lateral queda aparte. En Chats, la lista y los detalles llevan el tono del
  asistente.
- Tipografía de estilo Apple: San Francisco en los dispositivos de Apple e Inter (fuente libre, incluida en la app)
  en el resto.
- Chats, pestaña Email: «✉ Nuevo correo» escribe un correo nuevo con asunto (hilo nuevo, admite adjunto). Si el
  cliente tiene email pero no hay hilos de correo, la pestaña sale igualmente para escribirle.
- Chats: adjuntar un archivo (📎, hasta 15 MB) al responder por WhatsApp, Telegram o correo; queda en la ficha del
  cliente junto al mensaje.
- **IA que responde** por WhatsApp (sección «IA»): instrucciones del negocio, modo supervisado (propone y una persona
  envía o descarta) o automático, horas de inactividad del equipo antes de entrar, horario (siempre o fuera de la
  oficina) y «Probar la IA». Pasa el chat a una persona si se lo piden, hay una queja o no sabe la respuesta; respeta
  la ventana de 24 h de WhatsApp; máximo 5 respuestas por chat y día; se puede pausar en cada chat y sus mensajes se
  marcan con «🤖 IA». Migración `0003_ia_que_responde.sql`.
- Sección **Plantillas** en la barra lateral: lista de plantillas de cada cuenta de WhatsApp con su estado en Meta,
  vista previa como la verá el cliente, editor con vista previa en directo y borrado. Sustituye a la ventana de
  plantillas de «Mis cuentas».
- Botón **«Plantilla»** en la caja de escribir de Chats (WhatsApp): enviar una plantilla aprobada rellenando sus
  variables (la primera se propone con el nombre del cliente); se guarda en la conversación con el texto rellenado.
- Sección **Contactos** (sustituye a «Clientes» en la barra): tabla de contactos con buscador, filtros por estado,
  etiqueta, agente, canal y no leídos, columnas a elegir y «+ Nuevo contacto»; al pulsar uno se abre su ficha.
- **Propiedades de contacto** (DNI, nacionalidad, fecha de alta…): las define un administrador (texto, número, fecha o
  lista de opciones) en Administración, se rellenan en la ficha, salen como columnas en la tabla, se conservan al unir
  clientes y se incluyen en la exportación de datos. Migración `0002_propiedades_contacto.sql`.
- Buscador rápido (Ctrl+K): «Ir a Chats» e «Ir a Contactos».
- Sección **Chats** en la barra lateral: conversaciones por cliente con el último mensaje y los no leídos («Todos» /
  «No leídos», buscador y, para administradores, «Todo el equipo»), mensajes separados por canal en pestañas, caja
  para escribir y enviar por la cuenta conectada (con «✨ Redactar con IA») y detalles del contacto. La vista anterior
  pasa a ser la sección **Clientes**; el tutorial cambia solo de sección para enseñar cada parte.
- Barra lateral a la izquierda con las secciones (Inicio: panel de actividad; Chats) y, abajo, Mis cuentas,
  Respuestas guardadas y Administración. El menú de usuario queda con el tutorial, la contraseña y cerrar sesión.
- Nueva marca: la app se llama **Hilvana Chat** («Todas tus conversaciones, en un solo hilo»), con logo propio en la
  cabecera, la pantalla de entrada y la pestaña del navegador.
- Túnel fijo para los webhooks de WhatsApp con ngrok (`NGROK_AUTHTOKEN` y `NGROK_DOMAIN` en `.env`): la URL no
  cambia, se pone una sola vez en Meta y el túnel se abre solo al iniciar sesión junto con la app.
- Administración → Ajustes: casilla «Analizar con IA a cada cliente cuando le llegan mensajes» (activada por
  defecto). Desactivada, los mensajes no se envían a Claude hasta pulsar «✨ Actualizar con IA».
- Plantillas de WhatsApp: en «Mis cuentas», «Plantillas» muestra las de cada cuenta con su estado en Meta y
  permite crear una nueva (categoría, idioma, texto con variables y sus ejemplos) y enviarla a revisión.
- WhatsApp Business del móvil en coexistencia: «Conectar con WhatsApp Business» (registro insertado de Meta) conecta
  el número que cada persona ya usa en la app, que sigue funcionando en el móvil. Entran los mensajes recibidos, los
  enviados desde el móvil, hasta 6 meses de historial (sin lanzar la IA) y los nombres de la agenda; si se desconecta
  desde el móvil, la cuenta se pausa y su dueño recibe un aviso. Webhook único de la app en `/api/webhooks/whatsapp`.
- Webhooks de WhatsApp accesibles desde internet sin publicar la app: `scripts/webhook-publico.ps1` arranca una
  puerta que solo atiende `/api/webhooks/...` (`python -m app.webhook_gateway`, en 127.0.0.1:8010) y un túnel de
  Cloudflare hacia ella; «Mis cuentas» muestra la URL pública del webhook para copiarla en Meta.
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
- La bandeja «Sin responder» de todo el equipo también exige el permiso para ver los chats del equipo.
- `GET /api/chats?scope=team` comprueba el permiso en el servidor (antes solo lo escondía la pantalla).
- Conexión a la base de datos cifrada con TLS 1.3 y certificado verificado (`DB_SSLMODE=verify-full`). PostgreSQL
  solo acepta conexiones cifradas y con contraseña SCRAM; con un servidor remoto, la app se niega a conectarse
  sin cifrar.
- Usuarios separados: la app trabaja con `proyectochats_app`, que solo lee y escribe datos; el dueño del
  esquema (`DATABASE_ADMIN_URL`) solo se usa para migrar. `scripts/postgres.ps1 asegurar` lo aplica a una
  instalación existente y cambia las contraseñas (aleatorias, generadas con un generador criptográfico).
- Tiempos límite de conexión y de consulta. `backend/.env`, la contraseña del superusuario y las claves privadas
  quedan legibles solo por el usuario de Windows.

### Cambiado
- **Todas las pantallas con el nuevo sistema de diseño**: la ficha en listas agrupadas al estilo iOS, tareas y
  notas en tarjetas, burbujas tipo iMessage, etiquetas de canal en píldora, tablas unificadas, ajustes de IA
  agrupados y estados vacíos con icono. Misma lógica y mismo funcionamiento.
- **Sistema de diseño con tokens** (tokens.css): botones, campos, tarjetas, ventanas, menús y navegación con
  esquinas al estilo iOS, sombras muy finas, rejilla de 4 px y transiciones suaves; tema claro y oscuro en un solo bloque.
- **Barra superior nueva**: flota sobre el fondo con efecto cristal, saluda por el nombre con la fecha y muestra
  el resumen del día («N sin responder», «N tareas para hoy» o «Todo al día»), que lleva a cada lista.
- **La barra superior sigue el tema**: en claro es clara (de blanco a lavanda) con el logo y los textos en
  índigo; en oscuro, índigo profundo como hasta ahora.
- **Logo nuevo**: dos paredes que forman una H con un bocadillo entre ellas y tres puntos «escribiendo…», con
  la paleta de la app. Versión para fondo claro y oscuro (barra superior y entrada) e icono para la pestaña:
  la H sin fondo, ocupando todo el icono, que cambia de tonos con el tema del navegador.
- **Aspecto más moderno**, con la misma paleta: degradados sutiles en el fondo, la barra superior, las tarjetas,
  los botones principales, las selecciones, las burbujas de los mensajes y los avatares (en tema claro y oscuro).
- **«Sin responder» se ve y funciona como «Todos» y «No leídos»**: la misma lista, el mismo buscador y el mismo
  selector «Mis chats / Todo el equipo»; las acciones (Responder, Atendido, Posponer) aparecen al pasar el ratón.
- **Quién lleva a un cliente es su responsable** (uno solo, o «Sin responsable»), no quien tenga cada conversación:
  desaparece «la lleva X» de los mensajes (queda «cuenta de X», la cuenta por la que entró) y la bandeja dice el
  responsable. En Detalles, el responsable y las etiquetas se cambian directamente, sin abrir «Editar».
- Contacto abierto desde Contactos: el enlace «← Volver a la tabla» pasa a ser una cabecera de la lista
  («Contactos», cuántos hay y si la tabla tiene filtros) con el estilo de las tarjetas.
- Las plantillas de WhatsApp solo las crea y las borra un administrador (son de la empresa y Meta puntúa su
  calidad); los demás usuarios las ven y envían las aprobadas desde el chat.
- «Sin responder» pasa a ser un filtro de Mis Chats («Todos · No leídos · Sin responder»). Desaparece la pantalla
  antigua de la ficha con su columna «Clientes / Sin responder / Tareas»; los atajos g c / g s / g t llevan a
  Contactos, Sin responder y Tareas.
- La sección «IA que responde» pasa a llamarse **«Respuestas con IA»**; a quien no es administrador le avisa
  claramente, arriba, de que solo un administrador puede cambiarla.
- El **Panel de actividad** pasa a ser una sección de la barra lateral (debajo de «Respuestas con IA») en vez de una
  ventana. «Mis cuentas» y «Administración» dejan la barra lateral y pasan al menú de la empresa; el nombre de la
  empresa se cambia en «Datos de la empresa» (ya no en Ajustes).
- La sección «Chats» pasa a llamarse **«Mis Chats»**.
- Código reorganizado sin cambiar el comportamiento: la recepción de WhatsApp en `whatsapp.py`; la bandeja y el
  alta de mensajes fuera de `search.py` (`inbox.py`, `conversations.py`); un único acceso a la API de Meta, a la
  verificación de webhooks y a las llamadas de texto a Claude; el envío desde el borrador en `drafts.js`; un
  autocompletado común para @menciones y /atajos; y utilidades de pruebas compartidas.
- Más reorganización sin cambios de comportamiento: los errores de la API de Claude se traducen en un solo sitio
  (`agent._create`); el turno con el asistente y las reglas de editar un cliente pasan a sus servicios; exportar y
  borrar un cliente pasan a `privacy.py`; la cookie de sesión se lee en `api/deps.py`; `sync_email` dividido; sin
  consultas del cliente duplicadas en los repositorios; un único flujo de chat para el asistente y Chispa.
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
- Una lista desplegable podía cerrarse sola si se abría justo después de desplazar la ventana.
- Los desplegables dentro de una ventana (p. ej. Estado y Responsable en «Editar cliente») no dejaban elegir.
- Chats: al volver de un correo nuevo a otra pestaña, el botón de enviar ya no sigue diciendo «Enviar correo».
- Posibles duplicados: si hay varios (p. ej. el mismo remitente desde varias direcciones), un solo aviso con todos
  y «Unir todos aquí», en vez de un aviso amarillo por cada uno.
- Las casillas dentro de los formularios (Ajustes, respuestas guardadas) quedan alineadas con su texto.
- Correo: la conexión con los servidores IMAP y SMTP comprueba su certificado (antes no se verificaba y la
  contraseña podía acabar en un servidor falso); si no es válido, no se envía la contraseña y se explica.
- Correo: si la carpeta de enviados configurada no existe, se busca la que el servidor marca como enviados (o una
  de nombre habitual), así entran también los correos enviados aunque el nombre no coincida.
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
