from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Test-isolation guard: never touch the developer's default data directory.
# Must run before any app module import so Settings picks this up.
_TEST_DATA_DIR = Path(__file__).resolve().parents[2] / "tmp" / "pytest-trainer-data"
_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TRAINER_DATA_DIR", str(_TEST_DATA_DIR))

provider_fixtures = importlib.import_module("provider_fixtures")
seed_verified_capabilities = provider_fixtures.seed_verified_capabilities
verified_capability_result = provider_fixtures.verified_capability_result


try:
    importlib.import_module("trafilatura")
except ImportError:
    @dataclass
    class _Document:
        title: str | None = None
        text: str | None = None
        author: str | None = None
        date: str | None = None
        url: str | None = None

        def as_dict(self) -> dict[str, Any]:
            return {
                "title": self.title,
                "text": self.text,
                "author": self.author,
                "date": self.date,
                "url": self.url,
            }

    trafilatura_stub = ModuleType("trafilatura")
    settings_stub = ModuleType("trafilatura.settings")
    settings_stub.Document = _Document
    trafilatura_stub.settings = settings_stub
    def _bare_extraction(content: str, **_kwargs: object) -> dict[str, object] | None:
        import re

        text = re.sub(r"<[^>]+>", " ", content)
        text = " ".join(text.split()).strip()
        return {"title": "", "text": text, "author": None, "date": None} if text else None

    trafilatura_stub.bare_extraction = _bare_extraction
    sys.modules["trafilatura"] = trafilatura_stub
    sys.modules["trafilatura.settings"] = settings_stub


__all__ = ["seed_verified_capabilities", "verified_capability_result"]
