from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, TypeVar, overload

import pytest

try:  # hypothesis ships with the dev extra; property tests import it too.
    from hypothesis import HealthCheck
    from hypothesis import settings as hypothesis_settings

    # Input-strategy generation is CPU-bound. On a loaded CI runner or while a
    # full xdist suite is running, Hypothesis can spend >1s generating the
    # first valid example and fail the run with FailedHealthCheck: too_slow.
    # That is a property-test infrastructure signal, not a product failure
    # (and it reproduced only under load). Keep the deadline; suppress just
    # the generation-speed check for every property test.
    hypothesis_settings.register_profile(
        "trainer-ci",
        suppress_health_check=[HealthCheck.too_slow],
    )
    hypothesis_settings.load_profile("trainer-ci")
except ImportError:  # pragma: no cover - runtime installs without dev extras
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Test-isolation guard: never touch the developer's default data directory.
# Must run before any app module import so Settings picks this up.
#
# The suite runs under xdist with 4-8 processes. A single shared data
# directory makes those processes race on the same SQLite files and lets one
# worker observe another worker's evidence/card state, which showed up as
# order-dependent failures in the evidence, flashcard and evaluator modules.
# Scope the directory to the worker process so each worker owns its state.
_TEST_WORKER = os.environ.get("PYTEST_XDIST_WORKER") or f"pid{os.getpid()}"
_TEST_DATA_DIR = (
    Path(__file__).resolve().parents[2] / "tmp" / f"pytest-trainer-data-{_TEST_WORKER}"
)
_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
# Assignment, not setdefault: the controller imports this module first and its
# environment is inherited by every worker, so setdefault would hand all
# workers the controller's directory and re-introduce the shared-state races.
os.environ["TRAINER_DATA_DIR"] = str(_TEST_DATA_DIR)

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

    # The stub modules are ``ModuleType`` subclasses so that the attributes
    # assigned below are declared, and therefore type-checked; importing them
    # behaves exactly like importing a plain ``ModuleType``.
    class _TrafilaturaSettingsModule(ModuleType):
        Document: type[_Document]

    class _TrafilaturaModule(ModuleType):
        settings: _TrafilaturaSettingsModule
        bare_extraction: Callable[..., dict[str, object] | None]

    trafilatura_stub = _TrafilaturaModule("trafilatura")
    settings_stub = _TrafilaturaSettingsModule("trafilatura.settings")
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


# §五: SQLite fast pragmas for the test process. Windows CI measured the
# server suite at 57m42s serial vs ~15m on Linux/macOS — the gap is fsync
# journaling on NTFS across thousands of throwaway per-test connections.
# Every database here lives in a tmp_path deleted after the test, so
# durability is irrelevant; production defaults are untouched (this file
# only exists under tests/).
_original_sqlite_connect: Callable[..., sqlite3.Connection] = sqlite3.connect

# typeshed declares ``sqlite3.connect`` as a generic set of overloads, which a
# transparent ``*args, **kwargs`` wrapper cannot be assigned to as-is. The
# overloads below restate its stdlib signatures (3.12+) for the type checker
# only; the implementation still forwards every argument untouched, so omitted
# arguments keep the interpreter's own defaults.
_IsolationLevel = Literal["DEFERRED", "IMMEDIATE", "EXCLUSIVE"]
_SqlitePath = str | bytes | PathLike[str] | PathLike[bytes]
_ConnectionT = TypeVar("_ConnectionT", bound=sqlite3.Connection)


@overload
def _fast_sqlite_connect(
    database: _SqlitePath,
    timeout: float = 5.0,
    detect_types: int = 0,
    isolation_level: _IsolationLevel = "DEFERRED",
    check_same_thread: bool = True,
    cached_statements: int = 128,
    uri: bool = False,
    *,
    autocommit: bool = ...,
) -> sqlite3.Connection: ...


@overload
def _fast_sqlite_connect(
    database: _SqlitePath,
    timeout: float,
    detect_types: int,
    isolation_level: _IsolationLevel,
    check_same_thread: bool,
    factory: type[_ConnectionT],
    cached_statements: int = 128,
    uri: bool = False,
    *,
    autocommit: bool = ...,
) -> _ConnectionT: ...


@overload
def _fast_sqlite_connect(
    database: _SqlitePath,
    timeout: float = 5.0,
    detect_types: int = 0,
    isolation_level: _IsolationLevel = "DEFERRED",
    check_same_thread: bool = True,
    *,
    factory: type[_ConnectionT],
    cached_statements: int = 128,
    uri: bool = False,
    autocommit: bool = ...,
) -> _ConnectionT: ...


def _fast_sqlite_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
    connection = _original_sqlite_connect(*args, **kwargs)
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = OFF")
    try:
        connection.execute("PRAGMA journal_mode = MEMORY")
    except sqlite3.OperationalError:
        pass
    return connection


sqlite3.connect = _fast_sqlite_connect


@pytest.fixture(autouse=True)
def _isolate_external_check_cache():
    """Keep the process-level tool-check cache from leaking across tests.

    In the product the cache is deliberately long-lived: a learner re-verifying
    an unchanged file should not re-pay a pyright cold start. In the suite that
    same sharing would let one test's verdict satisfy another test's assertion,
    making results depend on execution order. Clearing between tests preserves
    per-test isolation without giving up the production win.
    """
    from app.evaluator.check_cache import CHECK_RESULT_CACHE

    CHECK_RESULT_CACHE.clear()
    yield
    CHECK_RESULT_CACHE.clear()


# Registered after conftest's own fixtures so it can see `real_tools`. This is
# what keeps the suite off the real linters by default; see the module for why.
pytest_plugins: list[str] = ["fake_external_tools"]
