# Control de versiones

Objetivo: que el historial cuente **cómo** se construyó la app en pasos pequeños, revisables y reversibles,
en vez de saltos de miles de líneas.

## 1. Regla de oro: un commit = un cambio lógico

- Cada commit hace **una sola cosa** y se puede describir en una línea sin usar «y».
- Cada commit deja la app **funcionando** (arranca y pasan las pruebas rápidas).
- Tamaño orientativo: **menos de ~300 líneas cambiadas**. El hook avisa a partir de 400 y bloquea a partir de 800
  (se puede forzar a propósito, ver §5).
- Mejor 6 commits pequeños que 1 grande: `git revert` y `git bisect` solo sirven si los cambios están separados.

### Cómo trocear una funcionalidad

Una funcionalidad nueva (por ejemplo «notas internas») se reparte así, en este orden:

| # | Commit | Ejemplo |
|---|---|---|
| 1 | Esquema de base de datos | `feat(notas): tablas de notas y avisos` |
| 2 | Lógica del backend | `feat(notas): detectar @menciones y crear avisos` |
| 3 | Rutas de la API | `feat(notas): rutas para crear, editar y borrar notas` |
| 4 | Pruebas del backend | `test(notas): notas, menciones y permisos` |
| 5 | Interfaz | `feat(notas): pestaña Notas con autocompletado de menciones` |
| 6 | Tutorial y ayuda | `docs(tutorial): paso de notas y avisos; Chispa los explica` |
| 7 | Documentación | `docs(readme): notas internas y avisos` |

Si un paso sale grande (p. ej. la interfaz), se divide otra vez: marcado HTML → estilos → comportamiento.
Las correcciones que aparecen por el camino van en **su propio** commit `fix(...)`, no mezcladas.

Herramienta clave para trocear lo ya escrito: `git add -p` (añade por fragmentos, no archivos enteros).

## 2. Mensajes: Conventional Commits en español

```
tipo(ámbito): resumen en presente, sin punto final (máx. 72 caracteres)

Por qué se hace el cambio y cualquier detalle que no se vea en el código.
```

| Tipo | Cuándo |
|---|---|
| `feat` | Funcionalidad nueva para el usuario |
| `fix` | Corrección de un error |
| `refactor` | Cambia el código sin cambiar el comportamiento |
| `perf` | Mejora de rendimiento |
| `style` | Solo estética de la interfaz (CSS) o formato |
| `test` | Añade o corrige pruebas |
| `docs` | README, guías, tutorial, textos de ayuda |
| `chore` | Herramientas, dependencias, configuración |

Ámbitos habituales: `auth`, `asistente`, `chispa`, `clientes`, `ficha`, `tareas`, `notas`, `bandeja`,
`borradores`, `importar`, `documentos`, `busqueda`, `panel`, `integraciones`, `datos` (protección de datos),
`tutorial`, `seguridad`, `db`, `ui`, `readme`, `tests`, `git`.

Plantilla: `.gitmessage` (se activa con el script de §5).

## 3. Ramas

- `main`: siempre funciona y es lo que se despliega. **No se trabaja directamente en `main`.**
- Una rama por funcionalidad o arreglo, corta (de horas a pocos días):
  - `feat/<tema>` · `fix/<tema>` · `chore/<tema>` · `docs/<tema>` — p. ej. `feat/plantillas-whatsapp`.
- Se integra en `main` con **merge normal (sin squash)** para conservar los commits pequeños:
  `git switch main && git merge --no-ff feat/<tema>` (o un Pull Request en GitHub con «Create a merge commit»).
- Antes de integrar: `git rebase main` en la rama si `main` ha avanzado, y pasar las pruebas.

## 4. Versiones y registro de cambios

- Versionado semántico `vMAYOR.MENOR.PARCHE` con etiquetas de git. Mientras la app esté en desarrollo: `v0.x`.
  - Funcionalidad nueva → sube MENOR (`v0.3.0` → `v0.4.0`). Solo arreglos → PARCHE (`v0.4.1`).
- Cada versión se anota en [`CHANGELOG.md`](../CHANGELOG.md) (sección «Sin publicar» mientras se trabaja).
- Etiquetar: `git tag -a v0.4.0 -m "v0.4.0: plantillas de WhatsApp"` y `git push --tags`.

## 5. Guardianes automáticos (hooks)

Instalación, una vez por equipo (en la raíz del repositorio):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/instalar-hooks.ps1
```

Activa la plantilla de mensaje y estos hooks de `.githooks/`:

| Hook | Qué hace |
|---|---|
| `commit-msg` | Rechaza mensajes que no siguen `tipo(ámbito): resumen` (admite `Merge` y `Revert`). |
| `pre-commit` | Impide añadir secretos o datos (`.env`, `*.db`, `secret.key`, `backend/data/`). Avisa si el commit supera 400 líneas y lo **bloquea** a partir de 800. |

Para un commit grande a propósito (p. ej. mover archivos): `$env:GIT_COMMIT_GRANDE=1; git commit ...`
(y explica el porqué en el cuerpo del mensaje).

## 6. Pruebas antes de cada commit

Ver [`tests/README.md`](../tests/README.md). Mínimo antes de cada commit: las pruebas rápidas.
Antes de integrar en `main`: la batería completa, incluido el recorrido en el navegador.

## 7. Historial anterior

Los dos primeros commits (`c360944`, `6e8d047`) son anteriores a esta guía y agrupan mucho trabajo.
Se etiquetan como `v0.1.0` y `v0.2.0` y se describen por partes en el `CHANGELOG.md`. No se reescriben:
ya están en GitHub y reescribirlos obligaría a forzar la subida.
