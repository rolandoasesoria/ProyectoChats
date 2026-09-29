"""Administración desde la consola del servidor (desde la carpeta backend).

  python -m app.manage create-user USUARIO "Nombre Apellido" [--email EMAIL] [--admin]
  python -m app.manage set-password USUARIO
  python -m app.manage list-users

Útil para crear el primer administrador; el resto se puede gestionar desde la app.
"""
import argparse
import getpass
import sys

from fastapi import HTTPException

from . import auth
from .db import get_conn, init_db


def _ask_password() -> str:
    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="Crear una cuenta")
    create.add_argument("username")
    create.add_argument("name")
    create.add_argument("--email")
    create.add_argument("--admin", action="store_true", help="Darle rol de administrador")
    reset = sub.add_parser("set-password", help="Poner una contraseña nueva a una cuenta")
    reset.add_argument("username")
    sub.add_parser("list-users", help="Listar cuentas")
    args = parser.parse_args()

    init_db()
    try:
        if args.command == "create-user":
            user = auth.create_user(args.username, args.name, _ask_password(), args.email,
                                    "admin" if args.admin else "user")
            print(f"Cuenta creada: {user['username']} ({user['role']})")
        elif args.command == "set-password":
            with get_conn() as conn:
                row = conn.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                                   (args.username,)).fetchone()
            if not row:
                sys.exit("No existe ese usuario.")
            auth.update_user(row["id"], password=_ask_password())
            print("Contraseña actualizada; se han cerrado sus sesiones abiertas.")
        elif args.command == "list-users":
            for u in auth.list_users():
                state = "activo" if u["active"] else "desactivado"
                print(f"{u['id']:>3}  {u['username'] or '-':<15} {u['name']:<25} {u['role']:<6} {state}")
    except HTTPException as exc:
        sys.exit(exc.detail)


if __name__ == "__main__":
    main()
