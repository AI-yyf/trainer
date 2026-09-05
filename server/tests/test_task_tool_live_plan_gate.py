"""Fail-closed ReAct specify_task / next_task: no live plan → no TaskSpec."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from provider_fixtures import seed_verified_capabilities

from app.core.models import LearningPlan, PlanStage, ProviderConfig
from app.llm.provider_service import ProviderService, _build_agent_tool_context_extra
from app.memory.workspace_recovery import leftover_formal_plan_is_live_for_fill
from tests.test_api import build_client


def _runtime(workspace: dict) -> dict:
    value = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
    return value if isinstance(value, dict) else {}


def _provider_payload() -> dict[str, object]:
    return {
        "name": "deterministic-agent",
        "base_url": "https://provider.invalid/v1",
        "api_key_ref": "test-only",
        "model": "test-model",
        "protocol": "openai_chat_completions",
        "capabilities": {"tools": True, "streaming": False},
    }


class _ScriptedTaskToolProvider:
    protocol = "openai_chat_completions"

    def __init__(self, tool_name: str, arguments: dict[str, Any]) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0
        self.tools_seen: list[list[dict[str, Any]] | None] = []

    async def call(
        self,
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        self.tools_seen.append(tools)
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"task-mint-{self.tool_name}",
                        "name": self.tool_name,
                        "arguments": self.arguments,
                    }
                ],
            }
        return {
            "content": "Stay with the first-look next step. Do not invent a task.",
            "tool_calls": [],
        }


def test_pressure_deny_list_includes_specify_and_next_task() -> None:
    extra = _build_agent_tool_context_extra(
        coach_context={
            "scenario": "general",
            "live_formal_plan_for_task_mint": True,
            "pressure_blocks_live_object_mint": True,
        },
        attachment_delivery={"attachments_present": False},
        answer_mode="guided",
        current_file=None,
        learner_message="Specify the next task for token refresh.",
    )
    assert "specify_task" in extra["denied_tool_names"]
    assert "next_task" in extra["denied_tool_names"]
    assert "generate_training_card" in extra["denied_tool_names"]


@pytest.mark.parametrize("tool_name", ["specify_task", "next_task"])
def test_agent_loop_no_live_plan_does_not_mint_task_via_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    workspace_id = f"workspace-tool-{tool_name}-no-plan"
    scripted = _ScriptedTaskToolProvider(
        tool_name,
        {"natural_language_goal": "Add an expiry check for the refresh token"}
        if tool_name == "specify_task"
        else {"focus_area": "token refresh"},
    )

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path, configure_provider=False) as client:
        seed_verified_capabilities(
            client.app.state.runtime,
            ProviderConfig.model_validate(_provider_payload()),
            "test-only-key",
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "No live plan lab",
                "profile": {
                    "long_term_goal": "Understand first without inventing a task",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Specify the next task for shipping one auth check.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _provider_payload(),
                "api_key": "test-only-key",
            },
        )
        runtime = client.app.state.runtime
        snapshot = runtime.memory_service.snapshot(workspace_id)
        session = runtime.get_session(session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body.get("snapshot") or {}).get("current_task") in (None, {})
    assert snapshot.workspace.get("current_task") in (None, {})
    assert session is None or session.snapshot.current_task is None
    assert runtime.repository.get_latest_plan(workspace_id) is None
    tool_names = {
        str((schema.get("function") or {}).get("name") or schema.get("name") or "")
        for schemas in scripted.tools_seen
        for schema in (schemas or [])
        if isinstance(schema, dict)
    }
    assert "specify_task" not in tool_names
    assert "next_task" not in tool_names


def test_agent_loop_leftover_not_live_does_not_mint_or_resurrect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-tool-leftover-not-live"
    leftover_step = "Keep one auth check"
    scripted = _ScriptedTaskToolProvider(
        "specify_task",
        {"natural_language_goal": "Resurrect leftover into a live task"},
    )

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path, configure_provider=False) as client:
        seed_verified_capabilities(
            client.app.state.runtime,
            ProviderConfig.model_validate(_provider_payload()),
            "test-only-key",
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Leftover lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        runtime = client.app.state.runtime
        leftover = LearningPlan(
            id="plan-leftover-tool",
            title="Leftover formal plan",
            summary="Stored but not live",
            current_step=leftover_step,
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Keep one auth check",
                    goal="Keep one auth check",
                    outcomes=["pass"],
                    status="active",
                )
            ],
            current_stage_id="stage-1",
        )
        runtime.repository.save_plan(workspace_id, leftover)
        runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": leftover_step,
                "plan_id": "",
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=_runtime(runtime.memory_service.snapshot(workspace_id).workspace),
            existing=_runtime(runtime.memory_service.snapshot(workspace_id).workspace),
        )

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Specify the next task from the leftover plan.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _provider_payload(),
                "api_key": "test-only-key",
            },
        )
        after = runtime.memory_service.snapshot(workspace_id)
        session = runtime.get_session(session_id)
        plan_after = runtime.repository.get_latest_plan(workspace_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body.get("snapshot") or {}).get("current_task") in (None, {})
    assert after.workspace.get("current_task") in (None, {})
    assert session is None or session.snapshot.current_task is None
    assert plan_after is not None
    assert str(getattr(plan_after, "id", "") or "") == "plan-leftover-tool"


def test_agent_loop_live_plan_tool_specify_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-tool-live-specify"
    scripted = _ScriptedTaskToolProvider(
        "specify_task",
        {"natural_language_goal": "Add an expiry check for the refresh token"},
    )

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path) as client:
        seed_verified_capabilities(
            client.app.state.runtime,
            ProviderConfig.model_validate(_provider_payload()),
            "test-only-key",
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Live plan lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship token refresh under a live plan"],
            },
        )
        assert generated.status_code == 200, generated.text
        plan = generated.json().get("plan") or generated.json()
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert plan_id

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Specify the next task for the refresh token expiry check.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _provider_payload(),
                "api_key": "test-only-key",
            },
        )
        runtime = client.app.state.runtime
        session = runtime.get_session(session_id)
        plan_after = runtime.repository.get_latest_plan(workspace_id)

    assert response.status_code == 200, response.text
    assert session is not None
    task = session.snapshot.current_task
    assert task is not None
    assert task.title
    assert str((task.metadata or {}).get("plan_id") or "").strip() == plan_id
    assert plan_after is not None
    assert str(getattr(plan_after, "id", "") or getattr(plan_after, "plan_id", "") or "") == plan_id


def test_http_task_specify_after_plan_generate_still_works(tmp_path: Path) -> None:
    workspace_id = "workspace-http-specify-still"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "HTTP still works"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship one HTTP specify slice"],
            },
        )
        assert generated.status_code == 200, generated.text
        plan_id = str(
            (generated.json().get("plan") or generated.json()).get("id")
            or (generated.json().get("plan") or generated.json()).get("plan_id")
            or ""
        ).strip()
        assert plan_id
        specified = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "natural_language_goal": "Add one expiry check",
            },
        )
        assert specified.status_code == 200, specified.text
        task = specified.json()
        assert task.get("title")
        assert str((task.get("metadata") or {}).get("plan_id") or "").strip() == plan_id
