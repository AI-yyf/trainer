"""Regression tests for the maturity harness's turn classification.

Locks the 2026-10-13 review fixes:

- a server ``downgraded`` grounding outcome is an M2 failure and can never be
  classified ``passed`` (even when the local recompute agrees — M5 ok);
- M5 reconciliation runs against the same inputs the server used (accumulated
  history, learner message, mirrored workspace file checker), so correct turns
  are not failed by a weaker local corpus;
- the classification enum has no unreachable members (``mock`` had no path).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO_ROOT / "scripts" / "maturity" / "real_teaching_journeys_minimax.py"

CASE = {
    "id": "probe-case",
    "topic_tokens": ["grid"],
    "runtime": "python",
    "primary_file": "x.py",
}


@pytest.fixture(scope="module")
def harness() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "server"))
    spec = importlib.util.spec_from_file_location("maturity_harness", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(
    *,
    next_step: str,
    reply: str = "我们看一下边界。",
    outcome: str | None = None,
    symbols: tuple[str, ...] = (),
    retry_used: bool = False,
    flag: bool = False,
    fell_back: bool = False,
    clean_stamp: bool = False,
) -> dict:
    if fell_back:
        agent_meta: dict[str, object] = {"fell_back": True}
    elif clean_stamp:
        agent_meta = {}
    else:
        agent_meta = {
            "grounding_outcome": outcome,
            "grounding_ungrounded_symbols": list(symbols),
            "grounding_retry_used": retry_used,
            "next_step_requires_confirmation": flag,
        }
    return {
        "reply": {"content": reply},
        "coach_turn": {"next_step": next_step, "requires_confirmation": flag},
        "agent_meta": agent_meta,
        "snapshot": {"memory": {}},
    }


def test_downgraded_server_turn_is_never_passed(harness: Any) -> None:
    """M2: a downgraded turn is a grounding failure even when M5 agrees."""
    payload = _payload(
        outcome="downgraded",
        next_step="给我 `parse_header()` 的函数名。",
        symbols=("parse_header",),
        flag=True,
    )

    result = harness.classify_and_check_turn(
        CASE, 1, payload, None, code_text="grid = 1\n", message="为什么失败"
    )

    assert result["classification"] == "failed"
    assert result["grounding_pass"] is False
    assert result["flagged"] is True
    # The reconciliation itself agrees (M5 ok) — the failure is M2, not M5.
    assert result["reconciliation"] == "ok"


def test_grounded_stamp_with_matching_local_recompute_passes(harness: Any) -> None:
    payload = _payload(outcome="grounded", next_step="再对 `grid` 做一次实验。")

    result = harness.classify_and_check_turn(
        CASE, 1, payload, None, code_text="grid = 1\n", message="我们看边界"
    )

    assert result["classification"] == "passed"
    assert result["grounding_pass"] is True
    assert result["reconciliation"] == "ok"


def test_clean_reply_without_stamp_requires_a_grounded_step(harness: Any) -> None:
    grounded = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(next_step="再对 `grid` 做一次实验。", clean_stamp=True),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert grounded["classification"] == "passed"

    ungrounded = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(next_step="给我 `parse_header()` 的函数名。", clean_stamp=True),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert ungrounded["classification"] == "failed"
    assert "no grounding stamp" in ungrounded["reconciliation"]


def test_corrected_outcome_requires_retry_flag_and_no_downgrade_flag(harness: Any) -> None:
    ok = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(
            outcome="corrected",
            next_step="再对 `grid` 做一次实验。",
            retry_used=True,
        ),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert ok["classification"] == "passed"

    missing_retry = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(
            outcome="corrected",
            next_step="再对 `grid` 做一次实验。",
            retry_used=False,
        ),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert missing_retry["classification"] == "failed"
    assert "without retry_used" in missing_retry["reconciliation"]

    flagged = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(
            outcome="corrected",
            next_step="再对 `grid` 做一次实验。",
            retry_used=True,
            flag=True,
        ),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert flagged["classification"] == "failed"
    assert "requires_confirmation" in flagged["reconciliation"]


def test_recovery_override_is_not_a_teaching_pass(harness: Any) -> None:
    result = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(outcome="recovery_override", next_step="继续上一轮。"),
        None,
        code_text="grid = 1\n",
        message="继续",
    )
    assert result["classification"] == "failed"
    assert "recovery override" in result["reconciliation"]


def test_provider_error_and_local_fallback_classification(harness: Any) -> None:
    error = harness.classify_and_check_turn(
        CASE, 1, None, "HTTP 502", code_text="grid = 1\n", message="为什么失败"
    )
    assert error["classification"] == "provider_error"

    fallback = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(next_step="继续。", fell_back=True),
        None,
        code_text="grid = 1\n",
        message="继续",
    )
    assert fallback["classification"] == "local_fallback"


def test_history_anchored_symbol_reconciles_with_history(harness: Any) -> None:
    """M5 parity: the server anchors symbols in the conversation history; the
    local recompute needs the same history to agree."""
    payload = _payload(
        outcome="grounded",
        next_step="在 `history_helper` 里补一个边界判断。",
        reply="我们看之前那条线。",
    )
    history_text = "user: 我们之前定义了 history_helper\nassistant: 好，记住它。"
    code_text = "grid = 1\n"

    with_history = harness.classify_and_check_turn(
        CASE,
        1,
        payload,
        None,
        code_text=code_text,
        message="继续之前那条线",
        history_text=history_text,
    )
    assert with_history["classification"] == "passed"

    # Control: without the history corpus the local recompute disagrees and
    # the same turn is failed — the exact mismatch the parity fix removes.
    without_history = harness.classify_and_check_turn(
        CASE,
        1,
        payload,
        None,
        code_text=code_text,
        message="继续之前那条线",
        history_text="",
    )
    assert without_history["classification"] == "failed"


def test_file_pointer_reconciles_with_workspace_checker(harness: Any, tmp_path: Path) -> None:
    """M5 parity: the local recompute mirrors the server's workspace-scoped
    file checker instead of guessing."""
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    next_step = "查看 `legacy_report.py` 的第 10 行。"

    missing = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(outcome="downgraded", next_step=next_step, symbols=("legacy_report.py",), flag=True),
        None,
        code_text="grid = 1\n",
        message="看一下旧报告",
        workspace_root=workspace_root,
    )
    assert missing["classification"] == "failed"
    assert missing["reconciliation"] == "ok"  # both sides agree it is missing

    (workspace_root / "legacy_report.py").write_text("x = 1\n", encoding="utf-8")
    present = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(outcome="grounded", next_step=next_step),
        None,
        code_text="grid = 1\n",
        message="看一下旧报告",
        workspace_root=workspace_root,
    )
    assert present["classification"] == "passed"


def test_classification_enum_has_no_unreachable_members(harness: Any) -> None:
    """``mock`` had no assignment path anywhere in the harness (2026-10-13
    review): the enum now lists exactly the producible states."""
    assert set(harness.TURN_CLASSIFICATIONS) == {
        "passed",
        "failed",
        "provider_error",
        "local_fallback",
        "skipped_no_credentials",
    }
