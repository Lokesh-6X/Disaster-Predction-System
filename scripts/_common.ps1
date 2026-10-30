# Shared helpers for the scripts in this folder. Dot-source it:  . "$PSScriptRoot\_common.ps1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$MosquittoDir = 'C:\Program Files\mosquitto'

function Read-DotEnv {
    param([string]$Path = (Join-Path $ProjectRoot '.env'))
    if (-not (Test-Path $Path)) {
        throw ".env not found at $Path. Copy .env.example to .env and fill it in."
    }
    $vars = @{}
    foreach ($line in Get-Content $Path) {
        $text = $line.Trim()
        if ($text -eq '' -or $text.StartsWith('#')) { continue }
        $eq = $text.IndexOf('=')
        if ($eq -lt 1) { continue }
        $vars[$text.Substring(0, $eq).Trim()] = $text.Substring($eq + 1).Trim()
    }
    return $vars
}

function Assert-Venv {
    if (-not (Test-Path $VenvPython)) {
        throw "Python environment not found. Run:  py -3.13 -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements-dev.txt"
    }
}
