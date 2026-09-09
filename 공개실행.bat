@echo off
setlocal
rem Double-click to run: starts Dify + MCP server + frontend (Caddy), then opens
rem a temporary external URL via Cloudflare Tunnel (cloudflared) for demos.
rem This file can be copied/moved anywhere (Desktop, Start Menu, etc.) - it
rem always points back at the fixed project folder below.
set "ROOT=C:\Users\woolis\Desktop\STD"
cd /d "%ROOT%"
set "PATH=%ROOT%\tools;%PATH%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\poc-start.ps1" -Public
if errorlevel 1 (
    echo.
    echo Startup failed - see the output above.
    pause
    endlocal
    exit /b 1
)

echo.
echo Check the URLs above. When the demo is done, run stop.bat to shut everything down.
echo These are temporary tunnel URLs - they change every time you run this.
echo Press any key to close this window.
pause >nul
endlocal
