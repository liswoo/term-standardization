param([switch]$Restart)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8='1'
$listeners=@(Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue)
if ($listeners -and !$Restart) { Write-Output 'MCP port 8100 is already listening.'; exit 0 }
foreach ($listener in $listeners) {
    $process=Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if (!$process.CommandLine -or !$process.CommandLine.Contains((Join-Path $PSScriptRoot 'server.py'))) { throw 'Unexpected process on port 8100.' }
}
docker compose up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Database did not start.' }
& "$PSScriptRoot\.venv\Scripts\python.exe" manage.py init-db
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
# Idempotent reseed: the terms_data Docker volume is local to this machine and
# never travels with git, so switching machines (or a fresh clone) starts with
# an empty database unless this also reseeds it every time, not just once.
& "$PSScriptRoot\.venv\Scripts\python.exe" manage.py import-catalog data/scenario_catalog.json
if ($LASTEXITCODE -ne 0) { throw 'Catalog import failed.' }
& "$PSScriptRoot\.venv\Scripts\python.exe" manage.py import-guideline data/standard_guide.md
if ($LASTEXITCODE -ne 0) { throw 'Guideline import failed.' }
foreach ($listener in $listeners) { Stop-Process -Id $listener.OwningProcess }
New-Item -ItemType Directory -Force -Path "$PSScriptRoot\.runtime" | Out-Null
$process=Start-Process -FilePath "$PSScriptRoot\.venv\Scripts\python.exe" -ArgumentList ('"'+(Join-Path $PSScriptRoot 'server.py')+'"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot\.runtime\server.log" -RedirectStandardError "$PSScriptRoot\.runtime\server-error.log" -PassThru
$process.Id | Set-Content -LiteralPath "$PSScriptRoot\.runtime\server.pid"
Start-Sleep -Seconds 3
if (!(Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue)) { throw 'MCP did not start; inspect .runtime/server-error.log.' }
Write-Output 'MCP ready: http://host.docker.internal:8100/mcp'
