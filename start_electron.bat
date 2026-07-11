@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe
  echo Please run: uv sync --all-extras --dev
  pause
  exit /b 1
)

if not exist "node_modules\electron" goto install_node_dependencies
if not exist "node_modules\.bin\vite.cmd" goto install_node_dependencies
goto node_dependencies_ready

:install_node_dependencies
  echo [INFO] Installing Electron dependencies...
  npm.cmd install
  if errorlevel 1 (
    echo [ERROR] npm install failed.
    pause
    exit /b 1
  )

:node_dependencies_ready

if not exist "frontend\dist\index.html" (
  echo [INFO] Building Vue frontend...
  npm.cmd run build
  if errorlevel 1 (
    echo [ERROR] Vue frontend build failed.
    pause
    exit /b 1
  )
)

set CHINA_QUANT_PYTHON=%CD%\.venv\Scripts\python.exe
npm.cmd run start
if errorlevel 1 pause
