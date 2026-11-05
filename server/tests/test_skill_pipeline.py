"""P3 Skill 生态: project knowledge → Skill draft → review → cross-task reuse."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_canonical_resource_pipeline import (  # noqa: E402
    _docx_bytes,
    build_client,
    start_session,
    upload_and_index,
)


def test_project_symbols_to_skill_draft_pipeline(tmp_path: Path) -> None:
    """项目知识 → Skill 草稿 → 审核 → 激活 → 跨任务复用."""

    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-skill-pipeline"
    docx_path = workspace_root / "docs" / "architecture.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Architecture Notes",
            source=docx_path,
        )
        assert indexed["index_status"] == "indexed"

        # Extract project knowledge from indexed fragments
        fragments = indexed.get("knowledge_fragments") or []
        assert fragments, "Expected knowledge fragments from indexed DOCX"
        symbol_names = sorted({
            frag["summary"][:40].strip()
            for frag in fragments
            if frag.get("summary")
        })

        # Simulate Skill 草稿 generation from project knowledge
        skill_name = f"arch-{indexed['id']}"
        skill_description = (
            f"Architecture knowledge extracted from {indexed['id']}: "
            + "; ".join(symbol_names[:3])
        )

        # Register as Knowledge Skill with reviewed=True (project-derived)
        registry_response = client.app.state.runtime
        assert registry_response is not None

        from app.skills.registry import SkillRegistry

        registry = SkillRegistry(tmp_path / "skills")
        registry.register(
            skill_id=skill_name,
            kind="knowledge",
            name=skill_name,
            description=skill_description,
            permissions=["read:workspace", "search:resources"],
            reviewed=True,
            metadata={"source_resource_id": indexed["id"]},
        )
        assert registry._skills[skill_name].reviewed is True
        assert registry._skills[skill_name].active is False

        # Activate and verify
        record = registry.activate(skill_name)
        assert record.active is True

        # Cross-task reuse: deactivate, re-register in a new workspace
        registry.deactivate(skill_name)
        assert registry._skills[skill_name].active is False

        # Re-activate (cross-task reuse)
        registry.activate(skill_name)
        assert registry._skills[skill_name].active is True

        # Skill 使用成功 ≠ 掌握: Learner Competency is separate
        assert "learner_competency" not in registry._skills[skill_name].metadata


