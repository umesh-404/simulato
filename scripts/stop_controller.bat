@echo off
REM Simulato — Stop Main Control PC
REM Kills the process using port 8000 (the controller server).
REM
REM Usage: stop_controller.bat

if not defined CONTROLLER_PORT set CONTROLLER_PORT=8000
set PORT=%CONTROLLER_PORT%
echo Stopping Simulato controller on port %PORT%...

powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort %PORT% -ErrorAction SilentlyContinue; if ($c) { $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; echo 'Stopped.' } else { echo 'No process found on port %PORT%.' }"

echo Done.
