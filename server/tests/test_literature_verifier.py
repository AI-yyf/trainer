"""P1 #8 — literature verifier pack (§2.2 three-layer verification).

Guards: deterministic hooks behave locally and deterministically; rubric
items are anchor-forced (no anchor → construction error; anchor absent from
submission → Missing); and the combine rule never lets an LLM rubric review
verify without at least one deterministic pass or human adoption.
"""

from __future__ import annotations

import pytest

from app.evaluator.hooks import (
    BannedPhrasesHook,
    ParagraphStructureHook,
    QuoteBalanceHook,
    WordCountHook,
    hooks_from_card_config,
    run_hooks,
    unit_count,
)
from app.evaluator.models import CheckStatus
from app.evaluator.verifiers import (
    VERIFIER_REGISTRY,
    EmptyCommandPlanner,
    LocalRubricReviewer,
    RubricItem,
    RubricSpec,
    combine_verdict,
    literature_pack,
    verifier_pack_for,
)

# --- deterministic hooks ---------------------------------------------------


def test_unit_counts_cjk_chars_and_latin_words() -> None:
    assert unit_count("白描手法") == 4
    assert unit_count("plain words here") == 3
    # 2 CJK characters + 3 whitespace-separated latin words.
    assert unit_count("白描 with two words") == 5


def test_word_count_hook_window() -> None:
    hook = WordCountHook(min_units=10, max_units=20)
    inside = hook.run("一" * 15)
    below = hook.run("一" * 3)
    assert inside.status is CheckStatus.PASSED
    assert below.status is CheckStatus.FAILED
    with pytest.raises(ValueError):
        WordCountHook(min_units=20, max_units=10)


def test_banned_phrases_hook_hits_any_language() -> None:
    hook = BannedPhrasesHook(phrases=("非常", "amazing"))
    hit = hook.run("这片景色非常美丽")
    clean = hook.run("这片景色很美")
    latin = hook.run("This is amazing work")
    assert hit.status is CheckStatus.FAILED
    assert clean.status is CheckStatus.PASSED
    assert latin.status is CheckStatus.FAILED
    with pytest.raises(ValueError):
        BannedPhrasesHook(phrases=("  ", ""))


def test_paragraph_structure_hook_counts_blank_line_blocks() -> None:
    hook = ParagraphStructureHook(min_paragraphs=2)
    ok = hook.run("第一段。\n\n第二段。")
    single = hook.run("只有一段。")
    assert ok.status is CheckStatus.PASSED
    assert single.status is CheckStatus.FAILED


def test_quote_balance_hook_detects_stray_quotes() -> None:
    hook = QuoteBalanceHook()
    balanced = hook.run("他说：“来了。”然后就走了。")
    stray = hook.run("他说：“来了。然后就走了。")
    assert balanced.status is CheckStatus.PASSED
    assert stray.status is CheckStatus.FAILED


def test_run_hooks_fails_closed_on_crash() -> None:
    class Broken:
        name = "broken"

        def run(self, submission: str) -> object:
            raise RuntimeError("boom")

    results = run_hooks((Broken(), WordCountHook(min_units=0, max_units=5)), "内容")
    assert results[0].status is CheckStatus.ERROR
    assert "boom" in results[0].summary
    assert results[1].status is CheckStatus.PASSED


def test_hooks_from_card_config_builds_declared_set() -> None:
    hooks = hooks_from_card_config(
        {
            "word_count": {"min": 50, "max": 150},
            "banned_phrases": ["众所周知"],
            "min_paragraphs": 2,
            "quote_balance": True,
        }
    )
    names = [getattr(hook, "name", "") for hook in hooks]
    assert names == ["word-count", "banned-phrases", "paragraph-structure", "quote-balance"]
    assert hooks_from_card_config({}) == ()
    with pytest.raises(ValueError):
        hooks_from_card_config({"word_count": {"min": 200, "max": 100}})


# --- rubric lane -----------------------------------------------------------


def test_rubric_item_requires_anchor_and_caps_criteria() -> None:
    with pytest.raises(ValueError, match="anchor"):
        RubricItem(statement="用白描手法", anchor="  ")
    with pytest.raises(ValueError, match="statement"):
        RubricItem(statement="", anchor="原文")
    with pytest.raises(ValueError, match="at most 3"):
        RubricItem(statement="s", anchor="a", criteria=("1", "2", "3", "4"))
    item = RubricItem(statement="s", anchor="a", criteria=("1", "2", "3"))
    assert item.criteria == ("1", "2", "3")


def test_local_rubric_reviewer_matches_only_anchored_items() -> None:
    spec = RubricSpec(
        items=(
            RubricItem(statement="提到小伙计视角", anchor="小伙计"),
            RubricItem(statement="引用原文句子", anchor="孔乙己是站着喝酒而穿长衫的唯一的人"),
        )
    )
    review = LocalRubricReviewer().review(
        spec,
        "从“孔乙己是站着喝酒而穿长衫的唯一的人”可见叙述者是旁观的小伙计。",
    )
    assert review.status is CheckStatus.PASSED
    assert len(review.matched) == 2

    partial = LocalRubricReviewer().review(spec, "小伙计是旁观者，但我记不清原文了。")
    assert partial.status is CheckStatus.FAILED
    assert partial.matched == ["提到小伙计视角"]
    assert "引用原文句子" in partial.missing


def test_local_rubric_reviewer_skips_empty_spec() -> None:
    review = LocalRubricReviewer().review(RubricSpec(items=()), "任意提交")
    assert review.status is CheckStatus.SKIPPED


# --- combine rule (the fail-closed core) ------------------------------------


def test_combine_verdict_fails_on_any_hook_failure() -> None:
    from app.evaluator.models import CheckResult

    hooks = (
        CheckResult(name="a", status=CheckStatus.PASSED, summary="ok"),
        CheckResult(name="b", status=CheckStatus.FAILED, summary="too short"),
    )
    verdict = combine_verdict(hooks, None)  # type: ignore[arg-type]
    assert verdict.status is CheckStatus.FAILED
    assert "b" in verdict.summary


def test_combine_verdict_never_lets_llm_review_verify_alone() -> None:
    from app.evaluator.models import CheckResult

    passing_rubric = LocalRubricReviewer().review(
        RubricSpec(items=(RubricItem(statement="s", anchor="a"),)),
        "包含 a 的提交",
    )
    assert passing_rubric.status is CheckStatus.PASSED
    # No deterministic hooks ran at all → PENDING, never PASSED.
    verdict = combine_verdict((), passing_rubric)
    assert verdict.status is CheckStatus.PENDING
    assert "not evidence" in verdict.summary
    # Human adoption breaks the tie explicitly.
    adopted = combine_verdict((), passing_rubric, human_adopted=True)
    assert adopted.status is CheckStatus.PASSED
    # A failed hook still blocks even with adoption.
    blocked = combine_verdict(
        (CheckResult(name="x", status=CheckStatus.FAILED, summary="no"),),
        passing_rubric,
        human_adopted=True,
    )
    assert blocked.status is CheckStatus.FAILED


def test_combine_verdict_passes_with_hook_plus_rubric() -> None:
    from app.evaluator.models import CheckResult

    hooks = (CheckResult(name="word-count", status=CheckStatus.PASSED, summary="ok"),)
    rubric = LocalRubricReviewer().review(
        RubricSpec(items=(RubricItem(statement="s", anchor="a"),)), "文本 a"
    )
    verdict = combine_verdict(hooks, rubric)  # type: ignore[arg-type]
    assert verdict.status is CheckStatus.PASSED


# --- pack registration ------------------------------------------------------


def test_literature_pack_registered_with_empty_planner() -> None:
    pack = VERIFIER_REGISTRY["literature"]
    assert pack == literature_pack()
    assert pack.subject_family == "literature"
    assert isinstance(pack.command_planner, EmptyCommandPlanner)
    assert pack.command_planner.plan(None) == ()  # type: ignore[arg-type]
    assert verifier_pack_for("literature") is pack


def test_literature_submission_verifier_end_to_end() -> None:
    from app.evaluator.verifiers import LiteratureSubmissionVerifier

    hooks = hooks_from_card_config({"word_count": {"min": 4, "max": 50}, "banned_phrases": ["非常"]})
    rubric = RubricSpec(
        items=(
            RubricItem(statement="出现锚点意象", anchor="月亮"),
            RubricItem(statement="引用原句", anchor="月光如水"),
        )
    )
    verifier = LiteratureSubmissionVerifier(hooks=hooks, rubric=rubric)

    good = verifier.verify("他说月光如水，月亮挂在楼角。")
    assert good.status is CheckStatus.PASSED

    banned = verifier.verify("月光如水，月亮很亮，非常安静地照着大地和原野。")
    assert banned.status is CheckStatus.FAILED  # banned phrase wins

    unanchored = verifier.verify("完全无关的一段文字，不算短，也没有任何锚点可用。")
    assert unanchored.status is CheckStatus.FAILED  # rubric missing → FAILED

    llm_only = LiteratureSubmissionVerifier(hooks=(), rubric=rubric)
    pending = llm_only.verify("月光如水，月亮挂在楼角。")
    assert pending.status is CheckStatus.PENDING  # rubric alone is not evidence
