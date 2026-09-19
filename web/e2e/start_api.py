"""Disposable API profiles for browser integration tests; no operational records are touched."""
import argparse
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "src"))
import uvicorn
from belgu.api.app import create_app
from belgu.application.service import BelguService
from belgu.demo.fixtures import seed_demo
from belgu.settings import Settings

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--mode", choices=["demo", "operational"], required=True)
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="belgu-browser-") as tmp:
    settings = Settings(db_url=f"sqlite:///{tmp}/case.db", evidence_dir=Path(tmp) / "evidence", mode=args.mode,
                        port=args.port, start_worker=False, web_dist=root / "web/dist")
    if args.mode == "demo":
        service = BelguService.open(settings.db_url, settings.evidence_dir)
        seed_demo(service)
        service.close()
    else:
        from seed_workbench import seed_workbench
        service = BelguService.open(settings.db_url, settings.evidence_dir)
        seed_workbench(service)
        service.close()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")
