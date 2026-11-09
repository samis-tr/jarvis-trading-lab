@echo off
rem Double-click: run today's forward step now (safe to repeat; virtual money only).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\forward-step.ps1"
echo.
pause
