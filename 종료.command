#!/usr/bin/env bash
# 더블클릭으로 실행: 실행 중인 모든 서비스(Dify, MCP 서버, Caddy, cloudflared 터널)를 종료합니다. 데이터는 보존됩니다.
cd "$(dirname "$0")"
./poc-stop.sh
echo ""
echo "종료되었습니다. 이 창은 아무 키나 누르면 닫힙니다."
read -n 1 -s -r
