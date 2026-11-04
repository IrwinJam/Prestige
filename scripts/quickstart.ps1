# Sets up a fresh checkout, runs the tests and the offline demo. No keys and no spend.
#   powershell -ExecutionPolicy Bypass -File scripts\quickstart.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m venv .venv
$py = Join-Path ".venv" "Scripts\python.exe"

& $py -m pip install -q --upgrade pip
& $py -m pip install -q -e ".[dev,security]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m prestige buddy demo
