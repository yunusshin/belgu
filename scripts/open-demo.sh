#!/usr/bin/env bash
set -euo pipefail
belgu_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$belgu_project_root"
belgu_demo_url="http://127.0.0.1:8765"
if ! curl --silent --fail --max-time 2 "$belgu_demo_url/api/health" >/dev/null; then
  mkdir -p .local/logs
  nohup bash scripts/run.sh demo >.local/logs/demo-launch.log 2>&1 </dev/null &
  for belgu_attempt in {1..30}; do
    if curl --silent --fail --max-time 1 "$belgu_demo_url/api/health" >/dev/null; then break; fi
    sleep 0.5
  done
fi
if ! curl --silent --fail --max-time 2 "$belgu_demo_url/api/health" >/dev/null; then
  printf '%s\n' 'Demo açılamadı. .local/logs/demo-launch.log dosyasını kontrol edin.' >&2
  exit 1
fi
exec xdg-open "$belgu_demo_url"
