"""Inicio de sesión, cuentas, contraseñas, conversaciones persistentes y medidas de seguridad."""
import sys
import time
import urllib.error
import urllib.request

from apitest import BASE, Session, check, results

anon = Session()
check("sin sesión /api/me = 401", anon.get("/api/me")[0] == 401)
check("sin sesión /api/clients = 401", anon.get("/api/clients")[0] == 401)
check("contraseña incorrecta = 401", anon.post("/api/auth/login", {"username": "ana", "password": "mala"})[0] == 401)

ana = Session()
st, me = ana.post("/api/auth/login", {"username": "ANA", "password": "demo1234"})
check("login sin distinguir mayúsculas en el usuario", st == 200 and me["role"] == "admin", me)
st, me = ana.patch("/api/me", {"theme": "dark", "tour_version": 1})
check("guardar tema y versión del tutorial", me["theme"] == "dark" and me["tour_version"] == 1, me)

# Administración de cuentas
marta = Session("marta")
check("no admin no lista usuarios = 403", marta.get("/api/admin/users")[0] == 403)
check("contraseña corta = 400", ana.post("/api/admin/users", {"username": "pepe", "name": "Pepe", "password": "corta"})[0] == 400)
st, pepe = ana.post("/api/admin/users", {"username": "pepe", "name": "Pepe", "password": "pepe12345"})
check("crear usuario", st == 200, pepe)
check("usuario duplicado = 409", ana.post("/api/admin/users", {"username": "Pepe", "name": "X", "password": "12345678"})[0] == 409)
pepe_s = Session("pepe", "pepe12345")
ana.patch(f"/api/admin/users/{pepe['id']}", {"active": False})
check("desactivar cierra sus sesiones", pepe_s.get("/api/me")[0] == 401)
check("desactivado no entra", Session().post("/api/auth/login", {"username": "pepe", "password": "pepe12345"})[0] == 401)
check("un admin no se desactiva a sí mismo = 400", ana.patch(f"/api/admin/users/{me['id']}", {"active": False})[0] == 400)

# Cambio de contraseña
check("contraseña actual mala = 400", marta.post("/api/me/password", {"current_password": "x", "new_password": "nueva12345"})[0] == 400)
check("cambiar contraseña", marta.post("/api/me/password", {"current_password": "demo1234", "new_password": "nueva12345"})[0] == 200)
check("la sesión actual sigue abierta", marta.get("/api/me")[0] == 200)
check("login con la nueva", Session().post("/api/auth/login", {"username": "marta", "password": "nueva12345"})[0] == 200)

# Conversaciones con el asistente (sin clave de API)
check("asistente sin clave = 503 con mensaje claro", ana.post("/api/chat", {"message": "hola", "client_id": 1})[0] == 503)
check("mascota sin clave = 503", ana.post("/api/help", {"message": "hola"})[0] == 503)
check("sin clave no se guarda nada", ana.get("/api/conversations/help")[1]["turns"] == [])
check("mensaje enorme = 422", ana.post("/api/chat", {"message": "x" * 5000})[0] == 422)

# Seguridad
check("/docs desactivado", anon.get("/docs")[0] == 404)
t0 = time.perf_counter(); anon.post("/api/auth/login", {"username": "nadie", "password": "x"})
t1 = time.perf_counter(); anon.post("/api/auth/login", {"username": "carlos", "password": "x"})
t2 = time.perf_counter()
check("mismo tiempo exista o no el usuario", abs((t1 - t0) - (t2 - t1)) < 0.2, f"{t1 - t0:.3f} / {t2 - t1:.3f}")
for _ in range(4):  # + el fallo de la comprobación de tiempos = 5 fallos seguidos
    anon.post("/api/auth/login", {"username": "carlos", "password": "mala"})
check("bloqueo tras 5 fallos aun con la contraseña buena = 429",
      anon.post("/api/auth/login", {"username": "carlos", "password": "demo1234"})[0] == 429)
ana.patch("/api/admin/users/2", {"password": "demo1234"})
check("restablecer la contraseña desbloquea", Session().post("/api/auth/login", {"username": "carlos", "password": "demo1234"})[0] == 200)
req = urllib.request.Request(BASE + "/api/me", data=b'{"theme": "light"}', method="PATCH",
                             headers={"Content-Type": "application/json", "Origin": "https://web-maliciosa.com"})
try:
    ana.opener.open(req)
    check("petición desde otra web = 403", False)
except urllib.error.HTTPError as e:
    check("petición desde otra web = 403", e.code == 403)
check("contraseña enorme en login = 422", anon.post("/api/auth/login", {"username": "ana", "password": "x" * 500})[0] == 422)
check("logout", ana.post("/api/auth/logout")[0] == 200 and ana.get("/api/me")[0] == 401)
sys.exit(0 if results["ok"] else 1)
