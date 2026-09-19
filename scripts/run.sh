#!/usr/bin/env bash
set -euo pipefail
BELGU_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BELGU_ROOT"
if [[ ! -x .venv/bin/belgu ]]; then
  printf '%s\n' 'Önce kurulum: bash scripts/setup.sh'
  exit 1
fi
BELGU_PROFILE="${1:-demo}"
case "$BELGU_PROFILE" in
  demo) BELGU_COMMAND=demo; BELGU_PORT="${BELGU_PORT:-8765}" ;;
  live) BELGU_COMMAND=serve; BELGU_PORT="${BELGU_PORT:-8766}" ;;
  doctor) exec .venv/bin/belgu doctor --data-dir "${BELGU_DATA_DIR:-$BELGU_ROOT/.local/data}" ;;
  *) printf '%s\n' 'Kullanım: bash scripts/run.sh [demo|live|doctor]'; exit 2 ;;
esac
if [[ ! -f web/dist/index.html ]]; then
  printf '%s\n' 'Arayüz derlenmemiş: npm --prefix web ci && npm --prefix web run build'
  exit 1
fi
printf 'Belgü %s: http://127.0.0.1:%s\n' "$BELGU_PROFILE" "$BELGU_PORT"
exec .venv/bin/belgu "$BELGU_COMMAND" --port "$BELGU_PORT" --host 127.0.0.1 \
  --data-dir "${BELGU_DATA_DIR:-$BELGU_ROOT/.local/data}" --web-dist "$BELGU_ROOT/web/dist"
