# Runs the kit simulator. Any arguments are passed through, e.g.:
#   .\scripts\start_simulator.ps1 --interval 10s
#   .\scripts\start_simulator.ps1 --backfill-hours 48 --speed 600
# See tools\kit_simulator.py --help for all options.
. "$PSScriptRoot\_common.ps1"
Assert-Venv
Set-Location $ProjectRoot
& $VenvPython (Join-Path $ProjectRoot 'tools\kit_simulator.py') @args
