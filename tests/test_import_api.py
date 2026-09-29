"""Prueba de la importación a través de la API (vista previa, importar, reimportar, cliente existente)."""
import base64
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001"
ok = True


def check(label, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label + (f"  -> {extra}" if extra and not cond else ""))


opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    try:
        with opener.open(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def b64(text: str | bytes) -> str:
    return base64.b64encode(text.encode() if isinstance(text, str) else text).decode()


call("POST", "/api/auth/login", {"username": "ana", "password": "demo1234"})

chat = """03/10/26, 9:15 - Pedro Sanz: Hola, ¿tenéis cajas de 40x30?
03/10/26, 9:20 - Ana Ruiz: Sí, desde 100 unidades
03/10/26, 9:21 - Pedro Sanz: Mi dirección es Av. Libertad 12, Valencia
"""
st, prev = call("POST", "/api/import/preview", {"filename": "Chat de WhatsApp con Pedro Sanz.txt", "data": b64(chat)})
check("vista previa", st == 200 and prev["total"] == 3 and prev["channel"] == "whatsapp", prev)
check("participantes", [p["key"] for p in prev["participants"]] == ["Pedro Sanz", "Ana Ruiz"], prev["participants"])

body = {"filename": "Chat de WhatsApp con Pedro Sanz.txt", "data": b64(chat), "client_key": "Pedro Sanz",
        "client_name": "Pedro Sanz", "handle": "+34611222333"}
st, res = call("POST", "/api/import/file", body)
check("importar a cliente nuevo", st == 200 and res["messages"] == 3 and res["duplicates"] == 0, res)
pedro = res["client_id"]

st, tl = call("GET", f"/api/clients/{pedro}/timeline?scope=mine")
check("mensajes en la línea de tiempo con direcciones", [m["direction"] for m in tl] == ["in", "out", "in"], tl)
st, found = call("GET", "/api/search?q=Libertad&scope=mine")
check("el contenido importado es buscable", any(r["client_id"] == pedro for r in found), found)

chat2 = chat + "04/10/26, 10:00 - Pedro Sanz: ¿Me confirmas el precio?\n"
st, prev = call("POST", "/api/import/preview", {"filename": "Chat de WhatsApp con Pedro Sanz.txt", "data": b64(chat2)})
check("reconoce el cliente ya existente por su nombre",
      any(p["client"] and p["client"]["id"] == pedro for p in prev["participants"]), prev)
# (el identificador guardado es el teléfono, no el nombre; por eso se elige el cliente a mano)
st, res = call("POST", "/api/import/file", {**body, "data": b64(chat2), "client_id": pedro, "handle": None})
check("reimportar: solo el mensaje nuevo", res["messages"] == 1 and res["duplicates"] == 3, res)
check("sigue en el mismo cliente", res["client_id"] == pedro)

mbox = (b"From x Tue Sep 22 09:05:00 2026\nFrom: Jorge Martin <jorge@talleresmartin.com>\nTo: ana@miempresa.com\n"
        b"Subject: Presupuesto nuevo\nDate: Tue, 22 Sep 2026 09:05:00 +0200\n\nQuiero 2.000 etiquetas mas\n\n"
        b"From y Tue Sep 22 10:00:00 2026\nFrom: Spam <spam@x.com>\nTo: ana@miempresa.com\n"
        b"Subject: Oferta\nDate: Tue, 22 Sep 2026 10:00:00 +0200\n\nCompra ya\n")
st, prev = call("POST", "/api/import/preview", {"filename": "buzon.mbox", "data": b64(mbox)})
jorge = next(p for p in prev["participants"] if p["key"] == "jorge@talleresmartin.com")
check("email: detecta que Jorge ya es cliente", jorge["client"] and jorge["client"]["name"] == "Jorge Martín", jorge)
st, res = call("POST", "/api/import/file", {"filename": "buzon.mbox", "data": b64(mbox),
                                             "client_key": "jorge@talleresmartin.com", "client_id": jorge["client"]["id"]})
check("email: solo importa el correo de Jorge", res["messages"] == 1 and res["client_id"] == jorge["client"]["id"], res)

st, res = call("POST", "/api/import/preview", {"filename": "x.txt", "data": "esto no es base64!!"})
check("base64 inválido = 400", st == 400, res)
st, res = call("POST", "/api/import/file", {**body, "client_key": "Alguien"})
check("participante inexistente = 400", st == 400, res)
sys.exit(0 if ok else 1)
