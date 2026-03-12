@echo off
setlocal
cd /d "%~dp0"

echo =========================================
echo       Starting Simulato Controller
echo =========================================

:: -----------------------------------------------
:: Step 1: Check if Ollama is installed
:: -----------------------------------------------
where ollama >nul 2>&1
if errorlevel 1 (
    echo [!] Ollama is NOT installed.
    echo     Download from: https://ollama.com/download
    echo     Install it, then re-run this script.
    pause
    exit /b 1
)

:: -----------------------------------------------
:: Step 2: Start Ollama server
:: -----------------------------------------------
echo.
echo [1/3] Starting local AI server (Ollama)...
start /B ollama serve > nul 2>&1

:: Wait max 10 seconds for Ollama to start
set "OLLAMA_STARTED="
for /l %%x in (1, 1, 10) do (
    curl -s http://localhost:11434/api/tags > nul 2>&1
    if not errorlevel 1 (
        set OLLAMA_STARTED=1
        goto :ollama_ready
    )
    timeout /t 1 /nobreak > nul
)

if not defined OLLAMA_STARTED (
    echo [WARNING] Ollama failed to respond within 10 seconds.
    echo          Local AI features will be unavailable.
    echo          Cloud AI (Grok/Gemini) will still work.
    goto :check_model_skip
)

:ollama_ready
echo     -> Ollama server started successfully!

:: -----------------------------------------------
:: Step 3: Auto-pull model if not present
:: -----------------------------------------------
echo.
echo [2/3] Checking local AI model...

:: Read model name from .env if present, otherwise use default
set "MODEL=qwen2.5-vl:7b"
if exist ".env" (
    for /f "tokens=1,2 delims==" %%a in ('findstr /i "OLLAMA_MODEL" .env') do (
        set "MODEL=%%b"
    )
)

:: Check if model is already pulled
ollama list 2>nul | findstr /i "%MODEL%" > nul 2>&1
if errorlevel 1 (
    echo     Model "%MODEL%" not found locally. Pulling now...
    echo     (This may take several minutes on first run)
    echo.
    ollama pull %MODEL%
    if errorlevel 1 (
        echo [WARNING] Failed to pull model "%MODEL%".
        echo          Local AI features will be unavailable.
    ) else (
        echo     -> Model "%MODEL%" ready!
    )
) else (
    echo     -> Model "%MODEL%" already available.
)

:check_model_skip

:: -----------------------------------------------
:: Step 4: Start Python backend
:: -----------------------------------------------
echo.
echo [3/3] Starting Python backend...

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [*] No .venv found - using system Python
)

:: Verify .env has API keys
if exist ".env" (
    findstr /i "GROK_API_KEY" .env > nul 2>&1
    if errorlevel 1 (
        findstr /i "GEMINI_API_KEY" .env > nul 2>&1
        if errorlevel 1 (
            echo [WARNING] No GROK_API_KEY or GEMINI_API_KEY found in .env
            echo          Primary AI solver will not work!
        )
    )
)

echo.
echo =========================================
echo   Simulato Controller is starting...
echo   API: http://localhost:8000
echo   Phones: connect to this IP on port 8000
echo =========================================
echo.

python -m controller.main

:: -----------------------------------------------
:: Teardown: When Python exits, stop Ollama
:: -----------------------------------------------
echo.
echo =========================================
echo       Shutting down Simulato
echo =========================================
echo Stopping local AI (Ollama)...
taskkill /F /IM ollama.exe > nul 2>&1
taskkill /F /IM "ollama app.exe" > nul 2>&1
echo Done.
pause
