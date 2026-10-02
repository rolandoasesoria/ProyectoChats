"""Integraciones (cuentas conectadas de email, Telegram y WhatsApp) y lo que necesitan para enviar."""
from ..db import Conn, rows

# Columnas que se pueden cambiar con `update` (los nombres se pegan en la consulta; los valores van como parámetros).
UPDATABLE = ("name", "owner_user_id", "enabled", "config")


def list_all(conn: Conn, owner_user_id: int | None = None) -> list[dict]:
    """Todas las integraciones, o solo las de una persona si se indica."""
    return rows(conn.execute(
        """SELECT i.id, i.kind, i.name, i.owner_user_id, u.name AS owner, i.config, i.enabled,
                  i.last_sync_at, i.last_error, i.created_at
             FROM integrations i JOIN users u ON u.id = i.owner_user_id
            WHERE ?::bigint IS NULL OR i.owner_user_id = ? ORDER BY i.id""", (owner_user_id, owner_user_id)))


def get(conn: Conn, integration_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    return dict(row) if row else None


def insert(conn: Conn, kind: str, name: str, owner_user_id: int, config: str) -> int:
    return conn.execute("INSERT INTO integrations (kind, name, owner_user_id, config) VALUES (?, ?, ?, ?) RETURNING id",
                        (kind, name, owner_user_id, config)).lastrowid


def update(conn: Conn, integration_id: int, fields: dict) -> None:
    """Cambia las columnas de `fields` (solo las de UPDATABLE)."""
    unknown = set(fields) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"Columnas no modificables: {', '.join(sorted(unknown))}")
    if fields:
        conn.execute(f"UPDATE integrations SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                     [*fields.values(), integration_id])


def delete(conn: Conn, integration_id: int) -> None:
    conn.execute("DELETE FROM integrations WHERE id = ?", (integration_id,))


def save_state(conn: Conn, integration_id: int, state: str, error: str | None) -> None:
    conn.execute("UPDATE integrations SET state = ?, last_sync_at = localtimestamp(0), last_error = ? WHERE id = ?",
                 (state, error, integration_id))


def lock_last_error(conn: Conn, integration_id: int) -> str | None:
    """Error guardado ahora mismo. Bloquea la fila hasta el final de la transacción (para avisar una sola vez)."""
    row = conn.execute("SELECT last_error FROM integrations WHERE id = ? FOR UPDATE", (integration_id,)).fetchone()
    return row["last_error"] if row else None


def set_last_error(conn: Conn, integration_id: int, error: str | None) -> None:
    conn.execute("UPDATE integrations SET last_error = ? WHERE id = ?", (error, integration_id))


def list_syncable(conn: Conn) -> list[dict]:
    """Integraciones activas que se revisan en segundo plano: email y Telegram traen lo pendiente; WhatsApp solo
    comprueba sus credenciales (los mensajes le llegan por webhook)."""
    return rows(conn.execute("SELECT id, kind, config, last_sync_at FROM integrations WHERE enabled = 1"))


def find_sender_id(conn: Conn, kind: str, user_id: int, role: str) -> int | None:
    """Integración activa del canal con la que puede enviar el usuario: la suya primero (un admin, cualquiera)."""
    row = conn.execute(
        """SELECT id FROM integrations WHERE kind = ? AND enabled = 1 AND (owner_user_id = ? OR ? = 'admin')
            ORDER BY owner_user_id = ? DESC, id LIMIT 1""",
        (kind, user_id, role, user_id)).fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------- Datos de otras tablas que usan las integraciones

def phone_handles(conn: Conn) -> list[str]:
    """Identificadores de WhatsApp y teléfono ya guardados."""
    return [r["handle"] for r in conn.execute("SELECT handle FROM client_identities WHERE channel IN ('whatsapp', 'phone')")]


def conversation(conn: Conn, conversation_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, channel, subject, client_id, owner_user_id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return dict(row) if row else None


def client_handles(conn: Conn, client_id: int, channel: str) -> list[str]:
    return [r["handle"] for r in conn.execute(
        "SELECT handle FROM client_identities WHERE client_id = ? AND channel = ? ORDER BY id", (client_id, channel))]


def last_incoming_external_id(conn: Conn, conversation_id: int) -> str | None:
    """Identificador externo del último mensaje recibido (para responder en el mismo hilo de email)."""
    row = conn.execute(
        """SELECT external_id FROM messages WHERE conversation_id = ? AND direction = 'in'
            AND external_id IS NOT NULL ORDER BY sent_at DESC, id DESC LIMIT 1""", (conversation_id,)).fetchone()
    return row["external_id"] if row else None


def insert_sent_message(conn: Conn, conversation_id: int, sender: str, body: str, sent_at: str,
                        external_id: str) -> int:
    return conn.execute(
        """INSERT INTO messages (conversation_id, direction, sender, body, sent_at, external_id)
           VALUES (?, 'out', ?, ?, ?, ?) RETURNING id""", (conversation_id, sender, body, sent_at, external_id)).lastrowid
