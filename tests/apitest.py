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
