param([switch]$Public)
# Windows equivalent of poc-start.sh
# Layout expected: this repo and Dify's own repo are sibling folders, e.g.
#   projects\term-standardization\   <- this repo (ROOT)
#   projects\dify\                   <- official Dify repo, cloned separately
$ErrorActionPreference='Stop'
$ROOT=$PSScriptRoot
$TOOLS=Join-Path $ROOT 'tools'
$RUNTIME=Join-Path $ROOT '.runtime'
New-Item -ItemType Directory -Force -Path $RUNTIME | Out-Null

function Start-QuickTunnel {
    param([string]$Label,[string]$Target,[string]$LogFile,[string]$PidFile)
    Remove-Item -Force -ErrorAction SilentlyContinue $LogFile
    $process=Start-Process -FilePath 'cloudflared' -ArgumentList @('tunnel','--url',$Target) `
        -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $LogFile -PassThru
    $process.Id | Set-Content -LiteralPath $PidFile
    for ($i=0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $LogFile) {
            $match=Select-String -Path $LogFile -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($match) { return $match.Matches[0].Value }
        }
    }
    throw "$Label 터널 URL을 못 찾았습니다; $LogFile 확인하세요."
}

Write-Output '[1/4] Dify (docker)...'
Push-Location (Join-Path $ROOT '..\dify\docker')
try { docker compose up -d } finally { Pop-Location }

Write-Output '[2/4] 용어표준화 DB + MCP 서버...'
& (Join-Path $ROOT 'term-standardization-mcp\start.ps1')

Write-Output '[3/4] Caddy (프론트엔드 + Dify API 프록시, :8090)...'
if (!(Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)) {
    $env:UI_DIR=Join-Path $ROOT 'term-standardization-ui'
    $process=Start-Process -FilePath 'caddy' -ArgumentList @('run','--config',(Join-Path $TOOLS 'Caddyfile')) `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RUNTIME 'caddy.log') -RedirectStandardError (Join-Path $RUNTIME 'caddy-error.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $RUNTIME 'caddy.pid')
    Start-Sleep -Seconds 2
    if (!(Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)) {
        throw 'Caddy did not start; inspect .runtime/caddy-error.log.'
    }
} else {
    Write-Output '  이미 실행 중 (포트 8090).'
}
Write-Output '  로컬 접속: http://localhost:8090'

$DifyStudioUrl='http://localhost/'
if ($Public) {
    Write-Output '[4/4] Cloudflare Tunnel (외부 공개 URL 발급 중)...'
    $AppUrl=Start-QuickTunnel -Label '프론트엔드' -Target 'http://localhost:8090' -LogFile (Join-Path $RUNTIME 'tunnel.log') -PidFile (Join-Path $RUNTIME 'tunnel.pid')
    $DifyStudioUrl=Start-QuickTunnel -Label 'Dify 스튜디오' -Target 'http://localhost:80' -LogFile (Join-Path $RUNTIME 'tunnel-dify.log') -PidFile (Join-Path $RUNTIME 'tunnel-dify.pid')
    Write-Output ''
    Write-Output "  사용자용(시연) URL : $AppUrl"
    Write-Output "  Dify 관리자 URL    : $DifyStudioUrl  (Dify 계정 로그인 필요)"
    Write-Output '  두 URL 모두 데모가 끝나면 poc-stop.ps1로 즉시 끄세요 (임시 URL, 재시작 시 바뀝니다).'
} else {
    Write-Output '[4/4] 외부 공개 생략 (poc-start.ps1 -Public 으로 재실행하면 발급됩니다)'
}

@"
// poc-start.ps1이 실행할 때마다 자동 생성/갱신됩니다. 직접 수정하지 마세요.
window.RUNTIME_CONFIG = { difyStudioUrl: "$DifyStudioUrl" };
"@ | Set-Content -LiteralPath (Join-Path $ROOT 'term-standardization-ui\runtime-config.js') -Encoding utf8

Write-Output ''
Write-Output '모두 준비됨.'
