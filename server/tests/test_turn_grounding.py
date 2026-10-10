"""Teaching-turn fact grounding (TeachingTurn fact object, first slice).

Covers the 2026-10-08 real-teaching-quality failures:

- a structured ``coach_turn.next_step`` that demands code symbols appearing
  nowhere in the reply/code must be detected and downgraded to
  ``requires_confirmation`` (case 03: "给我函数名/call site" for a file with no
  function);
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
    evaluate_next_step_grounding,
    extract_code_symbols,
    grounding_correction_instruction,
    is_verbatim_message_prefix,
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


def test_no_retry_hook_downgrades_immediately() -> None:
    decision = evaluate_next_step_grounding(
        "给我 `parse_header()` 的函数名。",
        "内层列表是同一个引用。",
        "grid = [[0] * 2]\n",
    )

    assert decision.grounded is False
    assert decision.retry_used is False
    assert decision.requires_confirmation is True


def test_correction_instruction_mentions_grounding_rule() -> None:
    chinese = grounding_correction_instruction("zh-CN")
    english = grounding_correction_instruction("en-US")

    assert "真实存在" in chinese
    assert "函数名" in chinese
    assert "really exist" in english


# ---------------------------------------------------------------------------
# Memory anchor anti-drift
# ---------------------------------------------------------------------------


def test_message_prefix_is_never_a_valid_anchor() -> None:
    assert is_verbatim_message_prefix("我亲自写了下面的修改", MESSAGE_PREFIX) is True
    assert is_verbatim_message_prefix("mutable default arguments", MESSAGE_PREFIX) is False
    # Short overlaps and identifier-like anchors stay valid technical facts.
    assert is_verbatim_message_prefix("lesson.py", "lesson.py 里的断言为什么失败") is False
    assert is_verbatim_message_prefix("", MESSAGE_PREFIX) is False


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
