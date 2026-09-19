#!/usr/bin/env bash
set -euo pipefail
BELGU_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BELGU_ROOT"
python3 -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ gerekli"'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
npm --prefix web ci --no-audit --no-fund
.venv/bin/python -m playwright install chromium
npm --prefix web run build
printf '%s\n' 'Hazır. Demo: bash scripts/run.sh demo' 'Canlı çalışma: bash scripts/run.sh live'
