#!/usr/bin/env bash
# Optional Ubuntu/Debian OCR install into this checkout; no administrator access.
set -euo pipefail
BELGU_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v tesseract >/dev/null; then
  tesseract --version
  exit 0
fi
if [[ -x "$BELGU_ROOT/.local/bin/tesseract" ]]; then
  "$BELGU_ROOT/.local/bin/tesseract" --version
  exit 0
fi
command -v apt-get >/dev/null || { printf '%s\n' 'Tesseract kurup BELGU_TESSERACT_PATH ile yolunu belirtin.'; exit 1; }
case "$(dpkg --print-architecture)" in
  arm64) BELGU_OCR_ARCH=aarch64-linux-gnu ;;
  amd64) BELGU_OCR_ARCH=x86_64-linux-gnu ;;
  *) printf '%s\n' 'Bu mimaride Tesseract sistem paketini kullanın.'; exit 1 ;;
esac
mkdir -p "$BELGU_ROOT/.local/ocr/packages" "$BELGU_ROOT/.local/ocr/runtime" "$BELGU_ROOT/.local/bin"
cd "$BELGU_ROOT/.local/ocr/packages"
apt-get download tesseract-ocr libtesseract5 liblept5 tesseract-ocr-eng tesseract-ocr-tur tesseract-ocr-osd libgif7
for package in *.deb; do dpkg-deb -x "$package" ../runtime; done
python3 - "$BELGU_ROOT" "$BELGU_OCR_ARCH" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1]);arch=sys.argv[2]
wrapper=root/'.local/bin/tesseract'
wrapper.write_text('''#!/usr/bin/env bash
set -euo pipefail
BELGU_OCR_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../ocr/runtime" && pwd)"
export LD_LIBRARY_PATH="$BELGU_OCR_ROOT/usr/lib/'''+arch+'''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TESSDATA_PREFIX="$BELGU_OCR_ROOT/usr/share/tesseract-ocr/5/tessdata"
exec "$BELGU_OCR_ROOT/usr/bin/tesseract" "$@"
''')
wrapper.chmod(0o755)
PY
"$BELGU_ROOT/.local/bin/tesseract" --version
"$BELGU_ROOT/.local/bin/tesseract" --list-langs
