"""Carga datos de demostración. Uso: python -m app.seed  (desde la carpeta backend)"""
from . import search
from .db import DB_PATH, get_conn, init_db

USERS = [(1, "Ana Ruiz", "ana@miempresa.com"),
         (2, "Carlos Pérez", "carlos@miempresa.com"),
         (3, "Marta López", "marta@miempresa.com")]

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


def seed() -> None:
    init_db()
    with get_conn() as conn:
        if conn.execute("SELECT count(*) FROM users").fetchone()[0]:
            print(f"La base de datos ya tiene datos ({DB_PATH}). Bórrala para volver a sembrar.")
            return
        conn.executemany("INSERT INTO users (id, name, email) VALUES (?, ?, ?)", USERS)

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
    print(f"Datos de demostración cargados en {DB_PATH}")


if __name__ == "__main__":
    seed()
