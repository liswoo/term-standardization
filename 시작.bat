@echo off
setlocal
rem Double-click to run: starts Dify + MCP server + frontend (Caddy) locally.
rem This file can be copied/moved anywhere (Desktop, Start Menu, etc.) - it
rem always points back at the fixed project folder below.
set "ROOT=C:\Users\woolis\Desktop\STD"
cd /d "%ROOT%"
set "PATH=%ROOT%\tools;%PATH%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\poc-start.ps1"
if errorlevel 1 (
    echo.
    echo Startup failed - see the output above.
    pause
    endlocal
    exit /b 1
)

echo.
echo Local URL: http://localhost:8090
echo Closing this window will NOT stop the server. Run stop.bat to stop it.
echo Press any key to close this window.
pause >nul
endlocal
