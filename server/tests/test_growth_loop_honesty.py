"""After understand, Coach next stays first-look / honest omit — not a spoken invented object."""

from __future__ import annotations

from pathlib import Path

from app.core.models import ProviderConfig, UserProfile
from app.llm.prompts import build_coaching_system_prompt
from tests.test_api import build_client


def test_onboarding_suggested_actions_do_not_mint_plan_or_task(tmp_path: Path) -> None:
    project = tmp_path / "auth-expiry-lab"
    project.mkdir()
    (project / "auth.py").write_text(
        "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
        encoding="utf-8",
    )
    with build_client(tmp_path / "trainer-data") as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-honesty-onboarding",
                "workspace_name": "Auth expiry lab",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200
        started_body = started.json()
        started_memory = started_body.get("memory") or (started_body.get("snapshot") or {}).get("memory") or {}
        understanding = (
            started_memory.get("workspace_understanding")
            or started_memory.get("workspaceUnderstanding")
            or {}
        )
        first_look = understanding.get("firstLookSummary") or understanding.get("first_look_summary") or {}
        first_look_next = str(
            first_look.get("recommendedNextStep") or first_look.get("recommended_next_step") or ""
        ).strip()
        assert first_look_next
        session_id = started_body.get("session_id") or started_body.get("sessionId")
        assert session_id
        state = client.app.state.runtime.get_session(str(session_id))
        assert state is not None
        state.snapshot.provider = ProviderConfig(
            name="ready-provider",
            baseUrl="http://example.test/v1",
            apiKeyRef="ready-ref",
            model="ready-model",
        )
        state.snapshot.sidecar_status = "ready"

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-honesty-onboarding",
                "intent": "coach",
                "message": (
                    "My long-term goal is to become a stronger backend engineer. "
                    "Please understand this project first and guide me step by step."
                ),
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["coach_turn"]["scenario"] in {"onboarding", "general"}
        actions = [str(item.get("action") or "") for item in payload.get("suggested_actions") or []]
        labels = " ".join(str(item.get("label") or "") for item in payload.get("suggested_actions") or [])
        assert actions
        assert all(action == "hint" for action in actions)
        assert "task" not in actions
        assert "next_task" not in actions
        assert "plan" not in actions
        assert "Build my long-term training plan" not in labels
        assert "长期训练计划" not in labels
        assert "Continue from this first look" in labels or first_look_next[:40] in labels
        next_step = str(
            payload["coach_turn"].get("next_step") or payload["coach_turn"].get("nextStep") or ""
        ).strip()
        lowered_next = next_step.lower()
        assert "generate a plan" not in lowered_next
        assert "training card" not in lowered_next
        assert payload.get("plan") in (None, {})
        assert not (payload.get("current_task") or payload.get("currentTask") or {}).get("title")


def test_growth_loop_honesty_prompt_uses_first_look_and_does_not_invite_mint() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn auth expiry", weekly_hours=5),
        "en-US",
        "guided",
        message="Help me understand this project first.",
        coach_context={
            "scenario": "onboarding",
            "workspace_understanding": {
                "first_look_summary": {
                    "recommended_next_step": "Add a token expiry test",
                }
            },
        },
    )
    assert "## Growth Loop Honesty" in prompt
    assert "Do not speak as if you created a learning plan" in prompt
    assert "The next step is the first-look recommended next: Add a token expiry test" in prompt
    assert "## Formal Plan Turn" not in prompt


def test_explicit_formal_plan_turn_skips_growth_loop_honesty_block() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn auth expiry", weekly_hours=5),
        "en-US",
        "guided",
        message="Generate a formal learning plan.",
        coach_context={"formal_plan_mutation": True},
    )
    assert "## Formal Plan Turn" in prompt
    assert "## Growth Loop Honesty" not in prompt


def test_pressure_blocks_keeps_growth_honesty_even_for_chat_card_ask() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn auth expiry", weekly_hours=5),
        "en-US",
        "guided",
        message="Create a practice card for token refresh.",
        coach_context={
            "explicit_training_card_request": True,
            "pressure_blocks_live_object_mint": True,
        },
    )
    assert "## Growth Loop Honesty" in prompt
    assert "hint-only" in prompt
    assert "Do not invent or mint a LearningPlan" in prompt


def test_chat_card_ask_keeps_growth_honesty_without_pressure() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn auth expiry", weekly_hours=5),
        "en-US",
        "guided",
        message="Create a practice card for token refresh.",
        coach_context={
            "explicit_training_card_request": True,
        },
    )
    assert "## Growth Loop Honesty" in prompt
    assert "POST /training/generate-card" in prompt
    assert "Do not invent a card_id" in prompt


def test_diagnose_turn_does_not_mint_plan_or_task(tmp_path: Path) -> None:
    project = tmp_path / "auth-expiry-lab"
    project.mkdir()
    (project / "auth.py").write_text(
        "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
        encoding="utf-8",
    )
    with build_client(tmp_path / "trainer-data") as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-honesty-diagnose",
                "workspace_name": "Auth expiry lab",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200
        started_body = started.json()
        session_id = started_body.get("session_id") or started_body.get("sessionId")
        assert session_id
        assert started_body.get("plan") in (None, {})
        state = client.app.state.runtime.get_session(str(session_id))
        assert state is not None
        state.snapshot.provider = ProviderConfig(
            name="ready-provider",
            baseUrl="http://example.test/v1",
            apiKeyRef="ready-ref",
            model="ready-model",
        )
        state.snapshot.sidecar_status = "ready"

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-honesty-diagnose",
                "intent": "coach",
                "message": (
                    "Help me diagnose why auth.py fails before we generate a plan or a task."
                ),
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["coach_turn"]["scenario"] in {"review", "debug_loop", "general", "onboarding"}
        assert payload["coach_turn"]["scenario"] != "principle"
        actions = [str(item.get("action") or "") for item in payload.get("suggested_actions") or []]
        labels = " ".join(str(item.get("label") or "") for item in payload.get("suggested_actions") or [])
        assert actions
        assert "task" not in actions
        assert "next_task" not in actions
        assert "plan" not in actions
        assert "Turn the principle into a tiny exercise" not in labels
        next_step = str(
            payload["coach_turn"].get("next_step") or payload["coach_turn"].get("nextStep") or ""
        ).strip()
        lowered_next = next_step.lower()
        assert "generate a plan" not in lowered_next
        assert "training card" not in lowered_next
        assert payload.get("plan") in (None, {})
        assert not (payload.get("current_task") or payload.get("currentTask") or {}).get("title")
        runtime = client.app.state.runtime
        assert runtime.repository.get_latest_plan("workspace-honesty-diagnose") is None


def test_teach_turn_after_diagnose_does_not_mint_a_task(tmp_path: Path) -> None:
    project = tmp_path / "auth-expiry-lab"
    project.mkdir()
    (project / "auth.py").write_text(
        "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
        encoding="utf-8",
    )
    with build_client(tmp_path / "trainer-data") as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-honesty-teach",
                "workspace_name": "Auth expiry lab",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200
        session_id = started.json().get("session_id") or started.json().get("sessionId")
        assert session_id
        state = client.app.state.runtime.get_session(str(session_id))
        assert state is not None
        state.snapshot.provider = ProviderConfig(
            name="ready-provider",
            baseUrl="http://example.test/v1",
            apiKeyRef="ready-ref",
            model="ready-model",
        )
        state.snapshot.sidecar_status = "ready"

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-honesty-teach",
                "intent": "coach",
                "message": (
                    "Explain the principle of fail-closed token checks. "
                    "Why must an empty token raise before we generate a task?"
                ),
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["coach_turn"]["scenario"] == "principle"
        actions = [str(item.get("action") or "") for item in payload.get("suggested_actions") or []]
        labels = " ".join(str(item.get("label") or "") for item in payload.get("suggested_actions") or [])
        assert actions
        assert all(action == "hint" for action in actions)
        assert "task" not in actions
        assert "next_task" not in actions
        assert "plan" not in actions
        assert "Turn the principle into a tiny exercise" not in labels
        assert "把这个原理转成一小道练习" not in labels
        assert payload.get("plan") in (None, {})
        assert not (payload.get("current_task") or payload.get("currentTask") or {}).get("title")
        assert client.app.state.runtime.repository.get_latest_plan("workspace-honesty-teach") is None
