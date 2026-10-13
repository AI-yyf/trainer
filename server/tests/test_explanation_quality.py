"""Explanation-quality dimensions (non-gating reporting layer).

Covers the ``app/llm/explanation_quality.py`` contract and its harness
integration:

- each dimension (``addresses_learner`` / ``language_alignment`` /
  ``anchored_symbols`` / ``no_solution_dump`` / ``explains_reasoning``)
  across its ``ok`` / ``weak`` / ``unclear`` verdicts, all deterministic
  (no model, no mock);
- the guided-mode solution-dump rule (>= 1 fenced block, >= 12 fenced code
  lines) and the direct/practice modes staying unjudged;
- purity: evaluation never writes the grounding gate (``gate_outcome`` /
  ``verdicts`` / claims stay untouched — the dimension is reporting only);
- the maturity harness records ``explanation_quality`` in its per-turn
  checks WITHOUT changing the classification, and aggregates the summary
  for the markdown report and ``report.json``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO_ROOT / "scripts" / "maturity" / "real_teaching_journeys_minimax.py"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.explanation_quality import (  # noqa: E402
    EXPLANATION_DIMENSIONS,
    EXPLANATION_VERDICTS,
    ExplanationQualityReport,
    evaluate_explanation_quality,
)
from app.llm.turn_grounding import (  # noqa: E402
    TeachingTurnFacts,
    build_teaching_turn_facts,
)


def _facts(**overrides: str) -> TeachingTurnFacts:
    values: dict[str, str] = {
        "turn_id": "t-explanation",
        "reply_text": "",
        "code_text": "",
        "history_text": "",
        "user_message": "",
        "next_step_text": "",
    }
    values.update(overrides)
    return build_teaching_turn_facts(**values)


def _quality(*, answer_mode: str = "guided", **overrides: str) -> ExplanationQualityReport:
    return evaluate_explanation_quality(_facts(**overrides), answer_mode=answer_mode)


def _dump_reply(line_count: int) -> str:
    """A reply carrying one fenced block with exactly ``line_count`` lines."""
    body = "\n".join(f"items.append({index})  # step {index}" for index in range(line_count))
    return f"完整改法如下：\n```python\n{body}\n```\n跑一次断言试试。"


# ---------------------------------------------------------------------------
# Dimension 1: addresses_learner
# ---------------------------------------------------------------------------


def test_addresses_learner_ok_when_reply_restates_the_question() -> None:
    report = _quality(
        user_message="为什么可变默认参数会在两次调用之间共享？解释一下 mutable_default 的行为",
        reply_text=(
            "为什么可变默认参数会在两次调用之间共享：因为默认参数只在函数定义时"
            "求值一次，`mutable_default` 这一个列表被所有调用共享。"
        ),
    )
    assert report.dimensions["addresses_learner"] == "ok"
    assert "user content tokens" in report.evidence["addresses_learner"]


def test_addresses_learner_weak_when_reply_ignores_the_question() -> None:
    report = _quality(
        user_message="为什么我的测试断言在并发场景下会失败？asyncio 的事件循环是怎么调度的",
        reply_text=(
            "这是一份关于列表切片边界行为的说明，与当前问题无关。"
            "slice boundary semantics differ."
        ),
    )
    assert report.dimensions["addresses_learner"] == "weak"
    assert "0/" in report.evidence["addresses_learner"]


def test_addresses_learner_unclear_without_user_message() -> None:
    empty = _quality(reply_text="因为默认参数只在定义时求值一次。")
    assert empty.dimensions["addresses_learner"] == "unclear"

    tokenless = _quality(user_message="？？？", reply_text="因为默认参数只在定义时求值一次。")
    assert tokenless.dimensions["addresses_learner"] == "unclear"


# ---------------------------------------------------------------------------
# Dimension 2: language_alignment
# ---------------------------------------------------------------------------


def test_language_alignment_ok_for_matching_script_with_english_code() -> None:
    """Fenced English code must never outvote Chinese prose."""
    report = _quality(
        user_message="为什么这段代码会抛出异常？",
        reply_text=(
            "因为列表索引越界了。\n```python\nprint(xs[9])  # IndexError\n```\n"
            "所以你看到 IndexError。"
        ),
    )
    assert report.dimensions["language_alignment"] == "ok"
    assert "cjk vs cjk" in report.evidence["language_alignment"]


def test_language_alignment_weak_for_wrong_script_prose() -> None:
    report = _quality(
        user_message="为什么我的断言失败了？",
        reply_text=(
            "Your assertion failed because the list is empty. Therefore the "
            "lookup returns nothing and the comparison never matches."
        ),
    )
    assert report.dimensions["language_alignment"] == "weak"
    assert "latin vs cjk" in report.evidence["language_alignment"]


def test_language_alignment_unclear_without_judgeable_input() -> None:
    empty = _quality(reply_text="因为默认参数只在定义时求值一次。")
    assert empty.dimensions["language_alignment"] == "unclear"

    code_only = _quality(user_message="为什么失败？", reply_text="```python\nprint(xs)\n```")
    assert code_only.dimensions["language_alignment"] == "unclear"


# ---------------------------------------------------------------------------
# Dimension 3: anchored_symbols
# ---------------------------------------------------------------------------


def test_anchored_symbols_ok_when_reply_covers_next_step_symbols() -> None:
    report = _quality(
        user_message="为什么返回值是 None？",
        reply_text=(
            "因为 `find_first` 现在对空输入直接返回 None，所以先在 `find_first` "
            "里补一个空列表守卫，然后再次运行 `run_checks` 确认。"
        ),
        next_step_text="在 `find_first` 里补一个空列表守卫，再运行 `run_checks` 验证。",
    )
    assert report.dimensions["anchored_symbols"] == "ok"
    assert "2/2 next-step symbols" in report.evidence["anchored_symbols"]


def test_anchored_symbols_weak_when_partially_covered() -> None:
    report = _quality(
        user_message="为什么返回值是 None？",
        reply_text="因为 `find_first` 对空输入直接返回 None，所以先补一个空列表守卫。",
        next_step_text="在 `find_first` 里补一个空列表守卫，再运行 `run_checks` 验证。",
    )
    assert report.dimensions["anchored_symbols"] == "weak"
    assert "run_checks" in report.evidence["anchored_symbols"]


def test_anchored_symbols_unclear_without_symbols() -> None:
    prose_only = _quality(
        user_message="然后呢？",
        reply_text="把第一条实际输出贴回来，我们一起确认。",
        next_step_text="把第一条实际输出贴回来，我们一起确认。",
    )
    assert prose_only.dimensions["anchored_symbols"] == "unclear"

    no_next_symbols = _quality(
        user_message="为什么失败？",
        reply_text="问题出在 `run_checks` 的边界上。",
        next_step_text="把第一条实际输出贴回来，我们一起确认。",
    )
    assert no_next_symbols.dimensions["anchored_symbols"] == "unclear"


# ---------------------------------------------------------------------------
# Dimension 4: no_solution_dump (guided mode only)
# ---------------------------------------------------------------------------


def test_solution_dump_guided_flags_large_fenced_block() -> None:
    report = _quality(answer_mode="guided", reply_text=_dump_reply(14))
    assert report.dimensions["no_solution_dump"] == "weak"
    assert report.solution_dump_suspected is True
    assert "14 code line(s)" in report.evidence["no_solution_dump"]


def test_solution_dump_guided_allows_small_snippets_and_prose() -> None:
    snippet = _quality(
        answer_mode="guided",
        reply_text="先试最小修改：\n```python\nitems = []\n```\n然后跑一次断言看看输出。",
    )
    assert snippet.dimensions["no_solution_dump"] == "ok"
    assert snippet.solution_dump_suspected is False

    prose = _quality(
        answer_mode="guided",
        reply_text="因为默认参数只在定义时求值一次，所以两次调用共享同一个列表。",
    )
    assert prose.dimensions["no_solution_dump"] == "ok"
    assert prose.solution_dump_suspected is False


def test_solution_dump_direct_and_practice_modes_are_not_judged() -> None:
    for mode in ("direct", "practice"):
        report = _quality(answer_mode=mode, reply_text=_dump_reply(14))
        assert report.dimensions["no_solution_dump"] == "unclear", mode
        assert report.solution_dump_suspected is False, mode
        assert "guided mode only" in report.evidence["no_solution_dump"]


# ---------------------------------------------------------------------------
# Dimension 5: explains_reasoning
# ---------------------------------------------------------------------------


def test_explains_reasoning_ok_when_marker_sits_near_code() -> None:
    report = _quality(
        user_message="为什么返回值是 None？",
        reply_text="因为 `find_first` 的空列表守卫缺失，函数直接返回了 None。",
    )
    assert report.dimensions["explains_reasoning"] == "ok"
    assert "1 within" in report.evidence["explains_reasoning"]


def test_explains_reasoning_weak_without_any_marker() -> None:
    report = _quality(
        user_message="然后呢？",
        reply_text="把 `find_first` 加上空列表守卫，再运行一次确认。",
    )
    assert report.dimensions["explains_reasoning"] == "weak"
    assert "no reasoning connective" in report.evidence["explains_reasoning"]


def test_explains_reasoning_weak_when_markers_are_far_from_code() -> None:
    filler = "这一段补充说明展开了很多相关的背景细节，供你参考。" * 10
    report = _quality(
        user_message="为什么会共享？",
        reply_text=(
            "因为默认参数在函数定义时只求值一次，所以两次调用共享同一个列表。"
            f"\n{filler}\n参见 `add_item` 的文档。"
        ),
    )
    assert report.dimensions["explains_reasoning"] == "weak"
    assert "0 within" in report.evidence["explains_reasoning"]


def test_explains_reasoning_unclear_for_empty_reply() -> None:
    report = _quality(user_message="为什么失败？")
    assert report.dimensions["explains_reasoning"] == "unclear"


# ---------------------------------------------------------------------------
# Purity + shape: the report never touches the grounding gate
# ---------------------------------------------------------------------------


def test_evaluation_is_pure_and_reports_all_dimensions() -> None:
    facts = build_teaching_turn_facts(
        turn_id="t-purity",
        reply_text="因为 `grid` 的两行是同一个引用，所以修改一行会看到另一行变化。",
        code_text="grid = [[0]]\ngrid[0].append(1)\n",
        history_text="",
        user_message="为什么我改了 grid[0] 之后 grid[1] 也变了？",
        next_step_text="再对 `grid` 做一次实验。",
    )
    report = evaluate_explanation_quality(facts, answer_mode="guided")

    assert isinstance(report, ExplanationQualityReport)
    assert set(report.dimensions) == set(EXPLANATION_DIMENSIONS)
    assert set(report.evidence) == set(EXPLANATION_DIMENSIONS)
    assert all(verdict in EXPLANATION_VERDICTS for verdict in report.dimensions.values())
    assert all(report.evidence[dim].strip() for dim in EXPLANATION_DIMENSIONS)

    # Non-gating by contract: no grounding field was written.
    assert facts.gate_outcome == "grounded"
    assert facts.verdicts == {}
    assert facts.conflicts == []
    assert facts.next_step_claims  # untouched, still populated


# ---------------------------------------------------------------------------
# Harness integration (scripts/maturity/real_teaching_journeys_minimax.py)
# ---------------------------------------------------------------------------

CASE = {
    "id": "probe-case",
    "topic_tokens": ["grid"],
    "runtime": "python",
    "primary_file": "x.py",
    "answer_mode": "guided",
}


@pytest.fixture(scope="module")
def harness() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "server"))
    spec = importlib.util.spec_from_file_location("maturity_harness_eq", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(*, next_step: str, reply: str) -> dict:
    return {
        "reply": {"content": reply},
        "coach_turn": {"next_step": next_step, "requires_confirmation": False},
        "agent_meta": {
            "grounding_outcome": "grounded",
            "grounding_ungrounded_symbols": [],
            "grounding_retry_used": False,
        },
        "snapshot": {"memory": {}},
    }


def test_harness_records_explanation_quality_without_changing_classification(
    harness: Any,
) -> None:
    grounded = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(
            next_step="再对 `grid` 做一次实验。",
            reply="因为 `grid` 的两行是同一个引用，所以我们再跑一次看输出。",
        ),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert grounded["classification"] == "passed"
    quality = grounded["explanation_quality"]
    assert set(quality["dimensions"]) == set(EXPLANATION_DIMENSIONS)
    assert quality["dimensions"]["no_solution_dump"] == "ok"
    assert quality["solution_dump_suspected"] is False

    # A failing turn still carries the reporting dimensions — attached to
    # every judged turn, never altering the verdict itself.
    failed = harness.classify_and_check_turn(
        CASE,
        1,
        {
            "reply": {"content": "我们看一下。"},
            "coach_turn": {"next_step": "给我 `parse_header()` 的函数名。", "requires_confirmation": True},
            "agent_meta": {
                "grounding_outcome": "downgraded",
                "grounding_ungrounded_symbols": ["parse_header"],
                "grounding_retry_used": False,
            },
            "snapshot": {"memory": {}},
        },
        None,
        code_text="grid = 1\n",
        message="为什么失败",
    )
    assert failed["classification"] == "failed"
    assert set(failed["explanation_quality"]["dimensions"]) == set(EXPLANATION_DIMENSIONS)


def test_harness_dump_suspected_flows_through_without_gating(harness: Any) -> None:
    """A guided-mode solution dump stays ``passed`` — reported, never gated."""
    dumped = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(next_step="再对 `grid` 做一次实验。", reply=_dump_reply(14)),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert dumped["classification"] == "passed"
    assert dumped["explanation_quality"]["solution_dump_suspected"] is True
    assert dumped["explanation_quality"]["dimensions"]["no_solution_dump"] == "weak"

    direct_case = {**CASE, "answer_mode": "direct"}
    direct = harness.classify_and_check_turn(
        direct_case,
        1,
        _payload(next_step="再对 `grid` 做一次实验。", reply=_dump_reply(14)),
        None,
        code_text="grid = 1\n",
        message="直接给改法",
    )
    assert direct["classification"] == "passed"
    assert direct["explanation_quality"]["solution_dump_suspected"] is False
    assert direct["explanation_quality"]["dimensions"]["no_solution_dump"] == "unclear"


def test_explanation_quality_summary_aggregates_counts_and_markdown(harness: Any) -> None:
    result = {
        "cases": [
            {
                "case": "a",
                "fixture": {"fixture_ok": True},
                "turns": [
                    {
                        "classification": "passed",
                        "explanation_quality": {
                            "dimensions": {
                                "addresses_learner": "ok",
                                "language_alignment": "ok",
                                "anchored_symbols": "ok",
                                "no_solution_dump": "ok",
                                "explains_reasoning": "weak",
                            },
                            "solution_dump_suspected": False,
                        },
                    },
                    {
                        "classification": "passed",
                        "explanation_quality": {
                            "dimensions": {
                                "addresses_learner": "weak",
                                "language_alignment": "unclear",
                                "anchored_symbols": "weak",
                                "no_solution_dump": "weak",
                                "explains_reasoning": "ok",
                            },
                            "solution_dump_suspected": True,
                        },
                    },
                ],
            },
            {
                "case": "b",
                "fixture": {"fixture_ok": True},
                "turns": [
                    # No explanation_quality record: skipped turns are not judged.
                    {"classification": "skipped_no_credentials"},
                ],
            },
        ]
    }

    summary = harness.explanation_quality_summary(result)
    assert summary["evaluated_turns"] == 2
    assert summary["solution_dump_suspected_turns"] == 1
    assert summary["dimensions"]["addresses_learner"] == {"ok": 1, "weak": 1, "unclear": 0}
    assert summary["dimensions"]["anchored_symbols"] == {"ok": 1, "weak": 1, "unclear": 0}
    assert summary["dimensions"]["no_solution_dump"] == {"ok": 1, "weak": 1, "unclear": 0}
    assert summary["dimensions"]["explains_reasoning"] == {"ok": 1, "weak": 1, "unclear": 0}
    assert summary["dimensions"]["language_alignment"] == {"ok": 1, "weak": 0, "unclear": 1}

    lines = harness.explanation_quality_markdown(summary)
    joined = "\n".join(lines)
    assert "解释质量汇总" in joined
    assert "solution_dump_suspected 回合：1/2" in joined
    assert "| addresses_learner | 1 | 1 | 0 |" in joined
    assert "非门控" in joined

    empty = harness.explanation_quality_summary({"cases": []})
    assert empty["evaluated_turns"] == 0
    assert empty["solution_dump_suspected_turns"] == 0
