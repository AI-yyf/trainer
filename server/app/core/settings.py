from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    app_name: str
    host: str
    port: int
    data_dir: Path
    database_name: str
    default_session_stage: str
    summary_message_limit: int
    enable_network_fetch: bool = False

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_name

    @classmethod
    def from_env(cls) -> "AppSettings":
        data_dir = Path(
            os.getenv(
                "TRAINER_DATA_DIR",
                str(Path.home() / ".trainer" / "server-data"),
            )
        )
        return cls(
            app_name=os.getenv("TRAINER_APP_NAME", "Trainer Server"),
            host=os.getenv("TRAINER_HOST", "127.0.0.1"),
            port=int(os.getenv("TRAINER_PORT", "8765")),
            data_dir=data_dir,
            database_name=os.getenv("TRAINER_DB_NAME", "trainer.db"),
            default_session_stage=os.getenv("TRAINER_DEFAULT_SESSION_STAGE", "intake"),
            summary_message_limit=int(os.getenv("TRAINER_SUMMARY_MESSAGE_LIMIT", "6")),
            enable_network_fetch=os.getenv("TRAINER_ENABLE_NETWORK_FETCH", "").strip().lower()
            in {"1", "true", "yes", "on"},
        )
