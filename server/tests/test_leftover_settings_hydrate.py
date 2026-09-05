from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import (
    ChatMessage,
    EvaluationReport,
    FirstLookSummary,
    ProviderConfig,
    ResourceRecord,
    WorkspaceUnderstandingSnapshot,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.workspace_recovery import PLAN_RUNTIME_KEY


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Leftover Settings Hydrate",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-leftover-settings-hydrate.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(_settings(tmp_path))
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": True,
            "tools": False,
            "json_schema": False,
            "streaming": True,
        },
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
    runtime.provider_service = ProviderService(
        config=provider,
        api_key="sk-test-not-a-real-key-aaaaaaaa",
    )
    runtime.provider_service_cache.clear()
    return TestClient(app)


def _start_session(client: TestClient, workspace_id: str) -> dict[str, object]:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": workspace_id,
            "profile": {
                "long_term_goal": "Ship one auth check",
                "weekly_hours": 4,
                "teaching_style": "guided",
                "answer_policy": "guided",
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def _resume_session(client: TestClient, workspace_id: str) -> dict[str, object]:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": workspace_id,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def test_session_start_omits_leftover_settings_and_sandbox_preview_when_recovered_step_empty(
    tmp_path: Path,
) -> None:
    leftover_rhythm = "Keep the leftover A rhythm"
    leftover_mode = "Keep the leftover A learning mode"
    leftover_learner = "Keep the leftover A learner"
    leftover_onboarding = "Keep the leftover A onboarding"
    leftover_project = "Keep the leftover A project context"
    leftover_sandbox_title = "Keep the leftover A sandbox preview"
    leftover_library_title = "Keep the leftover A library notes"
    leftover_conversation = "Keep the leftover A conversation"
    leftover_conversation_focus = "Keep the leftover A conversation focus"
    leftover_suggested_action = "Keep the leftover A suggested action"
    leftover_first_look_next = "Keep the leftover A first-look next"
    leftover_evaluation_summary = "Keep the leftover A evaluation headline"
    leftover_stream = "Keep the leftover A stream"
    leftover_stream_interrupt = "Keep the leftover A stream interrupt"
    leftover_transfer_concept = "Keep the leftover A transfer skill"
    leftover_transfer_why = "Keep the leftover A transfer why"
    leftover_transfer_next = "Keep the leftover A transfer next"
    leftover_sandbox_path = r"F:\workspace-a\notes.md"
    leftover_sandbox_root = r"F:\workspace-a"
    workspace_a = "workspace-leftover-settings-hydrate-a"
    workspace_b = "workspace-leftover-settings-hydrate-b"
    live_step = "Add a token expiry test"

    with _client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_a,
            plan_runtime={
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": workspace_a,
            },
            request_id="leftover-settings-hydrate-empty",
        )
        runtime.memory_service.update_workspace_state(
            workspace_a,
            preferred_rhythm=leftover_rhythm,
            preferred_learning_mode=leftover_mode,
            learner_name=leftover_learner,
            project_context=leftover_project,
            onboarding_request=leftover_onboarding,
            coach_defaults={
                "memory_scope": "personal",
                "working_set_mode": "broad",
                "review_cadence": "active",
                "review_reminder_mode": "ahead",
            },
            sandbox_preview={
                "path": leftover_sandbox_path,
                "title": leftover_sandbox_title,
                "excerpt": "A leftover sandbox preview",
            },
            sandbox_state={
                "root_path": leftover_sandbox_root,
                "selected_path": leftover_sandbox_path,
                "ready": True,
                "linked_resource_count": 3,
                "total_files": 4,
            },
            latest_conversation=[
                {
                    "id": "msg-leftover-a",
                    "role": "assistant",
                    "content": leftover_conversation,
                }
            ],
            active_thread={
                "focus_area": leftover_conversation_focus,
                "summary": leftover_conversation,
                "next_step": leftover_conversation,
            },
            latest_coach_turn={
                "suggested_actions": [
                    {
                        "id": "suggested-leftover-a",
                        "label": leftover_suggested_action,
                        "action": "task",
                    }
                ],
            },
            latest_transfer_state={
                "concept": leftover_transfer_concept,
                "state": "transferable",
                "scene_count": 1,
                "workspace_ids": [workspace_a],
                "scene_keys": ["default"],
                "why": leftover_transfer_why,
                "next": leftover_transfer_next,
            },
        )
        persisted_stream = runtime.memory_service.persist_streaming_checkpoint(
            workspace_a,
            request_id="stream-leftover-a",
            phase="interrupted",
            stream_message_id=leftover_stream,
            stop_reason=leftover_stream_interrupt,
            error=leftover_stream_interrupt,
            provider_name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            model="gpt-4o-mini",
        )
        assert persisted_stream is not None
        runtime.repository.save_resource(
            workspace_a,
            ResourceRecord(
                id="resource-leftover-a",
                kind="markdown",
                name=leftover_library_title,
                source="notes.md",
                summary="A leftover library item",
            ),
        )
        stored = runtime.memory_service.snapshot(workspace_a).workspace
        assert stored.get("preferred_rhythm") == leftover_rhythm
        assert (stored.get("sandbox_preview") or {}).get("title") == leftover_sandbox_title
        assert (stored.get("sandbox_state") or {}).get("selected_path") == leftover_sandbox_path
        assert leftover_conversation in str(stored.get("latest_conversation") or "")
        assert leftover_conversation_focus in str(stored.get("active_thread") or "")
        assert leftover_stream in str(stored.get("latest_streaming_checkpoint") or "")
        assert leftover_stream_interrupt in str(stored.get("latest_streaming_checkpoint") or "")
        stored_transfer = stored.get("latest_transfer_state") or {}
        assert stored_transfer.get("state") == "transferable"
        assert leftover_transfer_concept in str(stored_transfer)
        assert leftover_transfer_next in str(stored_transfer)
        assert any(item.name == leftover_library_title for item in runtime.memory_service.snapshot(workspace_a).resources)

        empty = _start_session(client, workspace_a)
        status = empty.get("plan_runtime_status") or {}
        assert status.get("recovered") is True
        assert not str(status.get("current_step") or "").strip()
        workspace = ((empty.get("memory") or {}).get("workspace") or {})
        assert leftover_rhythm not in str(workspace.get("preferred_rhythm") or "")
        assert leftover_mode not in str(workspace.get("preferred_learning_mode") or "")
        assert leftover_rhythm not in str(workspace.get("preferredRhythm") or "")
        assert leftover_learner not in str(workspace.get("learner_name") or "")
        assert leftover_onboarding not in str(workspace.get("onboarding_request") or "")
        assert leftover_project not in str(workspace.get("project_context") or "")
        assert workspace.get("coach_defaults") in (None, {})
        assert workspace.get("coachDefaults") in (None, {})
        sandbox = workspace.get("sandbox_preview") or workspace.get("sandboxPreview") or {}
        assert leftover_sandbox_title not in str(sandbox)
        leftover_sandbox_state = workspace.get("sandbox_state") or workspace.get("sandboxState") or {}
        assert leftover_sandbox_path not in str(leftover_sandbox_state)
        assert leftover_sandbox_root not in str(leftover_sandbox_state)
        empty_resources = ((empty.get("memory") or {}).get("resources") or empty.get("resources") or [])
        assert leftover_library_title not in str(empty_resources)
        assert leftover_conversation not in str(workspace.get("latest_conversation") or workspace.get("latestConversation") or "")
        assert leftover_conversation_focus not in str(workspace.get("active_thread") or workspace.get("activeThread") or "")
        assert leftover_conversation not in str(empty.get("messages") or [])
        empty_thread = ((empty.get("memory") or {}).get("active_thread") or (empty.get("memory") or {}).get("activeThread") or {})
        assert leftover_conversation_focus not in str(empty_thread)
        empty_turn = workspace.get("latest_coach_turn") or workspace.get("latestCoachTurn") or {}
        assert leftover_suggested_action not in str(empty_turn.get("suggested_actions") or [])
        empty_checkpoint = workspace.get("latest_streaming_checkpoint") or workspace.get("latestStreamingCheckpoint") or {}
        assert leftover_stream not in str(empty_checkpoint)
        assert leftover_stream_interrupt not in str(empty_checkpoint)
        empty_transfer = workspace.get("latest_transfer_state") or workspace.get("latestTransferState") or {}
        assert empty_transfer.get("state") != "transferable"
        assert empty_transfer.get("state") == "awaiting_second_scene"
        assert leftover_transfer_next not in str(empty_transfer)
        assert leftover_transfer_why not in str(empty_transfer)
        empty_orientation = empty.get("coach_orientation") or empty.get("coachOrientation") or {}
        assert leftover_stream not in str(empty_orientation)
        assert leftover_stream_interrupt not in str(empty_orientation)
        assert leftover_transfer_next not in str(empty_orientation)
        assert leftover_transfer_why not in str(empty_orientation)
        assert empty_orientation.get("primary_action") != "resume_checkpoint"
        assert empty_orientation.get("primaryAction") != "resume_checkpoint"
        stored_after = runtime.memory_service.snapshot(workspace_a).workspace
        assert stored_after.get("preferred_rhythm") == leftover_rhythm
        assert stored_after.get("learner_name") == leftover_learner
        assert stored_after.get("onboarding_request") == leftover_onboarding
        assert (stored_after.get("coach_defaults") or {}).get("memory_scope") == "personal"
        assert (stored_after.get("sandbox_preview") or {}).get("title") == leftover_sandbox_title
        assert (stored_after.get("sandbox_state") or {}).get("selected_path") == leftover_sandbox_path
        assert leftover_conversation in str(stored_after.get("latest_conversation") or "")
        assert leftover_conversation_focus in str(stored_after.get("active_thread") or "")
        assert leftover_stream in str(stored_after.get("latest_streaming_checkpoint") or "")
        assert leftover_stream_interrupt in str(stored_after.get("latest_streaming_checkpoint") or "")
        stored_after_transfer = stored_after.get("latest_transfer_state") or {}
        assert stored_after_transfer.get("state") == "transferable"
        assert leftover_transfer_concept in str(stored_after_transfer)
        assert any(
            item.name == leftover_library_title
            for item in runtime.memory_service.snapshot(workspace_a).resources
        )

        session_id = str(empty.get("session_id") or "")
        state = runtime.ensure_session(session_id, workspace_id=workspace_a)
        state.snapshot.messages.append(
            ChatMessage(id="msg-leftover-a", role="assistant", content=leftover_conversation)
        )
        state.snapshot.memory.workspace_understanding = WorkspaceUnderstandingSnapshot(
            first_look_summary=FirstLookSummary(
                recommended_next_step=leftover_first_look_next,
                why_this_guess="Keep the leftover A first-look why",
            )
        )
        state.snapshot.evaluation = EvaluationReport(
            summary=leftover_evaluation_summary,
            next_step="Stay on leftover A eval",
            passed=False,
        )
        runtime.save_session_state(session_id)
        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_a,
            plan_runtime={
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": workspace_a,
            },
            request_id="leftover-conversation-hydrate-empty",
        )
        resumed = _resume_session(client, workspace_a)
        assert leftover_conversation not in str(resumed.get("messages") or [])
        resumed_thread = ((resumed.get("memory") or {}).get("active_thread") or {})
        assert leftover_conversation_focus not in str(resumed_thread)
        resumed_workspace = ((resumed.get("memory") or {}).get("workspace") or {})
        resumed_turn = resumed_workspace.get("latest_coach_turn") or resumed_workspace.get("latestCoachTurn") or {}
        assert leftover_suggested_action not in str(resumed_turn.get("suggested_actions") or [])
        resumed_understanding = ((resumed.get("memory") or {}).get("workspace_understanding") or {})
        resumed_first_look = resumed_understanding.get("first_look_summary") or resumed_understanding.get("firstLookSummary") or {}
        assert leftover_first_look_next not in str(resumed_first_look)
        resumed_evaluation = resumed.get("evaluation") or {}
        assert leftover_evaluation_summary not in str(resumed_evaluation)
        stored_resume = runtime.memory_service.snapshot(workspace_a).workspace
        assert leftover_conversation in str(stored_resume.get("latest_conversation") or "")

        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_a,
            plan_runtime={
                "current_step": live_step,
                "why_now": "Expired tokens still leak.",
                "resume_state": "waiting",
                "workspace_id": workspace_a,
            },
            request_id="leftover-settings-hydrate-live",
        )
        live = _start_session(client, workspace_a)
        live_status = live.get("plan_runtime_status") or {}
        assert live_status.get("recovered") is True
        assert live_status.get("current_step") == live_step
        live_workspace = ((live.get("memory") or {}).get("workspace") or {})
        assert leftover_rhythm not in str(live_workspace.get("preferred_rhythm") or "")
        assert leftover_mode not in str(live_workspace.get("preferred_learning_mode") or "")
        assert leftover_learner not in str(live_workspace.get("learner_name") or "")
        assert leftover_onboarding not in str(live_workspace.get("onboarding_request") or "")
        assert leftover_project not in str(live_workspace.get("project_context") or "")
        assert live_workspace.get("coach_defaults") in (None, {})
        assert live_workspace.get("coachDefaults") in (None, {})
        live_sandbox = live_workspace.get("sandbox_preview") or {}
        assert leftover_sandbox_title not in str(live_sandbox)
        live_sandbox_state = live_workspace.get("sandbox_state") or live_workspace.get("sandboxState") or {}
        assert leftover_sandbox_path not in str(live_sandbox_state)
        live_resources = ((live.get("memory") or {}).get("resources") or live.get("resources") or [])
        assert leftover_library_title not in str(live_resources)
        assert leftover_conversation in str(live_workspace.get("latest_conversation") or live_workspace.get("latestConversation") or "")
        assert leftover_conversation_focus in str(live_workspace.get("active_thread") or live_workspace.get("activeThread") or "")
        live_checkpoint = live_workspace.get("latest_streaming_checkpoint") or live_workspace.get("latestStreamingCheckpoint") or {}
        assert leftover_stream in str(live_checkpoint)
        assert leftover_stream_interrupt in str(live_checkpoint)
        live_transfer = live_workspace.get("latest_transfer_state") or live_workspace.get("latestTransferState") or {}
        assert live_transfer.get("state") == "transferable"
        assert leftover_transfer_next in str(live_transfer)
        assert live_workspace.get(PLAN_RUNTIME_KEY, {}).get("resume_state") in {"waiting", "in_progress"}

        runtime.memory_service.update_workspace_state(
            workspace_a,
            latest_transfer_state={
                "concept": leftover_transfer_concept,
                "state": "transferable",
                "scene_count": 2,
                "workspace_ids": [workspace_a, "workspace-c"],
                "scene_keys": ["default", "workspace:workspace-c"],
                "why": leftover_transfer_why,
                "next": leftover_transfer_next,
            },
        )
        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_a,
            plan_runtime={
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": workspace_a,
            },
            request_id="leftover-transfer-hydrate-multi",
        )
        multi = _start_session(client, workspace_a)
        multi_status = multi.get("plan_runtime_status") or {}
        assert multi_status.get("recovered") is True
        assert not str(multi_status.get("current_step") or "").strip()
        multi_workspace = ((multi.get("memory") or {}).get("workspace") or {})
        multi_transfer = multi_workspace.get("latest_transfer_state") or multi_workspace.get("latestTransferState") or {}
        assert multi_transfer.get("state") == "transferable"
        assert [workspace_a, "workspace-c"] == (
            multi_transfer.get("workspace_ids") or multi_transfer.get("workspaceIds")
        )

        other = _start_session(client, workspace_b)
        other_workspace = ((other.get("memory") or {}).get("workspace") or {})
        other_status = other.get("plan_runtime_status") or {}
        assert leftover_rhythm not in str(other_workspace)
        assert leftover_mode not in str(other_workspace)
        assert leftover_learner not in str(other_workspace)
        assert leftover_onboarding not in str(other_workspace)
        assert leftover_project not in str(other_workspace)
        assert leftover_sandbox_title not in str(other_workspace)
        assert leftover_sandbox_path not in str(other_workspace)
        assert leftover_library_title not in str((other.get("memory") or {}).get("resources") or other.get("resources") or [])
        assert leftover_conversation not in str(other_workspace)
        assert leftover_conversation_focus not in str(other_workspace)
        assert leftover_conversation not in str(other.get("messages") or [])
        other_turn = other_workspace.get("latest_coach_turn") or other_workspace.get("latestCoachTurn") or {}
        assert leftover_suggested_action not in str(other_turn.get("suggested_actions") or [])
        assert leftover_first_look_next not in str((other.get("memory") or {}).get("workspace_understanding") or {})
        assert leftover_evaluation_summary not in str(other.get("evaluation") or {})
        assert leftover_stream not in str(other_workspace)
        assert leftover_stream_interrupt not in str(other_workspace)
        assert leftover_transfer_concept not in str(other_workspace)
        assert leftover_transfer_next not in str(other_workspace)
        other_transfer = other_workspace.get("latest_transfer_state") or other_workspace.get("latestTransferState") or {}
        assert other_transfer.get("state") != "transferable"
        other_orientation = other.get("coach_orientation") or other.get("coachOrientation") or {}
        assert leftover_stream not in str(other_orientation)
        assert leftover_stream_interrupt not in str(other_orientation)
        assert leftover_rhythm not in str(other_status)
        assert other_status.get("recovered") is not True
        assert not str(other_status.get("current_step") or "").strip()
