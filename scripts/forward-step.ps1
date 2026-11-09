# One daily step of the FORWARD paper simulation (virtual money only; no orders leave this PC).
# Safe to run any number of times: missed days are caught up, processed days are never repeated.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\forward-step.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$vpy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Write-Error "Run scripts\setup.ps1 first."; exit 1 }
$env:PYTHONIOENCODING = "utf-8"

# Alpaca PAPER data keys live in your Windows user environment (never in files). Load them into this
# process only; they are never printed.
foreach ($n in "APCA_API_KEY_ID", "APCA_API_SECRET_KEY") {
    if (-not [Environment]::GetEnvironmentVariable($n, "Process")) {
        $v = [Environment]::GetEnvironmentVariable($n, "User")
        if ($v) { [Environment]::SetEnvironmentVariable($n, $v, "Process") }
    }
}

$logDir = Join-Path $root "var\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("forward-" + (Get-Date -Format "yyyy-MM") + ".log")
"==== " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " ====" | Out-File -Append -Encoding utf8 $log
& $vpy -m jtl forward-step 2>&1 | Tee-Object -Variable out | Out-File -Append -Encoding utf8 $log
$out
exit $LASTEXITCODE
