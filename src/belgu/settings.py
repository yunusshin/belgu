from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BELGU_", extra="ignore")

    db_url: str = "sqlite:///./.belgu/belgu.db"
    evidence_dir: Path = Path(".belgu/evidence")
    mode: str = "operational"
    bind_host: str = "127.0.0.1"
    port: int = 8765
    start_worker: bool = True
    web_dist: Path = Path("web/dist")
