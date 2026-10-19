"""Maturity-harness run identity and report routing.

The acceptance artifact is evidence: a report that cannot be tied to a
checkout, provider, model or time is not verifiable later. Two properties are
load-bearing here:

- ``report.json`` carries a ``run`` block (commit, dirty state, model,
  provider *host*, platform, timestamps, counts) and never a credential;
- a full real-model run writes the canonical report, while a subset/skipped
  run writes its own dated file and cannot clobber the standing facts.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO_ROOT / "scripts" / "maturity" / "real_teaching_journeys_minimax.py"


@pytest.fixture()
def harness() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "server"))
    spec = importlib.util.spec_from_file_location("maturity_harness_metadata", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result() -> dict:
    return {
        "mode": "real",
        "cases": [
            {
                "case": "01-mutable-default",
                "fixture": {
                    "fixture_ok": True,
                    "pre_fix_exit": 1,
                    "post_fix_exit": 0,
                    "pre_fix_tail": "",
                    "post_fix_tail": "",
                },
                "turns": [
                    {"classification": "passed"},
                    {"classification": "passed"},
                ],
            },
            {
                "case": "02-late-binding",
                "fixture": {
                    "fixture_ok": False,
                    "pre_fix_exit": 1,
                    "post_fix_exit": 1,
                    "pre_fix_tail": "",
                    "post_fix_tail": "still failing",
                },
                "turns": [
                    {"classification": "failed"},
                    {"classification": "provider_error"},
                ],
            },
        ],
    }


def test_run_metadata_counts_and_never_leaks_provider_credentials(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "TRAINER_MATURITY_PROVIDER_BASE_URL",
        "https://user:pass@relay.example/v1?api_key=sk-secret-value",
    )
    monkeypatch.setenv("TRAINER_MATURITY_MODEL", "test-model")

    metadata = harness.build_run_metadata(
        _result(), harness.CASES[:2], started_at=time.time()
    )

    assert metadata["schema_version"] == 1
    assert metadata["mode"] == "real"
    assert metadata["model"] == "test-model"
    assert metadata["provider_host"] == "relay.example"
    assert metadata["case_count"] == 2
    assert metadata["turn_count"] == 4
    assert metadata["full_matrix"] is False
    assert metadata["classification_counts"] == {
        "passed": 2,
        "failed": 1,
        "provider_error": 1,
    }
    assert metadata["fixture_ok"] == 1
    assert metadata["platform"]
    assert metadata["started_at"] < metadata["finished_at"]

    serialized = json.dumps(metadata)
    for secret in ("sk-secret-value", "api_key", "user:pass"):
        assert secret not in serialized


def test_full_real_run_targets_canonical_and_override_wins(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRAINER_MATURITY_REPORT_PATH", raising=False)
    cases = harness.CASES
    assert (
        harness.report_target_path(cases, mode="real")
        == harness.STANDING_REPORT_PATH
    )

    monkeypatch.setenv("TRAINER_MATURITY_REPORT_PATH", "/tmp/explicit-report.md")
    assert (
        harness.report_target_path(cases, mode="real")
        == Path("/tmp/explicit-report.md")
    )


def test_subset_and_credentialless_runs_do_not_target_the_canonical_report(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRAINER_MATURITY_REPORT_PATH", raising=False)

    subset = harness.report_target_path(harness.CASES[:1], mode="real")
    assert subset != harness.STANDING_REPORT_PATH
    assert "subset-" in subset.name

    skipped = harness.report_target_path(harness.CASES, mode="skipped_no_credentials")
    assert skipped != harness.STANDING_REPORT_PATH
    assert "full-no-model" in skipped.name


def test_report_markdown_renders_run_identity(harness: Any, tmp_path: Path) -> None:
    result = _result()
    result["run"] = {
        "git_commit": "a" * 40,
        "git_dirty": True,
        "model": "test-model",
        "provider_host": "relay.example",
        "platform": "test-platform",
        "machine": "arm64",
        "python": "3.12.2",
        "started_at": "2026-10-19T00:00:00+00:00",
        "finished_at": "2026-10-19T00:10:00+00:00",
        "case_count": 2,
        "turn_count": 4,
        "full_matrix": False,
    }
    report = tmp_path / "report.md"
    harness.write_report(result, report)
    text = report.read_text(encoding="utf-8")

    assert "## 运行标识" in text
    assert "a" * 40 in text
    assert "relay.example" in text
    assert "test-model" in text
    assert "test-platform" in text
