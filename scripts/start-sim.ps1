# One-command LOCAL_SIM start (offline; no broker, no credentials, no order network calls).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start-sim.ps1 [-Dashboard] [-Csv path] [-TrCsv path]
param(
    [switch]$Dashboard,
    [string]$Csv = "",
    [string]$TrCsv = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$vpy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Write-Error "Run scripts\setup.ps1 first."; exit 1 }
$env:PYTHONIOENCODING = "utf-8"

$name = "sim-" + (Get-Date -Format "yyyyMMdd-HHmmss")
$simArgs = @("-m", "jtl", "sim", "--name", $name)
if ($Csv) { $simArgs += @("--csv", $Csv) }
if ($TrCsv) { $simArgs += @("--tr-csv", $TrCsv) }
& $vpy @simArgs
if ($LASTEXITCODE -ne 0) { Write-Error "simulation stopped (see message above)"; exit $LASTEXITCODE }

if ($Dashboard) {
    & $vpy -m jtl dashboard --db (Join-Path $root "var\runs\$name.db")
}
