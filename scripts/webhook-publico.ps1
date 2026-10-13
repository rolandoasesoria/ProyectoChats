# Publica en internet SOLO los webhooks de WhatsApp (para que Meta pueda avisar de los mensajes que llegan).
#
#   powershell -ExecutionPolicy Bypass -File scripts/webhook-publico.ps1          # arrancar y mostrar la URL pública
#   powershell -ExecutionPolicy Bypass -File scripts/webhook-publico.ps1 parar    # cerrar el túnel
#
# Arranca la puerta de webhooks (python -m app.webhook_gateway, en 127.0.0.1:8010, que solo responde a
# /api/webhooks/...) y un túnel hacia ella. El resto de la app NO se publica.
#
# - Con ngrok instalado y su token (NGROK_AUTHTOKEN en backend/.env, o ya guardado con «ngrok config add-authtoken»):
#   la URL es FIJA (el dominio gratuito de la cuenta; NGROK_DOMAIN en backend/.env lo indica expresamente). Se pone
#   una sola vez en Meta y scripts/arrancar.ps1 abre el túnel solo al iniciar sesión.
# - Sin ngrok: túnel rápido de Cloudflare (cloudflared.exe en %USERPROFILE%\cloudflared o en el PATH). Su URL cambia
#   cada vez que se abre: hay que copiarla en Meta (WhatsApp > Configuración > Webhook) cada vez.
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

function CerrarTuneles {
  Procesos "cloudflared.*tunnel" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Get-Process ngrok -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

if ($Accion -eq "parar") {
  CerrarTuneles
  Procesos "app\.webhook_gateway" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Remove-Item $UrlFile -ErrorAction SilentlyContinue
  Write-Output "Túnel cerrado: los webhooks ya no son accesibles desde internet."
  exit 0
}

$Ngrok = @((Join-Path $env:LOCALAPPDATA "Programs\ngrok\ngrok.exe"), (Get-Command ngrok -ErrorAction SilentlyContinue).Source) |
  Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
function ValorEnv([string]$nombre) {
  ((Get-Content (Join-Path $Backend ".env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "^$nombre=\S" } |
    Select-Object -First 1) -replace "^$nombre=", "").Trim()
}
if ($Ngrok) {
  # El token de backend/.env manda sobre el que hubiera guardado en ngrok (así el token y el dominio son de la misma cuenta).
  $token = ValorEnv "NGROK_AUTHTOKEN"
  if ($token) { & $Ngrok config add-authtoken $token | Out-Null }
  if (-not (Select-String -Path (Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml") -Pattern "authtoken" -Quiet -ErrorAction SilentlyContinue)) {
    $Ngrok = $null  # instalado pero sin token: no puede abrir túneles
  }
}
$Cloudflared = @((Join-Path $env:USERPROFILE "cloudflared\cloudflared.exe"), (Get-Command cloudflared -ErrorAction SilentlyContinue).Source) |
  Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $Ngrok -and -not $Cloudflared) { throw "No hay ngrok (con su token) ni cloudflared.exe para abrir el túnel." }
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
CerrarTuneles
Remove-Item $TunnelLog, $UrlFile -ErrorAction SilentlyContinue
$url = $null
if ($Ngrok) {
  $dominio = ValorEnv "NGROK_DOMAIN"
  $argumentos = @("http", "$Puerto", "--log", "`"$TunnelLog`"", "--log-format", "json")
  if ($dominio) { $argumentos += @("--url", $dominio) }
  Start-Process -FilePath $Ngrok -ArgumentList $argumentos -WindowStyle Hidden | Out-Null
  for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep -Milliseconds 500
    try {
      $tuneles = (Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2).tunnels
      $url = ($tuneles | Where-Object { $_.public_url -like "https*" } | Select-Object -First 1).public_url
    } catch { }
  }
} else {
  Start-Process -FilePath $Cloudflared -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$Puerto", "--logfile", "`"$TunnelLog`"" `
    -WindowStyle Hidden | Out-Null
  for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep -Milliseconds 500
    $m = Select-String -Path $TunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($m) { $url = $m.Matches[0].Value }
  }
}
if (-not $url) { throw "El túnel no ha dado una URL; revisa $TunnelLog" }
[IO.File]::WriteAllText($UrlFile, $url)
Write-Output "Webhooks publicados en: $url"
if ($Ngrok) { Write-Output "Es una URL fija: en Meta solo hay que ponerla una vez ($url/api/webhooks/whatsapp)." }
else { Write-Output "Esta URL cambia cada vez que se abre el túnel: cópiala en Meta ($url/api/webhooks/whatsapp)." }
