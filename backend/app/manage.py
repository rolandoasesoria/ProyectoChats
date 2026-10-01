"""Administración desde la consola del servidor (desde la carpeta backend).

  python -m app.manage create-user USUARIO "Nombre Apellido" [--email EMAIL] [--admin]
  python -m app.manage set-password USUARIO
  python -m app.manage list-users
  python -m app.manage migrate          aplica las migraciones pendientes (usuario DATABASE_ADMIN_URL)
  python -m app.manage db-status        conexión (cifrado, usuario) y migraciones aplicadas

Útil para crear el primer administrador; el resto se puede gestionar desde la app.
"""
import argparse
import getpass
import sys

from fastapi import HTTPException

from . import auth
from .config import config
from .db import get_conn, init_db, migrations, safe_url


def _ask_password() -> str:
    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden.")
    return password


def _db_status() -> None:
    with get_conn() as conn:
        info = conn.execute("""SELECT current_user AS usuario, s.ssl, s.version AS tls, s.cipher,
                                       has_schema_privilege('public', 'CREATE') AS puede_crear
                                  FROM pg_stat_ssl s WHERE s.pid = pg_backend_pid()""").fetchone()
    print(f"Conexión de la app: {safe_url(config.database.url)}")
    print(f"  usuario {info['usuario']}; cifrada: {'sí, ' + info['tls'] + ' ' + info['cipher'] if info['ssl'] else 'NO'}")
    print(f"  puede crear o borrar tablas: {'sí' if info['puede_crear'] else 'no'}")
    missing = migrations.pending()
    print(f"Migraciones: {len(migrations.discover()) - len(missing)} aplicadas, {len(missing)} pendientes")
    for m in missing:
        print(f"  pendiente: {m.name}")


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
    sub.add_parser("migrate", help="Aplicar las migraciones pendientes del esquema")
    sub.add_parser("db-status", help="Estado de la conexión y de las migraciones")
    args = parser.parse_args()

    if args.command == "migrate":
        applied = migrations.upgrade()
        print("Aplicadas: " + ", ".join(applied) if applied else "El esquema ya estaba al día.")
        return
    if args.command == "db-status":
        _db_status()
        return
    init_db()
    try:
        if args.command == "create-user":
            user = auth.create_user(args.username, args.name, _ask_password(), args.email,
                                    "admin" if args.admin else "user")
            print(f"Cuenta creada: {user['username']} ({user['role']})")
        elif args.command == "set-password":
            with get_conn() as conn:
                row = conn.execute("SELECT id FROM users WHERE lower(username) = lower(?)",
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
