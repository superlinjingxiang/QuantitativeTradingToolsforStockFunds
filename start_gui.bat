@echo off
setlocal

cd /d "%~dp0"

if exist ".uv-bootstrap\Scripts\uv.exe" (
    set "UV_CMD=.uv-bootstrap\Scripts\uv.exe"
) else (
    set "UV_CMD=uv"
)

echo Starting China Quant Platform from source...
echo Project: %CD%
echo.

"%UV_CMD%" run python -m china_quant_platform --gui

if errorlevel 1 (
    echo.
    echo Startup failed. Press any key to close this window.
    pause >nul
)

endlocal
