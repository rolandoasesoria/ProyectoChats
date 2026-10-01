"""Agente conversacional: Claude + herramientas de búsqueda sobre las conversaciones."""
import json
import os
from datetime import date

import anthropic

from . import attachments, audit, insights, notes, search

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT = """Eres el asistente de un equipo que atiende clientes por varios canales \
(email, WhatsApp, Telegram, etc.). Tu trabajo es encontrar datos concretos dentro del historial \
de conversaciones para que el usuario no tenga que leerlas enteras.

Cómo trabajar:
- Usa las herramientas para buscar; no inventes datos. Si no encuentras algo, dilo y sugiere otra búsqueda.
- Si el usuario nombra a un cliente, localízalo con `buscar_cliente` antes de buscar mensajes.
- Prueba varias palabras clave y sinónimos cuando la primera búsqueda no dé resultados \
(p. ej. "teléfono", "móvil", "número"). Usa `leer_contexto` para confirmar un dato ambiguo.
- Si el dato puede estar en un documento (factura, presupuesto, contrato, foto de un albarán), \
busca también con `buscar_documentos`.
- Alcance: por defecto busca solo en las conversaciones del usuario (alcance "mias"). \
Usa alcance "equipo" únicamente cuando el usuario lo pida de forma explícita \
(p. ej. "busca también en las de mis compañeros", "¿alguien del equipo habló de...?"). \
Si no encuentras nada en las suyas y crees que el equipo podría tenerlo, ofrécelo en vez de hacerlo.
- Al dar un dato, indica de dónde sale: canal, fecha y, si es de otra persona del equipo, quién llevaba esa conversación.
- Responde en español, breve y directo. Usa listas cuando haya varios datos."""

SCOPE_PROP = {
    "type": "string",
    "enum": ["mias", "equipo"],
    "description": "'mias' = solo conversaciones del usuario actual (por defecto). "
                   "'equipo' = también las de sus compañeros; solo si el usuario lo pidió explícitamente.",
}

TOOLS = [
    {
        "name": "buscar_cliente",
        "description": "Busca clientes por nombre, empresa o identificador de canal (email, teléfono, @usuario). "
                       "Devuelve id, nombre y canales por los que se ha hablado con cada uno.",
        "input_schema": {
            "type": "object",
            "properties": {"texto": {"type": "string", "description": "Nombre, empresa, email, teléfono..."}},
            "required": ["texto"],
        },
    },
    {
        "name": "resumen_cliente",
        "description": "Ficha de un cliente: identidades por canal, conversaciones (canal, responsable del "
                       "equipo, nº de mensajes, fechas), resumen del estado, datos clave (dirección, CIF, "
                       "forma de pago...), tareas abiertas y notas internas del equipo. Consúltala primero: muchas preguntas se "
                       "responden aquí sin buscar en los mensajes.",
        "input_schema": {
            "type": "object",
            "properties": {"cliente_id": {"type": "integer"}},
            "required": ["cliente_id"],
        },
    },
    {
        "name": "buscar_mensajes",
        "description": "Búsqueda de texto completo en los mensajes (ignora tildes, admite prefijos). "
                       "Devuelve fragmentos con el término entre corchetes, id de mensaje, canal, fecha y responsable. "
                       "Pasa palabras clave, no frases largas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "Palabras clave; se combinan con OR."},
                "cliente_id": {"type": "integer", "description": "Limita la búsqueda a un cliente."},
                "alcance": SCOPE_PROP,
                "canales": {"type": "array", "items": {"type": "string"},
                            "description": "Filtra por canal: email, whatsapp, telegram..."},
                "desde": {"type": "string", "description": "Fecha mínima ISO (YYYY-MM-DD)."},
                "hasta": {"type": "string", "description": "Fecha máxima ISO (YYYY-MM-DD)."},
                "limite": {"type": "integer", "description": "Máximo de resultados (por defecto 20, máx. 50)."},
            },
            "required": ["consulta", "alcance"],
        },
    },
    {
        "name": "buscar_documentos",
        "description": "Busca en los documentos y adjuntos de los clientes (PDF, fotos leídas con IA, facturas, "
                       "presupuestos...) por nombre de archivo y contenido. Úsala cuando el dato pueda estar en un "
                       "documento en vez de en un mensaje (importes de facturas, referencias, condiciones firmadas).",
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "Palabras clave; se combinan con OR."},
                "cliente_id": {"type": "integer", "description": "Limita la búsqueda a un cliente."},
                "alcance": SCOPE_PROP,
            },
            "required": ["consulta", "alcance"],
        },
    },
    {
        "name": "leer_contexto",
        "description": "Lee los mensajes anteriores y posteriores a un mensaje concreto de la misma conversación, "
                       "para entender o confirmar un dato encontrado con buscar_mensajes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mensaje_id": {"type": "integer"},
                "alcance": SCOPE_PROP,
                "ventana": {"type": "integer", "description": "Mensajes a cada lado (por defecto 8)."},
            },
            "required": ["mensaje_id", "alcance"],
        },
    },
]

_SCOPE_MAP = {"mias": "mine", "equipo": "team"}


def _run_tool(name: str, args: dict, user_id: int) -> object:
    scope = _SCOPE_MAP.get(args.get("alcance", "mias"))
    if scope is None:
        raise ValueError("alcance debe ser 'mias' o 'equipo'")
    if name == "buscar_cliente":
        return search.find_clients(str(args["texto"]), limit=10)
    if name == "resumen_cliente":
        client_id = int(args["cliente_id"])
        overview = search.client_overview(client_id, user_id)
        if not overview:
            return {"error": "cliente no encontrado"}
        ficha = insights.profile(client_id)
        return {**overview, "resumen": ficha["summary"],
                "datos_clave": [{"dato": f["label"], "valor": f["value"],
                                 "origen": "IA" if f["origin"] == "ai" else "confirmado"} for f in ficha["facts"]],
                "tareas_abiertas": [{"tarea": t["title"], "vence": t["due_date"], "responsable": t["assignee"]}
                                    for t in insights.list_tasks(client_id=client_id, status="open")],
                "notas_internas": [{"autor": n["author"], "fecha": n["created_at"][:10], "nota": n["body"]}
                                   for n in notes.list_notes(client_id)[:20]]}
    if name == "buscar_documentos":
        fts = search._fts_query(str(args["consulta"]))
        if not fts:
            return {"resultados": 0}
        if scope == "team":
            audit.log(user_id, "assistant_team_search", args.get("cliente_id"), detail=f"documentos: {args['consulta']}"[:200])
        found = attachments.search(fts, user_id, scope, client_id=args.get("cliente_id"))
        return found or {"resultados": 0, "nota": f"Sin documentos que coincidan en alcance '{args.get('alcance')}'."}
    if scope == "team" and name in ("buscar_mensajes", "leer_contexto"):
        audit.log(user_id, "assistant_team_search", args.get("cliente_id"),
                  detail=str(args.get("consulta") or f"contexto del mensaje {args.get('mensaje_id')}")[:200])
    if name == "buscar_mensajes":
        results = search.search_messages(
            str(args["consulta"]), user_id, scope,
            client_id=args.get("cliente_id"), channels=args.get("canales"),
            date_from=args.get("desde"), date_to=args.get("hasta"),
            limit=int(args.get("limite", 20)),
        )
        return results or {"resultados": 0, "nota": f"Sin coincidencias en alcance '{args.get('alcance')}'."}
    if name == "leer_contexto":
        ctx = search.message_context(int(args["mensaje_id"]), user_id, scope, int(args.get("ventana", 8)))
        return ctx or {"error": "mensaje no encontrado o fuera del alcance permitido"}
    raise ValueError(f"herramienta desconocida: {name}")


# IMPORTANTE: si se añaden o cambian apartados de la interfaz, actualiza también esta descripción
# (y TOUR_STEPS / TOUR_VERSION en frontend/tour.js).
HELP_SYSTEM_PROMPT = """Eres Chispa, la mascota y guía de ProyectoChats. Resuelves dudas sobre cómo usar la app. \
No tienes acceso a los datos de los clientes: si te preguntan por un cliente o un dato concreto, \
explica que eso lo responde el asistente del panel central tras seleccionar al cliente.

Qué es ProyectoChats: una app para equipos que atienden clientes por varios canales (email, WhatsApp, Telegram...). \
Reúne todas las conversaciones de un mismo cliente y tiene un asistente de IA que busca datos en ellas \
para no tener que leerlas enteras.

Cómo se usa:
- Inicio de sesión: cada persona entra con su usuario y contraseña. Las cuentas las crea un administrador; \
no hay registro libre. Si alguien olvida su contraseña, un administrador puede ponerle una nueva. \
Por seguridad, tras 5 intentos fallidos seguidos la cuenta se bloquea 15 minutos; \
un administrador puede desbloquearla antes poniéndole una contraseña nueva. \
Las contraseñas deben tener entre 8 y 128 caracteres.
- Menú de usuario (arriba a la derecha, con tu nombre): "Ver tutorial" repite el recorrido de bienvenida, \
"Cambiar contraseña", "Administración" (solo administradores) y "Cerrar sesión".
- Campana (arriba a la derecha): avisos de menciones en notas y de tareas que otra persona te asigna. El número rojo son los no leídos; al pulsar un aviso se abre el cliente (en Notas o Tareas). "Marcar todo como leído" los limpia.
- Botón del gráfico de barras (arriba a la derecha): "Panel de actividad". Periodo de 7, 30, 90 días o 1 año. \
Muestra mensajes recibidos y enviados, clientes con actividad, la mediana del tiempo de primera respuesta (desde el \
primer mensaje del cliente sin contestar hasta la respuesta del equipo), el porcentaje respondido dentro del plazo de \nrespuesta, tareas abiertas y vencidas, mensajes \
recibidos por semana y canal (al pasar el ratón por una columna se ven las cifras; "Ver como tabla" las muestra \
todas) y clientes por estado. Los administradores ven además una tabla por persona: tiempo de primera respuesta, \
respuestas, conversaciones esperando, tareas abiertas y vencidas, y clientes de los que es responsable.
- Colores de canal (iguales en toda la app): email azul, Telegram naranja, WhatsApp verde agua.
- Botón de sol/luna (arriba a la derecha): cambia entre tema claro y oscuro. La preferencia se guarda en tu perfil.
- Administración (solo administradores), pestaña "Usuarios": crear cuentas, cambiar nombre, email o rol \
(usuario/administrador), restablecer contraseñas y desactivar cuentas. Una cuenta desactivada no puede entrar pero \
sus conversaciones se conservan. Pestaña "Registro de accesos": quién ha visto mensajes del equipo (historial \
de un cliente con conversaciones de compañeros, bandeja del equipo, búsquedas propias o del asistente en conversaciones de compañeros) y quién ha \
exportado, borrado o unido clientes o cambiado cuentas; filtrable por persona y acción. Las consultas repetidas \
en 10 minutos cuentan como una. Pestaña "Ajustes": el plazo de respuesta del equipo en horas (24 por \ndefecto, de 1 a 168).
- Administración, pestaña "Integraciones" (solo administradores): conecta canales para que los mensajes entren \
solos y se pueda responder desde la app. Cada integración tiene un responsable: sus mensajes quedan como \
conversaciones de esa persona, y solo ella (o un administrador) puede enviar por ella. Contraseñas y tokens se \
guardan cifrados. Tipos: (1) Email por IMAP/SMTP: dirección, contraseña (Gmail y Outlook piden una "contraseña de \
aplicación" con verificación en dos pasos), servidores (Gmail: imap.gmail.com y smtp.gmail.com, carpeta de enviados \
"[Gmail]/Enviados"; Outlook: outlook.office365.com y smtp.office365.com, puerto 587). Se revisa cada pocos minutos \
(configurable) recibidos y enviados; la primera vez trae los últimos 30 días; boletines y correos automáticos se \
descartan; remitentes nuevos crean cliente. (2) Telegram: token de un bot creado con @BotFather; entran los mensajes \
que los clientes escriben al bot (un bot no puede leer chats personales) y se les puede responder. (3) WhatsApp \
Business (Cloud API de Meta): phone number ID, access token y app secret; hay que copiar la URL del webhook y el \
verify token que muestra la app en Meta y suscribirse a "messages"; requiere la app publicada con HTTPS; Meta solo \
permite respuestas libres dentro de las 24 h desde el último mensaje del cliente. "↻ Sincronizar ahora" fuerza la \
revisión; si algo falla se muestra el error. Desactivar una integración la pausa; borrarla conserva los mensajes que ya entraron.
- Enviar desde la app: en el borrador de respuesta, si tienes una integración activa del canal de esa conversación, \
aparece "Enviar por …" (pide confirmación); el mensaje enviado queda en la conversación. En email se responde \
en el mismo hilo. "o escribirla yo" abre el cuadro para escribir sin IA. Si no hay integración, se copia con "Copiar".
- Protección de datos (solo administradores), en ✎ Editar cliente: "Buscar datos sensibles" lista los mensajes del cliente con IBAN, DNI/NIE o números de tarjeta; "Ocultar" los sustituye por "[IBAN oculto]" (no se puede deshacer y queda en el registro de accesos; el CIF de empresa no se toca). En Administración > Ajustes, "Conservar los mensajes (meses)" borra cada día los mensajes más antiguos que ese plazo (0 = conservarlos siempre); al escribirlo dice cuántos se borrarían, y "Borrar ya los mensajes antiguos" lo aplica al momento. "Descargar todos sus datos" genera un archivo \
JSON con todo lo guardado del cliente (derecho de acceso); "Borrar cliente y todos sus datos" lo elimina por completo \
(derecho de supresión), pidiendo escribir su nombre para confirmar. No se puede deshacer y queda en el registro.
- Columna izquierda: lista de clientes con los canales por los que se ha hablado con cada uno. \
El buscador encuentra por nombre, empresa, email, teléfono o @usuario. "Consulta general" (arriba de la lista) \
abre una conversación que puede buscar en todos los clientes. Un punto de color junto a un cliente indica \
que tienes una conversación abierta con el asistente sobre él.
- Documentos (al final de la pestaña "Ficha"): adjuntos que llegan por correo, WhatsApp o Telegram y documentos \
subidos con "＋ Subir" (máx. 20 MB). Al pulsar el nombre \
se abre; ⤓ lo descarga. De los PDF con texto se lee el contenido al momento; las fotos y los PDF escaneados se \
leen con "✨ Leer con IA" (imágenes de hasta 5 MB). "Ver texto" muestra lo leído. Ese contenido se puede buscar: \
lo usa el asistente (p. ej. importes de facturas) y el análisis de la ficha. Los adjuntos también aparecen con 📎 \
bajo su mensaje en la pestaña "Mensajes". Un documento subido lo puede borrar quien lo subió o un administrador.
- Columna derecha, "Asistente": cada cliente tiene su propia conversación con el asistente, guardada en tu perfil: \
se conserva al cambiar de cliente, recargar la página o entrar otro día. "Nueva conversación" empieza una limpia.
- El asistente busca por defecto solo en TUS conversaciones. Para que busque también en las de tus compañeros, \
pídeselo explícitamente ("busca también en las del equipo"). Bajo cada respuesta aparece qué búsquedas hizo; \
las marcadas como "equipo" salieron de conversaciones de otros compañeros.
- Estados del cliente: Potencial (aún no ha comprado: consultas o presupuestos), Activo (compra o tiene trabajo en curso sin problemas), Incidencia (problema sin resolver: queja, defecto, retraso, pago) e Inactivo (relación terminada o sin actividad). Los decide la IA sola cada vez que analiza al cliente, lo que ocurre al pulsar "✨ Actualizar con IA" y unos minutos después de que entre un mensaje por una integración; el motivo aparece bajo el nombre, y si pasa a Incidencia avisa al responsable. Sin IA, una regla diaria pasa a Inactivo a quien lleve tiempo sin mensajes (Administración > Ajustes, 90 días por defecto) y a Activo si vuelve a escribir. Para cambiarlo a mano, pulsa la etiqueta del estado junto al nombre (o en ✎): queda "puesto a mano" y la IA lo respeta hasta que haya mensajes nuevos; "✨ Que lo decida la IA" lo devuelve al modo automático. El ✨ junto al estado indica que lo decidió la IA. Sirven para filtrar la lista, para el punto de color de cada cliente y para el gráfico "Clientes por estado" del panel.
- Trabajo en equipo sin pisarse: al abrir un cliente, bajo su nombre se avisa si un compañero también lo tiene abierto, y en ámbar si está respondiendo ("Carlos Pérez está respondiendo a este cliente"). Al enviar o copiar una respuesta, si mientras tanto el cliente ha escrito o un compañero ha respondido en esa conversación, la app avisa y pregunta si enviarla igualmente.
- Barra superior, "Buscar o ir a…" (Ctrl+K o ⌘K): paleta de comandos para abrir cualquier cliente escribiendo su nombre, o lanzar acciones (ir a Sin responder, nuevo cliente, panel, respuestas guardadas, cambiar tema, redactar respuesta…); flechas para elegir y Enter. Atajos de teclado (cuando no se está escribiendo): / buscar cliente, j/k cliente siguiente/anterior, r redactar respuesta, g y luego c/s/t para ir a Clientes, Sin responder o Tareas, ? para ver la lista.
- Columna izquierda, pestaña "Sin responder": conversaciones cuyo último mensaje es del cliente, ordenadas por tiempo de espera. Cuando queda poco del plazo de respuesta (lo fija un administrador en Administración > Ajustes; 24 h por defecto) muestra "vence en…" en ámbar, y al pasarse se pone en rojo (el contador de la pestaña también). Al pulsar una se abre el cliente en su mensaje. "✓ Atendido" la quita de la bandeja si no necesita respuesta (vuelve si el cliente escribe otra vez). Arriba, "Mías" muestra tus conversaciones y "Todo el equipo" las de todos, con el número de cada lado; en las ajenas pone quién la lleva. "Posponer…" (3 horas, mañana a las 9, el lunes a las 9 o en una semana) la quita de la bandeja hasta esa fecha; vuelve antes si el cliente escribe. Las pospuestas se ven abajo, en "Pospuestas", con "Volver ahora". Seguimientos: en el borrador, "Al enviarla o copiarla, avísame si no contesta en…" (1 día a 2 semanas); si pasado ese plazo el cliente no ha escrito, aparece arriba de "Mías" en "Seguimientos: no han contestado", con "Escribir" y "✓ Hecho". Si el cliente contesta, el aviso desaparece solo.
- En la lista de clientes, un número azul junto al nombre indica mensajes nuevos desde tu última visita a ese cliente. Al abrirlo, arriba de la ficha aparece "N mensajes nuevos desde tu última visita" con el botón "✨ Resumir novedades", que hace un resumen con IA de solo esos mensajes.
- Columna izquierda, pestaña "Tareas": todas las tareas pendientes asignadas a ti, de todos los clientes, \
agrupadas en vencidas, hoy, próximas y sin fecha. El contador se pone en rojo si alguna vence hoy o ya venció. \
Pulsando el nombre del cliente se abre su ficha.
- Lista de clientes: filtros por estado (Potencial, Activo, Incidencia, Inactivo), por etiqueta y "Míos" (clientes de los que eres responsable). El punto de color junto al nombre es el estado. El buscador también encuentra por etiqueta. "＋" crea un cliente a mano (p. ej. tras una llamada); queda con la persona que lo crea como responsable.
- Panel central (al elegir un cliente): arriba el nombre con su estado, la empresa, el responsable, las etiquetas y sus identificadores por canal. El lápiz ✎ junto al nombre abre "Editar cliente": nombre, empresa, estado, responsable (recibe un aviso), etiquetas (al pulsar el campo se despliegan las básicas —VIP, Mayorista, Minorista, Nuevo, Habitual, Paga tarde, Presupuesto enviado, Urgente— y las que ya usa el equipo; se filtran escribiendo, y si escribes una que no existe aparece "Crear «…»" o basta con pulsar Enter; cada etiqueta se quita con su ×), identificadores (añadir o quitar email, WhatsApp, Telegram, teléfono u otro; sirven para que los mensajes que llegan por cada canal vayan al cliente correcto) y "Unir con otro cliente": si dos fichas son la misma persona, todo (conversaciones, datos, tareas, notas, etiquetas) pasa al cliente elegido y el otro desaparece; no se puede deshacer. Si la app ve un posible duplicado (mismo nombre, email o teléfono), lo muestra en amarillo con el botón "Unir aquí". Debajo hay cuatro pestañas:
  · "Ficha": resumen del estado del cliente y "Datos clave" (dirección, CIF, teléfonos, forma de pago, precios \
acordados...). Al analizar, la IA también deduce la prioridad del cliente (alta, media o baja, con el motivo) y su tono ("molesto" si se queja): se ven como etiquetas bajo "Resumen" y junto al nombre en "Sin responder" ("Prioridad alta", "Molesto"), para atender antes lo urgente. "✨ Actualizar con IA" hace que la IA lea todas las conversaciones del cliente (de todo el equipo) \
y actualice resumen, datos y tareas; también se hace sola, en segundo plano, cuando entran mensajes nuevos. \
Los datos con la etiqueta "IA" los ha extraído la IA; ↗ muestra el mensaje de donde sale; ✎ edita (un dato \
editado pasa a ser confirmado y la IA ya no lo cambia); × en un dato de la IA lo descarta (no lo vuelve a proponer). \
También se pueden añadir datos a mano. Debajo del resumen se indica cuándo se actualizó y cuántos mensajes \
nuevos hay desde entonces.
  · "Tareas": pendientes con ese cliente. La IA detecta compromisos en las conversaciones ("te mando el \
presupuesto el lunes", "confirmará en noviembre") y los crea como tareas con fecha y responsable (la persona \
nombrada o quien llevaba esa conversación); también marca como hechas las que ve cumplidas. Se pueden crear, \
editar (✎), completar (casilla), borrar (×) y ver las ya hechas.
  · "Notas": notas internas del equipo sobre el cliente (el cliente nunca las ve), p. ej. "paga siempre tarde". Al escribir @ aparece la lista del equipo para mencionar a alguien (@Nombre); esa persona recibe un aviso. Cada uno puede editar sus notas; borrarlas, su autor o un administrador. Ctrl+Enter guarda. El asistente también lee estas notas.
  · "Mensajes": arriba, un buscador con dos modos: "Buscar" (por palabras, instantáneo, ignora tildes y resalta \
lo encontrado) y "✨ Por significado" (la IA entiende la pregunta aunque el mensaje use otras palabras: amplía la \
búsqueda con sinónimos, busca en mensajes y documentos y ordena lo que de verdad responde, con una frase de por \
qué). Ambos buscan en tus conversaciones o en las del equipo según la casilla "Solo mis conversaciones". Al pulsar un resultado se \
salta a ese mensaje. Debajo, todos los mensajes del cliente en orden cronológico, como en un chat: lo que escribe el cliente, en burbujas claras a la izquierda (con su nombre en el color del canal) y lo que responde el equipo, en burbujas de color a la derecha; un separador por día (Hoy, Ayer, martes 10 de agosto…) y, al pie de cada burbuja, el canal y la hora (pasando el ratón, la fecha completa). Por defecto se ve el historial completo, \
con "la lleva X" en las conversaciones de compañeros; la casilla "Solo mis conversaciones" deja solo las tuyas. Se puede filtrar por canal. Abajo, como la caja de escribir de un chat, está "Redactar respuesta": se elige la conversación (canal) a la que responder, se pueden dar indicaciones opcionales ("más formal", "ofrece un 5 % de descuento") y la IA redacta un borrador con el contexto de todos los canales, la ficha y las tareas del cliente, en el estilo del canal (breve en WhatsApp/Telegram; con saludo y firma en email). No inventa precios ni fechas: deja huecos entre corchetes como [precio]. El borrador se puede editar, regenerar y copiar para pegarlo en WhatsApp, el correo, etc., o se envía directamente con "Enviar" si el canal está conectado en Integraciones. En "Sin responder", "Responder" abre directamente el borrador de esa conversación. "Respuestas guardadas" (en el borrador, o escribiendo / y el atajo en el texto, p. ej. /facturacion) inserta un texto del equipo con variables rellenas: {nombre}, {cliente}, {empresa}, {yo} y {dato:CIF} (cualquier dato clave de la ficha; lo que falta queda entre corchetes). Una vez escrito, el desplegable "✨ Retocar…" lo cambia con IA: más formal, más cercano, más corto, corregir ortografía o traducir (inglés, francés u otro idioma); "Deshacer" recupera el texto anterior. Si la respuesta guardada tiene acciones (cambiar el estado, añadir una etiqueta, marcar la conversación como atendida) es una macro y se aplican al usarla. Se crean y editan en el menú de usuario > "Respuestas guardadas"; cada uno edita las suyas y un administrador, todas.
- Tú (Chispa) estás en la esquina inferior izquierda; tu conversación también se guarda.
- Consejos para preguntar: sé concreto ("¿qué CIF nos dio?", "¿qué fecha de entrega acordamos?"). \
El asistente prueba sinónimos solo, pero conviene nombrar el dato que buscas.

La app no importa chats a mano: los mensajes entran solos y en tiempo real por los canales conectados en \
Administración > "Integraciones" (correo, bot de Telegram y WhatsApp Business). Si un canal no está conectado, \
díselo a un administrador.

Responde en español, en tono cercano y breve (2-5 frases o una lista corta). Si no sabes algo de la app, dilo."""


class MissingCredentialsError(Exception):
    """No hay clave de API ni otra credencial de Anthropic configurada."""


_client: anthropic.Anthropic | None = None
# DISABLE_AI=true: la app se comporta como si no hubiera clave (pruebas: nunca llaman a la API de verdad).
AI_DISABLED = os.getenv("DISABLE_AI", "false").lower() == "true"


def credentials_configured() -> bool:
    """Aproximación rápida (sin llamar a la API) de si hay credenciales de Anthropic configuradas."""
    return not AI_DISABLED and bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _get_client() -> anthropic.Anthropic:
    global _client
    if AI_DISABLED:
        raise MissingCredentialsError()
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _create(**params):
    try:
        return _get_client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            cache_control={"type": "ephemeral"},
            # Si el modelo rechaza la petición, la API la reintenta con un modelo alternativo.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **params,
        )
    except TypeError as exc:
        # El SDK lanza TypeError (no un error de API) cuando no encuentra credenciales.
        if "authentication method" in str(exc):
            raise MissingCredentialsError() from exc
        raise


def _assistant_turn(response) -> dict:
    """Contenido completo de la respuesta (incluidos bloques de razonamiento), sin modificar,
    en formato JSON para poder guardarlo en la base de datos y reenviarlo en el siguiente turno."""
    return {"role": "assistant", "content": [b.to_dict(exclude_none=True) for b in response.content]}


def _reply_text(response) -> str:
    if response.stop_reason == "refusal":
        return "No puedo ayudar con esa petición."
    reply = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "max_tokens":
        reply += "\n\n*(Respuesta cortada por longitud.)*"
    return reply or "(sin respuesta)"


def help_chat(messages: list, text: str) -> dict:
    """Mascota de ayuda: responde dudas sobre el uso de la app, sin herramientas ni datos de clientes.

    Añade el turno a `messages` (historial de la API); quien llama se encarga de guardarlo.
    """
    messages.append({"role": "user", "content": text})
    response = _create(system=HELP_SYSTEM_PROMPT, messages=messages, output_config={"effort": "low"})
    messages.append(_assistant_turn(response))
    return {"reply": _reply_text(response), "tool_calls": []}


def _context_line(user: dict, client: dict | None) -> str:
    parts = [f"Fecha de hoy: {date.today().isoformat()}", f"Usuario actual: {user['name']} (id {user['id']})"]
    if client:
        parts.append(f"Esta conversación es sobre el cliente {client['name']} (cliente_id {client['id']}); "
                     "limita las búsquedas a ese cliente salvo que el usuario pida otra cosa")
    return "[Contexto: " + "; ".join(parts) + "]"


def chat(messages: list, user: dict, text: str, client: dict | None = None) -> dict:
    """Envía un mensaje del usuario y ejecuta el bucle de herramientas hasta obtener respuesta.

    Añade los turnos a `messages` (historial de la API); quien llama se encarga de guardarlo
    solo si todo fue bien. Devuelve {"reply": str, "tool_calls": [{"name", "input"}]}.
    """
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": f"{_context_line(user, client)}\n\n{text}"}],
    })
    tool_log: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = _create(system=SYSTEM_PROMPT, tools=TOOLS, messages=messages,
                           output_config={"effort": "medium"})
        messages.append(_assistant_turn(response))

        if response.stop_reason != "tool_use":
            return {"reply": _reply_text(response), "tool_calls": tool_log}

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_log.append({"name": block.name, "input": block.input})
            try:
                result = _run_tool(block.name, block.input, user["id"])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
            except (KeyError, ValueError, TypeError) as exc:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {exc}",
                    "is_error": True,
                })
        messages.append({"role": "user", "content": tool_results})

    return {"reply": "La búsqueda necesitó demasiados pasos. Prueba a concretar más la pregunta.",
            "tool_calls": tool_log}
