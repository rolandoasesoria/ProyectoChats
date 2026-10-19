"""«Mi perfil»: cada usuario cambia su nombre, email, tema y foto (y no los de los demás)."""
import base64
import sys

from apitest import BASE, Session, check, results

marta, carlos = Session("marta"), Session("carlos")
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

# Nombre y email
st, me = marta.patch("/api/me", {"name": "  Marta   López Gil ", "email": "marta.lopez@miempresa.com"})
check("cambia su nombre (sin espacios de sobra) y su email",
      st == 200 and me["name"] == "Marta López Gil" and me["email"] == "marta.lopez@miempresa.com", me)
check("el resto del equipo ve el nombre nuevo",
      any(u["name"] == "Marta López Gil" for u in carlos.get("/api/team")[1]))
check("nombre vacío = 400", marta.patch("/api/me", {"name": "   "})[0] == 400)
check("email sin @ = 400", marta.patch("/api/me", {"email": "marta"})[0] == 400)
check("email de otra persona del equipo = 409", marta.patch("/api/me", {"email": "Carlos@miempresa.com"})[0] == 409)
check("volver a guardar el suyo no choca consigo mismo",
      marta.patch("/api/me", {"email": "marta.lopez@miempresa.com"})[0] == 200)
check("el email se puede dejar vacío", marta.patch("/api/me", {"email": ""})[1]["email"] is None)
check("solo con el tema, lo demás se queda igual",
      marta.patch("/api/me", {"theme": "dark"})[1]["name"] == "Marta López Gil")
check("no puede cambiarse el rol ni los permisos",
      marta.patch("/api/me", {"role": "admin", "can_view_team_chats": True})[1]["role"] == "user"
      and marta.get("/api/me")[1]["can_view_team_chats"] == 0)

# Foto de perfil
check("sin foto", marta.get("/api/me")[1]["avatar_version"] == "" and carlos.get("/api/users/3/avatar")[0] == 404)
check("una foto que no es imagen = 400",
      marta.call("PUT", "/api/me/avatar", {"data": base64.b64encode(b"<svg onload=alert(1)>").decode()})[0] == 400)
check("más de 256 KB = 400",
      marta.call("PUT", "/api/me/avatar", {"data": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 270_000).decode()})[0] in (400, 422))
st, me = marta.call("PUT", "/api/me/avatar", {"data": PNG})
check("subir una foto", st == 200 and len(me["avatar_version"]) == 12, me)
check("el equipo sabe qué foto tiene (para la caché del navegador)",
      next(u for u in carlos.get("/api/team")[1] if u["id"] == 3)["avatar_version"] == me["avatar_version"])
photo = carlos.opener.open(BASE + f"/api/users/3/avatar?v={me['avatar_version']}")
check("los demás la ven, con su tipo", photo.status == 200 and photo.headers["Content-Type"] == "image/png"
      and photo.read() == base64.b64decode(PNG))
check("sin sesión no se ve", Session().get("/api/users/3/avatar")[0] == 401)
check("quitarla", marta.delete("/api/me/avatar")[1]["avatar_version"] == "" and carlos.get("/api/users/3/avatar")[0] == 404)

marta.patch("/api/me", {"name": "Marta López", "email": "marta@miempresa.com", "theme": "system"})
sys.exit(0 if results["ok"] else 1)
