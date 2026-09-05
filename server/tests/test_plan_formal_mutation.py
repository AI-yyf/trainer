from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import (
    LearningPlan,
    PlanStage,
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            AppSettings(
                app_name="Trainer Formal Plan Mutation Test Server",
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


def seed_formal_plan(*, plan_id: str) -> LearningPlan:
    return LearningPlan(
        id=plan_id,
        title="Persisted formal plan",
        summary="Keep this plan unchanged until an explicit formal mutation is requested.",
        stages=[
            PlanStage(
                id="stage-foundation",
                title="Foundation",
                goal="Understand the existing planner boundary",
                outcomes=["Identify the authorization flag"],
                status="active",
            )
        ],
        current_stage_id="stage-foundation",
        current_step="Inspect the turn route before changing the plan.",
        next_after_current="Add the smallest regression test.",
    )


def configure_tool_capable_provider(runtime) -> None:
    provider = ProviderConfig(
        name="test-tool-provider",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.formal-plan-test",
        model="test-model",
        capabilities={"chat": True, "tools": True, "streaming": True},
    )
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
    runtime.provider_service_cache.clear()
    runtime.remember_provider_capability_test(
        provider,
        "sk-test",
        ProviderTestResponse(
            ok=True,
            detail="mocked provider capability test",
            capability_evidence=[
                ProviderCapabilityEvidence(
                    name="tools",
                    declared=True,
                    observed=True,
                    state="verified",
                ),
                ProviderCapabilityEvidence(
                    name="streaming",
                    declared=True,
                    observed=True,
                    state="verified",
                ),
            ],
            tools_ready=True,
            tool_probe_status="verified",
        ),
    )


def contains_cjk(text: object) -> bool:
    value = str(text or "")
    return any("\u4e00" <= char <= "\u9fff" for char in value)


@pytest.mark.asyncio
async def test_save_formal_plan_revises_existing_live_unfrozen_plan(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-revise-live"
    existing = seed_formal_plan(plan_id="plan-revise-live")

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Plan revise"},
        )
        assert started.status_code == 200, started.text
        runtime.repository.save_plan(workspace_id, existing)
        runtime.memory_service.bind_explicit_generated_plan(workspace_id, existing)
        result = await build_default_tool_registry().invoke(
            ToolContext(
                runtime=runtime,
                workspace_id=workspace_id,
                session_id=started.json()["session_id"],
                extra={"formal_plan_mutation": True, "allow_coach_only_tools": True},
            ),
            "save_formal_plan",
            {
                "title": "Revised login error plan",
                "summary": "Discussed the frozen path and narrowed the first stage.",
                "current_step": "Map one login error code to the visible message.",
                "verify_method": ["Wrong password shows the real return code."],
                "stages": [
                    {
                        "id": "stage-errors",
                        "title": "Error mapping",
                        "goal": "Map one login error code to the visible message.",
                        "outcomes": ["Wrong password shows the real return code."],
                        "status": "active",
                    },
                    {
                        "id": "stage-retry",
                        "title": "Retry path",
                        "goal": "Keep retry copy aligned with the mapped code.",
                        "outcomes": ["Retry stays on the same screen."],
                        "status": "pending",
                    },
                ],
            },
        )
        assert result.get("ok") is True, result
        assert result.get("committed") is True
        revised = runtime.repository.get_latest_plan(workspace_id)
        assert revised is not None
        assert revised.id == existing.id
        assert revised.title == "Revised login error plan"
        assert len(revised.stages) == 2
        assert revised.stages[0].title == "Error mapping"


def test_plan_discussion_without_explicit_mutation_stays_coaching_and_preserves_formal_plan(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-plan-discussion-only"
    seeded_plan = seed_formal_plan(plan_id="plan-discussion-only")

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)

        start_response = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Plan discussion only"},
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]

        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        state.snapshot.plan = seeded_plan.model_copy(deep=True)
        runtime.repository.save_plan(workspace_id, seeded_plan)
        runtime.memory_service.bind_explicit_generated_plan(workspace_id, seeded_plan)

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
                new=AsyncMock(return_value="Let us discuss the current plan without changing it."),
            ) as coaching_reply,
            patch.object(
                runtime.planner_service,
                "generate_plan",
                wraps=runtime.planner_service.generate_plan,
            ) as generate_plan,
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "plan",
                    "message": "Can we discuss the current plan before I change anything?",
                    "use_agent_loop": False,
                },
            )

        assert response.status_code == 200, response.text
        generate_plan.assert_not_called()
        coaching_reply.assert_awaited_once()

        response_plan = response.json()["snapshot"]["plan"]
        persisted_plan = runtime.repository.get_latest_plan(workspace_id)
        assert response_plan["id"] == seeded_plan.id
        assert response_plan["current_step"] == seeded_plan.current_step
        assert response_plan["title"] == seeded_plan.title
        assert (response_plan.get("workspace_id") or response_plan.get("workspaceId")) == workspace_id
        assert state.snapshot.plan is not None
        assert state.snapshot.plan.workspace_id == workspace_id
        assert state.snapshot.plan.id == seeded_plan.id
        assert state.snapshot.plan.current_step == seeded_plan.current_step
        assert state.snapshot.plan.model_dump() == seeded_plan.model_dump()
    assert persisted_plan is not None
    assert persisted_plan.workspace_id == workspace_id
    assert persisted_plan.model_dump() == seeded_plan.model_dump()


def test_plan_discussion_with_agent_loop_can_ground_in_resources_without_mutation(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-plan-agent-discussion"
    seeded_plan = seed_formal_plan(plan_id="plan-agent-discussion")

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)

        start_response = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Plan agent discussion"},
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]

        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        state.snapshot.plan = seeded_plan.model_copy(deep=True)
        runtime.repository.save_plan(workspace_id, seeded_plan)
        runtime.memory_service.bind_explicit_generated_plan(workspace_id, seeded_plan)

        async def model_discusses_with_grounding(*args: object, **kwargs: object) -> dict[str, object]:
            coach_context = kwargs["coach_context"]
            assert isinstance(coach_context, dict)
            assert coach_context.get("formal_plan_mutation") is not True
            tool_context = ToolContext(
                runtime=coach_context["__runtime__"],
                workspace_id=coach_context["workspace_id"],
                session_id=coach_context["session_id"],
                profile=args[0],
                response_language=kwargs.get("response_language"),
                extra={},
            )
            registry = build_default_tool_registry()
            plan_result = await registry.invoke(tool_context, "inspect_plan", {})
            resource_result = await registry.invoke(
                tool_context,
                "search_resources",
                {"query": "architecture", "mode": "broad", "limit": 3},
            )
            return {
                "content": "I checked the active plan and searched the resource library without changing the formal plan.",
                "summary": "The current plan is still the source of truth.",
                "next_step": "Confirm the learning scope before formal generation.",
                "stop_reason": "completed",
                "tool_events": [
                    {"type": "tool_result", "name": "inspect_plan", "result": plan_result},
                    {"type": "tool_result", "name": "search_resources", "result": resource_result},
                ],
                "fell_back": False,
            }

        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=model_discusses_with_grounding),
            ) as coaching_reply_agentic,
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(side_effect=AssertionError("discussion must stay in the Agent loop")),
            ),
            patch.object(
                runtime.planner_service,
                "generate_plan",
                wraps=runtime.planner_service.generate_plan,
            ) as generate_plan,
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "plan",
                    "message": "Discuss the current plan and search the resource library before changing it.",
                    "use_agent_loop": True,
                },
            )

        assert response.status_code == 200, response.text
        generate_plan.assert_not_called()
        coaching_reply_agentic.assert_awaited_once()
        payload = response.json()
        tool_events = payload["agent_meta"]["tool_events"]
        assert [event["name"] for event in tool_events] == ["inspect_plan", "search_resources"]
        response_plan = payload["snapshot"]["plan"]
        assert response_plan["id"] == seeded_plan.id
        persisted_plan = runtime.repository.get_latest_plan(workspace_id)
        assert persisted_plan is not None
        assert persisted_plan.model_dump() == seeded_plan.model_dump()


def test_explicit_formal_plan_mutation_alias_generates_and_persists_a_plan(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-formal-mutation"

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Formal plan mutation",
                "profile": {
                    "long_term_goal": "Learn FastAPI route design",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]

        async def model_commits_plan(*args, **kwargs):
            coach_context = kwargs["coach_context"]
            tool_context = ToolContext(
                runtime=coach_context["__runtime__"],
                workspace_id=coach_context["workspace_id"],
                session_id=coach_context["session_id"],
                profile=args[0],
                response_language=kwargs.get("response_language"),
                extra={
                    "formal_plan_mutation": True,
                    "allow_coach_only_tools": True,
                },
            )
            tool_result = await build_default_tool_registry().invoke(
                tool_context,
                "save_formal_plan",
                {
                    "title": "FastAPI route learning",
                    "summary": "Build a grounded route-design learning path from the live conversation.",
                    "current_step": "Inspect one route boundary and verify one request path.",
                    "verify_method": ["One focused endpoint test passes."],
                    "stages": [
                        {
                            "id": "stage-boundary",
                            "title": "Route boundary",
                            "goal": "Explain request validation and response ownership.",
                            "outcomes": ["Name the boundary", "Verify one request path"],
                            "resources": ["resource-route-notes"],
                            "status": "active",
                        }
                    ],
                },
            )
            assert tool_result["ok"] is True
            return {
                "content": "I used the current conversation and resource evidence to commit the formal plan.",
                "summary": "The route-boundary plan is committed.",
                "next_step": "Inspect one request path.",
                "stop_reason": "completed",
                "tool_events": [{"type": "tool_result", "name": "save_formal_plan", "result": tool_result}],
                "fell_back": False,
            }

        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=model_commits_plan),
            ) as coaching_reply_agentic,
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value="The authorized formal plan is ready for review."),
            ),
            patch.object(
                runtime.planner_service,
                "generate_plan",
                wraps=runtime.planner_service.generate_plan,
            ) as generate_plan,
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "plan",
                    "formalPlanMutation": True,
                    "message": "Create a formal learning plan for FastAPI route design.",
                    "goals": ["Learn FastAPI route design"],
                    "use_agent_loop": False,
                },
            )

        assert response.status_code == 200, response.text
        generate_plan.assert_not_called()
        coaching_reply_agentic.assert_awaited_once()

        response_plan = response.json()["snapshot"]["plan"]
        persisted_plan = runtime.repository.get_latest_plan(workspace_id)
        assert response.json()["intent"] == "plan"
        assert response_plan["title"] == "FastAPI route learning"
        assert response_plan["stages"][0]["resources"] == ["resource-route-notes"]
        formal_context = coaching_reply_agentic.call_args.kwargs["coach_context"]
        assert formal_context["formal_plan_mutation"] is True
    assert persisted_plan is not None
    assert persisted_plan.title == response_plan["title"]


def test_formal_plan_turn_without_save_tool_stays_uncommitted(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-missing-save-tool"
    seeded_plan = seed_formal_plan(plan_id="plan-missing-save-tool")

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)
        seed_verified_capabilities(
            runtime,
            runtime.provider_config,
            runtime.provider_api_key,
            tools=True,
        )
        start_response = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Missing save tool"},
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]
        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        state.snapshot.plan = seeded_plan.model_copy(deep=True)
        runtime.repository.save_plan(workspace_id, seeded_plan)
        runtime.memory_service.bind_explicit_generated_plan(workspace_id, seeded_plan)

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
                new=AsyncMock(return_value="The formal plan is saved and ready to start."),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(
                    return_value={
                        "content": "The formal plan is saved and ready to start.",
                        "summary": "The formal plan is saved and ready to start.",
                        "next_step": "Inspect the turn route.",
                        "stop_reason": "completed",
                        "tool_events": [],
                        "fell_back": False,
                    }
                ),
            ),
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "plan",
                    "formalPlanMutation": True,
                    "message": "Create the formal learning plan now.",
                    "use_agent_loop": False,
                },
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["agent_meta"]["formal_plan_commit"] == "missing"
        assert "not committed" in payload["reply"]["content"].lower()
        assert payload["snapshot"]["plan"]["id"] == seeded_plan.id
        persisted_plan = runtime.repository.get_latest_plan(workspace_id)

    assert persisted_plan is not None
    assert persisted_plan.model_dump() == seeded_plan.model_dump()


def test_generated_plan_localizes_zh_cn_stage_titles_and_verification(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-zh-cn-localization"

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Plan zh-cn localization",
                "profile": {
                    "long_term_goal": "Create a two-week TypeScript async error plan",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "response_language": "zh-CN",
                "answer_mode": "auto",
            },
        )
        assert settings_response.status_code == 200, settings_response.text

        response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Create a two-week TypeScript async error plan"],
                "constraints": ["Keep each stage reviewable"],
            },
        )

    assert response.status_code == 200, response.text
    plan_payload = response.json()["plan"]
    runtime_status = response.json()["plan_runtime_status"]
    assert plan_payload["title"].startswith("训练计划：")
    assert plan_payload["stages"][0]["title"] == "基础"
    assert plan_payload["stages"][1]["title"] == "练习"
    assert plan_payload["stages"][2]["title"] == "整合"
    assert plan_payload["current_step"].startswith("先落地围绕")
    assert plan_payload["verify_method"][0].startswith("实现一个可见切片来证明")
    assert runtime_status["current_stage"]["title"] == "基础"
    assert runtime_status["current_step"].startswith("先落地围绕")
    assert runtime_status["verify_method"][0].startswith("实现一个可见切片来证明")


def test_plan_update_localizes_coach_turn_and_suggested_actions_for_zh_cn(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-plan-update-zh-cn-localization"
    seeded_plan = seed_formal_plan(plan_id="plan-update-zh-cn-localization")

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)
        runtime.repository.save_plan(workspace_id, seeded_plan)

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Plan update zh-cn localization",
            },
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "response_language": "zh-CN",
                "answer_mode": "auto",
            },
        )
        assert settings_response.status_code == 200, settings_response.text

        response = client.post(
            "/plan/update",
            json={
                "plan_id": seeded_plan.id,
                "workspace_id": workspace_id,
                "instructions": "Rework the formal plan around async error handling.",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    coach_turn = payload["coach_turn"]
    assert contains_cjk(coach_turn["summary"])
    assert contains_cjk(coach_turn["encouragement"])
    assert contains_cjk(coach_turn["review_queue_summary"])
    assert all(contains_cjk(action["label"]) for action in payload["suggested_actions"])
    assert all(contains_cjk(action["rationale"]) for action in payload["suggested_actions"])
    assert all(contains_cjk(action["prompt"]) for action in payload["suggested_actions"])


def test_frozen_session_plan_cannot_be_replaced_by_generation(tmp_path: Path) -> None:
    workspace_id = "workspace-frozen-session-plan"
    frozen_plan = seed_formal_plan(plan_id="plan-frozen-session").model_copy(update={"frozen": True})

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)
        start_response = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Frozen session plan"},
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]
        runtime.repository.save_plan(workspace_id, frozen_plan)

        response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Replace the frozen plan"],
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "这条计划已冻结。先恢复为可编辑状态，再生成新的版本。"
    persisted_plan = runtime.repository.get_latest_plan(workspace_id)
    assert persisted_plan is not None
    assert persisted_plan.model_dump() == frozen_plan.model_dump()


def test_frozen_workspace_plan_cannot_be_replaced_by_direct_generation(tmp_path: Path) -> None:
    workspace_id = "workspace-frozen-direct-plan"
    frozen_plan = seed_formal_plan(plan_id="plan-frozen-direct").model_copy(update={"frozen": True})

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        configure_tool_capable_provider(runtime)
        runtime.repository.save_plan(workspace_id, frozen_plan)

        response = client.post(
            "/plan/generate",
            json={
                "workspace_id": workspace_id,
                "profile": UserProfile(long_term_goal="Replace the frozen plan").model_dump(mode="json"),
                "goals": ["Replace the frozen plan"],
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "This plan is frozen. Resume it before creating a new version."
    persisted_plan = runtime.repository.get_latest_plan(workspace_id)
    assert persisted_plan is not None
    assert persisted_plan.model_dump() == frozen_plan.model_dump()


def test_frozen_plan_rejects_direct_content_updates_until_explicit_resume(tmp_path: Path) -> None:
    workspace_id = "workspace-frozen-direct-update"
    frozen_plan = seed_formal_plan(plan_id="plan-frozen-direct-update").model_copy(
        update={"frozen": True}
    )

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.repository.save_plan(workspace_id, frozen_plan)

        blocked = client.post(
            "/plan/update",
            json={
                "plan_id": frozen_plan.id,
                "workspace_id": workspace_id,
                "title": "Replacement plan title",
                "instructions": "Rewrite the formal plan.",
                "frozen": True,
            },
        )

        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "This plan is frozen. Resume it before changing the formal plan."
        persisted_before_resume = runtime.repository.get_latest_plan(workspace_id)
        assert persisted_before_resume is not None
        assert persisted_before_resume.model_dump() == frozen_plan.model_dump()

        resumed = client.post(
            "/plan/update",
            json={
                "plan_id": frozen_plan.id,
                "workspace_id": workspace_id,
                "frozen": False,
            },
        )

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["plan"]["frozen"] is False
    persisted = runtime.repository.get_latest_plan(workspace_id)
    assert persisted is not None
    assert persisted.frozen is False
    assert persisted.title == frozen_plan.title
    assert persisted.summary == frozen_plan.summary
    assert persisted.current_step == frozen_plan.current_step


def test_frozen_plan_update_notice_uses_requested_language(tmp_path: Path) -> None:
    expected_messages = {
        "zh-CN": "这条计划已冻结。请先恢复为可编辑状态，再修改正式计划。",
        "en-US": "This plan is frozen. Resume it before changing the formal plan.",
        "es-ES": "Este plan está congelado. Reanúdalo antes de cambiar el plan principal.",
        "fr-FR": "Ce plan est gelé. Reprenez-le avant de modifier le plan principal.",
        "de-DE": "Dieser Plan ist eingefroren. Setzen Sie ihn fort, bevor Sie den Hauptplan ändern.",
        "ja-JP": "この計画は固定されています。正式な計画を変更する前に、再開してください。",
        "ko-KR": "이 계획은 고정되어 있습니다. 정식 계획을 바꾸기 전에 다시 시작하세요.",
        "pt-BR": "Este plano está congelado. Retome-o antes de alterar o plano principal.",
    }

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        for index, (response_language, expected_message) in enumerate(expected_messages.items()):
            workspace_id = f"workspace-frozen-localized-{index}"
            frozen_plan = seed_formal_plan(plan_id=f"plan-frozen-localized-{index}").model_copy(
                update={"frozen": True}
            )
            runtime.repository.save_plan(workspace_id, frozen_plan)

            response = client.post(
                "/plan/update",
                json={
                    "plan_id": frozen_plan.id,
                    "workspace_id": workspace_id,
                    "title": "Replacement plan title",
                    "response_language": response_language,
                },
            )

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == expected_message


def test_frozen_plan_ignores_explicit_formal_mutation_turn(tmp_path: Path) -> None:
    workspace_id = "workspace-frozen-turn-mutation"
    frozen_plan = seed_formal_plan(plan_id="plan-frozen-turn").model_copy(update={"frozen": True})

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.provider_config = None
        runtime.provider_api_key = None
        start_response = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Frozen turn plan"},
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]
        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        state.snapshot.plan = frozen_plan.model_copy(deep=True)
        runtime.repository.save_plan(workspace_id, frozen_plan)

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
                new=AsyncMock(return_value="Discuss the frozen plan without changing it."),
            ),
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "plan",
                    "formalPlanMutation": True,
                    "message": "Replace the current frozen plan.",
                    "response_language": "ja-JP",
                    "use_agent_loop": False,
                },
            )

    assert response.status_code == 200, response.text
    assert "この計画は固定されています。正式な計画を変更する前に、再開してください。" in response.json()["reply"][
        "content"
    ]
    persisted_plan = runtime.repository.get_latest_plan(workspace_id)
    assert persisted_plan is not None
    assert persisted_plan.model_dump() == frozen_plan.model_dump()


class _ScriptedSaveFormalPlanProvider:
    protocol = "openai_chat_completions"

    def __init__(self) -> None:
        self.calls = 0
        self.tools_seen: list[list[dict[str, Any]] | None] = []
        self.attachments_will_be_sent = lambda: False

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
                        "id": "auto-mint-understand-plan",
                        "name": "save_formal_plan",
                        "arguments": {
                            "title": "Ship one invented plan",
                            "summary": "The understand turn felt ready for a formal plan.",
                            "stages": [
                                {
                                    "title": "Invented stage",
                                    "goal": "Mint a plan the learner did not ask for.",
                                }
                            ],
                        },
                    }
                ],
            }
        return {
            "content": "Stay with the first-look next step. Do not invent a plan.",
            "tool_calls": [],
        }


def _training_provider_payload() -> dict[str, object]:
    return {
        "name": "deterministic-agent",
        "base_url": "https://provider.invalid/v1",
        "api_key_ref": "test-only",
        "model": "test-model",
        "protocol": "openai_chat_completions",
        "capabilities": {"tools": True, "streaming": False},
    }


def test_agent_loop_understand_turn_does_not_mint_via_save_formal_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _ScriptedSaveFormalPlanProvider()

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    workspace_id = "workspace-understand-no-agent-plan"
    with build_client(tmp_path) as client:
        seed_verified_capabilities(
            client.app.state.runtime,
            ProviderConfig.model_validate(_training_provider_payload()),
            "test-only-key",
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Understand without invented plan",
                "profile": {
                    "long_term_goal": "Understand first without inventing a plan",
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
                "message": (
                    "Help me understand this VS Code remote workspace first, then verify one tiny step."
                ),
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _training_provider_payload(),
                "api_key": "test-only-key",
            },
        )

        persisted_plan = client.app.state.runtime.repository.get_latest_plan(workspace_id)
        stored_cards = client.app.state.runtime.memory_service.get_cards(workspace_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    snapshot = payload["snapshot"]
    assert "save_formal_plan" not in {
        schema.get("function", {}).get("name")
        for schema in (scripted.tools_seen[0] or [])
    }
    assert persisted_plan is None
    assert snapshot.get("plan") in (None, {})
    assert snapshot.get("current_task") in (None, {})
    assert stored_cards == []
    assert snapshot["memory"]["active_training_card_routing"] is None
    title = str((snapshot.get("plan") or {}).get("title") or "")
    assert title != "Ship one invented plan"
    orientation = snapshot.get("coach_orientation") or snapshot.get("coachOrientation") or {}
    assert orientation.get("primary_action") != "generate_plan"
    assert "Ship one invented plan" not in str(orientation.get("next_step") or "")
    status = snapshot.get("plan_runtime_status") or snapshot.get("planRuntimeStatus") or {}
    next_action = str(
        status.get("next_training_action") or status.get("nextTrainingAction") or ""
    )
    assert next_action != "Ship one invented plan"
    assert not next_action.startswith("Continue:")


def test_high_urgency_chat_save_this_plan_does_not_commit_without_formal_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """High urgency + agent tools + chat 'save this plan' must not mint LearningPlan.

    formal_plan_mutation stays required; explicit intent=plan + formalPlanMutation
    still binds (see test_explicit_formal_plan_mutation_under_high_urgency_keeps_mutation_flag).
    """
    scripted = _ScriptedSaveFormalPlanProvider()

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    workspace_id = "workspace-urgency-chat-save-no-plan"
    urgent_save = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Please save this plan for token refresh."
    )
    with build_client(tmp_path) as client:
        seed_verified_capabilities(
            client.app.state.runtime,
            ProviderConfig.model_validate(_training_provider_payload()),
            "test-only-key",
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Urgency chat save without formal mutation",
                "profile": {
                    "long_term_goal": "Ship token refresh without silent plan mint",
                    "weekly_hours": 2,
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
                "message": urgent_save,
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _training_provider_payload(),
                "api_key": "test-only-key",
            },
        )

        persisted_plan = client.app.state.runtime.repository.get_latest_plan(workspace_id)
        stored_cards = client.app.state.runtime.memory_service.get_cards(workspace_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    snapshot = payload["snapshot"]
    adaptation = (snapshot.get("memory") or {}).get("coaching_adaptation") or {}
    assert adaptation.get("task_urgency") == "high"
    tool_names = {
        schema.get("function", {}).get("name")
        for schema in (scripted.tools_seen[0] or [])
        if isinstance(schema, dict)
    }
    assert "save_formal_plan" not in tool_names
    assert persisted_plan is None
    assert snapshot.get("plan") in (None, {})
    assert snapshot.get("current_task") in (None, {})
    assert stored_cards == []
    title = str((snapshot.get("plan") or {}).get("title") or "")
    assert title != "Ship one invented plan"
