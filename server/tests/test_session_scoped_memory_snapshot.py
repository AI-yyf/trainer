from __future__ import annotations

from pathlib import Path

from app.core.models import TeachingKnowledgeAsset
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService, StructuredMemoryService


def test_structured_snapshot_selects_session_not_max_updated_at() -> None:
    structured = StructuredMemoryService()
    structured.append_session_message("session-a", "token-A-private")
    structured.append_session_message("session-b", "token-B-private")
    # B is newer via max(updated_at); A must still win when requested.
    structured.merge_session_coach_patch(
        "session-a",
        {
            "latest_turn_summary": "summary-A token-A-private",
            "latest_coach_summary": "coach-A token-A-private",
            "active_thread": {
                "scenario": "general",
                "focus_area": "focus-A",
                "summary": "summary-A token-A-private",
                "next_step": "next-A",
                "blocker": "",
                "verified_result": "",
            },
        },
    )
    structured.merge_session_coach_patch(
        "session-b",
        {
            "latest_turn_summary": "summary-B token-B-private",
            "latest_coach_summary": "coach-B token-B-private",
            "active_thread": {
                "scenario": "general",
                "focus_area": "focus-B",
                "summary": "summary-B token-B-private",
                "next_step": "next-B",
                "blocker": "",
                "verified_result": "",
            },
        },
    )
    structured.update_workspace(
        latest_turn_summary="workspace-leak token-B-private",
        latest_coach_summary="workspace-leak token-B-private",
        active_thread={
            "scenario": "general",
            "focus_area": "workspace-leak",
            "summary": "workspace-leak token-B-private",
            "next_step": "leak",
            "blocker": "",
            "verified_result": "",
        },
    )

    snap_a = structured.snapshot(session_id="session-a")
    snap_b = structured.snapshot(session_id="session-b")

    assert snap_a.session is not None
    assert snap_a.session.session_id == "session-a"
    assert snap_b.session is not None
    assert snap_b.session.session_id == "session-b"
    assert snap_a.workspace.get("latest_turn_summary") == "summary-A token-A-private"
    assert snap_b.workspace.get("latest_turn_summary") == "summary-B token-B-private"
    assert "token-B-private" not in str(snap_a.workspace.get("active_thread"))
    assert "token-A-private" not in str(snap_b.workspace.get("active_thread"))
    assert "workspace-leak" not in str(snap_a.workspace.get("latest_coach_summary"))
    assert "workspace-leak" not in str(snap_b.workspace.get("latest_turn_summary"))


def test_reflections_and_teaching_assets_are_session_scoped() -> None:
    structured = StructuredMemoryService()
    structured.add_reflection("task", "reflect-A token-A", session_id="session-a")
    structured.add_reflection("task", "reflect-B token-B", session_id="session-b")
    structured.upsert_teaching_asset(
        TeachingKnowledgeAsset(
            kind="concept_card",
            title="asset-A",
            summary="asset body token-A",
            workspace_id="ws",
            session_id="session-a",
            origin="reflection",
            source_key="reflection::ws::session-a::a",
        )
    )
    structured.upsert_teaching_asset(
        TeachingKnowledgeAsset(
            kind="concept_card",
            title="asset-B",
            summary="asset body token-B",
            workspace_id="ws",
            session_id="session-b",
            origin="reflection",
            source_key="reflection::ws::session-b::b",
        )
    )
    structured.upsert_teaching_asset(
        TeachingKnowledgeAsset(
            kind="concept_card",
            title="resource-shared",
            summary="index body shared",
            workspace_id="ws",
            origin="resource",
            source_key="resource::ws::shared",
        )
    )

    snap_a = structured.snapshot(session_id="session-a")
    snap_b = structured.snapshot(session_id="session-b")

    assert [item.summary for item in snap_a.reflections] == ["reflect-A token-A"]
    assert [item.summary for item in snap_b.reflections] == ["reflect-B token-B"]
    titles_a = {item.title for item in snap_a.teaching_assets}
    titles_b = {item.title for item in snap_b.teaching_assets}
    assert titles_a == {"asset-A", "resource-shared"}
    assert titles_b == {"asset-B", "resource-shared"}


def test_memory_service_snapshot_isolates_same_workspace_sessions(tmp_path: Path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "session-scoped-memory.db"))
    workspace_id = "same-workspace"

    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-a",
        scenario="general",
        focus_area="focus-A",
        summary="remember token-A-private",
        next_step="stay on A",
        decision="decision-A token-A-private",
        teaching_note="note-A token-A-private",
    )
    service.record_coaching_reflection(
        workspace_id=workspace_id,
        session_id="session-a",
        scenario="general",
        focus_area="focus-A",
        summary="reflect token-A-private",
        next_step="next A",
        review_note="review-A token-A-private",
    )
    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-b",
        scenario="general",
        focus_area="focus-B",
        summary="remember token-B-private",
        next_step="stay on B",
        decision="decision-B token-B-private",
        teaching_note="note-B token-B-private",
    )
    service.record_coaching_reflection(
        workspace_id=workspace_id,
        session_id="session-b",
        scenario="general",
        focus_area="focus-B",
        summary="reflect token-B-private",
        next_step="next B",
        review_note="review-B token-B-private",
    )

    snap_a = service.snapshot(workspace_id, session_id="session-a")
    snap_b = service.snapshot(workspace_id, session_id="session-b")

    blob_a = " ".join(
        [
            snap_a.recent_summary,
            snap_a.current_focus,
            " ".join(snap_a.reflections),
            " ".join(snap_a.teaching_observations),
            str(snap_a.active_thread.model_dump() if snap_a.active_thread else {}),
            str(snap_a.workspace.get("latest_turn_summary") or ""),
            str(snap_a.workspace.get("latest_coach_summary") or ""),
            " ".join(asset.summary for asset in snap_a.teaching_assets),
        ]
    )
    blob_b = " ".join(
        [
            snap_b.recent_summary,
            snap_b.current_focus,
            " ".join(snap_b.reflections),
            " ".join(snap_b.teaching_observations),
            str(snap_b.active_thread.model_dump() if snap_b.active_thread else {}),
            str(snap_b.workspace.get("latest_turn_summary") or ""),
            str(snap_b.workspace.get("latest_coach_summary") or ""),
            " ".join(asset.summary for asset in snap_b.teaching_assets),
        ]
    )

    assert "token-A-private" in blob_a
    assert "token-B-private" not in blob_a
    assert "token-B-private" in blob_b
    assert "token-A-private" not in blob_b
    assert snap_a.active_thread is not None
    assert snap_b.active_thread is not None
    assert "token-A-private" in (snap_a.active_thread.summary or "")
    assert "token-B-private" in (snap_b.active_thread.summary or "")
