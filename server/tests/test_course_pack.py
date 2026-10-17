"""P1 #10: course.json manifest import/export + the literature subject family.

The contract under test:

* ``course.json`` is validated fail-closed (type, version, title, stages,
  resource kinds) and inspected, never adopted — import writes nothing;
* rubric entries obey the §2.2 anchor rule: anchored objects are counted,
  anchor-free entries are downgraded to ``self_reported`` and named;
* ``subject_family`` resolves through the verifier registry with the same
  fail-closed default as ``verifier_pack_for``;
* the taxonomy learns the ``literature`` family without changing how any
  existing code/theory text classifies;
* export builds a manifest from real workspace data that import accepts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.models import LearningPlan, PlanStage, ResourceRecord, TrainingCardCandidateSnapshot
from app.evaluator.verifiers import verifier_pack_for
from app.training.course_pack import (
    COURSE_MANIFEST_TYPE,
    COURSE_MANIFEST_VERSION,
    build_course_manifest,
    inspect_course_manifest,
)
from app.training.subject_taxonomy import (
    classify_learning_subject,
    verifier_subject_family,
)


def _manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "_type": COURSE_MANIFEST_TYPE,
        "version": COURSE_MANIFEST_VERSION,
        "title": "现代文学精读：从鲁迅到张爱玲",
        "subject_family": "literature",
        "summary": "三阶段精读计划",
        "stages": [
            {"id": "stage-1", "title": "精读《呐喊》", "goal": "建立细读方法", "outcomes": ["批注 3 处"]},
            {"id": "stage-2", "title": "仿写练习", "goal": "迁移叙事视角", "outcomes": []},
        ],
        "resources": [
            {"name": "呐喊.pdf", "kind": "pdf", "source": "resources/nahan.pdf", "contentHash": "abc123"}
        ],
        "card_pack": [
            {
                "card_type": "practice",
                "title": "批注练习",
                "learning_family": "literature",
                "acceptance_criteria": ["指出叙事视角"],
                "rubric": [
                    {"statement": "引用原文作为批注", "anchor": "他没有说自己不平"},
                    "说明修辞效果",
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_import_rejects_unknown_manifest_type() -> None:
    with pytest.raises(ValueError, match="unsupported course manifest _type"):
        inspect_course_manifest(_manifest(_type="other.pack"))


def test_import_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="unsupported course manifest version"):
        inspect_course_manifest(_manifest(version=99))


def test_import_requires_title_and_stage() -> None:
    with pytest.raises(ValueError, match="non-empty title"):
        inspect_course_manifest(_manifest(title="   "))
    with pytest.raises(ValueError, match="at least one stage"):
        inspect_course_manifest(_manifest(stages=[]))
    with pytest.raises(ValueError, match="non-empty title"):
        inspect_course_manifest(_manifest(stages=[{"title": " "}]))


def test_import_rejects_unsupported_resource_kind() -> None:
    with pytest.raises(ValueError, match="unsupported kind 'exe'"):
        inspect_course_manifest(
            _manifest(resources=[{"name": "tool", "kind": "exe", "source": "x"}])
        )


def test_import_reports_anchor_trust() -> None:
    inspection = inspect_course_manifest(_manifest())
    trust = inspection.trust
    assert (trust.stages, trust.resources, trust.cards) == (2, 1, 1)
    assert trust.anchored_rubric_entries == 1
    assert trust.self_reported_rubric_entries == 1
    assert trust.downgraded_cards == ["批注练习"]
    assert any("self_reported" in note for note in trust.notes)
    assert any("never become verified evidence" in note for note in trust.notes)


def test_import_resolves_subject_family_through_the_registry() -> None:
    matched = inspect_course_manifest(_manifest())
    assert matched.trust.declared_subject_family == "literature"
    assert matched.trust.resolved_subject_family == "literature"
    assert matched.trust.subject_family_matched is True

    unknown = inspect_course_manifest(_manifest(subject_family="linguistics"))
    assert unknown.trust.resolved_subject_family == "code"
    assert unknown.trust.subject_family_matched is False
    assert any("falls back to 'code'" in note for note in unknown.trust.notes)
    # The resolution must equal what the registry itself would do.
    assert unknown.trust.resolved_subject_family == verifier_pack_for("linguistics").subject_family


def test_build_then_inspect_round_trip() -> None:
    stages = [
        PlanStage(id="s1", title="精读", goal="方法", outcomes=["批注"], resources=["res-1"]),
        PlanStage(id="s2", title="仿写", goal="迁移", outcomes=[]),
    ]
    resources = [
        ResourceRecord(
            id="res-1",
            kind="pdf",
            name="呐喊.pdf",
            source="library/nahan.pdf",
            content_hash="abc123",
            tags=["精读"],
            summary="短篇小说集",
        )
    ]
    manifest = build_course_manifest(
        title="现代文学精读",
        subject_family="literature",
        summary="三阶段",
        stages=stages,
        resources=resources,
    )
    assert manifest["_type"] == COURSE_MANIFEST_TYPE
    assert manifest["version"] == COURSE_MANIFEST_VERSION
    assert manifest["stages"][0]["resources"] == ["res-1"]
    assert manifest["resources"][0]["name"] == "呐喊.pdf"
    assert manifest["resources"][0]["contentHash"] == "abc123"
    assert manifest["resources"][0]["tags"] == ["精读"]

    inspection = inspect_course_manifest(manifest)
    assert inspection.manifest.title == "现代文学精读"
    assert inspection.manifest.subject_family == "literature"
    assert inspection.trust.stages == 2
    assert inspection.trust.resources == 1
    assert inspection.trust.subject_family_matched is True
    assert inspection.trust.self_reported_rubric_entries == 0
    assert inspection.trust.downgraded_cards == []


def test_classify_literature_family() -> None:
    assert classify_learning_subject("精读《呐喊》第一篇").family == "literature"
    assert classify_learning_subject("精读《呐喊》第一篇").subtype == "reading"
    assert classify_learning_subject("仿写鲁迅的白描笔法").family == "literature"
    assert classify_learning_subject("仿写鲁迅的白描笔法").subtype == "writing"
    assert classify_learning_subject("批注练习：意象与修辞").family == "literature"

    # Existing classifications must not drift: generic wording stays theory.
    assert classify_learning_subject("essay writing practice").family == "theory"
    assert classify_learning_subject("essay writing practice").subtype == "writing"
    assert classify_learning_subject("novel chapter theme").family == "theory"
    assert classify_learning_subject("novel chapter theme").subtype == "reading"

    # Code markers keep precedence over literature wording.
    code_subject = classify_learning_subject("debug loop 精读 traceback")
    assert code_subject.family == "code"
    assert code_subject.subtype == "debug"


def test_verifier_subject_family_mapping() -> None:
    assert verifier_subject_family("literature") == "literature"
    assert verifier_subject_family(" LITERATURE ") == "literature"
    assert verifier_subject_family("code") == "code"
    assert verifier_subject_family("theory") == "code"
    assert verifier_subject_family(None) == "code"
    assert verifier_subject_family("japanese") == "code"
    assert verifier_subject_family("literature") == verifier_pack_for("literature").subject_family


def test_card_snapshot_adopts_literature_family() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        focus_area="精读《呐喊》",
        target_skill="细读与批注",
    )
    assert card.learning_family == "literature"
    assert card.learning_subtype == "reading"


def test_card_snapshot_keeps_theory_for_generic_writing() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        focus_area="英语写作",
        target_skill="opening sentence",
    )
    assert card.learning_family == "theory"
    assert card.learning_subtype == "writing"


def test_course_import_endpoint_inspects_without_writing(tmp_path: Path) -> None:

    from test_api import build_client

    with build_client(tmp_path) as client:
        response = client.post("/resource/course/import", json={"manifest": _manifest()})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["manifest"]["_type"] == COURSE_MANIFEST_TYPE
        assert body["manifest"]["subject_family"] == "literature"
        assert body["trust"]["anchored_rubric_entries"] == 1
        assert body["trust"]["self_reported_rubric_entries"] == 1

        rejected = client.post(
            "/resource/course/import", json={"manifest": _manifest(_type="nope")}
        )
        assert rejected.status_code == 422
        assert "unsupported course manifest _type" in rejected.json()["detail"]

        # Nothing adopted: no plan exists after import.
        runtime = client.app.state.runtime
        assert runtime.repository.get_latest_plan("workspace-course-import") is None


def test_course_export_endpoint_builds_manifest_from_workspace(tmp_path: Path) -> None:

    from test_api import build_client

    workspace_id = "workspace-course-export"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "course-export",
                "workspace_path": str(tmp_path / "export-root"),
            },
        )
        assert started.status_code == 200, started.text

        runtime = client.app.state.runtime
        runtime.repository.save_plan(
            workspace_id,
            LearningPlan(
                id="plan-course-export",
                title="现代文学精读",
                summary="三阶段精读计划",
                stages=[
                    PlanStage(id="s1", title="精读", goal="方法", outcomes=["批注"]),
                    PlanStage(id="s2", title="仿写", goal="迁移", outcomes=[]),
                ],
            ),
        )

        response = client.post(
            "/resource/course/export",
            json={"workspace_id": workspace_id, "subject_family": "literature"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["manifest"]["title"] == "现代文学精读"
        assert body["manifest"]["subject_family"] == "literature"
        assert [stage["id"] for stage in body["manifest"]["stages"]] == ["s1", "s2"]
        assert body["trust"]["stages"] == 2
        assert body["trust"]["resolved_subject_family"] == "literature"

        missing = client.post(
            "/resource/course/export",
            json={"workspace_id": workspace_id, "plan_id": "plan-does-not-exist"},
        )
        assert missing.status_code == 404
