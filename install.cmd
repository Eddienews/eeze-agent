@echo off
rem Eeze Agent — one-click launcher (installs/updates and opens the app).
rem Safe to run again: it re-syncs dependencies and reopens the browser.
setlocal
set "REPO=%~dp0"
where pwsh >nul 2>nul && (pwsh -NoProfile -ExecutionPolicy Bypass -File "%REPO%scripts\install.ps1" %*) || (powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%scripts\install.ps1" %*)
if errorlevel 1 (
  echo.
  echo Setup failed — see the messages above.
  pause
  exit /b 1
)
