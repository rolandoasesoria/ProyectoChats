# Arranca todo lo necesario para usar la app en este equipo: PostgreSQL, el túnel fijo de los webhooks de WhatsApp
# (si hay ngrok configurado; ver webhook-publico.ps1) y el servidor de la app, sin ventanas. Pensado para el arranque automático al iniciar sesión (ver -InstalarInicio).
#
#   powershell -ExecutionPolicy Bypass -File scripts/arrancar.ps1                  # arrancar ahora
#   powershell -ExecutionPolicy Bypass -File scripts/arrancar.ps1 -InstalarInicio  # arrancar solo al iniciar sesión
#   powershell -ExecutionPolicy Bypass -File scripts/arrancar.ps1 -QuitarInicio    # dejar de arrancar solo
#
# El registro de la app queda en backend/data/app.log. Si la app ya está en marcha, no hace nada.
param([switch]$InstalarInicio, [switch]$QuitarInicio)
$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Repo "backend"
$Atajo = Join-Path ([Environment]::GetFolderPath("Startup")) "ProyectoChats.lnk"

if ($InstalarInicio -or $QuitarInicio) {
  # Accesos directos antiguos que solo arrancaban PostgreSQL.
  Remove-Item (Join-Path ([Environment]::GetFolderPath("Startup")) "PostgreSQL (ProyectoChats).lnk") -ErrorAction SilentlyContinue
  if ($QuitarInicio) { Remove-Item $Atajo -ErrorAction SilentlyContinue; Write-Output "Arranque automático desactivado."; exit 0 }
  $sh = New-Object -ComObject WScript.Shell
  $s = $sh.CreateShortcut($Atajo)
  $s.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $s.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  $s.WorkingDirectory = $Repo
  $s.WindowStyle = 7
  $s.Description = "Arranca PostgreSQL y la app ProyectoChats al iniciar sesión"
  $s.Save()
  Write-Output "Arranque automático activado: $Atajo"
  exit 0
}

# 1. PostgreSQL (espera a que acepte conexiones).
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "postgres.ps1") iniciar | Out-Null

# 2. El túnel fijo de los webhooks de WhatsApp (solo si hay ngrok con su token y no está ya abierto). Va en segundo
#    plano: si falla, la app arranca igual y el fallo queda en backend/data/tunel-arranque.log.
$conNgrok = (Select-String -Path (Join-Path $Backend ".env") -Pattern "^NGROK_AUTHTOKEN=\S" -Quiet -ErrorAction SilentlyContinue) `
  -or (Select-String -Path (Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml") -Pattern "authtoken" -Quiet -ErrorAction SilentlyContinue)
if ($conNgrok -and -not (Get-Process ngrok -ErrorAction SilentlyContinue)) {
  New-Item -ItemType Directory -Force (Join-Path $Backend "data") | Out-Null
  Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -WindowStyle Hidden `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$(Join-Path $PSScriptRoot 'webhook-publico.ps1')`"" `
    -RedirectStandardOutput (Join-Path $Backend "data\tunel-arranque.log") | Out-Null
}

# 3. La app, si no está ya escuchando en su puerto.
$puerto = 8000
$linea = Get-Content (Join-Path $Backend ".env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "^PORT=\d+" } | Select-Object -First 1
if ($linea) { $puerto = [int]($linea -replace "^PORT=", "") }
if (Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue) {
  Write-Output "La app ya está en marcha en http://localhost:$puerto"
  exit 0
}
$log = Join-Path $Backend "data\app.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
Start-Process -FilePath (Join-Path $Backend ".venv\Scripts\python.exe") -ArgumentList "-m", "app.serve" `
  -WorkingDirectory $Backend -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err" | Out-Null
for ($i = 0; $i -lt 40; $i++) {
  if (Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "App en marcha: http://localhost:$puerto"
    exit 0
  }
  Start-Sleep -Milliseconds 500
}
Write-Output "La app no ha arrancado; revisa $log.err"
exit 1
