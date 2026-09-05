from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.llm.provider_service import ProviderService
from tests.test_api import build_client


def test_session_keeps_full_history_and_force_new_starts_a_fresh_thread(tmp_path: Path) -> None:
    workspace_id = "workspace-unlimited-history"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Unlimited history",
                "profile": {
                    "long_term_goal": "Keep every coaching turn until the learner starts over",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        with patch.object(ProviderService, "coaching_reply", autospec=True) as coaching_reply:
            coaching_reply.return_value = "记下这一轮，稍后还会用到。"
            for index in range(20):
                response = client.post(
                    "/session/message",
                    json={
                        "session_id": session_id,
                        "workspace_id": workspace_id,
                        "message": f"marker-{index} ECONNREFUSED-锚点-7731 keep this turn",
                        "response_language": "zh-CN",
                    },
                )
                assert response.status_code == 200, response.text

        restored = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Unlimited history",
            },
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["session_id"] == session_id
        messages = restored.json().get("messages") or []
        user_contents = [str(item.get("content") or "") for item in messages if item.get("role") == "user"]
        assert len(user_contents) >= 20
        assert any("marker-0" in content for content in user_contents)
        assert any("marker-19" in content for content in user_contents)
        assert any("ECONNREFUSED-锚点-7731" in content for content in user_contents)

        fresh = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Unlimited history",
                "force_new": True,
            },
        )
        assert fresh.status_code == 200, fresh.text
        assert fresh.json()["session_id"] != session_id
        fresh_messages = fresh.json().get("messages") or []
        assert not any("marker-19" in str(item.get("content") or "") for item in fresh_messages)
        assert not any("ECONNREFUSED-锚点-7731" in str(item.get("content") or "") for item in fresh_messages)


def test_force_new_does_not_drop_the_live_plan(tmp_path: Path) -> None:
    from app.core.models import LearningPlan, PlanStage

    workspace_id = "workspace-force-new-keeps-plan"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Force new keeps plan"},
        )
        assert started.status_code == 200, started.text
        runtime = client.app.state.runtime
        plan = LearningPlan(
            id="plan-force-new-keep",
            title="Keep this live plan across a new conversation",
            current_step="Stay on the current stage",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Current",
                    goal="Stay on the current stage",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime.repository.save_plan(workspace_id, plan)
        runtime.memory_service.bind_explicit_generated_plan(workspace_id, plan)

        fresh = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Force new keeps plan",
                "force_new": True,
            },
        )

    assert fresh.status_code == 200, fresh.text
    restored_plan = fresh.json().get("plan") or {}
    assert str(restored_plan.get("id") or restored_plan.get("plan_id") or "") == plan.id
    assert not any(
        "Stay on the current stage" in str(item.get("content") or "")
        for item in (fresh.json().get("messages") or [])
        if item.get("role") == "user"
    )
