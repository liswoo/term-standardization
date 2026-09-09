# Windows equivalent of poc-stop.sh
$ErrorActionPreference='Continue'
$ROOT=$PSScriptRoot
$RUNTIME=Join-Path $ROOT '.runtime'

function Stop-Tracked {
    param([string]$Name,[string]$PidFile)
    if (Test-Path $PidFile) {
        $trackedId=Get-Content -LiteralPath $PidFile
        Stop-Process -Id $trackedId -ErrorAction SilentlyContinue
        Remove-Item -Force $PidFile
        Write-Output "  $Name 중지."
    } else {
        Write-Output "  $Name 실행 기록 없음 (건너뜀)."
    }
}

Write-Output '[1/4] Cloudflare Tunnel 중지...'
Stop-Tracked -Name '프론트엔드 Tunnel' -PidFile (Join-Path $RUNTIME 'tunnel.pid')
Stop-Tracked -Name 'Dify 스튜디오 Tunnel' -PidFile (Join-Path $RUNTIME 'tunnel-dify.pid')

Write-Output '[2/4] Caddy 중지...'
Stop-Tracked -Name 'Caddy' -PidFile (Join-Path $RUNTIME 'caddy.pid')

Write-Output '[3/4] MCP 서버 중지...'
Stop-Tracked -Name 'MCP server' -PidFile (Join-Path $ROOT 'term-standardization-mcp\.runtime\server.pid')

Write-Output '[4/4] 도커 컨테이너 정지 (데이터는 보존, docker compose stop)...'
Push-Location (Join-Path $ROOT 'term-standardization-mcp')
try { docker compose stop } finally { Pop-Location }
Push-Location (Join-Path $ROOT '..\dify\docker')
try { docker compose stop } finally { Pop-Location }

Write-Output ''
Write-Output '모두 정지됨. 데이터는 보존되어 poc-start.ps1로 다시 시작할 수 있습니다.'
