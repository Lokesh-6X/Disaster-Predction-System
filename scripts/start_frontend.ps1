# Starts the dashboard dev server on http://localhost:5173 (API calls are forwarded to the backend).
. "$PSScriptRoot\_common.ps1"
$frontend = Join-Path $ProjectRoot 'frontend'
Set-Location $frontend
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host 'Installing frontend packages (first run)...'
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
}
npm run dev
