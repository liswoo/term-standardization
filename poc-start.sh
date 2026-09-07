#!/usr/bin/env bash
# macOS/Linux equivalent of poc-start.ps1
# Layout expected: this repo and Dify's own repo are sibling folders, e.g.
#   ~/projects/term-standardization/   <- this repo (ROOT)
#   ~/projects/dify/                   <- official Dify repo, cloned separately
set -euo pipefail
PUBLIC=false
if [[ "${1:-}" == "--public" ]]; then PUBLIC=true; fi
ROOT="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$ROOT/tools"
RUNTIME="$ROOT/.runtime"
mkdir -p "$RUNTIME"

start_quick_tunnel() {
  local label="$1" target="$2" logfile="$3" pidfile="$4"
  rm -f "$logfile"
  cloudflared tunnel --url "$target" >"$logfile" 2>&1 &
  echo $! >"$pidfile"
  for _ in $(seq 1 30); do
    sleep 1
    if [[ -f "$logfile" ]]; then
      local url
      url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$logfile" | head -1 || true)
      if [[ -n "$url" ]]; then echo "$url"; return 0; fi
    fi
  done
  echo "${label} 터널 URL을 못 찾았습니다; ${logfile} 확인하세요." >&2
  return 1
}

echo "[1/4] Dify (docker)..."
(cd "$ROOT/../dify/docker" && docker compose up -d)

echo "[2/4] 용어표준화 DB + MCP 서버..."
"$ROOT/term-standardization-mcp/start.sh"

echo "[3/4] Caddy (프론트엔드 + Dify API 프록시, :8090)..."
if ! lsof -tiTCP:8090 -sTCP:LISTEN >/dev/null 2>&1; then
  export UI_DIR="$ROOT/term-standardization-ui"
  nohup caddy run --config "$TOOLS/Caddyfile" >"$RUNTIME/caddy.log" 2>"$RUNTIME/caddy-error.log" &
  echo $! >"$RUNTIME/caddy.pid"
  sleep 2
  if ! lsof -tiTCP:8090 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Caddy did not start; inspect .runtime/caddy-error.log." >&2
    exit 1
  fi
else
  echo "  이미 실행 중 (포트 8090)."
fi
echo "  로컬 접속: http://localhost:8090"

DIFY_STUDIO_URL="http://localhost/"
if $PUBLIC; then
  echo "[4/4] Cloudflare Tunnel (외부 공개 URL 발급 중)..."
  APP_URL=$(start_quick_tunnel "프론트엔드" "http://localhost:8090" "$RUNTIME/tunnel.log" "$RUNTIME/tunnel.pid")
  DIFY_STUDIO_URL=$(start_quick_tunnel "Dify 스튜디오" "http://localhost:80" "$RUNTIME/tunnel-dify.log" "$RUNTIME/tunnel-dify.pid")
  echo ""
  echo "  사용자용(시연) URL : $APP_URL"
  echo "  Dify 관리자 URL    : $DIFY_STUDIO_URL  (Dify 계정 로그인 필요)"
  echo "  두 URL 모두 데모가 끝나면 poc-stop.sh로 즉시 끄세요 (임시 URL, 재시작 시 바뀝니다)."
else
  echo "[4/4] 외부 공개 생략 (poc-start.sh --public 으로 재실행하면 발급됩니다)"
fi

cat >"$ROOT/term-standardization-ui/runtime-config.js" <<EOF
// poc-start.sh가 실행할 때마다 자동 생성/갱신됩니다. 직접 수정하지 마세요.
window.RUNTIME_CONFIG = { difyStudioUrl: "$DIFY_STUDIO_URL" };
EOF

echo ""
echo "모두 준비됨."
