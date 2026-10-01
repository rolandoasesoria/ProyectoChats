# Ejecuta las pruebas. Uso (desde la raíz del repositorio):
#   powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1            -> pruebas rápidas (sin navegador)
#   powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1 -Todas     -> también el recorrido en el navegador
#   powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1 test_notes_api.py test_ui.py   -> solo esas
#
# Las pruebas "de API" se ejecutan contra una instancia propia en el puerto 8001 con una base de datos nueva
# (datos de ejemplo) en tests/.tmp, distinta para cada archivo. Nunca tocan backend/data.
param(
  [switch]$Todas,
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Pruebas
)
$tests = $PSScriptRoot
$backend = Join-Path (Split-Path $tests -Parent) "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
$tmp = Join-Path $tests ".tmp"
New-Item -ItemType Directory -Force $tmp | Out-Null

$env:PYTHONIOENCODING = "utf-8"
$env:PORT = "8001"
$env:DISABLE_SYNC = "true"
$env:DISABLE_AI = "true"   # aunque backend/.env tenga clave, las pruebas no llaman a la API de Claude
$env:DATA_DIR = $tmp

# Base de datos de pruebas (TEST_DATABASE_URL de backend/.env). Se vacía antes de cada archivo, así que
# nunca debe ser la base de datos real: su nombre tiene que contener "test".
$testUrl = (Get-Content (Join-Path $backend ".env") -ErrorAction SilentlyContinue |
  Where-Object { $_ -match "^TEST_DATABASE_URL=" } | Select-Object -First 1) -replace "^TEST_DATABASE_URL=", ""
if (-not $testUrl -or ($testUrl -split "/")[-1] -notmatch "test") {
  Write-Output "Falta TEST_DATABASE_URL (una base de datos cuyo nombre contenga 'test') en backend/.env."
  Write-Output "Ejecuta: powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 instalar"
  exit 1
}
$env:DATABASE_URL = $testUrl
$env:TEST_DATABASE_URL = $testUrl

# Sin servidor: lógica pura, con respuestas de Claude simuladas.
$unitarias = @("check_js.py", "test_emails.py", "test_insights.py", "test_agent_tools.py")
# Con servidor de pruebas.
$api = @("test_auth_api.py", "test_profile_api.py", "test_inbox_api.py", "test_notes_api.py",
         "test_clients_api.py", "test_privacy_api.py", "test_dashboard_api.py", "test_documents_api.py",
         "test_search_api.py", "test_drafts.py", "test_integrations.py", "test_replies_api.py", "test_followups_api.py", "test_settings_api.py", "test_redaction_api.py", "test_presence_api.py", "test_status_api.py")
$ui = @("test_ui.py")

if (-not $Pruebas) { $Pruebas = $unitarias + $api + $(if ($Todas) { $ui } else { @() }) }

$fallos = @()
foreach ($t in $Pruebas) {
  Write-Output "=== $t"
  $server = $null
  if ($unitarias -notcontains $t) {
    Remove-Item "$tmp\attachments" -Recurse -ErrorAction SilentlyContinue
    Push-Location $backend
    & $py -m app.seed --reset --basico | Out-Null
    $server = Start-Process -FilePath $py -ArgumentList "-m", "app.serve" -WorkingDirectory $backend -PassThru `
      -WindowStyle Hidden -RedirectStandardError "$tmp\server.log" -RedirectStandardOutput "$tmp\server.out"
    Pop-Location
    for ($i = 0; $i -lt 40; $i++) {
      try { Invoke-WebRequest "http://127.0.0.1:8001/login.html" -UseBasicParsing -TimeoutSec 1 | Out-Null; break }
      catch { Start-Sleep -Milliseconds 250 }
    }
  }
  Push-Location $tests
  & $py $t | Where-Object { $_ -notmatch "^(Datos de demostración|Usuarios:)" }
  if ($LASTEXITCODE -ne 0) { $fallos += $t }
  Pop-Location
  if ($server) { Stop-Process -Id $server.Id -Force; Start-Sleep -Milliseconds 300 }
}
if ($fallos) { Write-Output "=== FALLOS en: $($fallos -join ', ')"; exit 1 }
Write-Output "=== Todo OK ($($Pruebas.Count) archivos)"
