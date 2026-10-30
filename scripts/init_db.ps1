# Creates the database user and database named in .env (safe to run again).
# psql asks for the PostgreSQL superuser password — it is never stored.
param([string]$SuperUser = 'postgres')

. "$PSScriptRoot\_common.ps1"
$e = Read-DotEnv

$psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
if (-not $psql) { $psql = 'C:\Program Files\PostgreSQL\17\bin\psql.exe' }
if (-not (Test-Path $psql)) { throw "psql not found. Add PostgreSQL's bin folder to PATH." }

$user = $e['DB_USER']
$db = $e['DB_NAME']
$password = $e['DB_PASSWORD'].Replace("'", "''")

# \gexec runs each generated statement; the WHERE NOT EXISTS parts make this re-runnable.
$sql = @"
SELECT format('CREATE ROLE %I LOGIN', '$user') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$user')\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', '$user', '$password')\gexec
SELECT format('CREATE DATABASE %I OWNER %I', '$db', '$user') WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$db')\gexec
"@

$sqlFile = Join-Path ([IO.Path]::GetTempPath()) 'weather_init_db.sql'
Set-Content -Path $sqlFile -Value $sql -Encoding ascii
try {
    Write-Host "Connecting to PostgreSQL at $($e['DB_HOST']):$($e['DB_PORT']) as '$SuperUser'..."
    & $psql -h $e['DB_HOST'] -p $e['DB_PORT'] -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -q -f $sqlFile
    if ($LASTEXITCODE -ne 0) { throw "psql failed (exit code $LASTEXITCODE)" }
} finally {
    Remove-Item $sqlFile -ErrorAction SilentlyContinue
}

Write-Host "Database '$db' and user '$user' are ready."
# Phase 2 adds: apply schema migrations (alembic upgrade head)
