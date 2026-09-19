from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def service(tmp_path: Path):
    from belgu.application.service import BelguService

    svc = BelguService.open(f"sqlite:///{tmp_path / 'belgu.db'}", tmp_path / "evidence")
    yield svc
    svc.close()


@pytest.fixture
def api(tmp_path: Path):
    from belgu.api.app import create_app
    from belgu.settings import Settings

    app = create_app(Settings(db_url=f"sqlite:///{tmp_path / 'api.db'}", evidence_dir=tmp_path / "evidence", mode="test", start_worker=True))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client
