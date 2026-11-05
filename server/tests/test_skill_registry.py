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
    skills = registry.list_skills()
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
