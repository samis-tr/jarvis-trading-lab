# One-command setup for Jarvis Trading Lab (PAPER-ONLY, local).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Creates .venv inside the project (on D:), installs pinned free dependencies, runs lint + tests.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = "py"
try { & $py -3.12 --version | Out-Null } catch { Write-Error "Python 3.12 not found (py -3.12)."; exit 1 }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment in $root\.venv ..."
    & $py -3.12 -m venv .venv
}
$vpy = Join-Path $root ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt --quiet
& $vpy -m pip install -e . --no-deps --quiet

if (-not (Test-Path "config.yaml")) { Copy-Item "config.example.yaml" "config.yaml"; Write-Host "Created config.yaml from example." }
New-Item -ItemType Directory -Force "var" | Out-Null

Write-Host "Running ruff ..."
& $vpy -m ruff check src tests
if ($LASTEXITCODE -ne 0) { Write-Error "ruff failed"; exit 1 }
Write-Host "Running test-suite (offline, mocked providers, no API keys) ..."
& $vpy -m pytest -q -p no:warnings
if ($LASTEXITCODE -ne 0) { Write-Error "tests failed"; exit 1 }
Write-Host ""
Write-Host "Setup OK. Start a local simulation with:  powershell -ExecutionPolicy Bypass -File scripts\start-sim.ps1"
