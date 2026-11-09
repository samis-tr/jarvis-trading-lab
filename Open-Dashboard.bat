@echo off
rem Double-click: open the read-only forward leaderboard (local only, http://127.0.0.1:8765).
cd /d "%~dp0"
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8765/api/compare | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  start "Jarvis Trading Lab dashboard" /min cmd /c ".venv\Scripts\python.exe -m jtl dashboard --forward"
  powershell -NoProfile -Command "Start-Sleep -Seconds 3"
)
start "" http://127.0.0.1:8765/
