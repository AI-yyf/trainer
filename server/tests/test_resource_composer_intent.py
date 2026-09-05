from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities
from pydantic import ValidationError
from test_router_stream_scenarios import mark_provider_capabilities_verified

from app.core.models import (
    LearningPlan,
    PlanStage,
    ProviderConfig,
    SessionMessageRequest,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.prompts import build_coaching_system_prompt
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            AppSettings(
                app_name="Trainer Resource Composer Intent Test Server",
                host="127.0.0.1",
                port=8765,
                data_dir=tmp_path,
                database_name="trainer-test.db",
                default_session_stage="intake",
                summary_message_limit=6,
                enable_network_fetch=False,
            )
        )
    )


def test_resource_composer_intent_is_semantic_only_and_alias_safe() -> None:
    request = SessionMessageRequest.model_validate(
        {
            "message": "Keep this focused.",
            "resourceComposerIntent": {
                "mode": "organize",
                "resourceIds": ["resource-1", "resource-1", "resource:note-2"],
            },
        }
    )

    assert request.resource_composer_intent is not None
    assert request.resource_composer_intent.mode == "organize"
    assert request.resource_composer_intent.resource_ids == ["resource-1", "resource:note-2"]
    assert request.model_dump(by_alias=True)["resourceComposerIntent"] == {
        "mode": "organize",
        "resourceIds": ["resource-1", "resource:note-2"],
    }

    with pytest.raises(ValidationError):
        SessionMessageRequest.model_validate(
            {
                "message": "Move this material.",
                "resource_composer_intent": {
                    "mode": "organize",
                    "targetPath": "C:\\outside-workspace",
                },
            }
        )
    with pytest.raises(ValidationError):
        SessionMessageRequest.model_validate(
            {
                "message": "Use this material.",
                "resource_composer_intent": {
                    "mode": "locate",
                    "resource_ids": ["../not-a-resource-id"],
                },
            }
        )


@pytest.mark.parametrize("mode", ["locate", "download", "organize", "cards"])
def test_resource_composer_intent_accepts_each_supported_mode(mode: str) -> None:
    request = SessionMessageRequest.model_validate(
        {
            "message": "Keep the resource task focused.",
            "resource_composer_intent": {"mode": mode},
        }
    )

    assert request.resource_composer_intent is not None
    assert request.resource_composer_intent.mode == mode


def test_resource_composer_prompt_is_advisory_and_keeps_governance_explicit() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn resource-grounded coaching"),
        message="Help me decide what to do with this source.",
        coach_context={
            "active_view": "resources",
            "resource_composer_intent": {
                "mode": "cards",
                "resource_ids": ["resource-note-1"],
            },
        },
    )

    assert "Resource task: derive one or two grounded learning-card candidates" in prompt
    assert "never authorizes writing the learner's project" in prompt
    assert "Managed sandbox library tools may still list, edit, and index" in prompt
    assert "Do not mention internal routing, metadata, or UI controls" in prompt
    assert "Formal Plan changes still require the explicit formal-plan mutation path" in prompt
    assert (
        "Do not create or activate a Training card solely because this Resources action was selected"
        in prompt
    )


def test_resource_composer_intent_reaches_coach_context_without_rewriting_chat_or_plan(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-resource-composer-intent"
    user_text = "Keep this focused and identify the next useful study move."
    seeded_plan = LearningPlan(
        id="resource-composer-plan",
        title="Existing governed plan",
        summary="This stays stable until an explicit formal mutation.",
        stages=[
            PlanStage(
                id="resource-stage",
                title="Ground resources",
                goal="Use only confirmed library evidence",
                outcomes=["Name the source before proposing a handoff"],
                status="active",
            )
        ],
        current_stage_id="resource-stage",
        current_step="Inspect the selected material.",
    )

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="resource-composer-context-test",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.resource-composer",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-fake"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test-fake")
        runtime.provider_service_cache.clear()
        seed_verified_capabilities(runtime, provider, "sk-test-fake", tools=True)

        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Resource intent"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        state.snapshot.plan = seeded_plan.model_copy(deep=True)
        runtime.repository.save_plan(workspace_id, seeded_plan)

        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value="Here is one candidate to review before any handoff."),
            ) as coaching_reply,
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=AssertionError("explicit use_agent_loop=false must stay off the agent loop")),
            ),
            patch.object(
                runtime.resource_service,
                "build_requested_resource_context",
                wraps=runtime.resource_service.build_requested_resource_context,
            ) as build_requested_context,
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "coach",
                    "active_view": "resources",
                    "formal_plan_mutation": False,
                    "message": user_text,
                    "resource_composer_intent": {
                        "mode": "cards",
                        "resource_ids": ["resource-note-1"],
                    },
                    "use_agent_loop": False,
                },
            )

        assert response.status_code == 200, response.text
        coaching_reply.assert_awaited_once()
        assert coaching_reply.await_args.args[1] == user_text
        coach_context = coaching_reply.await_args.kwargs["coach_context"]
        assert coach_context["resource_composer_intent"] == {
            "mode": "cards",
            "resource_ids": ["resource-note-1"],
        }
        build_requested_context.assert_not_called()
        reply_content = str(((response.json().get("reply") or {}).get("content")) or "")
        assert "resource_composer" not in reply_content
        assert "Here is one candidate" in reply_content
        persisted_plan = runtime.repository.get_latest_plan(workspace_id)
        assert persisted_plan is not None
        assert persisted_plan.model_dump() == seeded_plan.model_dump()


@pytest.mark.parametrize("path", ["/turn", "/turn/stream"])
def test_resources_intent_uses_grounded_coach_flow_for_both_turn_routes(
    tmp_path: Path,
    path: str,
) -> None:
    workspace_id = f"workspace-resource-intent-{path.rsplit('/', 1)[-1]}"
    payload = {
        "workspace_id": workspace_id,
        "message": "Organize the selected resources.",
        "intent": "resources",
        "active_view": "resources",
        "resource_composer_intent": {
            "mode": "organize",
            "resource_ids": [],
        },
        "use_agent_loop": False,
    }

    async def resource_stream(*_args: object, **_kwargs: object):
        yield "Resources lane response."

    with build_client(tmp_path) as client:
        if path == "/turn/stream":
            runtime = client.app.state.runtime
            provider = ProviderConfig(
                name="resource-composer-stream-test",
                base_url="http://127.0.0.1:9/v1",
                api_key_ref="trainer.resource-composer",
                model="gpt-4o-mini",
                capabilities={"chat": True, "tools": True, "streaming": True},
            )
            runtime.provider_config = provider
            runtime.provider_api_key = "sk-test-fake"
            runtime.provider_service = ProviderService(config=provider, api_key="sk-test-fake")
            runtime.provider_service_cache.clear()
            mark_provider_capabilities_verified(runtime, provider, "sk-test-fake", tools=True)
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value="Resources lane response."),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_stream",
                new=resource_stream,
            ),
        ):
            response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    if path == "/turn":
        assert response.json()["intent"] == "resources"
    else:
        assert 'event: complete' in response.text
        assert '"intent": "resources"' in response.text


def test_explicit_resource_ids_build_attachment_context(tmp_path: Path) -> None:
    workspace_id = "workspace-explicit-resource-ids"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Explicit resource IDs"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value="I will use the attached source only when it is available."),
            ),
            patch.object(
                runtime.resource_service,
                "build_requested_resource_context",
                wraps=runtime.resource_service.build_requested_resource_context,
            ) as build_requested_context,
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "coach",
                    "message": "Use the attached source for this answer.",
                    "resource_ids": ["resource-note-1"],
                    "use_agent_loop": False,
                },
            )

    assert response.status_code == 200, response.text
    build_requested_context.assert_any_call(workspace_id, ["resource-note-1"])
