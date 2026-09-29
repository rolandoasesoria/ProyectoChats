"""Arranque del servidor para uso real (desde la carpeta backend): python -m app.serve

Lee la configuración de backend/.env:
  HOST, PORT                       dirección y puerto (por defecto 127.0.0.1:8000)
  SSL_CERTFILE, SSL_KEYFILE        certificado y clave para servir HTTPS directamente
  FORWARDED_ALLOW_IPS              IPs de proxys de confianza (p. ej. Caddy) cuyas cabeceras
                                   X-Forwarded-* se aceptan; por defecto solo 127.0.0.1
"""
import os

import uvicorn


def main() -> None:
    certfile = os.getenv("SSL_CERTFILE") or None
    keyfile = os.getenv("SSL_KEYFILE") or None
    if bool(certfile) != bool(keyfile):
        raise SystemExit("Para HTTPS hacen falta SSL_CERTFILE y SSL_KEYFILE a la vez.")
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
        # Detrás de un proxy HTTPS: usar la IP real del cliente y el esquema https que indica el proxy.
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        server_header=False,
    )


if __name__ == "__main__":
    main()
