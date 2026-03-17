@echo off
setlocal
cd /d "%~dp0"

echo =========================================
echo       Starting Simulato Controller
echo =========================================

set "MODEL=qwen2.5vl:7b-q4_K_M"
set "OLLAMA_KEEP_ALIVE=30m"
set "LOCAL_AI_ENABLED=True"

if exist ".env" (
    for /f "tokens=1,* delims==" %%a in ('findstr /i "^OLLAMA_MODEL=" .env') do set "MODEL=%%b"
    for /f "tokens=1,* delims==" %%a in ('findstr /i "^OLLAMA_KEEP_ALIVE=" .env') do set "OLLAMA_KEEP_ALIVE=%%b"
    for /f "tokens=1,* delims==" %%a in ('findstr /i "^LOCAL_AI_ASSIST_ENABLED=" .env') do set "LOCAL_AI_ENABLED=%%b"
)

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
curl -s http://localhost:11434/api/tags > nul 2>&1
if errorlevel 1 (
    start /B ollama serve > nul 2>&1
) else (
    echo     -> Ollama already running.
)

:: Wait max 30 seconds for Ollama to start
set "OLLAMA_STARTED="
for /l %%x in (1, 1, 30) do (
    curl -s http://localhost:11434/api/tags > nul 2>&1
    if not errorlevel 1 (
        set OLLAMA_STARTED=1
        goto :ollama_ready
    )
    timeout /t 1 /nobreak > nul
)

if /i "%LOCAL_AI_ENABLED%"=="True" if not defined OLLAMA_STARTED (
    echo [WARNING] Ollama failed to respond within 30 seconds.
    echo          Local AI is required for your current flow.
    echo          Please start Ollama manually and retry.
    pause
    exit /b 1
)

if not defined OLLAMA_STARTED goto :check_model_skip

:ollama_ready
echo     -> Ollama server started successfully!

:: -----------------------------------------------
:: Step 3: Auto-pull model if not present
:: -----------------------------------------------
echo.
echo [2/3] Checking local AI model...

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
:: Step 2.5: Warm up local AI model
:: -----------------------------------------------
echo.
echo [2.5/3] Warming up local AI model...
if /i "%LOCAL_AI_ENABLED%"=="True" (
    set "WARMUP_OK="
    for /l %%x in (1, 1, 3) do (
        curl -s -X POST http://localhost:11434/api/chat ^
          -H "Content-Type: application/json" ^
          -d "{\"model\":\"%MODEL%\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"stream\":false,\"keep_alive\":\"%OLLAMA_KEEP_ALIVE%\"}" ^
          --max-time 90 > nul 2>&1
        if not errorlevel 1 (
            set "WARMUP_OK=1"
            goto :warmup_done
        )
        echo     -> Warmup attempt %%x failed; retrying...
        timeout /t 2 /nobreak > nul
    )

    :warmup_done
    if defined WARMUP_OK (
        echo     -> Local AI warmup complete.
    ) else (
        echo [ERROR] Local AI warmup failed after retries.
        echo         Local AI is required for this workflow.
        echo         Try: ollama run %MODEL%
        pause
        exit /b 1
    )
) else (
    echo     -> Local AI assist disabled by config.
)

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
