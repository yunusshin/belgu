#!/usr/bin/env bash
set -euo pipefail

belgu_llama_server="${BELGU_LLAMA_SERVER:-$(command -v llama-server || true)}"
belgu_model_path="${BELGU_MODEL_PATH:-}"
belgu_model_log="${BELGU_MODEL_LOG:-.local/model/server.log}"

if [[ -z "$belgu_llama_server" || ! -x "$belgu_llama_server" ]]; then
  echo "llama-server bulunamadı; BELGU_LLAMA_SERVER veya PATH ile belirtin." >&2
  exit 1
fi
if [[ -z "$belgu_model_path" || ! -f "$belgu_model_path" ]]; then
  echo "İlk GGUF shard yolunu BELGU_MODEL_PATH ile belirtin." >&2
  exit 1
fi

mkdir -p "$(dirname "$belgu_model_log")"
exec "$belgu_llama_server" \
  --model "$belgu_model_path" \
  --host 127.0.0.1 \
  --port 8080 \
  --ctx-size 8192 \
  --parallel 1 \
  --n-gpu-layers 999 \
  --reasoning off \
  --reasoning-format none \
  --metrics \
  --no-webui \
  --offline \
  --log-file "$belgu_model_log"
