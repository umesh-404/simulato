@echo off
REM Build, install, and launch Simulato on connected USB device
cd /d "%~dp0"

set ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
if not exist "%ADB%" set ADB=adb

echo Checking connected devices...
"%ADB%" devices
echo.

echo Building and installing...
call gradlew.bat installDebug
if %ERRORLEVEL% neq 0 (
    echo Build/install failed.
    exit /b 1
)

echo Launching app...
"%ADB%" shell am start -n com.simulato.app/.HomeActivity

echo Done.
