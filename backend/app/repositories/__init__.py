"""Capa de datos: aquí, y solo aquí, está el SQL de la app.

Reglas:
- Un módulo por área (clientes, mensajes, tareas...). Sus funciones reciben la conexión como primer argumento
  (`conn`) y devuelven datos simples (dict, list, int...), nunca cursores.
- No contienen reglas de negocio ni comprueban permisos: eso es cosa de los servicios (app/*.py), que abren la
  transacción (`with get_conn() as conn:`) y llaman a uno o varios repositorios dentro de ella.
- Los valores siempre van como parámetros (`?`); nunca se pegan en el texto de la consulta.
"""
