# PostgreSQL portable para desarrollo (sin permisos de administrador ni servicio de Windows).
#
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 instalar   # una vez: descarga, crea BD y usuario
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 iniciar    # tras reiniciar el equipo
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 parar
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 estado
#
# Se instala en %USERPROFILE%\PostgreSQL (binarios, datos y registro). Desinstalar = parar y borrar esa carpeta.
# La conexión de la app (DATABASE_URL) se escribe en backend/.env. En producción, usa un PostgreSQL gestionado
# o instalado como servicio y pon allí su DATABASE_URL.
param(
  [Parameter(Position = 0)][ValidateSet("instalar", "iniciar", "parar", "estado")][string]$Accion = "estado",
  [string]$Zip = "",
  [int]$Puerto = 5432
)
$ErrorActionPreference = "Stop"
$Version = "18.6-1"
$Base = Join-Path $env:USERPROFILE "PostgreSQL"
$Bin = Join-Path $Base "pgsql\bin"
$Datos = Join-Path $Base "data"
$Log = Join-Path $Base "postgres.log"
$Repo = Split-Path $PSScriptRoot -Parent
$EnvFile = Join-Path $Repo "backend\.env"

function Pg([string]$exe) { Join-Path $Bin "$exe.exe" }
function Aleatoria { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }) }
function Activo { & (Pg "pg_ctl") status -D $Datos *> $null; return $LASTEXITCODE -eq 0 }

# pg_ctl start/stop se lanza como proceso aparte: si se redirige su salida, el servidor la hereda
# y PowerShell se queda esperando indefinidamente.
function PgCtl([string[]]$argumentos) {
  $p = Start-Process -FilePath (Pg "pg_ctl") -ArgumentList $argumentos -WindowStyle Hidden -PassThru
  $p.WaitForExit()
  if ($p.ExitCode -ne 0) { throw "pg_ctl $($argumentos[0]) ha fallado (revisa $Log)" }
}

function Poner-Variable([string]$nombre, [string]$valor) {
  $lineas = @()
  if (Test-Path $EnvFile) { $lineas = @(Get-Content $EnvFile -Encoding UTF8 | Where-Object { $_ -notmatch "^$nombre=" }) }
  $lineas += "$nombre=$valor"
  [IO.File]::WriteAllLines($EnvFile, $lineas, (New-Object Text.UTF8Encoding $false))
}

switch ($Accion) {
  "instalar" {
    if (Test-Path $Datos) { Write-Output "Ya está instalado en $Base. Usa 'iniciar'."; break }
    New-Item -ItemType Directory -Force $Base | Out-Null
    if (-not (Test-Path $Bin)) {
      if (-not $Zip) {
        $Zip = Join-Path $env:TEMP "postgresql-$Version-windows-x64-binaries.zip"
        if (-not (Test-Path $Zip)) {
          Write-Output "Descargando PostgreSQL $Version (unos 340 MB)..."
          Invoke-WebRequest "https://get.enterprisedb.com/postgresql/postgresql-$Version-windows-x64-binaries.zip" -OutFile $Zip -UseBasicParsing
        }
      }
      Write-Output "Descomprimiendo..."
      Expand-Archive -Path $Zip -DestinationPath $Base -Force
    }
    # Contraseñas aleatorias: la del superusuario queda en la carpeta de PostgreSQL; la de la app, en backend/.env.
    $superPwd = Aleatoria
    $appPwd = Aleatoria
    $pwfile = Join-Path $Base "superuser.pwd"
    [IO.File]::WriteAllText($pwfile, $superPwd)
    Write-Output "Creando la base de datos..."
    # Proveedor de configuración regional "builtin" (C.UTF-8): mayúsculas/minúsculas Unicode sin depender de Windows.
    & (Pg "initdb") -D $Datos -U postgres --pwfile=$pwfile --auth=scram-sha-256 -E UTF8 `
      --locale-provider=builtin --builtin-locale=C.UTF-8 --locale=C | Out-Null
    Add-Content (Join-Path $Datos "postgresql.conf") "`nlisten_addresses = 'localhost'`nport = $Puerto`n"
    PgCtl @("start", "-D", "`"$Datos`"", "-l", "`"$Log`"", "-w")
    $env:PGPASSWORD = $superPwd
    $sql = @"
CREATE ROLE proyectochats LOGIN PASSWORD '$appPwd';
CREATE DATABASE proyectochats OWNER proyectochats;
CREATE DATABASE proyectochats_test OWNER proyectochats;
"@
    $sql | & (Pg "psql") -q -h localhost -p $Puerto -U postgres -d postgres -v ON_ERROR_STOP=1 | Out-Null
    foreach ($db in "proyectochats", "proyectochats_test") {
      "CREATE EXTENSION IF NOT EXISTS unaccent;" | & (Pg "psql") -q -h localhost -p $Puerto -U postgres -d $db -v ON_ERROR_STOP=1 | Out-Null
    }
    Remove-Item Env:PGPASSWORD
    Poner-Variable "DATABASE_URL" "postgresql://proyectochats:$appPwd@localhost:$Puerto/proyectochats"
    Poner-Variable "TEST_DATABASE_URL" "postgresql://proyectochats:$appPwd@localhost:$Puerto/proyectochats_test"
    Write-Output "Listo: PostgreSQL en marcha en localhost:$Puerto. Conexión guardada en backend/.env."
  }
  "iniciar" {
    if (Activo) { Write-Output "PostgreSQL ya está en marcha."; break }
    PgCtl @("start", "-D", "`"$Datos`"", "-l", "`"$Log`"", "-w")
    Write-Output "PostgreSQL en marcha (registro: $Log)."
  }
  "parar" {
    if (-not (Activo)) { Write-Output "PostgreSQL no está en marcha."; break }
    PgCtl @("stop", "-D", "`"$Datos`"", "-m", "fast", "-w")
    Write-Output "PostgreSQL parado."
  }
  "estado" {
    if (-not (Test-Path $Datos)) { Write-Output "No instalado. Ejecuta: scripts/postgres.ps1 instalar" }
    elseif (Activo) { Write-Output "En marcha ($Base)." }
    else { Write-Output "Instalado pero parado. Ejecuta: scripts/postgres.ps1 iniciar" }
  }
}
