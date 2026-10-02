# Publica en internet SOLO los webhooks de WhatsApp (para que Meta pueda avisar de los mensajes que llegan).
#
#   powershell -ExecutionPolicy Bypass -File scripts/webhook-publico.ps1          # arrancar y mostrar la URL pública
#   powershell -ExecutionPolicy Bypass -File scripts/webhook-publico.ps1 parar    # cerrar el túnel
#
# Arranca la puerta de webhooks (python -m app.webhook_gateway, en 127.0.0.1:8010, que solo responde a
# /api/webhooks/...) y un túnel rápido de Cloudflare hacia ella. El resto de la app NO se publica.
# La URL pública cambia cada vez que se abre el túnel: cópiala en Meta (WhatsApp > Configuración > Webhook) cada vez.
# Para una URL fija hace falta un túnel con nombre en una cuenta de Cloudflare con dominio propio.
# Requiere cloudflared.exe en %USERPROFILE%\cloudflared (o en el PATH).
param([Parameter(Position = 0)][ValidateSet("arrancar", "parar")][string]$Accion = "arrancar")
$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Repo "backend"
$Data = Join-Path $Backend "data"
$UrlFile = Join-Path $Data "webhook_public_url.txt"
$TunnelLog = Join-Path $Data "tunel.log"
$GatewayLog = Join-Path $Data "webhook.log"
$Puerto = 8010
$linea = Get-Content (Join-Path $Backend ".env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "^WEBHOOK_PORT=\d+" } | Select-Object -First 1
if ($linea) { $Puerto = [int]($linea -replace "^WEBHOOK_PORT=", "") }

function Procesos([string]$patron) {
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $patron }
}

if ($Accion -eq "parar") {
  Procesos "cloudflared.*tunnel" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Procesos "app\.webhook_gateway" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Remove-Item $UrlFile -ErrorAction SilentlyContinue
  Write-Output "Túnel cerrado: los webhooks ya no son accesibles desde internet."
  exit 0
}

$Cloudflared = @((Join-Path $env:USERPROFILE "cloudflared\cloudflared.exe"), (Get-Command cloudflared -ErrorAction SilentlyContinue).Source) |
  Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $Cloudflared) { throw "No se encuentra cloudflared.exe (descárgalo en $env:USERPROFILE\cloudflared)." }
New-Item -ItemType Directory -Force $Data | Out-Null

# 1. La puerta de webhooks (solo /api/webhooks/...), si no está ya escuchando.
if (-not (Get-NetTCPConnection -LocalPort $Puerto -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process -FilePath (Join-Path $Backend ".venv\Scripts\python.exe") -ArgumentList "-m", "app.webhook_gateway" `
    -WorkingDirectory $Backend -WindowStyle Hidden -RedirectStandardOutput $GatewayLog -RedirectStandardError "$GatewayLog.err" | Out-Null
  for ($i = 0; $i -lt 30 -and -not (Get-NetTCPConnection -LocalPort $Puerto -State Listen -ErrorAction SilentlyContinue); $i++) {
    Start-Sleep -Milliseconds 500
  }
}

# 2. El túnel hacia esa puerta (uno solo: si había otro, se cierra).
Procesos "cloudflared.*tunnel" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item $TunnelLog, $UrlFile -ErrorAction SilentlyContinue
Start-Process -FilePath $Cloudflared -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$Puerto", "--logfile", "`"$TunnelLog`"" `
  -WindowStyle Hidden | Out-Null
$url = $null
for ($i = 0; $i -lt 60 -and -not $url; $i++) {
  Start-Sleep -Milliseconds 500
  $m = Select-String -Path $TunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($m) { $url = $m.Matches[0].Value }
}
if (-not $url) { throw "El túnel no ha dado una URL; revisa $TunnelLog" }
[IO.File]::WriteAllText($UrlFile, $url)
Write-Output "Webhooks publicados en: $url"
Write-Output "En «Mis cuentas» verás la URL completa del webhook de cada cuenta de WhatsApp para copiarla en Meta."
