@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_LAUNCHER="
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PYTHON_LAUNCHER=py -3"
if not defined PYTHON_LAUNCHER (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 set "PYTHON_LAUNCHER=python"
)

if not defined PYTHON_LAUNCHER (
  echo Error: Python was not found in PATH.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYTHON_LAUNCHER% -m venv .venv
)

if not exist "requirements.lock" (
  echo Error: requirements.lock not found in %CD%
  exit /b 1
)

echo Installing dependencies from requirements.lock...
".venv\Scripts\python.exe" -m pip install -r requirements.lock
if errorlevel 1 exit /b 1

echo Starting app...
".venv\Scripts\python.exe" main.py %*
