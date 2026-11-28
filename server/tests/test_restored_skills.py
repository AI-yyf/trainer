"""(u) Skills: the skill lifecycle is versioned, workspace-scoped and recoverable.

Guarantees covered:
  * registry, runtime, drafts and lifecycle transitions follow a single source of truth;
  * a skill from one workspace is never activated in another;
  * failing skills recover explicitly instead of silently disappearing.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_skill_registry.py
  * server/tests/test_skill_workspace_scope.py
  * server/tests/test_skill_lifecycle.py
  * server/tests/test_skill_draft.py
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.skills.registry import MAX_CONSECUTIVE_FAILURES, SkillRegistry, parse_skill_md
from app.skills.runtime import build_skill_guidance_block, record_skill_usage, select_active_skills

# ---------------------------------------------------------------------------
# Restored from test_skill_registry.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


SKILL_MD = """---
name: project-explorer
description: Understand a GitHub project's architecture and key modules
permissions: read:workspace, search:resources
---

# Project Explorer

Read the project tree first, then locate key symbols.
"""


def test_register_and_list() -> None:
    registry = SkillRegistry(Path(tmp_dir()))
    registry.register(
        skill_id="test-tutor",
        kind="tutor",
        name="Test Tutor",
        description="A tutor skill for testing.",
    )
    skills = [s for s in registry.list_skills() if s.skill_id == "test-tutor"]
    assert len(skills) == 1
    assert skills[0].kind == "tutor"
    assert skills[0].name == "Test Tutor"


def test_register_rejects_invalid_kind() -> None:
    registry = SkillRegistry(Path(tmp_dir()))
    with pytest.raises(ValueError, match="Invalid skill kind"):
        registry.register(skill_id="x", kind="invalid", name="X")


def test_activate_and_deactivate() -> None:
    registry = SkillRegistry(Path(tmp_dir()))
    registry.register(
        skill_id="kw-1", kind="knowledge", name="Know How",
        description="Project knowledge.",
    )
    record = registry.activate("kw-1")
    assert record.active is True
    record = registry.deactivate("kw-1")
    assert record.active is False


def test_action_skill_requires_review_before_activation() -> None:
    registry = SkillRegistry(Path(tmp_dir()))
    registry.register(
        skill_id="action-1", kind="action", name="Refactor",
        description="Rewrites source files.",
        permissions=["write:workspace"],
    )
    with pytest.raises(ValueError, match="not been reviewed"):
        registry.activate("action-1")
    # After marking as reviewed, activation succeeds.
    registry._skills["action-1"].reviewed = True
    record = registry.activate("action-1")
    assert record.active is True


def test_skill_md_progressive_loading(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(SKILL_MD, encoding="utf-8")
    front, body = parse_skill_md(skill_file)
    assert front["name"] == "project-explorer"
    assert "permissions" in front
    assert "Project Explorer" in body

    registry = SkillRegistry(tmp_path / "skills")
    registry.register_from_skill_md(skill_file, kind="knowledge", reviewed=True)
    record = registry.activate("project-explorer")
    assert record.active is True
    assert "symbol" in record.body  # body loaded on activation


def test_persistence_across_instances(tmp_path: Path) -> None:
    dir_path = tmp_path / "skills"
    registry = SkillRegistry(dir_path)
    registry.register(skill_id="persist-1", kind="knowledge", name="Persisted")
    registry.activate("persist-1")

    # A new instance should see the persisted skill.
    registry2 = SkillRegistry(dir_path)
    assert any(s.skill_id == "persist-1" for s in registry2.list_skills())


def tmp_dir() -> Path:
    import tempfile
    return Path(tempfile.mkdtemp())


def test_action_skill_cannot_be_pre_approved_at_registration(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    record = registry.register(
        skill_id="sneaky-action",
        kind="action",
        name="Sneaky",
        reviewed=True,
        permissions=["write:workspace"],
    )
    assert record.reviewed is False
    with pytest.raises(ValueError, match="not been reviewed"):
        registry.activate("sneaky-action")
    # Non-action kinds keep their explicit reviewed flag (read-only guidance).
    knowledge = registry.register(
        skill_id="ok-knowledge", kind="knowledge", name="OK", reviewed=True
    )
    assert knowledge.reviewed is True


def test_review_note_and_hash_survive_restart_and_flag_stale_edits(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\nname: runner\ndescription: runs things\npermissions: write:workspace\n---\n\nStep one.\n",
        encoding="utf-8",
    )
    registry = SkillRegistry(skills_dir)
    registry.register_from_skill_md(skill_md, kind="action")
    reviewed = registry.mark_reviewed("runner", note="accepted risk")
    assert reviewed.metadata["review_note"] == "accepted risk"
    assert reviewed.metadata["reviewed_content_hash"]

    # Note + pin survive a restart.
    reloaded = SkillRegistry(skills_dir)
    record = reloaded._skills["runner"]
    assert record.metadata["review_note"] == "accepted risk"
    assert record.reviewed is True

    # Editing the SKILL.md invalidates the review: activation is refused and
    # the stale skill is not selected into a turn.
    skill_md.write_text(
        "---\nname: runner\ndescription: runs things\npermissions: write:workspace\n---\n\nStep one changed.\n",
        encoding="utf-8",
    )
    assert reloaded.review_is_stale(record) is True
    with pytest.raises(ValueError, match="changed on disk"):
        reloaded.activate("runner")

    # Re-review pins the new content and unlocks activation again.
    reloaded.mark_reviewed("runner", note="re-approved")
    assert reloaded.review_is_stale(reloaded._skills["runner"]) is False
    assert reloaded.activate("runner").active is True


# ---------------------------------------------------------------------------
# Restored from test_skill_workspace_scope.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _distilled(registry: SkillRegistry, workspace_id: str, *, body: str = "Project knowledge body."):
    return registry.upsert_knowledge_skill(
        skill_id="project-queue",
        name="Queue project knowledge",
        description="Queue lock architecture and module map.",
        body=body,
        metadata={
            "origin": "project-analysis",
            "workspace_id": workspace_id,
            "commit_sha": f"commit-{workspace_id}",
            "front_matter": {
                "name": "project-queue",
                "description": "Queue lock architecture and module map.",
                "triggers": "queue lock, module map",
            },
        },
        workspace_id=workspace_id,
    )


def test_same_project_name_in_two_workspaces_stays_separate(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    first, created_first = _distilled(registry, "workspace-a", body="A body")
    second, created_second = _distilled(registry, "workspace-b", body="B body")

    assert created_first is True
    assert created_second is True
    assert first.skill_id != second.skill_id
    assert first.workspace_id == "workspace-a"
    assert second.workspace_id == "workspace-b"
    assert first.body == "A body"
    assert second.body == "B body"

    a_ids = {skill.skill_id for skill in registry.list_skills(workspace_id="workspace-a")}
    b_ids = {skill.skill_id for skill in registry.list_skills(workspace_id="workspace-b")}
    assert first.skill_id in a_ids
    assert second.skill_id not in a_ids
    assert second.skill_id in b_ids
    assert first.skill_id not in b_ids
    # Global first-party skills remain visible in every workspace.
    assert any(skill.workspace_id == "" for skill in registry.list_skills(workspace_id="workspace-a"))


def test_selection_and_injection_never_cross_workspaces(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    first, _ = _distilled(registry, "workspace-a", body="A-specific queue guidance.")
    second, _ = _distilled(registry, "workspace-b", body="B-specific queue guidance.")

    selected_a = select_active_skills(registry, "explain the queue lock module map", workspace_id="workspace-a")
    selected_b = select_active_skills(registry, "explain the queue lock module map", workspace_id="workspace-b")
    assert [skill.skill_id for skill in selected_a] == [first.skill_id]
    assert [skill.skill_id for skill in selected_b] == [second.skill_id]

    guidance_a = build_skill_guidance_block(selected_a, workspace_id="workspace-a")
    guidance_b = build_skill_guidance_block(selected_b, workspace_id="workspace-b")
    assert "A-specific queue guidance." in guidance_a
    assert "B-specific queue guidance." not in guidance_a
    assert "B-specific queue guidance." in guidance_b
    assert "A-specific queue guidance." not in guidance_b

    # A selected skill cannot be injected into another workspace even when the
    # caller passes the wrong selection object.
    assert build_skill_guidance_block(selected_a, workspace_id="workspace-b") == ""
    # Missing workspace context exposes only global skills, never project ones.
    selected_without_scope = select_active_skills(registry, "queue lock module map")
    assert all(skill.workspace_id == "" for skill in selected_without_scope)


def test_review_activation_and_usage_reject_other_workspace(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    record = registry.register(
        skill_id="queue-action",
        kind="action",
        name="Queue action",
        description="Queue lock mutation workflow.",
        permissions=["read:workspace"],
        workspace_id="workspace-a",
    )
    assert record.workspace_id == "workspace-a"

    with pytest.raises(KeyError):
        registry.mark_reviewed("queue-action", workspace_id="workspace-b")
    reviewed = registry.mark_reviewed("queue-action", workspace_id="workspace-a")
    assert reviewed.reviewed is True

    with pytest.raises(KeyError):
        registry.activate("queue-action", workspace_id="workspace-b")
    activated = registry.activate("queue-action", workspace_id="workspace-a")
    assert activated.active is True

    with pytest.raises(KeyError):
        registry.record_usage("queue-action", applied=True, workspace_id="workspace-b")
    with pytest.raises(KeyError):
        registry.record_failure("queue-action", error="boom", workspace_id="workspace-b")

    usage = registry.record_usage("queue-action", applied=True, workspace_id="workspace-a")
    assert usage.metadata["last_used_workspace"] == "workspace-a"


def test_registration_rejects_cross_workspace_skill_id_reuse(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(
        skill_id="shared-id",
        kind="knowledge",
        name="Shared",
        workspace_id="workspace-a",
    )
    with pytest.raises(ValueError, match="another workspace"):
        registry.register(
            skill_id="shared-id",
            kind="knowledge",
            name="Shared",
            workspace_id="workspace-b",
        )


def test_workspace_scope_survives_registry_restart(tmp_path: Path) -> None:
    storage = tmp_path / "skills"
    registry = SkillRegistry(storage)
    first, _ = _distilled(registry, "workspace-a")
    second, _ = _distilled(registry, "workspace-b")

    reloaded = SkillRegistry(storage)
    a_ids = {skill.skill_id for skill in reloaded.list_skills(workspace_id="workspace-a")}
    b_ids = {skill.skill_id for skill in reloaded.list_skills(workspace_id="workspace-b")}
    assert first.skill_id in a_ids and first.skill_id not in b_ids
    assert second.skill_id in b_ids and second.skill_id not in a_ids
    assert reloaded._skills[first.skill_id].workspace_id == "workspace-a"


def test_skill_api_filters_list_and_rejects_cross_workspace_review(tmp_path: Path) -> None:
    settings = AppSettings(
        app_name="Trainer skill scope",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-skill-scope.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        registered = client.post(
            "/skill/register",
            json={
                "skill_id": "api-scoped",
                "kind": "knowledge",
                "name": "API scoped",
                "description": "Workspace A only.",
                "workspace_id": "workspace-a",
            },
        )
        assert registered.status_code == 200
        assert registered.json()["skill"]["workspace_id"] == "workspace-a"

        listing_a = client.get("/skill/list", params={"workspace_id": "workspace-a"}).json()
        listing_b = client.get("/skill/list", params={"workspace_id": "workspace-b"}).json()
        assert "api-scoped" in {skill["skill_id"] for skill in listing_a["skills"]}
        assert "api-scoped" not in {skill["skill_id"] for skill in listing_b["skills"]}

        denied = client.post(
            "/skill/review",
            json={
                "skill_id": "api-scoped",
                "workspace_id": "workspace-b",
                "approved": True,
            },
        )
        assert denied.status_code == 404
        allowed = client.post(
            "/skill/review",
            json={
                "skill_id": "api-scoped",
                "workspace_id": "workspace-a",
                "approved": True,
            },
        )
        assert allowed.status_code == 200


def test_router_is_mounted_in_the_application(tmp_path: Path) -> None:
    app = create_app(
        AppSettings(
            app_name="Trainer skill router",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path / "data",
            database_name="trainer-skill-router.db",
            default_session_stage="intake",
            summary_message_limit=6,
            enable_network_fetch=False,
        )
    )
    with TestClient(app) as client:
        assert client.get("/skill/status").status_code == 200


# ---------------------------------------------------------------------------
# Restored from test_skill_lifecycle.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_skill_draft.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def client_for(tmp_path: Path) -> TestClient:
    app = create_app(AppSettings(
        app_name="Trainer Skill Draft", host="127.0.0.1", port=8765,
        data_dir=tmp_path, database_name="skills.db", default_session_stage="intake",
        summary_message_limit=6, enable_network_fetch=False,
    ))
    app.state.runtime.provider_config = ProviderConfig(
        name="skill-test", baseUrl="http://127.0.0.1:9/v1", model="test-model",
        apiKeyRef="test-only",
    )
    app.state.runtime.provider_api_key = "test-skill-key"
    app.state.runtime.provider_service = ProviderService(
        config=app.state.runtime.provider_config, api_key="test-skill-key",
    )
    return TestClient(app)


def test_skill_draft_errors_do_not_return_upstream_secret_text(tmp_path: Path) -> None:
    with client_for(tmp_path) as client, patch.object(ProviderService, "chat_completion", new=AsyncMock(side_effect=RuntimeError("secret-fixture-123"))):
        response = client.post("/provider/skill-draft", json={"description": "Check Python"})
        assert response.status_code == 502
        assert "secret-fixture-123" not in response.text


def test_saved_skills_survive_summary_and_session_restore_without_formal_plan(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        start = client.post("/session/start", json={
            "workspace_id": "workspace-skills", "workspace_name": "Skills",
        })
        assert start.status_code == 200, start.text
        session_id = start.json()["session_id"]
        skill = {"id": "custom-py-check", "trigger": "$py-check", "title": "Python check",
                 "detail": "Check one issue", "prompt": "Check the submitted code", "keywords": []}
        saved = client.post("/memory/settings", json={
            "workspace_id": "workspace-skills", "session_id": session_id,
            "coach_defaults": {"workingSetMode": "focused", "customSkills": [skill]},
        })
        assert saved.status_code == 200, saved.text
        for response in (
            saved,
            client.get("/memory/summary", params={"workspace_id": "workspace-skills"}),
            client.post("/session/start", json={"workspace_id": "workspace-skills", "workspace_name": "Skills"}),
        ):
            assert response.status_code == 200, response.text
            defaults = response.json()["memory"]["workspace"]["coach_defaults"]
            assert defaults["custom_skills"][0]["trigger"] == "$py-check"
            assert defaults["working_set_mode"] == "focused"
