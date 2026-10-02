from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.models import LearningPlan, PlanStage
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def make_app(tmp_path: Path):
    return create_app(AppSettings(app_name="Stage materials", host="127.0.0.1", port=8765,
        data_dir=tmp_path, database_name="materials.db", default_session_stage="intake",
        summary_message_limit=6, enable_network_fetch=False))


def seed(runtime, plan_id="plan-materials"):
    plan = LearningPlan(id=plan_id, title="List and tuple", current_step="Run two examples",
        stages=[PlanStage(id="stage-1", title="Mutability", goal="Compare mutations", outcomes=["Explain both outcomes"], status="active")])
    runtime.repository.save_plan("ws-materials", plan)
    runtime.memory_service.bind_explicit_generated_plan("ws-materials", plan)
    return plan


def body():
    return {"workspace_id": "ws-materials", "response_language": "zh-CN",
        "provider": {"name": "fixture", "baseUrl": "http://127.0.0.1:9/v1", "model": "saved-model",
                     "apiKeyRef": "fixture"}, "api_key": "fixture-secret"}


def payload(title="Guide"):
    return json.dumps({"materials": [{"kind": kind, "title": f"{title}-{kind}",
        "summary": "A real document", "content": "```python\nif True:\n    print(1)\n```"}
        for kind in ("study_guide", "cheat_sheet", "exercise_set", "code_examples")]})


def test_model_materials_reload_deduplicate_without_advancing_stage(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/session/start", json={"workspace_id": "ws-materials", "workspace_name": "Materials"})
        seed(app.state.runtime)
        with patch.object(ProviderService, "chat_completion", new=AsyncMock(return_value=payload())) as completion:
            generated = client.post("/plan/plan-materials/stages/stage-1/material/generate", json=body())
            assert generated.status_code == 200, generated.text
            assert completion.await_count == 1
            assert "zh-CN" in completion.await_args.args[0][-1]["content"]
        assert all(item["generationSource"] == "model" for item in generated.json()["materials"])
        assert app.state.runtime.repository.get_latest_plan("ws-materials").stages[0].status == "active"
        with patch.object(ProviderService, "chat_completion", new=AsyncMock(return_value=payload("New"))):
            client.post("/plan/plan-materials/stages/stage-1/material/generate", json=body())
        for response in (client.get("/plan/plan-materials/stages/stage-1/materials", params={"workspace_id": "ws-materials"}),
                         client.get("/memory/summary", params={"workspace_id": "ws-materials"})):
            data = response.json()
            materials = data.get("materials") or data["stageMaterials"]["stage-1"]
            assert len(materials) == 4
            assert all(item["title"].startswith("New") for item in materials)
    # New runtime exercises persisted assets, not the previous process's in-memory maps.
    with TestClient(make_app(tmp_path)) as client:
        restored = client.post("/session/start", json={"workspace_id": "ws-materials", "workspace_name": "Materials"})
        assert len(restored.json()["stageMaterials"]["stage-1"]) == 4


def test_materials_are_owned_by_plan_even_when_stage_ids_are_reused(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        runtime = client.app.state.runtime
        seed(runtime)
        with patch.object(ProviderService, "chat_completion", new=AsyncMock(return_value=payload())):
            client.post("/plan/plan-materials/stages/stage-1/material/generate", json=body())
        seed(runtime, "replacement")
        assert client.get("/plan/plan-materials/stages/stage-1/materials", params={"workspace_id": "ws-materials"}).status_code == 404
        response = client.get("/plan/replacement/stages/stage-1/materials", params={"workspace_id": "ws-materials"})
        assert response.json()["materials"] == []
        assert client.get("/memory/summary", params={"workspace_id": "ws-materials"}).json()["stageMaterials"] == {}


def test_invalid_model_results_are_explicit_templates(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        seed(client.app.state.runtime)
        with patch.object(ProviderService, "chat_completion", new=AsyncMock(return_value="not json")):
            response = client.post("/plan/plan-materials/stages/stage-1/material/generate", json=body())
        assert response.status_code == 200, response.text
        assert len(response.json()["materials"]) == 4
        assert all(item["generationSource"] == "template" for item in response.json()["materials"])


def test_timeout_does_not_save_template_or_material(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        seed(client.app.state.runtime)
        with patch('app.pedagogy.stage_material_composer.StageMaterialComposer.compose_stage_materials',
                   new=AsyncMock(side_effect=TimeoutError("fixture-secret"))):
            response = client.post("/plan/plan-materials/stages/stage-1/material/generate", json=body())
        assert response.status_code == 504
        assert "fixture-secret" not in response.text
        assert client.app.state.runtime.memory_service.list_teaching_assets("ws-materials", limit=100) == []


def test_plan_replacement_during_generation_rejects_late_materials(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        runtime = client.app.state.runtime
        seed(runtime)
        async def replace_plan(self, **kwargs):
            seed(runtime, "replacement")
            return []
        with patch('app.pedagogy.stage_material_composer.StageMaterialComposer.compose_stage_materials',
                   new=replace_plan):
            response = client.post("/plan/plan-materials/stages/stage-1/material/generate", json=body())
        assert response.status_code == 404
        assert runtime.memory_service.list_teaching_assets("ws-materials", limit=100) == []
