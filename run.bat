@echo off
setlocal

cd /d "%~dp0"
set "VENV_DIR=%~dp0.venv"

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

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYTHON_LAUNCHER% -m venv "%VENV_DIR%"
)

if not exist "requirements.lock" (
  echo Error: requirements.lock not found in %CD%
  exit /b 1
)

echo Installing dependencies from requirements.lock...
"%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.lock
if errorlevel 1 exit /b 1

echo Starting app...
"%VENV_DIR%\Scripts\python.exe" main.py %*
