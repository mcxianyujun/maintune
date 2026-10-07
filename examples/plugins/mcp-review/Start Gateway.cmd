@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 or newer is required.
  pause
  exit /b 1
)
if not exist ".private\gateway.json" (
  python setup_gateway.py
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
python gateway.py
pause
