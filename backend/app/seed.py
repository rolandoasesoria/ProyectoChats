"""Carga datos de demostración (desde la carpeta backend):

  python -m app.seed                   carga los datos si la base de datos está vacía
  python -m app.seed --reset           BORRA todo y vuelve a cargarlos
  python -m app.seed --reset --basico  solo los 3 clientes básicos (los usan las pruebas automáticas)

Sin --basico se añaden además los datos de prueba abundantes de demo_data.py (~80 clientes, 6 personas).
"""
import sys

from . import demo_data, search
from .auth import hash_password
from .db import get_conn, init_db, reset_db

DEMO_PASSWORD = "demo1234"
# (usuario, nombre, email, rol). En una base de datos vacía reciben los ids 1, 2 y 3 (las pruebas lo usan).
USERS = [("ana", "Ana Ruiz", "ana@miempresa.com", "admin"),
         ("carlos", "Carlos Pérez", "carlos@miempresa.com", "user"),
         ("marta", "Marta López", "marta@miempresa.com", "user")]

CONVERSATIONS = [
    # --- Laura Gómez: WhatsApp con Ana, email con Carlos, Telegram con Marta ---
    {"owner_user_id": 1, "channel": "whatsapp", "handle": "+34600111222", "client_name": "Laura Gómez",
     "messages": [
         ("in", "Laura", "Hola Ana, soy Laura de Floristería Gómez. Quería pedir presupuesto para 200 cajas", "2026-08-03T10:02:00"),
         ("out", "Ana", "¡Hola Laura! Claro, ¿de qué medida las necesitas?", "2026-08-03T10:05:00"),
         ("in", "Laura", "30x20x15 cm, con el logo impreso en una cara", "2026-08-03T10:07:00"),
         ("out", "Ana", "Perfecto. Te preparo el presupuesto hoy mismo", "2026-08-03T10:08:00"),
         ("in", "Laura", "Genial. La dirección de envío sería Calle Mayor 45, local 2, 28013 Madrid", "2026-08-05T16:30:00"),
         ("in", "Laura", "Y mejor que entreguen por la mañana, por las tardes está cerrado el almacén", "2026-08-05T16:31:00"),
     ]},
    {"owner_user_id": 2, "channel": "email", "handle": "laura@floristeriagomez.es", "client_id": None,
     "link_to": "+34600111222", "subject": "Datos de facturación",
     "messages": [
         ("in", "Laura Gómez", "Buenos días Carlos, os paso los datos para la factura: Floristería Gómez S.L., CIF B12345678, Calle Mayor 45, Madrid.", "2026-08-10T09:15:00"),
         ("out", "Carlos", "Gracias Laura, registrado. ¿Preferís pago por transferencia o domiciliación?", "2026-08-10T09:40:00"),
         ("in", "Laura Gómez", "Transferencia a 30 días, por favor. IBAN de cargo no hace falta entonces.", "2026-08-10T10:02:00"),
     ]},
    {"owner_user_id": 3, "channel": "telegram", "handle": "@lauragomezflores", "link_to": "+34600111222",
     "messages": [
         ("in", "Laura", "Marta, el pedido de cajas llegó bien pero 3 venían con el logo torcido", "2026-09-02T12:10:00"),
         ("out", "Marta", "Lo siento mucho Laura. Te enviamos 3 de reposición sin coste esta semana", "2026-09-02T12:25:00"),
         ("in", "Laura", "Gracias. Para el próximo pedido quizá subamos a 350 unidades en noviembre", "2026-09-02T12:27:00"),
     ]},
    # --- Jorge Martín: email con Ana y WhatsApp con Carlos ---
    {"owner_user_id": 1, "channel": "email", "handle": "jorge@talleresmartin.com", "client_name": "Jorge Martín",
     "subject": "Pedido etiquetas",
     "messages": [
         ("in", "Jorge Martín", "Hola Ana, necesitamos 5.000 etiquetas adhesivas resistentes a aceite para el taller.", "2026-07-21T08:50:00"),
         ("out", "Ana", "Hola Jorge, te recomiendo vinilo laminado. Precio orientativo 0,12 €/ud.", "2026-07-21T11:00:00"),
         ("in", "Jorge Martín", "Ok, adelante. Mi móvil por si hay dudas: 655 987 321", "2026-07-22T09:05:00"),
     ]},
    {"owner_user_id": 2, "channel": "whatsapp", "handle": "+34655987321", "link_to": "jorge@talleresmartin.com",
     "messages": [
         ("in", "Jorge", "Carlos, ¿podéis adelantar la entrega de las etiquetas al viernes 1 de agosto?", "2026-07-28T17:45:00"),
         ("out", "Carlos", "Lo miro con producción y te digo mañana", "2026-07-28T18:02:00"),
         ("out", "Carlos", "Confirmado: entrega el viernes 1 de agosto antes de las 12h", "2026-07-29T10:20:00"),
     ]},
    # --- Sofía Navarro: solo Telegram con Marta ---
    {"owner_user_id": 3, "channel": "telegram", "handle": "@sofianavarro", "client_name": "Sofía Navarro",
     "messages": [
         ("in", "Sofía", "Hola Marta, ¿hacéis bolsas de papel kraft con asa retorcida?", "2026-09-15T13:00:00"),
         ("out", "Marta", "Sí, desde 500 unidades. ¿Qué tamaño buscas?", "2026-09-15T13:12:00"),
         ("in", "Sofía", "Unas 32x12x41. Mi presupuesto máximo son 400 € en total", "2026-09-15T13:20:00"),
     ]},
]


def seed(reset: bool = False, basico: bool = False) -> None:
    if reset:
        reset_db()
    else:
        init_db()
    with get_conn() as conn:
        if conn.execute("SELECT count(*) FROM users").fetchone()[0]:
            print("La base de datos ya tiene datos. Usa --reset para borrarla y volver a cargarlos.")
            return
        conn.executemany(
            "INSERT INTO users (username, name, email, role, password_hash) VALUES (?, ?, ?, ?, ?)",
            [(*u, hash_password(DEMO_PASSWORD)) for u in USERS],
        )

    for conv in CONVERSATIONS:
        client_id = conv.get("client_id")
        if conv.get("link_to"):
            with get_conn() as conn:
                client_id = conn.execute(
                    "SELECT client_id FROM client_identities WHERE handle = ?", (conv["link_to"],)
                ).fetchone()["client_id"]
        search.import_conversation({
            **conv,
            "client_id": client_id,
            "messages": [{"direction": d, "sender": s, "body": b, "sent_at": t} for d, s, b, t in conv["messages"]],
        })

    with get_conn() as conn:
        conn.execute("UPDATE clients SET company = 'Floristería Gómez S.L.' WHERE name = 'Laura Gómez'")
        conn.execute("UPDATE clients SET company = 'Talleres Martín' WHERE name = 'Jorge Martín'")
    if not basico:
        t = demo_data.generar()
        print(f"Datos de prueba: {t['clientes']} clientes más, {t['conversaciones']} conversaciones, "
              f"{t['mensajes']} mensajes, {t['tareas']} tareas, {t['notas']} notas y {t['documentos']} documentos.")
    print("Datos de demostración cargados.")
    usuarios = [u[0] for u in USERS] + ([] if basico else [u[0] for u in demo_data.EXTRA_USERS])
    print(f"Usuarios: {', '.join(usuarios)} (contraseña: {DEMO_PASSWORD}). 'ana' es administradora.")


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv, basico="--basico" in sys.argv)
