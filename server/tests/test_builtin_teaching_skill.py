"""v1.5 — 内化 RethinkFun 状态流讲解法为内置教学能力 (builtin tutor skill + prompt contract)."""

from __future__ import annotations

from pathlib import Path

from app.skills.registry import SkillRegistry
from app.skills.runtime import build_skill_guidance_block, select_active_skills


def test_builtin_lecture_skill_is_seeded_active_and_reviewed(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    skill = registry._skills["rethinkfun-lecture"]
    assert skill.kind == "tutor"
    assert skill.active is True
    assert skill.reviewed is True
    assert skill.metadata["origin"] == "builtin"
    # The body carries the state-flow contract, not a definition dump.
    assert "状态流" in skill.body
    assert "缺口" in skill.body
    assert "公式晚出现" in skill.body
    assert "禁止" in skill.body and "代入即得" in skill.body
    assert len(skill.body) <= 1300  # stays within runtime injection budget


def test_builtin_seed_is_idempotent_and_never_overrides_user_records(tmp_path: Path) -> None:
    dir_path = tmp_path / "skills"
    first = SkillRegistry(dir_path)
    assert sum(1 for s in first.list_skills() if s.skill_id == "rethinkfun-lecture") == 1

    second = SkillRegistry(dir_path)
    assert sum(1 for s in second.list_skills() if s.skill_id == "rethinkfun-lecture") == 1

    # A user-created record with the same id must survive a reseed untouched.
    second._skills["rethinkfun-lecture"].body = "user override"
    second._persist()
    third = SkillRegistry(dir_path)
    assert third._skills["rethinkfun-lecture"].body == "user override"


def test_builtin_skill_selected_by_lecture_triggers(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")

    selected = select_active_skills(registry, "请彻底讲明白 Python 生成器的惰性求值")
    assert [s.skill_id for s in selected] == ["rethinkfun-lecture"]
    assert any(term in selected[0].matched_terms for term in ("讲明白", "彻底讲"))
    assert "状态流" in selected[0].body

    english = select_active_skills(registry, "give me a deep lecture on diffusion models")
    assert [s.skill_id for s in english] == ["rethinkfun-lecture"]

    # Ordinary bounded questions do not pull in the lecture contract.
    assert select_active_skills(registry, "what does this error mean?") == []


def test_builtin_guidance_block_keeps_tool_authority_neutral(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    selected = select_active_skills(registry, "好好讲讲状态管理")
    block = build_skill_guidance_block(selected)
    assert "### Skill: RethinkFun 讲解法" in block
    assert "缺口" in block
    assert "never expand your tool authority" in block


def test_coach_system_prompt_carries_deep_explanation_contract() -> None:
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_system_prompt

    prompt = build_coaching_system_prompt(
        profile=UserProfile(long_term_goal="learn state flow", weekly_hours=4),
        current_file=None,
        response_language="zh-CN",
    )
    assert "state-flow lecture contract" in prompt
    assert "old approach's failure" in prompt
    assert "formulas appear late" in prompt
    assert "3-5 steps" in prompt
    assert "at least one contrast case" in prompt
    assert "minimal working example" in prompt
    assert "never pad with \"obviously\"" in prompt


def test_applied_is_evidence_driven_not_name_substring(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from app.skills.runtime import record_skill_usage

    registry = SkillRegistry(tmp_path / "skills")
    highlights: list[str] = []

    class FakeMemory:
        def add_session_highlight(self, session_id: str, highlight: str) -> None:
            highlights.append(highlight)

    runtime = SimpleNamespace(skill_registry=registry, memory_service=FakeMemory())
    selected = select_active_skills(registry, "彻底讲明白 Python 生成器")

    # A real state-flow lecture that never names the skill still counts as
    # applied: the contract markers are the evidence (v1.5 replacement for the
    # old display-name substring guess).
    lecture = (
        "先看旧方案的失败：readlines() 把整个文件装进内存。"
        "缺口出现了：文件大到装不下。为了补这个缺口，我们需要一个对象，"
        "它一次只产出一个值。状态因此推进了。"
    )
    usages = record_skill_usage(
        runtime,
        "ws-evi",
        "session-evi",
        selected,
        stop_reason="completed",
        final_content=lecture,
    )
    assert usages[0]["applied"] is True
    assert usages[0]["evidence"]["basis"] == "contract_markers"
    assert usages[0]["evidence"]["cited"] is False
    meta = registry._skills["rethinkfun-lecture"].metadata
    assert meta["last_applied"] is True
    assert meta["last_evidence"]["basis"] == "contract_markers"

    # A reply that drifts to an unrelated lane (no markers, no citation) is
    # only "provided", never "applied".
    drift = "先把工作区落点说清楚：告诉我当前工作区是 SSH 还是 local。"
    usages = record_skill_usage(
        runtime,
        "ws-evi",
        "session-evi",
        selected,
        stop_reason="completed",
        final_content=drift,
    )
    assert usages[0]["applied"] is False
    assert usages[0]["evidence"]["basis"] == "contract_markers"
    assert len(usages[0]["evidence"]["markers_hit"]) < 3


def test_action_skill_applied_requires_declared_tool_execution(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from app.skills.runtime import SelectedSkill, record_skill_usage

    registry = SkillRegistry(tmp_path / "skills")
    registry.register(
        skill_id="graph-builder",
        kind="action",
        name="Graph Builder",
        description="Build a call graph",
        reviewed=True,
        metadata={"front_matter": {"tools": "list_project_modules, read_project_symbol"}},
    )
    runtime = SimpleNamespace(skill_registry=registry)
    selected = [
        SelectedSkill(
            skill_id="graph-builder",
            name="Graph Builder",
            kind="action",
            permissions=["read:workspace"],
            body="build graph",
        )
    ]

    without_tool = record_skill_usage(
        runtime, "ws", "s", selected, final_content="done", tool_events=[]
    )
    assert without_tool[0]["applied"] is False
    assert without_tool[0]["evidence"]["basis"] == "tool_execution"

    with_tool = record_skill_usage(
        runtime,
        "ws",
        "s",
        selected,
        final_content="done",
        tool_events=[{"name": "list_project_modules"}],
    )
    assert with_tool[0]["applied"] is True
    assert with_tool[0]["evidence"]["tools_hit"] == ["list_project_modules"]
