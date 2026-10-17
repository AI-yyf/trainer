"""Regression tests for the maturity harness's literature block (P2 #17).

The 28-case code matrix is untouched; the 2026-10-17 extension adds four
literature cases (category ``L``) whose fixture is an objective deliverable
checker (¶ anchors, verbatim quote/material cross-check, required sections)
instead of pre-broken code. These tests lock:

- the matrix shape (28 code + 4 literature = 32; code cases keep their ids,
  messages and topic tokens and default to ``subject="code"``);
- every literature case is markdown-primary, carries ``language_id``, and
  routes markdown through ``turn_payload`` (not the python/javascript code
  language path);
- the literature fixture backbone is locally real: the stub deliverable must
  fail the checker (exit≠0) and the scripted completed work must pass
  (exit=0) — no provider credentials needed;
- literature turn payloads never claim a python/javascript ``language_id``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO_ROOT / "scripts" / "maturity" / "real_teaching_journeys_minimax.py"

LITERATURE_IDS = (
    "L1-close-read-annotate",
    "L2-imitation-transfer",
    "L3-theory-concept-card",
    "L4-compare-two-pieces",
)


@pytest.fixture(scope="module")
def harness() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "server"))
    spec = importlib.util.spec_from_file_location("maturity_harness", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matrix_shape_code_and_literature(harness: Any) -> None:
    ids = {case["id"] for case in harness.CASES}
    assert len(harness.CASES) == 32
    assert set(LITERATURE_IDS) <= ids
    by_id = {case["id"]: case for case in harness.CASES}
    code_ids = [case["id"] for case in harness.CASES if case.get("subject", "code") == "code"]
    assert len(code_ids) == 28
    # The original code cases are untouched: their ids stay unique and their
    # subject defaults to code.
    for legacy in ("01-mutable-default", "A4-dict-mutation", "G4-return-after-days"):
        assert by_id[legacy].get("subject", "code") == "code"
    literature = [id_ for id_ in LITERATURE_IDS]
    subjects = {by_id[id_]["subject"] for id_ in literature}
    assert subjects == {"literature"}
    assert {by_id[id_]["category"] for id_ in literature} == {"L"}
    assert all(by_id[id_]["language_id"] == "markdown" for id_ in literature)


def test_literature_fixture_backbone_is_locally_real(harness: Any, tmp_path: Any) -> None:
    """Stub deliverable fails the checker; the completed work passes it."""
    by_id = {case["id"]: case for case in harness.CASES}
    for id_ in LITERATURE_IDS:
        fixture = harness.check_case_fixture(by_id[id_], tmp_path / id_)
        assert fixture["fixture_ok"] is True, (id_, fixture)
        assert fixture["pre_fix_exit"] != 0
        assert fixture["post_fix_exit"] == 0


def test_literature_turn_payload_keeps_markdown_language(harness: Any) -> None:
    by_id = {case["id"]: case for case in harness.CASES}
    code_case = by_id["01-mutable-default"]
    literature_case = by_id["L1-close-read-annotate"]
    provider = {"name": "probe"}
    code_payload = harness.turn_payload(
        "session", code_case, "msg", "grid = 1\n",
        file_path="projects/x/x.py", provider=provider, api_key="k",
    )
    assert code_payload["current_file"]["language_id"] == "python"
    literature_payload = harness.turn_payload(
        "session", literature_case, "msg", "¶1 渡船离开码头时，灯还没熄。",
        file_path="projects/L1/夜航.md", provider=provider, api_key="k",
    )
    assert literature_payload["current_file"]["language_id"] == "markdown"
    # The material is the primary file and must not claim a code language.
    assert literature_case["primary_file"].endswith(".md")
    assert {"精读", "批注", "锚点"} & set(literature_case["topic_tokens"])


def test_subset_selection_still_validates_literature_ids(harness: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("TRAINER_MATURITY_CASE_IDS", ",".join(LITERATURE_IDS))
    selected = harness.selected_cases()
    assert [case["id"] for case in selected] == list(LITERATURE_IDS)
    monkeypatch.setenv("TRAINER_MATURITY_CASE_IDS", "L9-imaginary")
    with pytest.raises(RuntimeError, match="TRAINER_MATURITY_CASE_IDS"):
        harness.selected_cases()


def test_skip_mode_report_never_targets_the_standing_report(harness: Any, monkeypatch: Any, tmp_path: Any) -> None:
    """No-credential runs (subset OR full) write their own dated file."""
    monkeypatch.delenv("TRAINER_MATURITY_REPORT_PATH", raising=False)
    cases = [case for case in harness.CASES]  # full matrix
    standing = harness.report_target_path(cases, mode="skipped_no_credentials")
    assert standing.name != "2026-10-13-teaching-journeys-report.md"
    subset = cases[:2]
    subset_path = harness.report_target_path(subset, mode="skipped_no_credentials")
    assert "subset" in subset_path.name and standing.name != subset_path.name
    override = tmp_path / "custom-report.md"
    monkeypatch.setenv("TRAINER_MATURITY_REPORT_PATH", str(override))
    assert harness.report_target_path(cases, mode="skipped_no_credentials") == override
