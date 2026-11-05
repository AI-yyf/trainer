"""P1 Skills 深化验收 — agent 运行时自动选择已激活技能 + 执行结果回流.

外部评估 P1 "升级为真实 Skills 体系" 的剩余面:
- 条件触发: SKILL.md front-matter trigger 匹配, 仅 active 技能, 渐进加载 body
- 权限约束: 注入块不扩权 (工具权限/workspace 写规则保持原样)
- 执行结果回流: 回合后 registry 使用统计 + memory 会话高亮
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.llm.provider_service import ProviderService
from app.skills.registry import SkillRegistry
from app.skills.runtime import (
    build_skill_guidance_block,
    record_skill_usage,
    select_active_skills,
)
from tests.test_api import build_client

SKILL_MD = """---
name: arch-explorer
description: Understand a GitHub project's architecture and key modules
permissions: read:workspace, search:resources
triggers: architecture, 架构, module map
---

# Arch Explorer

Read the project tree first, then locate key symbols with list_project_modules
before answering architecture questions.
"""

OTHER_SKILL_MD = """---
name: debug-coach
description: Coach a minimal debug loop with breakpoints
permissions: read:workspace
triggers: breakpoint, debugging
---

# Debug Coach

One breakpoint, one observable value.
"""


def _make_registry(tmp_path: Path, *, activate_arch: bool = True) -> SkillRegistry:
    tmp_path.mkdir(parents=True, exist_ok=True)
    registry = SkillRegistry(tmp_path / "skills")
    arch_md = tmp_path / "arch-explorer.md"
    arch_md.write_text(SKILL_MD, encoding="utf-8")
    debug_md = tmp_path / "debug-coach.md"
    debug_md.write_text(OTHER_SKILL_MD, encoding="utf-8")
    registry.register_from_skill_md(arch_md, kind="knowledge", reviewed=True)
    registry.register_from_skill_md(debug_md, kind="tutor", reviewed=True)
    if activate_arch:
        registry.activate("arch-explorer")
    registry.activate("debug-coach")
    return registry


def test_selection_matches_trigger_only_for_active_skills(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path, activate_arch=False)

    # arch-explorer is registered but NOT active: never selected.
    selected = select_active_skills(registry, "help me review the architecture of this repo")
    assert [s.skill_id for s in selected] == ["debug-coach"] or selected == []

    registry.activate("arch-explorer")
    selected = select_active_skills(registry, "help me review the architecture of this repo")
    assert [s.skill_id for s in selected] == ["arch-explorer"]
    assert "architecture" in selected[0].matched_terms
    # Progressive loading: the SKILL.md body arrives with the selection.
    assert "list_project_modules" in selected[0].body


def test_selection_prefers_trigger_match_and_limits_results(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    selected = select_active_skills(registry, "帮我画一张 architecture module map，先讲 breakpoint 调试")
    assert selected, "expected at least one match"
    # Trigger match (100+) ranks above plain description-token overlap.
    assert selected[0].skill_id == "arch-explorer"
    assert len(selected) <= 2


def test_selection_empty_when_nothing_matches(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    assert select_active_skills(registry, "how do I boil an egg?") == []
    assert select_active_skills(registry, "") == []


def test_guidance_block_never_expands_tool_authority(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    selected = select_active_skills(registry, "review the architecture please")
    block = build_skill_guidance_block(selected)
    assert "### Skill: arch-explorer" in block
    assert "list_project_modules" in block
    assert "never expand your tool authority" in block
    assert "workspace write/read rules apply exactly as before" in block
    # The declared permission line is explicitly marked informational.
    assert "(informational only)" in block


def test_record_skill_usage_updates_registry_and_memory(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    highlights: list[tuple[str, str]] = []

    class FakeMemory:
        def add_session_highlight(self, session_id: str, highlight: str) -> None:
            highlights.append((session_id, highlight))

    runtime = SimpleNamespace(skill_registry=registry, memory_service=FakeMemory())
    selected = select_active_skills(registry, "review the architecture please")
    # The message matches the trigger skill only — debug-coach stays dormant.
    assert [s.skill_id for s in selected] == ["arch-explorer"]

    usages = record_skill_usage(
        runtime,
        "ws-usage",
        "session-usage",
        selected,
        stop_reason="completed",
        final_content="Following arch-explorer, read the module map first.",
    )
    assert [u["skill_id"] for u in usages] == ["arch-explorer"]
    assert usages[0]["applied"] is True

    record_payload = registry._skills["arch-explorer"].metadata
    assert record_payload["usage_count"] == 1
    assert record_payload["applied_count"] == 1
    assert record_payload["last_applied"] is True
    assert record_payload["last_used_workspace"] == "ws-usage"
    assert highlights and highlights[0][0] == "session-usage"
    assert "Skill applied: arch-explorer" in highlights[0][1]

    # "provided" branch: a selected skill the final content never mentions.
    from app.skills.runtime import SelectedSkill

    dormant = SelectedSkill(
        skill_id="arch-explorer",
        name="arch-explorer",
        kind="knowledge",
        permissions=[],
        body="",
    )
    usages = record_skill_usage(
        runtime,
        "ws-usage",
        "session-usage-2",
        [dormant],
        stop_reason="completed",
        final_content="A reply that never mentions the skill.",
    )
    assert usages[0]["applied"] is False
    meta = registry._skills["arch-explorer"].metadata
    assert meta["usage_count"] == 2
    assert meta["applied_count"] == 1
    assert any("Skill provided: arch-explorer" in h for _, h in highlights)


def _patched_agent_provider():
    """Scripted agent provider capturing the messages it receives."""

    captured: dict[str, object] = {"calls": []}

    class FakeAgentProvider:
        def __init__(self, protocol: str) -> None:
            self.protocol = protocol

        async def call(self, messages, tools):
            captured["calls"] = {"messages": messages, "tools": tools or []}  # type: ignore[assignment]
            return {
                "content": (
                    "Following arch-explorer: read the module map first, then one symbol. "
                    "learn first, then verify one step."
                ),
                "tool_calls": [],
            }

        async def call_stream(self, messages, tools):  # type: ignore[no-untyped-def]
            result = await self.call(messages, tools)
            yield {
                "type": "final",
                "content": result["content"],
                "tool_calls": [],
                "stop_reason": "stop",
            }

    def fake_build(self: ProviderService, **kwargs: object):
        protocol = str(kwargs.get("protocol") or getattr(self._config, "protocol", ""))  # noqa: SL001
        provider = FakeAgentProvider(protocol)
        return provider, provider

    return captured, fake_build


def test_agentic_turn_injects_selected_skill_and_records_usage(tmp_path: Path) -> None:
    from unittest.mock import patch

    from provider_fixtures import seed_verified_capabilities

    from app.core.models import ProviderConfig
    from app.llm.provider_service import ProviderService as PS

    captured, fake_build = _patched_agent_provider()
    workspace_id = "workspace-skill-runtime"

    with build_client(tmp_path, configure_provider=False) as client:
        runtime = client.app.state.runtime
        runtime.skill_registry = _make_registry(tmp_path / "e2e-skills")
        provider = ProviderConfig(
            name="skill-runtime-provider",
            base_url="http://skill-runtime.test",
            api_key_ref="trainer.skill.runtime",
            model="MiniMax-M3",
            protocol="openai_chat_completions_compatible",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = PS(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        seed_verified_capabilities(runtime, provider, "sk-test", tools=True)
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
            },
        )
        assert start.status_code == 200, start.text
        session_id = start.json()["session_id"]

        with patch.object(
            ProviderService,
            "_build_agent_provider_with_budget",
            autospec=True,
            side_effect=fake_build,
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "coach",
                    "message": "Walk me through the architecture of this project.",
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
        assert response.status_code == 200, response.text

        messages = captured["calls"]["messages"]
        assert isinstance(messages, list) and messages
        system_texts = [
            str(m.get("content") or "") for m in messages if m.get("role") == "system"
        ]
        assert any(
            "### Skill: arch-explorer" in text and "never expand your tool authority" in text
            for text in system_texts
        ), "selected skill guidance must reach the agent as a system message"

        # 执行结果回流: registry usage stats persisted by the turn itself.
        record = runtime.skill_registry._skills["arch-explorer"].metadata
        assert record["usage_count"] == 1
        assert record["last_used_workspace"] == workspace_id
        assert record["last_used_session"] == session_id
