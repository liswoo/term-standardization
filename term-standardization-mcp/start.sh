#!/usr/bin/env bash
# macOS/Linux equivalent of start.ps1
set -euo pipefail
RESTART=false
if [[ "${1:-}" == "--restart" ]]; then RESTART=true; fi
cd "$(dirname "$0")"
export PYTHONUTF8=1

EXISTING_PID=$(lsof -tiTCP:8100 -sTCP:LISTEN 2>/dev/null || true)
if [[ -n "$EXISTING_PID" && "$RESTART" != true ]]; then
  echo "MCP port 8100 is already listening."
  exit 0
fi

docker compose up -d --wait
.venv/bin/python manage.py init-db
# Idempotent reseed: the terms_data Docker volume is local to this machine and
# never travels with git, so switching machines (or a fresh clone) starts with
# an empty database unless this also reseeds it every time, not just once.
.venv/bin/python manage.py import-catalog data/scenario_catalog.json
.venv/bin/python manage.py import-guideline data/standard_guide.md

if [[ -n "$EXISTING_PID" ]]; then
  kill "$EXISTING_PID" || true
  sleep 1
fi

mkdir -p .runtime
nohup .venv/bin/python server.py >.runtime/server.log 2>.runtime/server-error.log &
echo $! >.runtime/server.pid

for _ in $(seq 1 10); do
  sleep 1
  if lsof -tiTCP:8100 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "MCP ready: http://host.docker.internal:8100/mcp"
    exit 0
  fi
done
echo "MCP did not start; inspect .runtime/server-error.log." >&2
exit 1
