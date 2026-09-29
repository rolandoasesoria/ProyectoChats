# Activa los hooks del proyecto (.githooks) y la plantilla de mensaje de commit en este clon del repositorio.
# Uso (desde la raíz del repositorio):  powershell -ExecutionPolicy Bypass -File scripts/instalar-hooks.ps1

$raiz = git rev-parse --show-toplevel
if (-not $raiz) { Write-Error "Ejecuta este script dentro del repositorio."; exit 1 }
Set-Location $raiz

git config core.hooksPath .githooks
git config commit.template .gitmessage

Write-Output "Hooks activados (.githooks) y plantilla de commit configurada (.gitmessage)."
Write-Output "Guía: docs/CONTROL_DE_VERSIONES.md"
