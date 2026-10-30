# Runs this project's Mosquitto broker in this window (Ctrl+C to stop).
# The Windows Mosquitto service on port 1883 belongs to another project and is not touched.
. "$PSScriptRoot\_common.ps1"
$confFile = Join-Path $ProjectRoot 'config\mosquitto\mosquitto.conf'
if (-not (Test-Path $confFile)) { throw 'Broker is not set up yet. Run scripts\setup_broker.ps1 first.' }
& (Join-Path $MosquittoDir 'mosquitto.exe') -c $confFile
