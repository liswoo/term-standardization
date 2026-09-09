@echo off
setlocal
rem Double-click to run: stops all running services (Dify, MCP server, Caddy). Data is preserved.
rem This file can be copied/moved anywhere (Desktop, Start Menu, etc.) - it
rem always points back at the fixed project folder below.
set "ROOT=C:\Users\woolis\Desktop\STD"
cd /d "%ROOT%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\poc-stop.ps1"

echo.
echo Stopped. Data is preserved - run start.bat to start again.
echo Press any key to close this window.
pause >nul
endlocal
