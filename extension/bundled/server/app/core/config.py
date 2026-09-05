from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    sidecar_host: str = "127.0.0.1"
    sidecar_port: int = 8765
    data_dir: Path = Path(".trainer")
    database_name: str = "trainer.sqlite3"
    qdrant_dir_name: str = "qdrant"
    default_provider_base_url: str = "https://api.openai.com/v1"
    default_provider_model: str = "gpt-4.1-mini"
    enable_network_fetch: bool = False

    model_config = SettingsConfigDict(env_prefix="TRAINER_", extra="ignore")

    @property
    def database_path(self) -> Path:
      return self.data_dir / self.database_name

    @property
    def qdrant_path(self) -> Path:
      return self.data_dir / self.qdrant_dir_name
