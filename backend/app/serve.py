"""Arranque del servidor para uso real (desde la carpeta backend): python -m app.serve

Lee la configuración de backend/.env:
  HOST, PORT                       dirección y puerto (por defecto 127.0.0.1:8000)
  SSL_CERTFILE, SSL_KEYFILE        certificado y clave para servir HTTPS directamente
  FORWARDED_ALLOW_IPS              IPs de proxys de confianza (p. ej. Caddy) cuyas cabeceras
                                   X-Forwarded-* se aceptan; por defecto solo 127.0.0.1
"""
import uvicorn

from .config import config


def main() -> None:
    server = config.server
    if bool(server.ssl_certfile) != bool(server.ssl_keyfile):
        raise SystemExit("Para HTTPS hacen falta SSL_CERTFILE y SSL_KEYFILE a la vez.")
    uvicorn.run(
        "app.main:app",
        host=server.host,
        port=server.port,
        ssl_certfile=server.ssl_certfile,
        ssl_keyfile=server.ssl_keyfile,
        # Detrás de un proxy HTTPS: usar la IP real del cliente y el esquema https que indica el proxy.
        proxy_headers=True,
        forwarded_allow_ips=server.forwarded_allow_ips,
        server_header=False,
    )


if __name__ == "__main__":
    main()
