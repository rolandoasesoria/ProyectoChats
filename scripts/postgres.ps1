# PostgreSQL portable para desarrollo (sin permisos de administrador ni servicio de Windows).
#
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 instalar   # una vez: descarga, crea BD, usuarios y TLS
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 asegurar   # instalaciones anteriores: activa TLS y
#                                                                            # separa usuarios (cambia las contraseñas)
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 iniciar    # tras reiniciar el equipo
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 parar
#   powershell -ExecutionPolicy Bypass -File scripts/postgres.ps1 estado
#
# Se instala en %USERPROFILE%\PostgreSQL (binarios, datos, certificados y registro). Desinstalar = parar y borrar
# esa carpeta. Las conexiones de la app se escriben en backend/.env:
#   DATABASE_URL        usuario proyectochats_app: solo lee y escribe datos (con el que trabaja la app)
#   DATABASE_ADMIN_URL  usuario proyectochats: dueño de las tablas, solo para migrar
#   DB_SSLMODE / DB_SSLROOTCERT  conexión cifrada (TLS 1.3) verificando el certificado del servidor
# En producción, usa un PostgreSQL gestionado o instalado como servicio y pon allí estos mismos valores
# (backend/database/roles.sql crea los usuarios).
param(
  [Parameter(Position = 0)][ValidateSet("instalar", "asegurar", "iniciar", "parar", "estado")][string]$Accion = "estado",
  [string]$Zip = "",
  [int]$Puerto = 5432
)
$ErrorActionPreference = "Stop"
$Version = "18.6-1"
$Base = Join-Path $env:USERPROFILE "PostgreSQL"
$Bin = Join-Path $Base "pgsql\bin"
$Datos = Join-Path $Base "data"
$Certs = Join-Path $Base "certs"
$Log = Join-Path $Base "postgres.log"
$SuperPwdFile = Join-Path $Base "superuser.pwd"
$Repo = Split-Path $PSScriptRoot -Parent
$EnvFile = Join-Path $Repo "backend\.env"
$Python = Join-Path $Repo "backend\.venv\Scripts\python.exe"
$Owner = "proyectochats"
$AppRole = "proyectochats_app"
$Bases = @("proyectochats", "proyectochats_test")

function Pg([string]$exe) { Join-Path $Bin "$exe.exe" }
function Activo { & (Pg "pg_ctl") status -D $Datos *> $null; return $LASTEXITCODE -eq 0 }

# Contraseña aleatoria de 32 caracteres con un generador criptográfico.
function Aleatoria {
  $abc = [char[]]((48..57) + (65..90) + (97..122))
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  -join ($bytes | ForEach-Object { $abc[$_ % $abc.Length] })
}

# Archivo legible solo por el usuario actual (por SID: su nombre puede coincidir con el del equipo).
function Privado([string]$ruta) {
  $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  & icacls $ruta /reset | Out-Null
  & icacls $ruta /inheritance:r /grant:r "*$($sid):(R,W)" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "No se han podido proteger los permisos de $ruta" }
}

# pg_ctl start/stop se lanza como proceso aparte: si se redirige su salida, el servidor la hereda
# y PowerShell se queda esperando indefinidamente.
function PgCtl([string[]]$argumentos) {
  $p = Start-Process -FilePath (Pg "pg_ctl") -ArgumentList $argumentos -WindowStyle Hidden -PassThru
  $p.WaitForExit()
  if ($p.ExitCode -ne 0) { throw "pg_ctl $($argumentos[0]) ha fallado (revisa $Log)" }
}
function Arrancar { PgCtl @("start", "-D", "`"$Datos`"", "-l", "`"$Log`"", "-w") }
function Parar { PgCtl @("stop", "-D", "`"$Datos`"", "-m", "fast", "-w") }

# Ejecuta SQL como superusuario (el texto va por la entrada estándar: las contraseñas no aparecen en la línea de
# órdenes de ningún proceso).
function PsqlSuper([string]$bd, [string]$sql) {
  $env:PGPASSWORD = (Get-Content $SuperPwdFile -Raw).Trim()
  try {
    $sql | & (Pg "psql") -q -h localhost -p $Puerto -U postgres -d $bd -v ON_ERROR_STOP=1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "psql ha fallado en la base de datos $bd" }
  } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
}

function Poner-Variable([string]$nombre, [string]$valor) {
  $lineas = @()
  if (Test-Path $EnvFile) { $lineas = @(Get-Content $EnvFile -Encoding UTF8 | Where-Object { $_ -notmatch "^$nombre=" }) }
  $lineas += "$nombre=$valor"
  [IO.File]::WriteAllLines($EnvFile, $lineas, (New-Object Text.UTF8Encoding $false))
}

# TLS obligatorio, usuarios separados y contraseñas nuevas. Se puede repetir sin problema.
function Asegurar {
  if (-not (Test-Path $Python)) { throw "Falta el entorno de Python de la app ($Python)." }
  Write-Output "Creando certificados TLS..."
  $ca = & $Python (Join-Path $PSScriptRoot "certificados_bd.py") $Certs $Datos
  if ($LASTEXITCODE -ne 0) { throw "No se han podido crear los certificados." }
  Privado (Join-Path $Certs "ca.key")
  Privado (Join-Path $Datos "server.key")

  # Ajustes de seguridad en un archivo propio, incluido una sola vez desde postgresql.conf.
  $conf = Join-Path $Datos "postgresql.conf"
  if (-not (Select-String -Path $conf -SimpleMatch "include_if_exists = 'seguridad.conf'" -Quiet)) {
    Add-Content $conf "`ninclude_if_exists = 'seguridad.conf'`n"
  }
  [IO.File]::WriteAllLines((Join-Path $Datos "seguridad.conf"), @(
    "# Generado por scripts/postgres.ps1 asegurar",
    "listen_addresses = 'localhost'",
    "ssl = on",
    "ssl_cert_file = 'server.crt'",
    "ssl_key_file = 'server.key'",
    "ssl_min_protocol_version = 'TLSv1.3'",
    "password_encryption = 'scram-sha-256'"
  ), (New-Object Text.UTF8Encoding $false))
  # Solo conexiones cifradas y con contraseña (SCRAM), y solo desde este equipo.
  $hba = Join-Path $Datos "pg_hba.conf"
  if (-not (Test-Path "$hba.original")) { Copy-Item $hba "$hba.original" }
  [IO.File]::WriteAllLines($hba, @(
    "# Generado por scripts/postgres.ps1 asegurar (el original está en pg_hba.conf.original)",
    "# TYPE     DATABASE  USER  ADDRESS       METHOD",
    "hostssl    all       all   127.0.0.1/32  scram-sha-256",
    "hostssl    all       all   ::1/128       scram-sha-256",
    "host       all       all   0.0.0.0/0     reject",
    "host       all       all   ::/0          reject"
  ), (New-Object Text.UTF8Encoding $false))
  Write-Output "Reiniciando PostgreSQL con TLS..."
  if (Activo) { Parar }
  Arrancar

  Write-Output "Separando usuarios y cambiando contraseñas..."
  $ownerPwd = Aleatoria
  $appPwd = Aleatoria
  $env:PGSSLMODE = "verify-full"
  $env:PGSSLROOTCERT = $ca
  try {
    PsqlSuper "postgres" "ALTER ROLE $Owner WITH LOGIN PASSWORD '$ownerPwd' NOSUPERUSER NOCREATEROLE;"
    $roles = Get-Content (Join-Path $Repo "backend\database\roles.sql") -Raw -Encoding UTF8
    foreach ($bd in $Bases) {
      PsqlSuper $bd ("\set owner $Owner`n\set app $AppRole`n\set app_password '$appPwd'`n" + $roles)
    }
  } finally {
    Remove-Item Env:PGSSLMODE, Env:PGSSLROOTCERT -ErrorAction SilentlyContinue
  }

  Poner-Variable "DATABASE_URL" "postgresql://${AppRole}:$appPwd@localhost:$Puerto/proyectochats"
  Poner-Variable "DATABASE_ADMIN_URL" "postgresql://${Owner}:$ownerPwd@localhost:$Puerto/proyectochats"
  Poner-Variable "TEST_DATABASE_URL" "postgresql://${AppRole}:$appPwd@localhost:$Puerto/proyectochats_test"
  Poner-Variable "TEST_DATABASE_ADMIN_URL" "postgresql://${Owner}:$ownerPwd@localhost:$Puerto/proyectochats_test"
  Poner-Variable "DB_SSLMODE" "verify-full"
  Poner-Variable "DB_SSLROOTCERT" $ca
  Privado $EnvFile
  Write-Output "Listo: conexión cifrada (TLS 1.3, certificado verificado) y la app sin permisos para cambiar tablas."
  Write-Output "Reinicia la app para que use las contraseñas nuevas."
}

switch ($Accion) {
  "instalar" {
    if (Test-Path $Datos) { Write-Output "Ya está instalado en $Base. Usa 'iniciar' (o 'asegurar')."; break }
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
    # La contraseña del superusuario queda en la carpeta de PostgreSQL, legible solo por este usuario.
    [IO.File]::WriteAllText($SuperPwdFile, (Aleatoria))
    Privado $SuperPwdFile
    Write-Output "Creando la base de datos..."
    # Proveedor de configuración regional "builtin" (C.UTF-8): mayúsculas/minúsculas Unicode sin depender de Windows.
    & (Pg "initdb") -D $Datos -U postgres --pwfile=$SuperPwdFile --auth=scram-sha-256 -E UTF8 `
      --locale-provider=builtin --builtin-locale=C.UTF-8 --locale=C | Out-Null
    Add-Content (Join-Path $Datos "postgresql.conf") "`nlisten_addresses = 'localhost'`nport = $Puerto`n"
    Arrancar
    PsqlSuper "postgres" "CREATE ROLE $Owner LOGIN; CREATE DATABASE proyectochats OWNER $Owner; CREATE DATABASE proyectochats_test OWNER $Owner;"
    foreach ($bd in $Bases) { PsqlSuper $bd "CREATE EXTENSION IF NOT EXISTS unaccent;" }
    Asegurar
  }
  "asegurar" {
    if (-not (Test-Path $Datos)) { Write-Output "No instalado. Ejecuta: scripts/postgres.ps1 instalar"; break }
    Asegurar
  }
  "iniciar" {
    if (Activo) { Write-Output "PostgreSQL ya está en marcha."; break }
    Arrancar
    Write-Output "PostgreSQL en marcha (registro: $Log)."
  }
  "parar" {
    if (-not (Activo)) { Write-Output "PostgreSQL no está en marcha."; break }
    Parar
    Write-Output "PostgreSQL parado."
  }
  "estado" {
    if (-not (Test-Path $Datos)) { Write-Output "No instalado. Ejecuta: scripts/postgres.ps1 instalar" }
    elseif (Activo) { Write-Output "En marcha ($Base)." }
    else { Write-Output "Instalado pero parado. Ejecuta: scripts/postgres.ps1 iniciar" }
  }
}
