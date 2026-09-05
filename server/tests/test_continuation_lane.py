from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from provider_fixtures import seed_verified_capabilities


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Continuation Lane Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    app = create_app(settings)
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
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
    runtime.provider_service_cache.clear()
    seed_verified_capabilities(runtime, provider, "sk-test", tools=False)
    return TestClient(app)


def test_turn_continuation_inherits_active_thread_scenario_across_mixed_lanes(
    tmp_path: Path,
) -> None:
    captured_context: dict[str, object] = {}

    async def fake_coaching_reply(*args, **kwargs) -> str:
        coach_context = kwargs.get("coach_context")
        if isinstance(coach_context, dict):
            captured_context.update(coach_context)
        return "Stay on the current adaptation lane and lock the first boundary before widening."

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-mixed-lane-continuation",
                "workspace_name": "trainer-mixed-lane-continuation",
                "profile": {
                    "long_term_goal": "Keep vague follow-ups attached to the right teaching lane",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        for seeded_scenario, focus_area, summary, next_step in (
            (
                "remote_workspace",
                "remote onboarding",
                "Kept the remote entry path narrow.",
                "Verify one host label before opening another remote path.",
            ),
            (
                "debug_loop",
                "launch diagnostics",
                "Pinned the first breakpoint branch.",
                "Re-run one launch target and inspect the first failing frame.",
            ),
            (
                "function_guidance",
                "signature help",
                "Read one function boundary instead of the whole module.",
                "Inspect the first call site and name one parameter contract.",
            ),
            (
                "project_adaptation",
                "adaptation boundary",
                "Kept the adaptation branch focused on one boundary.",
                "Protect the first boundary before widening the migration.",
            ),
        ):
            runtime.memory_service.record_turn_memory(
                workspace_id="workspace-mixed-lane-continuation",
                session_id=session_id,
                scenario=seeded_scenario,
                focus_area=focus_area,
                summary=summary,
                next_step=next_step,
                response_language="en-US",
                answer_mode="guided",
            )

        seeded_snapshot = runtime.memory_service.snapshot("workspace-mixed-lane-continuation")
        assert seeded_snapshot.active_thread is not None
        assert seeded_snapshot.active_thread.scenario == "project_adaptation"

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-mixed-lane-continuation",
                "intent": "coach",
                "message": "Continue.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200, response.text
    assert captured_context["scenario"] == "project_adaptation"
    active_thread = captured_context.get("active_thread")
    assert isinstance(active_thread, dict)
    assert active_thread["scenario"] == "project_adaptation"

    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "project_adaptation"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "project_adaptation"
    assert payload["snapshot"]["coaching_state"]["scenario"] == "project_adaptation"
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "project_adaptation"
