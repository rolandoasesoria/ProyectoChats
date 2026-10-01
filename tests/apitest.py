"""Utilidades comunes para las pruebas contra la instancia de pruebas (puerto 8001)."""
import http.cookiejar
import json
import urllib.error
import urllib.request

import testdb  # noqa: F401  (DATABASE_URL de pruebas)

BASE = "http://127.0.0.1:8001"
results = {"ok": True}


def check(label, cond, extra=""):
    results["ok"] &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label + (f"  -> {extra}" if extra and not cond else ""))


class Session:
    def __init__(self, username=None, password="demo1234"):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        if username:
            st, body = self.call("POST", "/api/auth/login", {"username": username, "password": password})
            assert st == 200, body

    def call(self, method, path, body=None):
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None):
        return self.call("POST", path, body if body is not None else {})

    def patch(self, path, body):
        return self.call("PATCH", path, body)

    def delete(self, path):
        return self.call("DELETE", path)


def receive(channel: str, handle: str, body: str, *, owner: int = 1, client_name: str | None = None,
            client_id: int | None = None, direction: str = "in", sender: str | None = None,
            sent_at: str | None = None, attachments=None) -> dict:
    """Un mensaje que entra por una integración (WhatsApp, Telegram o email), por el mismo camino que los reales.
    Con client_id se guarda en ese cliente aunque el identificador sea nuevo."""
    from datetime import datetime

    from app import integrations, search
    message = {"direction": direction, "sender": sender or client_name or handle, "body": body,
               "sent_at": sent_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "attachments": attachments or []}
    if client_id is not None:
        return search.import_conversation({"owner_user_id": owner, "channel": channel, "handle": handle,
                                           "client_id": client_id, "client_name": client_name, "messages": [message]})
    return integrations.ingest({"kind": channel, "owner_user_id": owner}, handle=handle,
                               client_name=client_name or handle, direction=direction, sender=message["sender"],
                               body=body, sent_at=message["sent_at"], external_id=None, attachments=attachments)
