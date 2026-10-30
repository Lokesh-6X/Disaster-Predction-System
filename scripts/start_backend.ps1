# Starts the FastAPI backend on BACKEND_HOST:BACKEND_PORT (default http://127.0.0.1:8000).
. "$PSScriptRoot\_common.ps1"
Assert-Venv
Set-Location $ProjectRoot
& $VenvPython (Join-Path $ProjectRoot 'backend\run.py')
