"""Phase 3 — 统一 Skill 生命周期验收 (版本 / 失败恢复 / 单一状态源).

失败优先：此前 SkillRecord 无版本、无失败恢复状态；turn 失败只影响 return
값，技能本身永不进入 failing/quarantined，/skill/list 也没有版本与恢复语义。
现在：
- version 随内容变化递增并持久化；
- 连续失败入 streak (failing)，达阈值 quarantined 且选择器停止注入；
- /skill/retry 可重试恢复；成功执行自动清零；
- /skill/list 与 agent 选择读同一 registry 与同一 to_payload 序列化。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.skills.registry import MAX_CONSECUTIVE_FAILURES, SkillRegistry
from app.skills.runtime import record_skill_usage, select_active_skills


def test_version_increments_on_content_change_and_survives_restart(tmp_path: Path) -> None:
    dir_path = tmp_path / "skills"
    registry = SkillRegistry(dir_path)
    first = registry.register(
        skill_id="versioned", kind="knowledge", name="Versioned", description="v1"
    )
    assert first.version == 1

    same = registry.register(
        skill_id="versioned", kind="knowledge", name="Versioned", description="v1"
    )
    assert same.version == 1, "re-registering identical content must not bump"

    changed = registry.register(
        skill_id="versioned", kind="knowledge", name="Versioned", description="v2"
    )
    assert changed.version == 2

    reloaded = SkillRegistry(dir_path)
    record = reloaded._skills["versioned"]
    assert record.version == 2
    assert record.to_payload()["version"] == 2


def test_selection_without_application_does_not_clear_failure_streak(
    tmp_path: Path,
) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(
        skill_id="unused", kind="knowledge", name="Unused", description="state flow"
    )
    registry.activate("unused")
    registry.record_failure("unused", error="turn failed: provider_error")
    registry.record_failure("unused", error="turn failed: provider_error")

    record = registry.record_usage("unused", applied=False)
    metadata = record.to_payload()["metadata"]
    assert metadata["consecutive_failures"] == 2
    assert record.to_payload()["status"] == "failing"

    recovered = registry.record_usage("unused", applied=True)
    assert recovered.to_payload()["metadata"]["consecutive_failures"] == 0
    assert recovered.to_payload()["status"] == "ready"


def test_failures_quarantine_then_retry_recovers(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(
        skill_id="flaky", kind="knowledge", name="Flaky", description="state flow"
    )
    registry.activate("flaky")

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        registry.record_failure("flaky", error="turn failed: provider_error")

    payload = next(item for item in registry.to_payload() if item["skill_id"] == "flaky")
    assert payload["status"] == "quarantined"
    assert payload["failure_count"] == MAX_CONSECUTIVE_FAILURES
    assert payload["retryable"] is False
    assert payload["last_error"]

    # Quarantined skills disappear from the agent selection (same registry).
    selected_after_quarantine = select_active_skills(registry, "wombat calculus")
    assert all(skill.skill_id != "flaky" for skill in selected_after_quarantine)

    retried = registry.retry("flaky")
    retried_payload = retried.to_payload()
    assert retried_payload["status"] == "ready"
    assert retried_payload["failure_count"] == 0
    assert retried_payload["retryable"] is False  # nothing to retry when healthy
    assert any(
        skill.skill_id == "flaky"
        for skill in select_active_skills(registry, "explain the state flow")
    )


def test_successful_usage_clears_failure_streak(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(
        skill_id="recovering", kind="knowledge", name="Recovering", description="wombat calculus"
    )
    registry.activate("recovering")
    registry.record_failure("recovering", error="turn failed: timeout")
    assert registry._skills["recovering"].status() == "failing"

    runtime = SimpleNamespace(skill_registry=registry)
    selected = select_active_skills(registry, "wombat calculus")
    usages = record_skill_usage(
        runtime,
        "ws",
        "session",
        selected,
        stop_reason="completed",
        final_content="recovering 缺口出现了，先看状态。",
    )
    assert usages and usages[0].get("applied") is True
    assert registry._skills["recovering"].status() == "ready"
    assert registry._skills["recovering"].failure_streak == 0


def test_failed_turn_records_failure_for_selected_skills(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(
        skill_id="turn-fail", kind="knowledge", name="Turn Fail", description="wombat calculus"
    )
    registry.activate("turn-fail")
    runtime = SimpleNamespace(skill_registry=registry)
    selected = select_active_skills(registry, "wombat calculus")

    usages = record_skill_usage(
        runtime, "ws", "session", selected, stop_reason="provider_error", final_content=""
    )
    assert usages and usages[0]["failed"] is True
    record = registry._skills["turn-fail"]
    assert record.failure_streak == 1
    assert record.status() == "failing"


def test_list_payload_and_selection_share_one_state_source(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(skill_id="shared", kind="knowledge", name="Shared", description="wombat calculus")
    registry.activate("shared")
    # review_stale calculated inside to_payload (the /skill/list serialization).
    payload = next(item for item in registry.to_payload() if item["skill_id"] == "shared")
    assert payload["status"] == "ready"
    assert payload["version"] == 1
    # Selection uses the same record object the list serialized.
    selected_ids = [s.skill_id for s in select_active_skills(registry, "wombat calculus")]
    assert "shared" in selected_ids
    registry.record_failure("shared", error="boom")
    payload = next(item for item in registry.to_payload() if item["skill_id"] == "shared")
    assert payload["status"] == "failing"
    assert payload["retryable"] is True
