from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

from belgu.api.app import create_app
from belgu.application.jobs import Worker
from belgu.application.service import BelguService
from belgu.demo.fixtures import seed_demo
from belgu.settings import Settings


def _settings(args, *, demo: bool = False, start_worker: bool = True) -> Settings:
    data_dir = Path(args.data_dir).resolve()
    profile = "demo" if demo else "operational"
    profile_dir = data_dir / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        db_url=f"sqlite:///{profile_dir / 'belgu.db'}",
        evidence_dir=profile_dir / "evidence",
        mode="demo" if demo else "operational",
        bind_host=args.host,
        port=args.port,
        start_worker=start_worker,
        web_dist=Path(args.web_dist),
    )


def _serve(args, *, demo: bool = False) -> None:
    settings = _settings(args, demo=demo)
    if demo:
        service = BelguService.open(settings.db_url, settings.evidence_dir)
        investigation_id = seed_demo(service)
        service.close()
        print(f"Belgü kurmaca demo hazır: {investigation_id}")
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.port, log_level="info")


def _worker(args) -> None:
    settings = _settings(args, start_worker=False)
    service = BelguService.open(settings.db_url, settings.evidence_dir)
    worker = Worker(service, "belgu-cli-worker")
    print("Belgü worker çalışıyor; durdurmak için Ctrl+C")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        service.close()


def _doctor(args) -> None:
    settings = _settings(args, start_worker=False)
    service = BelguService.open(settings.db_url, settings.evidence_dir)
    try:
        from belgu.analysis.service import get_model_status
        connection = service.integrations.configured_connection()
        model = get_model_status(connection) if connection is not None else get_model_status()
    except Exception as exc:
        model = {"status": "unavailable", "message": str(exc)}
    print(json.dumps({"status": "ok", "database": settings.db_url, "evidence_dir": str(settings.evidence_dir), "model": model}, ensure_ascii=False, indent=2))
    service.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="belgu", description="Belgü — İşaretten istihbarata")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "demo", "worker", "doctor"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", default=".belgu")
        command.add_argument("--host", default="127.0.0.1")
        command.add_argument("--port", type=int, default=8765)
        command.add_argument("--web-dist", default="web/dist")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Belgü v1 yalnız loopback üzerinde çalışır (127.0.0.1/::1).")
    if args.command == "serve":
        _serve(args)
    elif args.command == "demo":
        _serve(args, demo=True)
    elif args.command == "worker":
        _worker(args)
    else:
        _doctor(args)


if __name__ == "__main__":
    main()
