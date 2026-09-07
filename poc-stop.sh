#!/usr/bin/env bash
# macOS/Linux equivalent of poc-stop.ps1
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="$ROOT/.runtime"

stop_tracked() {
  local name="$1" pidfile="$2"
  if [[ -f "$pidfile" ]]; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
    echo "  ${name} 중지."
  else
    echo "  ${name} 실행 기록 없음 (건너뜀)."
  fi
}

echo "[1/4] Cloudflare Tunnel 중지..."
stop_tracked "프론트엔드 Tunnel" "$RUNTIME/tunnel.pid"
stop_tracked "Dify 스튜디오 Tunnel" "$RUNTIME/tunnel-dify.pid"

echo "[2/4] Caddy 중지..."
stop_tracked "Caddy" "$RUNTIME/caddy.pid"

echo "[3/4] MCP 서버 중지..."
stop_tracked "MCP server" "$ROOT/term-standardization-mcp/.runtime/server.pid"

echo "[4/4] 도커 컨테이너 정지 (데이터는 보존, docker compose stop)..."
(cd "$ROOT/term-standardization-mcp" && docker compose stop)
(cd "$ROOT/../dify/docker" && docker compose stop)

echo ""
echo "모두 정지됨. 데이터는 보존되어 poc-start.sh로 다시 시작할 수 있습니다."
