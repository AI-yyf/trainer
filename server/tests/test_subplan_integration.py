"""Integration tests: SubPlan wired into PlannerService and MemoryService.snapshot()."""
from pathlib import Path

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import (
    EvidenceItem,
    LearningPlan,
    PlanStage,
    ProviderConfig,
    SubPlan,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path, *, configure_provider: bool = True) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    app = create_app(settings)
    if configure_provider:
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


# ---------------------------------------------------------------------------
# Test 1: snapshot() includes sub-plans when plan has sub-plans
# ---------------------------------------------------------------------------

def test_snapshot_includes_subplans(tmp_path: Path) -> None:
    """Create parent plan + sub-plan with 2 stages, call snapshot,
    assert subplans list contains the sub-plan."""
    with build_client(tmp_path) as client:
        # Start session
        start_resp = client.post("/session/start", json={
            "workspace_id": "ws-int-1",
            "workspace_name": "ws-int-1",
        })
        assert start_resp.status_code == 200
        start_data = start_resp.json()
        session_id = start_data.get("session_id")

        # Create a plan (pass session_id in payload)
        plan = LearningPlan(
            id="integration-plan-1",
            title="Integration Master Plan",
            stages=[
                PlanStage(id="s1", title="Foundation", goal="Build base", outcomes=["o1"]),
                PlanStage(id="s2", title="Practice", goal="Repeat", outcomes=["o2"]),
            ],
        )
        plan_payload = plan.model_dump(mode="json")
        plan_payload["session_id"] = session_id
        gen_resp = client.post("/plan/generate", json=plan_payload)
        assert gen_resp.status_code in (200, 201)
        plan_id = gen_resp.json().get("id", "integration-plan-1")

        # Create sub-plan with 2 stages
        sub = SubPlan(
            title="Sub: React Hooks",
            description="Learn useEffect patterns",
            stages=[
                PlanStage(id="sub-s1", title="useEffect", goal="Master useEffect", outcomes=["o1"]),
                PlanStage(id="sub-s2", title="useCallback", goal="Master useCallback", outcomes=["o2"]),
            ],
        )
        sub_resp = client.post(f"/plan/{plan_id}/subplan", json=sub.model_dump(mode="json"))
        assert sub_resp.status_code == 200

        # Call snapshot via memory summary endpoint (use session_id)
        snap_resp = client.get("/memory/summary", params={"session_id": session_id})
        assert snap_resp.status_code == 200
        data = snap_resp.json()

        # Assert subplans are included in the memory sub-object
        memory = data.get("memory", {})
        subplans = memory.get("subplans")
        assert subplans is not None, "memory.subplans should not be None"
        assert len(subplans) >= 1
        titles = [sp["title"] for sp in subplans]
        assert "Sub: React Hooks" in titles


# ---------------------------------------------------------------------------
# Test 2: evaluate_subplan_progress updates progress_percent
# ---------------------------------------------------------------------------

def test_evaluate_subplan_progress_advances(tmp_path: Path) -> None:
    """Create evidence targeting sub-plan stage, evaluate progress,
    assert progress_percent > 0."""
    with build_client(tmp_path) as client:
        start_resp = client.post("/session/start", json={
            "workspace_id": "ws-int-2",
            "workspace_name": "ws-int-2",
        })
        assert start_resp.status_code == 200
        session_id = start_resp.json().get("session_id")

        # Create parent plan (pass session_id in payload)
        plan = LearningPlan(
            id="integration-plan-2",
            title="Plan 2",
            stages=[
                PlanStage(id="pa", title="Alpha", goal="Do alpha", outcomes=["a1"]),
                PlanStage(id="pb", title="Beta", goal="Do beta", outcomes=["b1"]),
            ],
        )
        plan_payload = plan.model_dump(mode="json")
        plan_payload["session_id"] = session_id
        gen_resp = client.post("/plan/generate", json=plan_payload)
        plan_id = gen_resp.json().get("id", "integration-plan-2")

        # Create sub-plan with 2 stages
        sub = SubPlan(
            title="Sub: State Mgmt",
            description="State management patterns",
            stages=[
                PlanStage(id="ss1", title="useState", goal="Master useState", outcomes=["o1"]),
                PlanStage(id="ss2", title="useReducer", goal="Master useReducer", outcomes=["o2"]),
            ],
        )
        sub_resp = client.post(f"/plan/{plan_id}/subplan", json=sub.model_dump(mode="json"))
        assert sub_resp.status_code == 200

        # Enqueue evidence that targets the first stage concept
        evidence = EvidenceItem(
            source="evaluation",
            summary="User passed useState exercise",
            concepts=["useState"],
            outcome="pass",
            confidence=0.9,
        )
        ev_payload = evidence.model_dump(mode="json")
        ev_payload["workspace_id"] = "ws-int-2"
        ev_resp = client.post(
            "/evidence/enqueue",
            json=ev_payload,
        )
        assert ev_resp.status_code == 200
        evidence_id = ev_resp.json().get("id", "")

        # Adopt evidence to trigger plan evaluation
        if evidence_id:
            client.post(
                "/evidence/adopt",
                json={"evidence_id": evidence_id, "workspace_id": "ws-int-2"},
            )

        # Use the runtime service so the query exercises the same persistent store as the API.
        svc = client.app.state.runtime.planner_service

        # Fetch the subplans for this plan
        subplans = svc.get_subplans_for_plan(plan_id)
        assert len(subplans) == 1

        # Evaluate with evidence
        result = svc.evaluate_subplan_progress(subplans[0], [evidence])
        assert result.progress_percent > 0.0, (
            f"Expected progress_percent > 0, got {result.progress_percent}"
        )
        # With 2 stages and 1 matched, should be ~50%
        assert result.progress_percent >= 50.0


# ---------------------------------------------------------------------------
# Test 3: get_subplans_for_plan returns correct list
# ---------------------------------------------------------------------------

def test_get_subplans_for_plan_returns_correct_list(tmp_path: Path) -> None:
    """PlannerService.get_subplans_for_plan returns correct list."""
    with build_client(tmp_path) as client:
        start_resp = client.post("/session/start", json={
            "workspace_id": "ws-int-3",
            "workspace_name": "ws-int-3",
        })
        assert start_resp.status_code == 200
        session_id = start_resp.json().get("session_id")

        # Create parent plan (pass session_id in payload)
        plan = LearningPlan(
            id="integration-plan-3",
            title="Plan 3",
            stages=[PlanStage(id="sx", title="X", goal="Do X", outcomes=["x1"])],
        )
        plan_payload = plan.model_dump(mode="json")
        plan_payload["session_id"] = session_id
        gen_resp = client.post("/plan/generate", json=plan_payload)
        plan_id = gen_resp.json().get("id", "integration-plan-3")

        # Create 2 sub-plans
        sub_a = SubPlan(title="Sub A", description="First sub")
        sub_b = SubPlan(title="Sub B", description="Second sub")
        client.post(f"/plan/{plan_id}/subplan", json=sub_a.model_dump(mode="json"))
        client.post(f"/plan/{plan_id}/subplan", json=sub_b.model_dump(mode="json"))

        # Query via the runtime service backed by the test database.
        svc = client.app.state.runtime.planner_service
        subplans = svc.get_subplans_for_plan(plan_id)

        assert len(subplans) == 2
        titles = {sp.title for sp in subplans}
        assert titles == {"Sub A", "Sub B"}

        # Non-existent plan returns empty list
        empty = svc.get_subplans_for_plan("nonexistent-plan")
        assert empty == []
