@echo off
REM -----------------------------------------------------------------------
REM Ghost Agent build script.
REM
REM Compiles agent.py into a single self-contained .exe via PyInstaller.
REM The output .exe is disguised with a Windows-sounding process name.
REM
REM Requirements:
REM   pip install pyinstaller dxcam opencv-python-headless numpy
REM
REM Usage:
REM   build.bat              (builds TiWorker.exe — default)
REM   build.bat CustomName   (builds CustomName.exe)
REM -----------------------------------------------------------------------

set EXE_NAME=%1
if "%EXE_NAME%"=="" set EXE_NAME=TiWorker

echo Building Ghost Agent as %EXE_NAME%.exe ...

pyinstaller ^
    --onefile ^
    --noconsole ^
    --name %EXE_NAME% ^
    --clean ^
    agent.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo BUILD FAILED. Check errors above.
    exit /b 1
)

echo.
echo Build successful: dist\%EXE_NAME%.exe
echo Copy this file to the exam laptop and run it.
