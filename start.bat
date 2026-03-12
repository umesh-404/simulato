@echo off
setlocal
cd /d "%~dp0"

echo =========================================
echo       Starting Simulato Controller
echo =========================================

echo.
echo [1/2] Starting local AI (Ollama)...
start /B ollama serve > nul 2>&1

:: Wait max 5 seconds for Ollama to start
set "OLLAMA_STARTED="
for /l %%x in (1, 1, 5) do (
    curl -s http://localhost:11434/api/tags > nul
    if not errorlevel 1 (
        set OLLAMA_STARTED=1
        goto :ollama_ready
    )
    timeout /t 1 /nobreak > nul
)

if not defined OLLAMA_STARTED (
    echo [WARNING] Ollama failed to respond within 5 seconds. It may not be installed or is taking too long.
)
goto :start_python

:ollama_ready
echo     -^> Ollama model server started successfully!

:start_python
echo.
echo [2/2] Starting Python backend...
call .venv\Scripts\activate.bat
python -m controller.main

:: Teardown: When Python exits, kill Ollama
echo.
echo =========================================
echo       Shutting down Simulato
echo =========================================
echo Stopping local AI (Ollama)...
taskkill /F /IM ollama.exe > nul 2>&1
taskkill /F /IM ollama app.exe > nul 2>&1
echo Done.
pause
