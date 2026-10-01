"""Datos de prueba abundantes y realistas para experimentar con la app (python -m app.seed --reset).

Simula una empresa de packaging (cajas, bolsas, etiquetas...) con ~80 clientes de distintos sectores,
conversaciones por email, WhatsApp y Telegram repartidas en los últimos meses (según la fecha de hoy),
clientes atendidos por varias personas, estados, etiquetas, datos clave, tareas (algunas vencidas),
notas con @menciones, presupuestos en PDF adjuntos y algunos clientes duplicados a propósito.
Es determinista: siempre genera lo mismo para la misma fecha.
"""
import io
import random
from datetime import date, datetime, timedelta

from . import attachments, notes, search
from .auth import hash_password
from .db import get_conn

EXTRA_USERS = [("lucia", "Lucía Fernández", "lucia@miempresa.com"),
               ("javier", "Javier Moreno", "javier@miempresa.com"),
               ("elena", "Elena Sánchez", "elena@miempresa.com")]

NOMBRES = ["María", "Carmen", "Lucía", "Paula", "Sara", "Marta", "Elena", "Cristina", "Raquel", "Nuria", "Beatriz",
           "Pilar", "Rocío", "Silvia", "Irene", "Alba", "Andrés", "David", "Pablo", "Sergio", "Álvaro", "Javier",
           "Miguel", "Rubén", "Iván", "Diego", "Hugo", "Óscar", "Raúl", "Tomás", "Víctor", "Adrián", "Manuel", "Íñigo"]
APELLIDOS = ["García", "Martínez", "López", "Sánchez", "Pérez", "Gómez", "Díaz", "Moreno", "Muñoz", "Álvarez",
             "Romero", "Navarro", "Torres", "Domínguez", "Vázquez", "Ramos", "Gil", "Serrano", "Blanco", "Molina",
             "Castro", "Ortega", "Rubio", "Marín", "Sanz", "Iglesias", "Núñez", "Medina", "Garrido", "Cortés"]
SECTORES = [  # (tipo de negocio, etiqueta, productos habituales)
    ("Floristería", "retail", ["cajas de cartón", "pliegos de papel de seda", "etiquetas adhesivas"]),
    ("Pastelería", "hostelería", ["cajas para tartas", "bolsas de papel kraft", "pegatinas con logo"]),
    ("Cafetería", "hostelería", ["vasos de cartón", "bolsas de papel kraft", "servilletas impresas"]),
    ("Tienda de ropa", "retail", ["bolsas con asa retorcida", "pliegos de papel de seda", "etiquetas colgantes"]),
    ("Librería", "retail", ["bolsas de papel kraft", "sobres acolchados", "marcapáginas impresos"]),
    ("Cosmética online", "online", ["cajas de envío", "rollos de cinta adhesiva impresa", "tarjetas de agradecimiento"]),
    ("Bodega", "mayorista", ["cajas para botellas", "etiquetas de vino", "bolsas para botellas"]),
    ("Restaurante", "hostelería", ["cajas para comida para llevar", "bolsas de papel kraft", "pegatinas con logo"]),
    ("Joyería", "retail", ["cajitas con tapa", "bolsitas de terciopelo", "tarjetas de garantía"]),
    ("Catering", "eventos", ["cajas para catering", "etiquetas adhesivas", "servilletas impresas"]),
    ("Tienda de regalos", "retail", ["cajas de regalo", "rollos de papel de regalo", "lazos"]),
    ("Panadería", "hostelería", ["bolsas de papel para pan", "cajas para bollería", "pegatinas con logo"]),
    ("Herbolario", "retail", ["bolsas de papel kraft", "etiquetas adhesivas", "sobres de papel"]),
    ("Estudio de diseño", "eventos", ["cajas personalizadas", "tarjetas de visita", "sobres impresos"]),
    ("Tienda de juguetes", "retail", ["cajas de envío", "rollos de papel de regalo", "bolsas con asa"]),
]
ADJETIVOS = ["El Rincón", "La Esquina", "Las Flores", "Dulce", "Mediterránea", "del Sur", "Nova", "Verde", "La Plaza",
             "Artesana", "Luna", "Sol", "Aurora", "La Encina", "Brisa", "El Olivo"]
CIUDADES = [("Madrid", "28"), ("Valencia", "46"), ("Sevilla", "41"), ("Bilbao", "48"), ("Zaragoza", "50"),
            ("Málaga", "29"), ("Granada", "18"), ("Salamanca", "37"), ("Alicante", "03"), ("Valladolid", "47")]
CALLES = ["Calle Mayor", "Av. de la Constitución", "Calle Real", "Paseo de la Estación", "Calle San Juan",
          "Av. Libertad", "Calle del Carmen", "Plaza de España", "Calle Nueva", "Ronda Norte"]
COLORES = ["blanco", "negro", "kraft", "rosa palo", "verde oliva", "azul marino"]
PAGOS = ["transferencia a 30 días", "transferencia al contado", "domiciliación a 60 días", "tarjeta"]
HORARIOS = ["por las mañanas (9 a 13 h)", "por las tardes a partir de las 16 h", "de lunes a jueves",
            "solo martes y jueves"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _fecha_texto(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]}"


def _pdf(lineas: list[str]) -> bytes:
    """PDF mínimo de una página con texto (para los presupuestos adjuntos)."""
    ops = ["BT", "/F1 11 Tf", "14 TL", "60 780 Td"]
    for linea in lineas:
        texto = linea.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({texto}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("cp1252", errors="replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


class Generador:
    def __init__(self, hoy: date):
        self.r = random.Random(2026)
        self.hoy = hoy
        self.ahora = datetime.combine(hoy, datetime.min.time()) + timedelta(hours=18)
        self.presupuesto_n = 100
        self.usados = {"ana ruiz", "carlos pérez", "marta lópez", "lucía fernández", "javier moreno", "elena sánchez"}

    # ------------------------------------------------------------ clientes
    def cliente(self, i: int) -> dict:
        r = self.r
        nombre, apellido = r.choice(NOMBRES), r.choice(APELLIDOS)
        while f"{nombre} {apellido}".lower() in self.usados:
            nombre, apellido = r.choice(NOMBRES), r.choice(APELLIDOS)
        self.usados.add(f"{nombre} {apellido}".lower())
        tipo, etiqueta, productos = SECTORES[i % len(SECTORES)]
        empresa = f"{tipo} {r.choice(ADJETIVOS)}"
        ciudad, cp = r.choice(CIUDADES)
        slug = empresa.lower()
        for a, b in zip("áéíóúñ ", "aeioun-"):
            slug = slug.replace(a, b)
        usuario = f"{nombre}.{apellido}".lower()
        for a, b in zip("áéíóúñ", "aeioun"):
            usuario = usuario.replace(a, b)
        return {
            "nombre": nombre, "persona": f"{nombre} {apellido}", "empresa": empresa, "etiqueta": etiqueta,
            "productos": productos, "ciudad": ciudad,
            "direccion": f"{r.choice(CALLES)} {r.randint(2, 120)}, {cp}{r.randint(1, 80):03d} {ciudad}",
            "email": f"{usuario}@{slug}.es", "telefono": f"+346{r.randint(10000000, 99999999)}",
            "telegram": f"user{r.randint(100000000, 999999999)}",
            "cif": f"B{r.randint(10000000, 99999999)}", "pago": r.choice(PAGOS), "horario": r.choice(HORARIOS),
        }

    # ------------------------------------------------------------ escenarios de conversación
    def escenario(self, c: dict, tipo: str, agente: str) -> tuple[str | None, list[tuple[str, str, float]], dict]:
        """Devuelve (asunto, [(direccion, texto, horas_despues)], extras). extras: tarea, pdf, dato..."""
        r, prod = self.r, self.r.choice(c["productos"])
        cant = r.choice([100, 200, 250, 300, 500, 750, 1000, 1500, 2000])
        precio = round(r.uniform(0.08, 1.9), 2)
        n = c["nombre"]
        extras: dict = {}
        if tipo == "presupuesto":
            self.presupuesto_n += 1
            ref = f"P-{self.hoy.year}-{self.presupuesto_n}"
            msgs = [("in", f"Hola, soy {n} de {c['empresa']}. ¿Nos podéis pasar presupuesto para {cant} {prod}?", 0),
                    ("out", f"¡Hola {n}! Claro. ¿Las queréis con logo impreso o lisas?", r.uniform(0.2, 3)),
                    ("in", r.choice(["Con el logo a una tinta, por favor", "Lisas, en color " + r.choice(COLORES),
                                     "Con el logo a dos tintas si no se dispara el precio"]), r.uniform(0.5, 20)),
                    ("out", f"Te adjunto el presupuesto {ref}: {cant} {prod} a {precio:.2f} €/ud + IVA. "
                            f"Plazo de entrega: {r.choice([7, 10, 15])} días laborables.", r.uniform(1, 24))]
            extras["pdf"] = (f"Presupuesto {ref}.pdf", [
                f"PRESUPUESTO {ref}", f"Cliente: {c['empresa']} ({c['persona']})", f"Producto: {prod}",
                f"Cantidad: {cant} unidades", f"Precio unitario: {precio:.2f} EUR + IVA",
                f"Total: {cant * precio:.2f} EUR + IVA", "Validez: 30 días", f"Atendido por: {agente}"])
            final = r.random()
            if final < 0.45:
                entrega = self.hoy + timedelta(days=r.randint(-60, 20))
                msgs += [("in", f"Adelante con el pedido. Enviadlo a {c['direccion']}, mejor {c['horario']}.",
                          r.uniform(5, 72)),
                         ("out", f"¡Genial, {n}! Pedido confirmado. Entrega prevista el {_fecha_texto(entrega)}.",
                          r.uniform(0.5, 6))]
                extras["dato"] = [("Dirección de envío", c["direccion"]), ("Horario de entrega", c["horario"])]
            elif final < 0.7:
                rebaja = round(precio * 0.9, 2)
                msgs += [("in", f"¿Podéis dejarlo en {rebaja:.2f} €? Es un pedido grande y repetiremos.", r.uniform(5, 72)),
                         ("out", f"Te lo dejamos en {round(precio * 0.95, 2):.2f} €/ud si confirmas esta semana.",
                          r.uniform(1, 30)),
                         ("in", "Lo hablo con mi socio y te digo algo el lunes.", r.uniform(1, 12))]
                extras["tarea"] = (f"Llamar a {n} por el presupuesto {ref}", r.randint(-5, 10))
            else:
                msgs += [("in", "Lo consulto y os digo. ¡Gracias!", r.uniform(2, 40))]
                extras["tarea"] = (f"Seguimiento del presupuesto {ref} de {c['empresa']}", r.randint(-10, 7))
                extras["lead"] = True
            return f"Presupuesto {prod}", msgs, extras
        if tipo == "recurrente":
            msgs = [("in", f"¡Hola! Necesitamos otras {cant} {prod} como las del último pedido.", 0),
                    ("out", "Marchando. ¿Misma dirección de entrega de siempre?", r.uniform(0.1, 4)),
                    ("in", "Sí, la de siempre. Y si puede ser antes del viernes, mejor.", r.uniform(0.2, 10))]
            if r.random() < 0.8:
                msgs.append(("out", "Perfecto, sale el jueves. Te paso el número de seguimiento cuando lo tenga.",
                             r.uniform(0.5, 8)))
                if r.random() < 0.4:
                    msgs.append(("in", r.choice(["¡Gracias!", "Genial, gracias 🙌", "Perfecto 👍"]), r.uniform(0.2, 3)))
                    extras["gracias"] = True
            return None, msgs, extras
        if tipo == "incidencia":
            danadas = r.randint(3, 40)
            msgs = [("in", f"Buenas, nos han llegado {danadas} {prod} "
                           f"{r.choice(['dañadas', 'con el logo torcido', 'mojadas', 'de otra medida'])}.", 0),
                    ("out", f"Lo siento mucho, {n}. ¿Me mandas una foto para que lo vea producción?", r.uniform(0.2, 5)),
                    ("in", "Ahora te la mando. Las necesitamos para el sábado sin falta.", r.uniform(0.2, 6))]
            if r.random() < 0.8:
                msgs.append(("out", f"Te enviamos {danadas} de reposición sin coste mañana mismo.", r.uniform(1, 24)))
            else:
                extras["incidencia"] = True
                extras["tarea"] = (f"Enviar reposición de {danadas} {prod} a {c['empresa']}", r.randint(-4, 2))
            return f"Incidencia con el pedido de {prod}", msgs, extras
        if tipo == "facturacion":
            msgs = [("in", f"Os paso los datos para las facturas: {c['empresa']} S.L., CIF {c['cif']}, "
                           f"{c['direccion']}. Forma de pago: {c['pago']}.", 0),
                    ("out", "Gracias, ya están registrados en nuestro sistema.", r.uniform(0.5, 30))]
            extras["dato"] = [("CIF", c["cif"]), ("Forma de pago", c["pago"])]
            return "Datos de facturación", msgs, extras
        if tipo == "consulta":
            color = r.choice(COLORES)
            msgs = [("in", f"¿Tenéis {prod} en color {color}? ¿Cuál es el pedido mínimo?", 0),
                    ("out", f"Sí, en {color} y en kraft. El pedido mínimo es de {r.choice([50, 100, 250])} unidades.",
                     r.uniform(0.2, 8))]
            if r.random() < 0.5:
                msgs.append(("in", "¿Y me podríais mandar alguna muestra antes de decidir?", r.uniform(1, 30)))
                if r.random() < 0.5:
                    msgs.append(("out", f"Claro, te enviamos muestras a {c['direccion']} esta semana.", r.uniform(1, 20)))
                    extras["tarea"] = (f"Enviar muestras de {prod} a {c['empresa']}", r.randint(-3, 5))
            return f"Consulta sobre {prod}", msgs, extras
        # retraso: el cliente pregunta y espera respuesta
        msgs = [("in", f"Hola, ¿sabéis algo de nuestro pedido de {prod}? Lo necesitábamos para esta semana.", 0)]
        if r.random() < 0.4:
            msgs += [("out", "Lo reviso ahora mismo con logística y te digo.", r.uniform(0.2, 5)),
                     ("in", "Vale, quedo a la espera. Es urgente.", r.uniform(5, 30))]
        return f"Estado del pedido de {prod}", msgs, extras

    def estilo_email(self, texto: str, direccion: str, cliente: dict, agente: str) -> str:
        if direccion == "in":
            return f"Hola,\n\n{texto}\n\nUn saludo,\n{cliente['persona']}\n{cliente['empresa']}"
        return f"Hola {cliente['nombre']},\n\n{texto}\n\nUn saludo,\n{agente}\nMiEmpresa Packaging"


def _laborable(t: datetime, r: random.Random) -> datetime:
    """Lleva a horario laboral (9-20 h, sin domingos) un mensaje que cae de noche o en domingo."""
    if t.hour < 9 or t.hour >= 20:
        t = (t + timedelta(days=1 if t.hour >= 20 else 0)).replace(hour=9, minute=0) + timedelta(minutes=r.randint(0, 150))
    if t.weekday() == 6:
        t += timedelta(days=1)
    return t


def cerrar_conversaciones(g: "Generador", r: random.Random, nombres: dict[int, str], fichas: dict[int, dict]) -> int:
    """Las conversaciones que acaban con un mensaje del cliente reciben respuesta del equipo en la mayoría de
    los casos. Quedan sin responder unas pocas (sobre todo recientes), para que la bandeja sea realista."""
    respondidas = 0
    for item in search.unanswered(0, "team"):
        c = fichas.get(item["client_id"])
        if c is None:
            continue  # no es de los datos generados
        enviado = datetime.fromisoformat(item["sent_at"])
        reciente = enviado > g.ahora - timedelta(days=4)
        if r.random() < (0.5 if reciente else 0.06):
            continue  # se queda en "Sin responder"
        t = _laborable(enviado + timedelta(hours=r.uniform(0.3, 20)), r)
        if t > g.ahora:
            continue
        with get_conn() as conn:
            owner = conn.execute("SELECT owner_user_id FROM conversations WHERE id = ?",
                                 (item["conversation_id"],)).fetchone()[0]
            texto = r.choice(["¡Perfecto! Cualquier cosa, aquí estamos.", "Recibido, gracias. Lo dejamos anotado.",
                              "Genial, quedamos atentos a lo que nos digas.", "Hecho. Te avisamos en cuanto esté listo."])
            cuerpo = g.estilo_email(texto, "out", c, nombres[owner]) if item["channel"] == "email" else texto
            conn.execute("INSERT INTO messages (conversation_id, direction, sender, body, sent_at) VALUES (?, 'out', ?, ?, ?)",
                         (item["conversation_id"], nombres[owner].split()[0], cuerpo, t.strftime("%Y-%m-%dT%H:%M:%S")))
        respondidas += 1
    return respondidas


def _usuario_ids(conn) -> dict[str, int]:
    return {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}


def generar(hoy: date | None = None, clientes: int = 80) -> dict:
    """Añade los datos de prueba a una base de datos que ya tiene los datos básicos (usuarios ana, carlos, marta)."""
    g = Generador(hoy or date.today())
    r = g.r
    with get_conn() as conn:
        conn.executemany("INSERT INTO users (username, name, email, role, password_hash) VALUES (?, ?, ?, 'user', ?)",
                         [(*u, hash_password("demo1234")) for u in EXTRA_USERS])
        uid = _usuario_ids(conn)
        nombres = {r_["id"]: r_["name"] for r_ in conn.execute("SELECT id, name FROM users")}
    equipo = list(uid.values())
    canales_por_cliente = [["whatsapp"], ["email"], ["telegram"], ["email", "whatsapp"],
                           ["whatsapp", "telegram"], ["email", "whatsapp", "telegram"]]
    tipos = ["presupuesto", "recurrente", "incidencia", "facturacion", "consulta", "retraso"]
    total = {"clientes": 0, "conversaciones": 0, "mensajes": 0, "tareas": 0, "notas": 0, "documentos": 0}
    creados = []

    for i in range(clientes):
        c = g.cliente(i)
        responsable = r.choice(equipo) if r.random() < 0.7 else None
        canales = r.choice(canales_por_cliente)
        # Actividad: la mayoría reciente; unos pocos llevan meses sin hablar (inactivos).
        inactivo = r.random() < 0.12
        client_id = None
        estado = "active"
        for canal in canales:
            owner = responsable if responsable and r.random() < 0.6 else r.choice(equipo)
            # Varios episodios por canal (presupuesto, pedido, incidencia...), separados por días o semanas. En
            # WhatsApp y Telegram forman un único historial; en email cada asunto es una conversación.
            episodios = r.choice([2, 3, 3, 4, 5, 6])
            t = g.ahora - timedelta(days=r.randint(130, 180) if inactivo else int(r.triangular(20, 180, 60)),
                                    hours=r.uniform(0, 10))
            for _ in range(episodios):
                asunto, pasos, extras = g.escenario(c, r.choice(tipos), nombres[owner])
                mensajes = []
                for direccion, texto, horas in pasos:
                    t = _laborable(t + timedelta(hours=horas), r)
                    if t > g.ahora or (inactivo and t > g.ahora - timedelta(days=100)):
                        break
                    cuerpo = g.estilo_email(texto, direccion, c, nombres[owner]) if canal == "email" else texto
                    remitente = (c["persona"] if canal == "email" else c["nombre"]) if direccion == "in" \
                        else nombres[owner].split()[0]
                    mensajes.append({"direction": direccion, "sender": remitente, "body": cuerpo,
                                     "sent_at": t.strftime("%Y-%m-%dT%H:%M:%S")})
                if not mensajes:
                    break
                handle = {"email": c["email"], "whatsapp": c["telefono"], "telegram": c["telegram"]}[canal]
                res = search.import_conversation({
                    "owner_user_id": owner, "channel": canal, "handle": handle, "client_id": client_id,
                    "client_name": c["persona"], "subject": asunto if canal == "email" else None, "messages": mensajes})
                if client_id is None or canal == "email":
                    total["conversaciones"] += 1
                client_id = res["client_id"]
                total["mensajes"] += res["messages"]
                _extras(client_id, res["conversation_id"], extras, owner, g.hoy, total, r)
                if extras.get("lead") and estado == "active":
                    estado = "lead"
                if extras.get("incidencia") and t > g.ahora - timedelta(days=45):
                    estado = "issue"
                t = t + timedelta(days=r.uniform(3, 30))  # siguiente episodio
        if client_id is None:
            continue
        if inactivo:
            estado = "inactive"
        etiquetas = [c["etiqueta"]] + [t for t, p in (("VIP", 0.12), ("mayorista", 0.15), ("paga tarde", 0.1)) if r.random() < p]
        with get_conn() as conn:
            conn.execute("UPDATE clients SET company = ?, status = ?, assignee_user_id = ? WHERE id = ?",
                         (c["empresa"], estado, responsable, client_id))
            conn.executemany("INSERT INTO client_tags (client_id, tag) VALUES (?, ?) ON CONFLICT DO NOTHING",
                             [(client_id, t) for t in etiquetas])
        total["clientes"] += 1
        creados.append((client_id, c, canales))

    total["mensajes"] += cerrar_conversaciones(g, r, nombres, {cid: c for cid, c, _ in creados})

    # Notas internas con @menciones (generan avisos a los mencionados).
    frases = ["Ojo, {m}: siempre pide descuento y al final acepta el precio.", "Paga tarde; {m}, reclama la factura antes de enviar.",
              "Muy buen cliente, trato cercano. {m} lo conoce desde hace años.", "Prefiere que le llamen antes de las 12. Avisad a {m}.",
              "Tiene una tienda nueva en el centro: posible pedido grande. {m}, ¿lo llevas tú?"]
    for client_id, _, _ in r.sample(creados, min(18, len(creados))):
        autor, mencionado = r.sample(equipo, 2)
        notes.add_note(client_id, {"id": autor, "name": nombres[autor]},
                       r.choice(frases).format(m="@" + nombres[mencionado].split()[0]))
        total["notas"] += 1

    # Duplicados a propósito, para practicar "Unir clientes": uno con el mismo nombre (otro número) y otro
    # con el mismo teléfono escrito de otra forma.
    con_whatsapp = [(cid, c, canales) for cid, c, canales in creados if "whatsapp" in canales]
    for n, (client_id, c, _) in enumerate(r.sample(con_whatsapp, min(2, len(con_whatsapp)))):
        nombre = c["persona"] if n == 0 else f"{c['nombre']} ({c['empresa']})"
        dup = search.import_conversation({
            "owner_user_id": r.choice(equipo), "channel": "whatsapp", "handle": f"+346{r.randint(10000000, 99999999)}",
            "client_name": nombre, "subject": None,
            "messages": [{"direction": "in", "sender": c["nombre"],
                          "body": "Hola, soy yo otra vez, os escribo desde el móvil de la tienda.",
                          "sent_at": (g.ahora - timedelta(days=r.randint(1, 20))).strftime("%Y-%m-%dT%H:%M:%S")}]})
        if n == 1:
            tel = c["telefono"]
            with get_conn() as conn:
                conn.execute("INSERT INTO client_identities (client_id, channel, handle) VALUES (?, 'phone', ?)",
                             (dup["client_id"], f"{tel[:3]} {tel[3:6]} {tel[6:9]} {tel[9:]}"))
        total["clientes"] += 1
        total["mensajes"] += 1
    return total


def _extras(client_id, conv_id, extras, owner, hoy, total, r):
    """Datos clave, tarea y PDF de presupuesto asociados a una conversación generada."""
    with get_conn() as conn:
        last = conn.execute("SELECT id FROM messages WHERE conversation_id = ? ORDER BY sent_at DESC, id DESC LIMIT 1",
                            (conv_id,)).fetchone()
        for label, value in extras.get("dato", []):
            if not conn.execute("SELECT 1 FROM client_facts WHERE client_id = ? AND label = ?", (client_id, label)).fetchone():
                conn.execute("INSERT INTO client_facts (client_id, label, value, origin, updated_by) VALUES (?, ?, ?, 'manual', ?)",
                             (client_id, label, value, owner))
        if "tarea" in extras:
            titulo, dias = extras["tarea"]
            hecha = r.random() < 0.25
            conn.execute(
                """INSERT INTO tasks (client_id, title, due_date, assignee_user_id, status, origin, source_message_id,
                                      created_by, done_at)
                   VALUES (?, ?, ?, ?, ?, 'manual', ?, ?, ?)""",
                (client_id, titulo, (hoy + timedelta(days=dias)).isoformat(), owner, "done" if hecha else "open",
                 last["id"] if last else None, owner, datetime.now().strftime("%Y-%m-%dT%H:%M:%S") if hecha else None))
            total["tareas"] += 1
        if "pdf" in extras:
            first_out = conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND direction = 'out' ORDER BY sent_at LIMIT 1",
                (conv_id,)).fetchone()
            if first_out:
                nombre, lineas = extras["pdf"]
                attachments.save(conn, client_id, nombre, _pdf(lineas), "application/pdf", first_out["id"], owner)
                total["documentos"] += 1
