@echo off
REM Build, install, and launch Simulato on connected USB device
setlocal EnableExtensions
cd /d "%~dp0"

set ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
if not exist "%ADB%" set ADB=adb

echo Checking connected devices...
"%ADB%" devices
echo.

echo Building and installing...
set "LOGFILE=%TEMP%\simulato_gradle_install.log"
del /q "%LOGFILE%" >NUL 2>&1

call gradlew.bat --no-daemon installDebug > "%LOGFILE%" 2>&1
if errorlevel 1 goto gradle_failed
goto gradle_ok

:gradle_failed
findstr /c:"NoClassDefFoundError: org/gradle/api/internal/classpath/ModuleRegistry" "%LOGFILE%" >NUL 2>&1
if not errorlevel 1 goto retry_after_cache_clear
goto build_failed

:retry_after_cache_clear
echo Detected Gradle wrapper cache corruption (ModuleRegistry missing). Clearing cache and retrying once...
rmdir /s /q "%USERPROFILE%\.gradle\wrapper\dists\gradle-8.5-bin" >NUL 2>&1
call gradlew.bat --no-daemon installDebug > "%LOGFILE%" 2>&1
if errorlevel 1 goto build_failed_after_cache_clear
goto gradle_ok

:build_failed_after_cache_clear
echo Build/install failed (after cache clear). Full log:
type "%LOGFILE%"
exit /b 1

:build_failed
echo Build/install failed. Full log:
type "%LOGFILE%"
exit /b 1

:gradle_ok

echo Launching app...
"%ADB%" shell am start -n com.simulato.app/.HomeActivity

echo Done.
