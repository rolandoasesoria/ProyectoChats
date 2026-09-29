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

# Sin servidor: lógica pura, con respuestas de Claude simuladas.
$unitarias = @("check_js.py", "test_importers.py", "test_insights.py", "test_agent_tools.py")
# Con servidor de pruebas.
$api = @("test_auth_api.py", "test_profile_api.py", "test_inbox_api.py", "test_import_api.py", "test_notes_api.py",
         "test_clients_api.py", "test_privacy_api.py", "test_dashboard_api.py", "test_documents_api.py",
         "test_search_api.py", "test_drafts.py", "test_integrations.py")
$ui = @("test_ui.py")

if (-not $Pruebas) { $Pruebas = $unitarias + $api + $(if ($Todas) { $ui } else { @() }) }

$fallos = @()
foreach ($t in $Pruebas) {
  Write-Output "=== $t"
  $server = $null
  if ($unitarias -notcontains $t) {
    Remove-Item "$tmp\test.db*", "$tmp\attachments" -Recurse -ErrorAction SilentlyContinue
    $env:DB_PATH = "$tmp\test.db"
    Push-Location $backend
    & $py -m app.seed | Out-Null
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
