"""P1 #11: forking a course writes the plan and grounds the first card.

What must stay true:

* the fork resolves stage resource refs against the real library and keeps
  unresolved refs verbatim while reporting them;
* the first card comes from the card generator's ``resource_knowledge`` lane —
  and only from an indexed, trusted resource with a usable knowledge fragment;
* everything else degrades to ``deferred`` with the exact missing precondition
  (no improvised card), and the generated card is never bound into the ledger.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.models import ResourceRecord
from app.training.course_fork import (
    FIRST_CARD_DEFERRED,
    FIRST_CARD_GENERATED,
    fork_course_manifest,
)
from app.training.course_pack import (
    COURSE_MANIFEST_TYPE,
    COURSE_MANIFEST_VERSION,
    inspect_course_manifest,
)

_FRAGMENT_FOCUS = "叙事视角"


class _StubRepository:
    def __init__(self, records: list[ResourceRecord] | None = None) -> None:
        self.records = list(records or [])
        self.saved: list[tuple[str, Any]] = []

    def list_resources(self, workspace_id: str) -> list[ResourceRecord]:
        del workspace_id
        return list(self.records)

    def save_plan(self, workspace_id: str, plan: Any) -> None:
        self.saved.append((workspace_id, plan))


class _StubResourceService:
    def __init__(self, fragments: list[dict[str, Any]] | None = None) -> None:
        self.fragments = list(fragments or [])

    def build_requested_resource_context(
        self,
        workspace_id: str,
        resource_ids: list[str],
        *,
        max_items: int = 1,
        summary_chars: int = 220,
    ) -> dict[str, Any]:
        del workspace_id, max_items, summary_chars
        wanted = {str(rid) for rid in resource_ids}
        return {
            "resource_fragments": [
                fragment
                for fragment in self.fragments
                if str(fragment.get("resource_id") or "") in wanted
            ]
        }


def _runtime(
    records: list[ResourceRecord] | None = None,
    fragments: list[dict[str, Any]] | None = None,
) -> tuple[SimpleNamespace, _StubRepository]:
    repository = _StubRepository(records)
    runtime = SimpleNamespace(
        repository=repository,
        resource_service=_StubResourceService(fragments),
    )
    return runtime, repository


def _record(**overrides: Any) -> ResourceRecord:
    payload: dict[str, Any] = {
        "id": "res-1",
        "kind": "pdf",
        "name": "呐喊.pdf",
        "source": "library/nahan.pdf",
        "content_hash": "hash-nahan",
        "index_status": "indexed",
        "trust_score": 0.9,
        "freshness": "fresh",
    }
    payload.update(overrides)
    return ResourceRecord(**payload)


def _fragment(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "frag-1",
        "resource_id": "res-1",
        "source_type": "pdf",
        "focus_area": _FRAGMENT_FOCUS,
        "evidence_summary": "第一人称受限视角把叙述者排除在他人内心之外。",
    }
    payload.update(overrides)
    return payload


def _manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "_type": COURSE_MANIFEST_TYPE,
        "version": COURSE_MANIFEST_VERSION,
        "title": "现代文学精读",
        "subject_family": "literature",
        "summary": "三阶段精读计划",
        "stages": [
            {"id": "s1", "title": "精读《呐喊》", "goal": "方法", "outcomes": [], "resources": ["呐喊.pdf"]},
            {"id": "s2", "title": "仿写", "goal": "迁移", "outcomes": []},
        ],
        "resources": [
            {"name": "呐喊.pdf", "kind": "pdf", "source": "library/nahan.pdf", "contentHash": "hash-nahan"}
        ],
        "card_pack": [],
    }
    payload.update(overrides)
    return payload


def _fork(payload: dict[str, Any], runtime: Any, **kwargs: Any):
    return fork_course_manifest(
        inspect_course_manifest(payload).manifest,
        runtime=runtime,
        workspace_id="workspace-course",
        **kwargs,
    )


def test_fork_writes_plan_and_resolves_stage_resources() -> None:
    runtime, repository = _runtime([_record()])
    result = _fork(_manifest(), runtime)
    assert repository.saved, "the fork must persist the plan"
    workspace_id, saved_plan = repository.saved[0]
    assert workspace_id == "workspace-course"
    assert [stage.id for stage in saved_plan.stages] == ["s1", "s2"]
    assert saved_plan.stages[0].resources == ["res-1"]
    assert saved_plan.current_stage_id == "s1"
    assert result.unresolved_resource_refs == []


def test_fork_keeps_and_reports_unresolved_refs() -> None:
    runtime, _ = _runtime([])
    result = _fork(_manifest(), runtime)
    assert result.plan.stages[0].resources == ["呐喊.pdf"]
    assert result.unresolved_resource_refs == ["呐喊.pdf"]


def test_fork_defers_first_card_without_any_library_resource() -> None:
    runtime, _ = _runtime([])
    result = _fork(_manifest(), runtime)
    assert result.first_card is None
    assert result.first_card_status == FIRST_CARD_DEFERRED
    assert result.first_card_reason == "the library has no resources yet"


def test_fork_defers_when_referenced_resource_is_not_indexed() -> None:
    runtime, _ = _runtime([_record(index_status="pending")], [_fragment()])
    result = _fork(_manifest(), runtime)
    assert result.first_card is None
    assert result.first_card_reason == "no referenced resource is indexed yet"


def test_fork_defers_when_resource_is_not_trusted() -> None:
    runtime, _ = _runtime([_record(trust_score=0.1)], [_fragment()])
    result = _fork(_manifest(), runtime)
    assert result.first_card is None
    assert result.first_card_reason == "no indexed resource is trusted yet"


def test_fork_defers_when_trusted_resource_has_no_fragment() -> None:
    runtime, _ = _runtime([_record()], [])
    result = _fork(_manifest(), runtime)
    assert result.first_card is None
    assert result.first_card_reason == "trusted indexed resources carry no usable knowledge fragment yet"


def test_fork_generates_first_card_through_the_resource_lane() -> None:
    runtime, _ = _runtime([_record()], [_fragment()])
    result = _fork(_manifest(), runtime)
    assert result.first_card is not None
    assert result.first_card_status == FIRST_CARD_GENERATED
    card = result.first_card
    assert card.card_type == "practice"
    assert card.trust_state == "trusted"
    # Grounded in the indexed evidence, not in manifest prose.
    assert _FRAGMENT_FOCUS in f"{card.focus_area} {card.target_skill} {card.why_now} {card.scenario}"
    assert card.plan_links == [] or card.plan_links == ["s1"]


def test_fork_matches_resource_by_content_hash() -> None:
    runtime, _ = _runtime([_record()], [_fragment()])
    payload = _manifest(
        stages=[{"id": "s1", "title": "精读", "goal": "方法", "resources": ["hash-nahan"]}]
    )
    result = _fork(payload, runtime)
    assert result.plan.stages[0].resources == ["res-1"]
    assert result.first_card_status == FIRST_CARD_GENERATED


def test_course_adopt_endpoint_writes_fork_and_defers_honestly(tmp_path: Path) -> None:
    from test_api import build_client

    workspace_id = "workspace-course-adopt"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "course-adopt",
                "workspace_path": str(tmp_path / "adopt-root"),
            },
        )
        assert started.status_code == 200, started.text

        response = client.post(
            "/resource/course/adopt",
            json={"workspace_id": workspace_id, "manifest": _manifest()},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["plan"]["title"] == "现代文学精读"
        assert [stage["id"] for stage in body["plan"]["stages"]] == ["s1", "s2"]
        assert body["subject_family"] == "literature"
        assert body["first_card"] is None
        assert body["first_card_status"] == FIRST_CARD_DEFERRED
        assert body["unresolved_resource_refs"] == ["呐喊.pdf"]
        assert body["trust"]["resolved_subject_family"] == "literature"

        runtime = client.app.state.runtime
        stored = runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.title == "现代文学精读"
        assert len(stored.stages) == 2

        rejected = client.post(
            "/resource/course/adopt",
            json={"workspace_id": workspace_id, "manifest": _manifest(version=7)},
        )
        assert rejected.status_code == 422
