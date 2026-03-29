@echo off
setlocal
cd /d "%~dp0"

echo =========================================
echo       Starting Simulato Controller
echo =========================================

:: -----------------------------------------------
:: Step 1: Start Python backend
:: -----------------------------------------------
echo.
echo [1/1] Starting Python backend...

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [*] No .venv found - using system Python
)

echo [*] Checking OCR Python package (pytesseract)...
python -c "import pytesseract" >nul 2>&1
if errorlevel 1 (
    echo     -> pytesseract not found. Installing into current Python environment...
    python -m pip install pytesseract
    if errorlevel 1 (
        echo [WARNING] Failed to install pytesseract automatically.
        echo          OCR text extraction may be limited. Install manually:
        echo          python -m pip install pytesseract
    ) else (
        echo     -> pytesseract installed.
    )
) else (
    echo     -> pytesseract already installed.
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

echo.
echo =========================================
echo       Shutting down Simulato
echo =========================================
pause
