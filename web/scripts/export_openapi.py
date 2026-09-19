"""Export the current backend contract without starting a server or worker."""
import json
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "src"))
from belgu.api.app import create_app
from belgu.settings import Settings

with tempfile.TemporaryDirectory(prefix="belgu-schema-") as tmp:
    app = create_app(Settings(db_url="sqlite:///:memory:", evidence_dir=Path(tmp), start_worker=False))
    try:
        (root / "web/openapi.json").write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
    finally:
        app.state.service.close()
