"""Teaching-turn fact grounding (TeachingTurnFacts contract).

Covers the 2026-10-08 real-teaching-quality failures and the slice-2 contract:

- a structured ``coach_turn.next_step`` that demands code symbols appearing
  nowhere in the reply/code must be detected and downgraded to
  ``requires_confirmation`` (case 03: "给我函数名/call site" for a file with no
  function);
- slice 2: every symbol of every next-step claim must anchor (a fabricated
  symbol must not hide behind an anchored one), the corrective retry travels
  back as ``corrected_next_step``, file pointers use the injected existence
  checker with an ``unverifiable`` escape, and ``TeachingTurnFacts`` carries
  the claim/provenance fields the assembly flows share;
- memory anchors must never drift onto a verbatim message prefix
  (cases 01-03: ``coach_anchor``/``current_focus`` became the message prefix).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from provider_fixtures import seed_verified_capabilities

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import ProviderConfig
from app.db.repository import TrainerRepository
from app.llm.provider_service import ProviderService
from app.llm.turn_grounding import (
    FACT_KINDS,
    FACT_PROVENANCES,
    GroundingDecision,
    TeachingFact,
    WorkspaceEvidence,
    build_teaching_turn_facts,
    claim_domain,
    claim_key,
    domain_backing,
    evaluate_next_step_grounding,
    evaluate_turn_grounding,
    extract_claim_facts,
    extract_code_symbols,
    grounding_correction_instruction,
    grounding_outcome,
    is_verbatim_message_prefix,
    memory_provenance_summary,
    next_step_is_grounded,
    sanitize_memory_anchor,
)
from app.memory.models import (
    MemorySnapshot as LaneMemorySnapshot,
)
from app.memory.models import ProgressRecord, SessionSummary
from app.memory.service import MemoryService
from tests.test_api import build_client

MESSAGE_PREFIX = "我亲自写了下面的修改，帮我看看为什么还是报错"


# ---------------------------------------------------------------------------
# Pure next-step grounding validation
# ---------------------------------------------------------------------------


def test_ungrounded_next_step_demanding_missing_function_is_detected() -> None:
    """Case 03: the reply explains list aliasing; no function exists anywhere."""
    next_step = "给我 `parse_header()` 的函数名和 call site，我帮你逐行看。"
    reply = (
        "内层列表是同一个引用，所以修改 `grid[0]` 后 `grid[1]` 也变成了 `[1, 0]`。"
        "用 `grid[0] is grid[1]` 可以观察到这一点；列表推导式可以创建独立行。"
    )
    code = "grid = [[0] * 2]\ngrid[0].append(1)\nprint(grid)\n"

    assert extract_code_symbols(next_step) == ["parse_header"]
    assert next_step_is_grounded(next_step, reply, code) is False


def test_grounded_next_step_referencing_code_symbol_passes() -> None:
    next_step = "Run one more check on `grid` and confirm both rows print independently."
    reply = "The two rows share the same inner list reference."
    code = "grid = [[0], [0]]\ngrid[0].append(1)\nprint(grid)\n"

    assert next_step_is_grounded(next_step, reply, code) is True


def test_prose_only_next_step_is_grounded_without_code() -> None:
    """Fallback next steps are generic prose; no symbols means nothing to ground."""
    next_step = "把第一条实际输出贴回来，我们一起确认默认参数的创建时机。"

    assert next_step_is_grounded(next_step, "", "") is True


def test_toolchain_symbols_never_require_code_grounding() -> None:
    next_step = "Run the module once via `pytest` and keep the output visible."

    assert next_step_is_grounded(next_step, "", "") is True


def test_workspace_file_pointer_never_requires_code_grounding() -> None:
    """A file reference may point at a workspace file from an earlier turn."""
    next_step = "Run pytest on stuck.py and report the result."

    assert next_step_is_grounded(next_step, "Whitespace tightened; rerun pending.", "") is True
    assert next_step_is_grounded("Open `notes.md` before the next patch.", "", "") is True
    # Non-file dotted symbols stay groundable.
    assert next_step_is_grounded("Show `os.path.join` usage.", "", "x = 1\n") is False


def test_word_boundary_matching_avoids_false_grounding() -> None:
    """`parse` must not be grounded by `parse_header` appearing in the code."""
    next_step = "Show me the `parse` definition and its call site."
    code = "def parse_header(raw):\n    return raw\n"

    assert next_step_is_grounded(next_step, "", code) is False


def test_symbol_grounded_in_prior_user_message_code_passes() -> None:
    next_step = "Add one assert for `find_boundary` before widening scope."
    reply = "The closed upper bound avoids the out-of-range access."
    code = "xs = [1, 2]\n# learner pasted: def find_boundary(xs, target): ...\n"

    assert next_step_is_grounded(next_step, reply, code) is True


# ---------------------------------------------------------------------------
# Retry-once-then-downgrade semantics (fake generator, no live provider)
# ---------------------------------------------------------------------------


def test_retry_once_with_corrective_instruction_downgrades_still_ungrounded() -> None:
    attempts: list[str] = []

    def fake_regenerate() -> str:
        attempts.append("called")
        # A live retry would re-ask the provider with the corrective
        # instruction; the fake returns another fabricated requirement.
        return "补上 `format_rows()` 的定义位置。"

    decision = evaluate_next_step_grounding(
        "给我 `parse_header()` 的函数名。",
        "内层列表是同一个引用。",
        "grid = [[0] * 2]\n",
        retry_generate=fake_regenerate,
    )

    assert attempts == ["called"], "retry must run at most once"
    assert decision.grounded is False
    # Unified retry_used semantics (2026-10-13 review): the flag means "a
    # regeneration was attempted for this decision" — it stays True even when
    # the regeneration was unusable; the corrected outcome is carried by
    # corrected_next_step instead.
    assert decision.retry_used is True
    assert decision.requires_confirmation is True
    assert decision.downgraded is True


def test_retry_once_with_grounded_regeneration_clears_the_flag() -> None:
    def fake_regenerate() -> str:
        return "Run one more experiment on `grid` and keep both outputs."

    decision = evaluate_next_step_grounding(
        "给我 `parse_header()` 的函数名。",
        "内层列表是同一个引用。",
        "grid = [[0] * 2]\n",
        retry_generate=fake_regenerate,
    )

    assert decision.grounded is True
    assert decision.retry_used is True
    assert decision.requires_confirmation is False
    assert decision.corrected_next_step == "Run one more experiment on `grid` and keep both outputs."


def test_no_retry_hook_downgrades_immediately() -> None:
    decision = evaluate_next_step_grounding(
        "给我 `parse_header()` 的函数名。",
        "内层列表是同一个引用。",
        "grid = [[0] * 2]\n",
    )

    assert decision.grounded is False
    assert decision.retry_used is False
    assert decision.requires_confirmation is True


def test_trim_ungrounded_segments_keeps_the_canonical_step() -> None:
    from app.llm.turn_grounding import trim_ungrounded_segments

    step = (
        "先挑第一层受影响的边界，落下最小安全 patch，验证完再动下一层。"
        " 复盘节奏：这一步落地后，再围绕「nested_alias.py」做一次很窄的 patch 式回看。"
    )
    assert trim_ungrounded_segments(step, ["nested_alias.py"]) == (
        "先挑第一层受影响的边界，落下最小安全 patch，验证完再动下一层。"
    )
    # No locatable segment: return the original so the caller downgrades.
    assert trim_ungrounded_segments("Keep going.", ["ghost.py"]) == "Keep going."
    assert trim_ungrounded_segments(step, []) == step


def test_correction_instruction_mentions_grounding_rule() -> None:
    chinese = grounding_correction_instruction("zh-CN")
    english = grounding_correction_instruction("en-US")

    assert "真实存在" in chinese
    assert "函数名" in chinese
    assert "really exist" in english
    # The rejected step is shown to the model as context; the instruction must
    # forbid copying its ungrounded names (the E4 case repeated nested_alias.py).
    assert "复制" in chinese
    assert "copy such names" in english


# ---------------------------------------------------------------------------
# Memory anchor anti-drift
# ---------------------------------------------------------------------------


def test_message_prefix_is_never_a_valid_anchor() -> None:
    assert is_verbatim_message_prefix("我亲自写了下面的修改", MESSAGE_PREFIX) is True
    assert is_verbatim_message_prefix("mutable default arguments", MESSAGE_PREFIX) is False
    # Short overlaps and identifier-like anchors stay valid technical facts.
    assert is_verbatim_message_prefix("lesson.py", "lesson.py 里的断言为什么失败") is False
    assert is_verbatim_message_prefix("", MESSAGE_PREFIX) is False


def test_maturity_drift_fragments_are_rejected_as_message_prefix() -> None:
    """2026-10-13 real-model maturity runs: 19/56 turns anchored on fragments
    of the learner's opening ("items 打印出来是空的", "我加了 or 0") because
    their identifier tokens exempted them. The anchor must describe the
    teaching state, never echo the learner's message opening.
    """
    for anchor, message in (
        ("items 打印出来是空的", "items 打印出来是空的，怎么回事？"),
        ("我加了 or 0", "我加了 or 0 之后 items 打印出来是空的"),
        ("我保存了 task 并 await 它", "我保存了 task 并 await 它但没有效果"),
        ("同一份逻辑搬到 JS 后", "同一份逻辑搬到 JS 后行为不一样"),
    ):
        assert is_verbatim_message_prefix(anchor, message) is True
        assert sanitize_memory_anchor(anchor, message) == ""


def test_latin_token_lane_anchor_is_not_treated_as_drift() -> None:
    """Mixed-script lane labels (``我有一个 AI idea``) survive sanitization.

    Rejecting them wiped the new lane's focus on a general→idea switch, and
    the thread fell back to the previous lane's stale focus (regression:
    test_turn_agentic_idea_switch_drops_previous_general_lane_context).
    """
    message = "我有一个 AI idea，想把它落地成一个最小可验证的原型。"

    assert is_verbatim_message_prefix("我有一个 AI idea", message) is False
    assert sanitize_memory_anchor("我有一个 AI idea", message) == "我有一个 AI idea"
    # Pure-CJK narration openings stay rejected.
    assert sanitize_memory_anchor("我亲自写了下面的修改", MESSAGE_PREFIX) == ""


def test_sanitize_memory_anchor_falls_back_to_previous_anchor_then_empty() -> None:
    prefix = MESSAGE_PREFIX[:10]

    assert sanitize_memory_anchor(prefix, MESSAGE_PREFIX) == ""
    assert (
        sanitize_memory_anchor(prefix, MESSAGE_PREFIX, previous_anchor="lesson.py")
        == "lesson.py"
    )
    assert sanitize_memory_anchor("", MESSAGE_PREFIX, previous_anchor="lesson.py") == "lesson.py"
    assert sanitize_memory_anchor("", MESSAGE_PREFIX) == ""
    assert (
        sanitize_memory_anchor("mutable default arguments", MESSAGE_PREFIX)
        == "mutable default arguments"
    )
    # A previous anchor that is itself the message prefix must not be retained.
    assert sanitize_memory_anchor(prefix, MESSAGE_PREFIX, previous_anchor=prefix) == ""


def test_record_turn_memory_never_persists_message_prefix_focus(tmp_path: Path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "anchor-drift.db"))
    workspace_id = "workspace-anchor-drift"
    focus = MESSAGE_PREFIX[:12]
    summary = "解释了嵌套列表共享引用的成因。"
    next_step = "再用一个可变对象实验验证一次边界。"

    service.record_coaching_reflection(
        workspace_id=workspace_id,
        scenario="general",
        focus_area=focus,
        summary=summary,
        next_step=next_step,
        user_message=MESSAGE_PREFIX,
    )
    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-anchor-drift",
        user_message=MESSAGE_PREFIX,
        scenario="general",
        focus_area=focus,
        summary=summary,
        next_step=next_step,
    )

    snapshot = service.snapshot(workspace_id)
    assert focus not in snapshot.coach_anchor
    assert focus not in snapshot.current_focus
    workspace_text = str(snapshot.workspace)
    assert focus not in workspace_text
    active_thread = snapshot.workspace.get("active_thread") or {}
    assert focus not in str(active_thread.get("focus_area") or "")


def test_record_turn_memory_keeps_technical_concept_focus(tmp_path: Path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "anchor-concept.db"))
    workspace_id = "workspace-anchor-concept"

    service.record_coaching_reflection(
        workspace_id=workspace_id,
        scenario="general",
        focus_area="mutable default arguments",
        summary="Explained when the default object is created.",
        next_step="Verify with one print of __defaults__.",
        user_message="why does my default list keep growing between calls",
    )
    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-anchor-concept",
        user_message="why does my default list keep growing between calls",
        scenario="general",
        focus_area="mutable default arguments",
        summary="Explained when the default object is created.",
        next_step="Verify with one print of __defaults__.",
    )

    snapshot = service.snapshot(workspace_id)
    assert snapshot.coach_anchor == "mutable default arguments"
    assert "mutable default arguments" in snapshot.current_focus


def test_record_turn_memory_keeps_identifier_anchor_opening_the_message(
    tmp_path: Path,
) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "anchor-identifier.db"))
    workspace_id = "workspace-anchor-identifier"

    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-anchor-identifier",
        user_message="lesson.py 里的断言为什么失败",
        scenario="general",
        focus_area="lesson.py",
        summary="Read the assertion contract first.",
        next_step="Run one failing assert and read the message.",
    )

    snapshot = service.snapshot(workspace_id)
    assert snapshot.workspace.get("latest_turn_focus_area") == "lesson.py"


def test_derive_coach_anchor_filters_narration_scenario_and_fragment_junk(
    tmp_path: Path,
) -> None:
    """Derivation-time belt-and-braces: whatever landed in lane workspace
    state, the snapshot never surfaces a narration opening, a bare scenario
    name, or a code fragment as coach_anchor (real-model MiniMax runs
    observed exactly these three drift shapes)."""
    service = MemoryService(TrainerRepository(tmp_path / "anchor-derive.db"))
    lane = LaneMemorySnapshot(
        workspace={
            "latest_coach_focus_area": "我的脚本 assert 失败了",
            "latest_turn_focus_area": "我亲自写了下面的修改（用 None 哨兵",
        },
        session=SessionSummary(
            session_id="session-anchor-derive",
            recent_messages=[
                "user: 我的脚本 assert 失败了，第二个 assert 报 items 是 [1, 2]。",
                "assistant: 我们一起看第一个栈帧。",
            ],
        ),
    )

    anchor = service._derive_coach_anchor(None, lane)
    assert "我的脚本 assert 失败了" not in anchor
    assert "我亲自写了下面的修改" not in anchor
    assert anchor == "implementation"

    # Bare scenario lanes are not concepts.
    scenario_lane = LaneMemorySnapshot(
        progress=[
            ProgressRecord(
                lane="general",
                focus_area="",
                summary="Reviewed the failure report.",
                next_step="Read one stack frame together.",
            )
        ],
    )
    assert service._derive_coach_anchor(None, scenario_lane) == "implementation"

    # Grounded technical labels survive derivation.
    grounded_lane = LaneMemorySnapshot(
        workspace={"latest_coach_focus_area": "mutable-default.py"},
    )
    assert service._derive_coach_anchor(None, grounded_lane) == "mutable-default.py"

    # current_focus never re-anchors on the narration prefix either.
    focus = service._derive_current_focus(None, "", lane)
    assert "我的脚本 assert 失败了" not in focus
    assert "我亲自写了下面的修改" not in focus


# ---------------------------------------------------------------------------
# Slice 2: TeachingTurnFacts contract
# (per-claim anchoring, file checks, corrected-next-step carrier, provenance)
# ---------------------------------------------------------------------------


def test_every_symbol_of_a_claim_must_anchor() -> None:
    """A fabricated symbol must not hide behind an anchored one."""
    next_step = "在 `find` 里补一个 `debug_trace()` 调用，再跑一次断言。"
    reply = "边界用闭区间时循环才能覆盖最后一个元素。"
    code = "def find(xs, target):\n    lo, hi = 0, len(xs) - 1\n"

    assert next_step_is_grounded(next_step, reply, code) is False
    decision = evaluate_next_step_grounding(next_step, reply, code)
    assert decision.grounded is False
    assert decision.referenced_symbols == ["debug_trace"]
    assert decision.requires_confirmation is True


def test_whitelist_drops_project_nouns_but_keeps_builtins() -> None:
    assert next_step_is_grounded("把 `log` 输出补上后再跑。", "", "") is False
    assert next_step_is_grounded("清掉 `todo` 注释。", "", "") is False
    assert next_step_is_grounded("补一个 `fixme` 标记。", "", "") is False
    assert next_step_is_grounded("先用 `print` 看一眼输出。", "", "") is True
    assert next_step_is_grounded("运行 `pytest` 看结果。", "", "") is True


def test_build_teaching_turn_facts_populates_claims_and_verdicts() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-42",
        reply_text="内层列表是同一个引用，`grid[0] is grid[1]` 为 True。",
        code_text="grid = [[0], [0]]\ngrid[0].append(1)\n",
        history_text="user: 为什么 grid 两行联动",
        user_message="我的脚本 assert 失败了，IndexError 指向第二行。",
        next_step_text="再对 `grid` 做一次独立行实验。",
    )

    assert facts.turn_id == "turn-42"
    assert [fact.value for fact in facts.next_step_claims] == ["grid"]
    assert any(
        fact.kind == "error_text" and fact.value == "IndexError"
        for fact in facts.learner_provided
    )
    assert facts.memory_provenance["next_step"] == "model_claim"
    assert facts.memory_provenance["summary"] == "model_claim"

    decision = evaluate_turn_grounding(facts)
    assert decision.grounded is True
    assert facts.gate_outcome == "grounded"
    assert facts.verdicts == {"symbol:grid": "grounded"}


def test_corrected_next_step_carrier_and_corrected_outcome() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-43",
        reply_text="两行共享同一个内层引用。",
        code_text="grid = [[0], [0]]\n",
        history_text="",
        user_message="",
        next_step_text="给我 `parse_header()` 的函数名和 call site。",
    )

    decision = evaluate_turn_grounding(
        facts,
        retry_generate=lambda: "再对 `grid` 做一次独立行实验。",
    )

    assert decision.grounded is True
    assert decision.retry_used is True
    assert decision.corrected_next_step == "再对 `grid` 做一次独立行实验。"
    assert facts.gate_outcome == "corrected"
    assert grounding_outcome(decision) == "corrected"
    assert [fact.value for fact in facts.next_step_claims] == ["grid"]
    assert facts.verdicts == {"symbol:grid": "grounded"}


def test_failed_retry_downgrades_and_reports_ungrounded_symbols() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-44",
        reply_text="",
        code_text="grid = [[0], [0]]\n",
        history_text="",
        user_message="",
        next_step_text="补上 `format_rows()` 的定义位置。",
    )

    decision = evaluate_turn_grounding(
        facts,
        retry_generate=lambda: "再补一个 `parse_header()` 的 call site。",
    )

    assert decision.grounded is False
    assert decision.retry_used is True
    assert decision.requires_confirmation is True
    assert decision.corrected_next_step is None
    assert decision.referenced_symbols == ["format_rows"]
    assert facts.gate_outcome == "downgraded"
    assert facts.verdicts == {"symbol:format_rows": "ungrounded"}
    assert grounding_outcome(decision) == "downgraded"


def test_empty_regeneration_is_not_a_pass() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-45",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text="给我 `parse_header()` 的函数名。",
    )

    decision = evaluate_turn_grounding(facts, retry_generate=lambda: "")

    assert decision.grounded is False
    # An empty regeneration is still an attempt (unified semantics).
    assert decision.retry_used is True
    assert decision.requires_confirmation is True
    assert decision.corrected_next_step is None


def test_file_pointer_checker_semantics_and_unverifiable_escape() -> None:
    step = "查看 `legacy_report.py` 的第 10 行。"

    facts = build_teaching_turn_facts(
        turn_id="turn-46",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text=step,
        workspace_evidence=WorkspaceEvidence(
            file_exists=lambda path: path != "legacy_report.py",
        ),
    )
    decision = evaluate_turn_grounding(facts)
    assert decision.grounded is False
    assert decision.requires_confirmation is True
    assert facts.verdicts == {"file_path:legacy_report.py": "ungrounded"}

    facts = build_teaching_turn_facts(
        turn_id="turn-46",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text=step,
        workspace_evidence={"file_exists": lambda path: True},
    )
    assert evaluate_turn_grounding(facts).grounded is True
    assert facts.verdicts == {"file_path:legacy_report.py": "grounded"}

    # Remote / URI workspace: the checker cannot answer -> unverifiable, never
    # a fabricated downgrade.
    facts = build_teaching_turn_facts(
        turn_id="turn-46",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text=step,
        workspace_evidence=WorkspaceEvidence(file_exists=lambda path: None),
    )
    assert evaluate_turn_grounding(facts).grounded is True
    assert facts.verdicts == {"file_path:legacy_report.py": "unverifiable"}

    # No evidence at all keeps the same escape.
    facts = build_teaching_turn_facts(
        turn_id="turn-46",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text=step,
    )
    assert evaluate_turn_grounding(facts).grounded is True
    assert facts.verdicts == {"file_path:legacy_report.py": "unverifiable"}


def test_unverifiable_flag_overrides_a_checker() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-46b",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text="查看 `legacy_report.py` 的第 10 行。",
        workspace_evidence=WorkspaceEvidence(
            file_exists=lambda path: False,
            unverifiable=True,
        ),
    )

    assert evaluate_turn_grounding(facts).grounded is True
    assert facts.verdicts == {"file_path:legacy_report.py": "unverifiable"}


def test_workspace_verified_fact_anchors_a_symbol() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-47",
        reply_text="先把它接进现有流程。",
        code_text="",
        history_text="",
        user_message="",
        next_step_text="调用 `load_dataset()` 载入样本。",
        workspace_evidence={
            "verified_facts": [{"kind": "symbol", "value": "load_dataset"}],
        },
    )

    decision = evaluate_turn_grounding(facts)

    assert decision.grounded is True
    assert facts.verdicts == {"symbol:load_dataset": "grounded"}
    assert facts.workspace_verified[0].provenance == "tool_verified"


def test_learner_message_anchors_and_error_text_is_recorded() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-48",
        reply_text="",
        code_text="",
        history_text="",
        user_message="我贴一下报错：ValueError: need more than 1 value；函数叫 parse_pairs。",
        next_step_text="回到 `parse_pairs` 里补一个解包检查。",
    )

    assert any(
        fact.kind == "error_text" and fact.value == "ValueError"
        for fact in facts.learner_provided
    )
    assert any(fact.value == "parse_pairs" for fact in facts.learner_provided)
    assert evaluate_turn_grounding(facts).grounded is True


def test_claim_key_and_domain_normalization() -> None:
    assert claim_key("symbol", "`parse_header()`") == "symbol:parse_header"
    assert claim_key("file_path", "stuck.py") == "file_path:stuck.py"
    assert (
        claim_domain(TeachingFact(kind="file_path", value="./src/utils.py"))
        == "src/utils.py"
    )
    assert claim_domain(TeachingFact(kind="symbol", value="`parse_header`")) == "parse_header"
    assert (
        claim_domain(TeachingFact(kind="code_fragment", value="Grid[0]  IS  Grid[1]"))
        == "Grid[0] IS Grid[1]"
    )


def test_claim_extraction_kinds() -> None:
    facts = extract_claim_facts(
        "打开 `notes.md`，调用 `load_rows()`，观察 `grid[0]` 和 os.path.join 行为。",
        source="next_step",
    )
    kinds = {fact.value: fact.kind for fact in facts}

    assert kinds == {
        "notes.md": "file_path",
        "load_rows": "symbol",
        "grid[0]": "code_fragment",
        "os.path.join": "symbol",
    }
    assert {"file_path", "symbol", "code_fragment"} <= FACT_KINDS
    assert "tool_verified" in FACT_PROVENANCES


def test_hyphenated_file_reference_is_one_claim() -> None:
    facts = extract_claim_facts(
        "再运行一次 `python mutable-default.py`。",
        source="next_step",
    )

    assert [(fact.kind, fact.value) for fact in facts] == [
        ("file_path", "mutable-default.py"),
    ]


def test_multi_token_code_literal_keeps_significant_sub_tokens() -> None:
    """Variables / call paths survive; language keywords never become claims."""
    facts = extract_claim_facts("把 `hi = len(xs) - 1` 写进循环。", source="next_step")

    assert [(fact.kind, fact.value) for fact in facts] == [("symbol", "hi")]

    facts = extract_claim_facts(
        "用 `subprocess.run(cmd, check=True)` 执行，输出写到 `build-output.txt`。",
        source="next_step",
    )

    assert [(fact.kind, fact.value) for fact in facts] == [
        ("file_path", "build-output.txt"),
        ("symbol", "subprocess.run"),
    ]

    assert extract_claim_facts(
        "用 `for i, x in enumerate(xs)` 打印每个索引。",
        source="next_step",
    ) == []


def test_agent_evidence_carries_next_step_and_fallback_provenance() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-49",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        agent_evidence={
            "next_step": "给我 `parse_header()` 的函数名。",
            "fell_back": True,
            "request_id": "req-7",
        },
    )

    assert [fact.value for fact in facts.next_step_claims] == ["parse_header"]
    assert facts.request_id == "req-7"
    assert facts.memory_provenance["next_step"] == "local_fallback"
    assert facts.next_step_claims[0].provenance == "local_fallback"


def test_reply_claims_are_recorded_but_never_downgrade() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-50",
        reply_text="可以用 `enumerate` 直接在循环里拿到索引。",
        code_text="xs = [1, 2]\n",
        history_text="",
        user_message="",
        next_step_text="把观察到的输出贴回来。",
    )

    assert any(fact.value == "enumerate" for fact in facts.reply_claims)
    decision = evaluate_turn_grounding(facts)
    assert decision.grounded is True


def test_grounding_outcome_vocabulary() -> None:
    assert grounding_outcome(GroundingDecision(grounded=True)) == "grounded"
    assert (
        grounding_outcome(
            GroundingDecision(grounded=True, retry_used=True, corrected_next_step="x")
        )
        == "corrected"
    )
    assert (
        grounding_outcome(GroundingDecision(grounded=False, requires_confirmation=True))
        == "downgraded"
    )


# ---------------------------------------------------------------------------
# R2: reply claims, domain consistency, repeat-asking, creation instructions
# ---------------------------------------------------------------------------


def test_creation_instruction_never_trips_the_file_checker() -> None:
    def _all_missing(path: str) -> bool:
        return False

    facts = build_teaching_turn_facts(
        turn_id="turn-60",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text="新建 `debug_demo.py` 写一个最小复现。",
        workspace_evidence=WorkspaceEvidence(file_exists=_all_missing),
    )

    decision = evaluate_turn_grounding(facts)

    assert decision.grounded is True
    assert facts.verdicts == {"file_path:debug_demo.py": "unverifiable"}

    # A plain "look at this file" on a missing file still downgrades.
    facts = build_teaching_turn_facts(
        turn_id="turn-60",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text="查看 `legacy_report.py` 的第 10 行。",
        workspace_evidence=WorkspaceEvidence(file_exists=_all_missing),
    )
    assert evaluate_turn_grounding(facts).grounded is False


def test_repeat_asking_learner_provided_fact_is_ungrounded() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-61",
        reply_text="我们来定位。",
        code_text="def add_item(item, items=[]):\n    items.append(item)\n",
        history_text="",
        user_message="我把失败贴一下：AssertionError，函数叫 add_item。",
        next_step_text="把 `add_item` 的完整实现贴出来，我逐行看。",
    )

    decision = evaluate_turn_grounding(facts)

    assert decision.grounded is False
    assert decision.referenced_symbols == ["add_item"]
    assert decision.requires_confirmation is True


def test_demand_on_a_model_only_symbol_conflicts_and_downgrades() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-62",
        reply_text="你的 `parse_header` 函数里需要检查边界。\n\n下一步：把 `parse_header` 发我。",
        code_text="grid = [[0], [0]]\n",
        history_text="",
        user_message="",
        next_step_text="给我 `parse_header()` 的函数名和 call site。",
    )

    decision = evaluate_turn_grounding(facts)

    assert decision.grounded is False
    assert decision.referenced_symbols == ["parse_header"]
    assert [conflict.domain for conflict in facts.conflicts] == ["parse_header"]
    assert facts.conflicts[0].winner == "model_claim"
    assert facts.visible_next_step


def test_new_symbol_introduction_is_never_a_conflict() -> None:
    """Explicit false-positive budget: teaching a new symbol stays grounded."""
    facts = build_teaching_turn_facts(
        turn_id="turn-63",
        reply_text="可以用 `enumerate` 直接在循环里拿到索引。",
        code_text="xs = [1, 2]\n",
        history_text="",
        user_message="",
        next_step_text="用 `enumerate` 打印每个索引。",
    )

    decision = evaluate_turn_grounding(facts)

    assert decision.grounded is True
    assert facts.conflicts == []


def test_explanation_request_is_not_a_demand() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-64",
        reply_text="我们看 `find` 的边界。",
        code_text="def find(xs, target):\n    pass\n",
        history_text="",
        user_message="",
        next_step_text="给我讲讲 `find` 的边界思路。",
    )

    assert evaluate_turn_grounding(facts).grounded is True


def test_domain_backing_ranking() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-65",
        reply_text="",
        code_text="def add_item(item, items=[]):\n    pass\n",
        history_text="",
        user_message="",
        next_step_text="",
        workspace_evidence={"verified_facts": [{"kind": "symbol", "value": "load_dataset"}]},
    )

    assert domain_backing(facts, "add_item") == "learner_provided"
    assert domain_backing(facts, "load_dataset") == "workspace_verified"
    assert domain_backing(facts, "ghost_function") == ""


def test_reply_claim_verdicts_are_diagnostic_only() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-66",
        reply_text="把 `grid` 的行分开看，用 `independent_row` 创建。",
        code_text="grid = [[0], [0]]\n",
        history_text="",
        user_message="",
        next_step_text="再对 `grid` 做一次实验。",
    )

    decision = evaluate_turn_grounding(facts)

    assert decision.grounded is True
    assert facts.verdicts["symbol:grid"] == "grounded"
    assert facts.verdicts["symbol:independent_row"] == "ungrounded"


def test_memory_provenance_summary_carries_outcome_and_conflicts() -> None:
    facts = build_teaching_turn_facts(
        turn_id="turn-67",
        reply_text="你的 `parse_header` 函数里……",
        code_text="grid = 1\n",
        history_text="",
        user_message="",
        next_step_text="给我 `parse_header()` 的函数名。",
    )
    decision = evaluate_turn_grounding(facts)

    summary = memory_provenance_summary(facts, decision)

    assert summary["grounding_outcome"] == "downgraded"
    assert summary["conflicted_claims"] == "parse_header"
    assert summary["summary"] == "model_claim"


# ---------------------------------------------------------------------------
# R3: demand targeting, retry context, visible-next-step comparison
# ---------------------------------------------------------------------------


def test_run_and_paste_output_is_not_a_demand() -> None:
    """Running the learner's function and pasting its OUTPUT is normal
    debugging guidance; only a request that directly governs the symbol itself
    is repeat-asking (2026-10-13 review)."""
    code = "def find(xs, target):\n    return -1\n"

    assert next_step_is_grounded("运行 `find`，把输出贴回来。", "我们看看 find。", code) is True
    assert next_step_is_grounded("Run `find` and paste the output.", "Let's inspect find.", code) is True
    # The contrast case stays ungrounded: asking for the symbol's own content.
    assert next_step_is_grounded("把 `find` 的完整实现贴出来。", "我们看看。", code) is False
    assert (
        next_step_is_grounded("给我 `parse_header()` 的函数名和 call site。", "我们看看。", code)
        is False
    )


def test_retry_context_follows_the_regenerated_text() -> None:
    """A creation instruction offered as the correction keeps the §2.5⑥
    exemption (its context comes from the retried text, not the rejected one)."""
    facts = build_teaching_turn_facts(
        turn_id="turn-70",
        reply_text="",
        code_text="",
        history_text="",
        user_message="",
        next_step_text="给我 `parse_header()` 的函数名。",
        workspace_evidence=WorkspaceEvidence(file_exists=lambda path: False),
    )

    decision = evaluate_turn_grounding(
        facts,
        retry_generate=lambda: "新建 `debug_demo.py` 写一个最小复现。",
    )

    assert decision.grounded is True
    assert decision.retry_used is True
    assert decision.corrected_next_step == "新建 `debug_demo.py` 写一个最小复现。"
    assert decision.requires_confirmation is False
    assert facts.gate_outcome == "corrected"
    assert facts.next_step_text == "新建 `debug_demo.py` 写一个最小复现。"


def test_visible_next_step_corroboration_recorded_in_conflicts() -> None:
    """``visible_next_step`` participates: the conflict record says whether the
    reply's own stated next step mentioned the demanded domain."""
    corroborated = build_teaching_turn_facts(
        turn_id="turn-71",
        reply_text="你的 `parse_header` 函数里需要检查边界。\n\n下一步：把 `parse_header` 发我。",
        code_text="grid = 1\n",
        history_text="",
        user_message="",
        next_step_text="给我 `parse_header()` 的函数名。",
    )
    evaluate_turn_grounding(corroborated)
    assert [
        (conflict.domain, conflict.reply_step_corroborated)
        for conflict in corroborated.conflicts
    ] == [("parse_header", True)]

    body_only = build_teaching_turn_facts(
        turn_id="turn-72",
        reply_text="你的 `parse_header` 函数里需要检查边界。",
        code_text="grid = 1\n",
        history_text="",
        user_message="",
        next_step_text="给我 `parse_header()` 的函数名。",
    )
    evaluate_turn_grounding(body_only)
    assert [
        (conflict.domain, conflict.reply_step_corroborated)
        for conflict in body_only.conflicts
    ] == [("parse_header", False)]


# ---------------------------------------------------------------------------
# R2: field-level memory admission (MemoryService.record_turn_reflection)
# ---------------------------------------------------------------------------


def _memory_service(tmp_path: Path) -> MemoryService:
    return MemoryService(TrainerRepository(tmp_path / "admission.db"))


def _mastery_scores(service: MemoryService, workspace_id: str) -> dict[str, float]:
    return {
        key: record.score
        for key, record in service._structured_for(workspace_id)._mastery.items()
    }


def test_record_turn_reflection_downgrade_never_writes_the_step(tmp_path: Path) -> None:
    service = _memory_service(tmp_path)

    service.record_turn_reflection(
        workspace_id="workspace-admission-downgrade",
        session_id="session-admission",
        user_message="看报错",
        scenario="debug_loop",
        focus_area="binary-search",
        summary="我们定位了边界问题。",
        next_step="给我 `parse_header()` 的函数名。",
        memory_provenance={
            "grounding_outcome": "downgraded",
            "conflicted_claims": "parse_header",
            "summary": "model_claim",
            "next_step": "model_claim",
            "focus": "model_claim",
        },
    )

    snapshot = service.snapshot("workspace-admission-downgrade")
    workspace = snapshot.workspace
    assert workspace.get("latest_coach_next_step") == ""
    assert workspace.get("latest_turn_next_step") == ""
    assert (workspace.get("active_thread") or {}).get("next_step") == ""
    assert workspace.get("latest_coach_grounding_outcome") == "downgraded"
    assert workspace.get("latest_coach_provenance") == {
        "summary": "model_claim",
        "next_step": "model_claim",
        "focus": "model_claim",
    }
    assert _mastery_scores(service, "workspace-admission-downgrade") == {}


def test_record_turn_reflection_mastery_requires_fact_backing(tmp_path: Path) -> None:
    service = _memory_service(tmp_path)

    service.record_turn_reflection(
        workspace_id="workspace-admission-mastery",
        session_id="session-admission",
        user_message="看报错",
        scenario="debug_loop",
        focus_area="binary-search",
        summary="定位了边界问题。",
        next_step="再对 `grid` 做一次实验。",
        memory_provenance={
            "grounding_outcome": "grounded",
            "summary": "model_claim",
            "next_step": "model_claim",
            "focus": "learner_provided",
        },
    )
    mastery = _mastery_scores(service, "workspace-admission-mastery")
    assert mastery["binary-search"] > 0
    assert mastery["binary-search:next-step"] > 0

    service.record_turn_reflection(
        workspace_id="workspace-admission-model-claim",
        session_id="session-admission",
        user_message="看报错",
        scenario="debug_loop",
        focus_area="binary-search",
        summary="定位了边界问题。",
        next_step="再对 `grid` 做一次实验。",
        memory_provenance={
            "grounding_outcome": "grounded",
            "summary": "model_claim",
            "next_step": "model_claim",
            "focus": "model_claim",
        },
    )
    # DESIGN.md §2.7: a pure model-claim focus never advances mastery.
    assert _mastery_scores(service, "workspace-admission-model-claim") == {}


def test_record_turn_reflection_local_fallback_writes_no_focus(tmp_path: Path) -> None:
    service = _memory_service(tmp_path)

    service.record_turn_reflection(
        workspace_id="workspace-admission-fallback",
        session_id="session-admission",
        user_message="看报错",
        scenario="debug_loop",
        focus_area="binary-search",
        summary="s",
        next_step="n",
        memory_provenance={
            "grounding_outcome": "recovery_override",
            "summary": "local_fallback",
            "next_step": "local_fallback",
            "focus": "local_fallback",
        },
    )

    snapshot = service.snapshot("workspace-admission-fallback")
    assert snapshot.workspace.get("latest_coach_focus_area") == ""
    assert snapshot.workspace.get("latest_turn_focus_area") == ""
    assert _mastery_scores(service, "workspace-admission-fallback") == {}


def test_record_turn_reflection_strips_conflicted_claims(tmp_path: Path) -> None:
    service = _memory_service(tmp_path)

    service.record_turn_reflection(
        workspace_id="workspace-admission-strip",
        session_id="session-admission",
        user_message="看报错",
        scenario="debug_loop",
        focus_area="lesson",
        summary="你定义了 parse_header 并完成了检查。",
        next_step="打开 lesson.py。",
        memory_provenance={
            "grounding_outcome": "downgraded",
            "conflicted_claims": "parse_header",
            "summary": "model_claim",
            "next_step": "model_claim",
            "focus": "learner_provided",
        },
    )

    snapshot = service.snapshot("workspace-admission-strip")
    summary = str(snapshot.workspace.get("latest_coach_summary") or "")
    assert "parse_header" not in summary
    assert "你定义了" in summary
    # A model-claim summary never raises the verified result (§2.7).
    assert snapshot.workspace.get("latest_turn_verified_result") == ""


def test_record_turn_reflection_without_provenance_keeps_legacy_behaviour(
    tmp_path: Path,
) -> None:
    service = _memory_service(tmp_path)

    service.record_turn_reflection(
        workspace_id="workspace-admission-legacy",
        session_id="session-admission",
        user_message="看报错",
        scenario="debug_loop",
        focus_area="legacy-focus",
        summary="这次通过了。",
        next_step="下一步继续。",
    )

    snapshot = service.snapshot("workspace-admission-legacy")
    assert snapshot.workspace.get("latest_coach_next_step") == "下一步继续。"
    assert snapshot.workspace.get("latest_turn_verified_result") == "这次通过了。"
    assert _mastery_scores(service, "workspace-admission-legacy")["legacy-focus"] > 0


def test_memory_provenance_summary_feeds_record_turn_reflection(tmp_path: Path) -> None:
    """The two halves of the §2.6 interface compose end to end."""
    facts = build_teaching_turn_facts(
        turn_id="turn-68",
        reply_text="你的 `parse_header` 函数里……",
        code_text="grid = 1\n",
        history_text="",
        user_message="看报错",
        next_step_text="给我 `parse_header()` 的函数名。",
    )
    decision = evaluate_turn_grounding(facts)
    service = _memory_service(tmp_path)

    service.record_turn_reflection(
        workspace_id="workspace-admission-interface",
        session_id="session-admission",
        user_message="看报错",
        scenario="debug_loop",
        focus_area="parse_header",
        summary="我们核对 parse_header。",
        next_step=str(facts.next_step_text),
        memory_provenance=memory_provenance_summary(facts, decision),
    )

    snapshot = service.snapshot("workspace-admission-interface")
    assert snapshot.workspace.get("latest_coach_next_step") == ""
    assert snapshot.workspace.get("latest_coach_grounding_outcome") == "downgraded"
    assert "parse_header" not in str(snapshot.workspace.get("latest_coach_summary") or "")


# ---------------------------------------------------------------------------
# Assembly path: scripted provider double as the coach_finalize author
# ---------------------------------------------------------------------------


def _provider_payload() -> dict[str, object]:
    return {
        "name": "scripted-grounding",
        "base_url": "https://provider.invalid/v1",
        "api_key_ref": "test-only",
        "model": "scripted-model",
        "protocol": "openai_chat_completions",
        "capabilities": {"tools": True, "streaming": False},
    }


GRID_FILE = {
    "path": "lesson.py",
    "language_id": "python",
    "content": "grid = [[0], [0]]\ngrid[0].append(1)\nprint(grid)\n",
}


class _ScriptedFinalizeProvider:
    """One coach_finalize call whose next_step is configurable."""

    protocol = "openai_chat_completions"

    def __init__(self, next_step: str) -> None:
        self.next_step = next_step
        self.calls = 0
        self.attachments_will_be_sent = lambda: False

    async def call(
        self,
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        self.calls += 1
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "finalize-grounding",
                    "name": "coach_finalize",
                    "arguments": {
                        "summary": (
                            "两行共享同一个内层列表引用，`grid[0] is grid[1]` 为 True；"
                            "用列表推导式创建独立行即可修复。"
                        ),
                        "next_step": self.next_step,
                    },
                }
            ],
        }

    async def call_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ):
        response = await self.call(messages, tools)
        yield {
            "type": "final",
            "content": response["content"],
            "tool_calls": response["tool_calls"],
            "stop_reason": "tool_calls" if response["tool_calls"] else "stop",
        }


def _start_session(client: Any, workspace_id: str, tmp_path: Path) -> str:
    started = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": "Turn grounding",
            "workspace_path": str(tmp_path / "learner-project"),
        },
    )
    assert started.status_code == 200, started.text
    return str(started.json()["session_id"])


def _turn_payload(session_id: str, workspace_id: str, message: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "intent": "coach",
        "message": message,
        "response_language": "zh-CN",
        "answer_mode": "guided",
        "use_agent_loop": True,
        "provider": _provider_payload(),
        "api_key": "test-only-key",
        "current_file": GRID_FILE,
    }


def _run_scripted_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspace_id: str,
    next_step: str,
    *,
    learner_message: str = "为什么修改 `grid[0]` 之后 `grid[1]` 也变了？",
    current_file: dict[str, object] | None = None,
) -> dict[str, Any]:
    scripted = _ScriptedFinalizeProvider(next_step)

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path / "sidecar", configure_provider=False) as client:
        runtime = client.app.state.runtime
        seed_verified_capabilities(
            runtime,
            ProviderConfig.model_validate(_provider_payload()),
            "test-only-key",
        )
        session_id = _start_session(client, workspace_id, tmp_path)
        payload = _turn_payload(session_id, workspace_id, learner_message)
        if current_file is not None:
            payload["current_file"] = current_file
        response = client.post("/turn", json=payload)
        assert response.status_code == 200, response.text
        return dict(response.json())


def test_turn_downgrades_ungrounded_next_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 03: fabricated function demand is flagged, never plan-ready."""
    body = _run_scripted_turn(
        tmp_path,
        monkeypatch,
        "workspace-grounding-ungrounded",
        "给我 `parse_header()` 的函数名和 call site，我帮你逐行看。",
    )

    coach_turn = body.get("coach_turn")
    assert isinstance(coach_turn, dict)
    assert coach_turn.get("requires_confirmation") is True
    agent_meta = body.get("agent_meta") or {}
    assert agent_meta.get("next_step_requires_confirmation") is True
    # The ungrounded demand must not leak into persisted thread memory.
    active_thread = (body.get("snapshot", {}).get("memory", {}) or {}).get("active_thread") or {}
    assert "parse_header" not in str(active_thread)


def test_turn_keeps_grounded_next_step_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grounded_step = "再对 `grid` 做一次独立行实验，确认两行打印互不影响。"
    body = _run_scripted_turn(
        tmp_path,
        monkeypatch,
        "workspace-grounding-grounded",
        grounded_step,
    )

    coach_turn = body.get("coach_turn")
    assert isinstance(coach_turn, dict)
    assert coach_turn.get("requires_confirmation") is False
    assert coach_turn.get("next_step") == grounded_step
    agent_meta = body.get("agent_meta") or {}
    assert not agent_meta.get("next_step_requires_confirmation")


def test_turn_narration_message_never_becomes_coach_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real-harness leak: a /turn whose first clause is narration ("我的脚本
    assert 失败了") must not persist the message prefix as memory.coach_anchor
    — the anchor falls back to the grounded current-file topic label."""
    narration_message = "我的脚本 assert 失败了，第二个 assert 报 items 是 [1, 2]。为什么会这样？"
    grounded_step = "再运行一次 `python mutable-default.py`，确认两个 assert 都通过。"
    body = _run_scripted_turn(
        tmp_path,
        monkeypatch,
        "workspace-narration-anchor",
        grounded_step,
        learner_message=narration_message,
        current_file={
            "path": "mutable-default.py",
            "language_id": "python",
            "content": (
                "def add_item(item, items=[]):\n"
                "    items.append(item)\n"
                "    return items\n\n"
                "assert add_item(1) == [1]\n"
                "assert add_item(2) == [2]\n"
            ),
        },
    )

    memory = body.get("snapshot", {}).get("memory", {}) or {}
    anchor = str(memory.get("coach_anchor") or "")
    focus = str(memory.get("current_focus") or "")
    workspace = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    focus_area = str(
        workspace.get("latest_coach_focus_area")
        or workspace.get("latest_turn_focus_area")
        or ""
    )
    thread = memory.get("active_thread") or {}

    assert "我的脚本 assert 失败了" not in anchor
    assert "我的脚本 assert 失败了" not in focus
    assert "我的脚本 assert 失败了" not in focus_area
    assert "我的脚本 assert 失败了" not in str(thread.get("focus_area") or "")
    # The anchor falls back to the grounded file/topic label, not empty.
    assert anchor.strip()
    assert "mutable-default" in anchor
