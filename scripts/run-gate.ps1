# Runs the full safety test-suite + a deterministic local simulation and records var\gate.json.
# Paper trading (Phase 4, not built yet) will refuse to start unless this gate passed on the current code.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
& (Join-Path $root ".venv\Scripts\python.exe") -m jtl gate
exit $LASTEXITCODE
