#!/usr/bin/env bash
# 더블클릭으로 실행: Dify + MCP 서버 + 프론트엔드를 띄우고 cloudflared로 외부 공개 URL을 발급합니다.
cd "$(dirname "$0")"
./poc-start.sh --public
echo ""
echo "위 URL을 확인하세요. 데모가 끝나면 '종료.command'를 실행해 반드시 꺼주세요."
echo "이 창은 아무 키나 누르면 닫힙니다."
read -n 1 -s -r
