@echo off
REM Simulato — Start Main Control PC
REM Starts the FastAPI controller server for phone connections.
REM
REM Usage: start_controller.bat
REM
REM Optional env vars: PI_HOST, PI_PORT, CONTROLLER_PORT, GROK_API_KEY

cd /d "%~dp0\.."

echo === Simulato Controller ===
echo Project: %CD%
echo.

if defined GROK_API_KEY (
    echo [+] GROK_API_KEY is set
) else (
    echo [*] GROK_API_KEY not set - AI features will fail until set
)

if not defined CONTROLLER_PORT set CONTROLLER_PORT=8000
echo [+] Listening on 0.0.0.0:%CONTROLLER_PORT%
echo.

powershell -NoProfile -Command "$c=(Get-NetTCPConnection -LocalPort %CONTROLLER_PORT% -ErrorAction SilentlyContinue|Measure-Object).Count; exit [int]($c -gt 0)" > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Port %CONTROLLER_PORT% is already in use.
    echo     Run: scripts\stop_controller.bat
    echo     Then try again.
    exit /b 1
)

if exist ".venv\Scripts\activate.bat" (
    echo [+] Activating virtual environment
    call .venv\Scripts\activate.bat
) else (
    echo [*] No .venv found - using system Python
)

echo [+] Starting controller server...
python -m controller.main
