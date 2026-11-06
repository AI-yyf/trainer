"""Skill registry: permission model + SKILL.md progressive loading (P3 §八)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.skills.registry import SkillRegistry, parse_skill_md

SKILL_MD = """---
name: project-explorer
description: Understand a GitHub project's architecture and key modules
permissions: read:workspace, search:resources
---

# Project Explorer

Read the project tree first, then locate key symbols.
"""

SKILL_MD_ACTION = """---
name: auto-refactor
description: Automated refactoring workflow
permissions: write:workspace, execute:scripts
---

# Auto Refactor

Dangerous: rewrites source files.
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
