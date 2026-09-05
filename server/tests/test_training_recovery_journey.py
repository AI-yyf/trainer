"""Deterministic recovery coverage for a full Learn-first training journey."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.evaluator.models import CheckCommand, CheckResult, CheckStatus
from app.evaluator.service import EvaluationPipeline, EvaluatorService
from app.llm.provider_service import ProviderService
from app.main import create_app


class _DeterministicRunner:
    def __init__(self, pytest_status: CheckStatus = CheckStatus.PASSED) -> None:
        self._pytest_status = pytest_status

    def run(self, command: CheckCommand) -> CheckResult:
        status = self._pytest_status if command.name == "pytest" else CheckStatus.PASSED
        return CheckResult(
            name=command.name,
            status=status,
            command=command.argv,
            summary=f"{command.name} {status.value} in deterministic journey runner.",
        )


class _ScriptedAgentProvider:
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
                        "id": "create-learn-first-card",
                        "name": "generate_training_card",
                        "arguments": {
                            "focus_area": "query normalization",
                            "target_skill": "implement normalize_query",
                            "card_type": "practice",
                            "why_now": "One small verified search behavior is the current gap.",
                        },
                    }
                ],
            }
        return {
            "content": "I prepared one learn-first practice step. Implement it, verify the current file, then reflect before returning.",
            "tool_calls": [],
        }


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer training recovery journey test",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer.db",
        default_session_stage="intake",
        summary_message_limit=6,
    )


def _patch_agent_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> _ScriptedAgentProvider:
    scripted = _ScriptedAgentProvider()

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    return scripted


def _patch_card_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    async def chat_completion(*_args: Any, **_kwargs: Any) -> str:
        return json.dumps(
            {
                "title": "Practice: query normalization",
                "focus_area": "query normalization",
                "target_skill": "implement normalize_query",
                "scenario": "A search helper receives user input before querying.",
                "problem_statement": "Implement normalize_query so equivalent input reaches one search path.",
                "api_hints": ["strip()", "lower()"],
                "deliverable": "A small normalize_query implementation.",
                "self_check": ["Whitespace is removed", "Case is normalized"],
                "grading_rubric": ["Returns normalized text", "Keeps the change focused"],
                "stuck_recovery": "Start with one input and inspect the returned string.",
                "reflection_prompt": "Which input difference did normalization remove?",
                "verification_steps": ["Run one mixed-case input", "Confirm the normalized output"],
                "success_signal": "The same logical query produces one normalized value.",
                "return_with": "The implementation and one observed verification result.",
                "learner_deliverables": ["The current-file implementation", "One verification result"],
            }
        )

    monkeypatch.setattr(ProviderService, "chat_completion", chat_completion)


def _training_provider_payload() -> dict[str, object]:
    return {
        "name": "deterministic-agent",
        "base_url": "https://provider.invalid/v1",
        "api_key_ref": "test-only",
        "model": "test-model",
        "protocol": "openai_chat_completions",
        "capabilities": {"tools": True, "streaming": False},
    }


def test_agent_card_current_file_recovery_reflect_and_return_are_continuous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "training-recovery-journey"
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    file_path = workspace_path / "query_tools.py"
    source = "def normalize_query(value: str) -> str:\n    return value.strip().lower()\n"
    file_path.write_text(source, encoding="utf-8")

    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)
    training_provider = ProviderConfig.model_validate(_training_provider_payload())
    app.state.runtime.provider_config = training_provider
    app.state.runtime.provider_api_key = "test-only-key"
    app.state.runtime.provider_service = ProviderService(
        config=training_provider,
        api_key="test-only-key",
    )
    app.state.runtime.provider_service_cache.clear()
    seed_verified_capabilities(app.state.runtime, training_provider, "test-only-key")
    app.state.runtime.evaluator_service = EvaluatorService(
        pipeline=EvaluationPipeline(runner=_DeterministicRunner(CheckStatus.SKIPPED))
    )
    assert app.state.runtime.card_generation_service is not None
    app.state.runtime.card_generation_service._provider = None
    _patch_card_provider(monkeypatch)
    scripted = _patch_agent_provider(monkeypatch)

    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Recovery journey",
                "workspace_path": str(workspace_path),
                "profile": {
                    "long_term_goal": "Build reliable search behavior",
                    "weekly_hours": 4,
                    "teaching_style": "hands-on",
                    "answer_policy": "guided",
                },
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        generated_plan = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Build one verified query normalization behavior"],
                "constraints": ["Keep the first exercise small and observable"],
            },
        )
        assert generated_plan.status_code == 200, generated_plan.text
        plan_id = generated_plan.json()["plan"]["id"]

        # Composer chat/ReAct must not mint; explicit HTTP generate-card binds the live id.
        card_resp = client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_id,
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "query normalization",
                "target_skill": "implement normalize_query",
                "context_hint": "One small verified search behavior is the current gap.",
                "response_language": "en-US",
            },
        )
        assert card_resp.status_code == 200, card_resp.text
        card_payload = card_resp.json()
        assert card_payload.get("success") is True
        created_card = card_payload["card"]
        card_id = created_card["card_id"]
        learning_loop = created_card["learning_loop"]
        assert created_card["card_type"] == "practice"
        assert learning_loop["completion_requires_verification"] is True
        assert all(learning_loop[key] for key in ("learn", "try", "verify", "reflect", "return"))
        assert (
            client.app.state.runtime.memory_service.live_selected_training_card_id(workspace_id)
            == card_id
        )

        # Chat "create a card" with agent loop must not mint/clobber the live card.
        agent_turn = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "Create a learn-first training card for query normalization before I widen this search work.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _training_provider_payload(),
                "api_key": "test-only-key",
            },
        )
        assert agent_turn.status_code == 200, agent_turn.text
        agent_body = agent_turn.json()
        assert "generate_training_card" not in {
            schema.get("function", {}).get("name")
            for schemas in scripted.tools_seen
            for schema in (schemas or [])
        }
        # Scripted provider may still *attempt* a tool call; result must not mint/clobber.
        for event in (agent_body.get("agent_meta") or {}).get("tool_events") or []:
            if event.get("name") == "generate_training_card" and event.get("type") == "tool_result":
                result = event.get("result") or {}
                assert result.get("ok") is False
        assert (
            client.app.state.runtime.memory_service.live_selected_training_card_id(workspace_id)
            == card_id
        )
        assert len(client.app.state.runtime.memory_service.get_cards(workspace_id)) == 1

        evaluation_request = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "file_path": str(file_path),
            "language_id": "python",
            "content": source,
            "diagnostics": [],
            "evaluation_source": "training",
            "training_card_id": card_id,
            "training_card_title": created_card["title"],
            "acceptance_criteria": ["Implement normalize_query for user input."],
            "learner_deliverables": ["A current-file implementation of normalize_query."],
            "expected_symbols": ["normalize_query"],
        }
        skipped_evaluation = client.post("/evaluate/current-file", json=evaluation_request)
        assert skipped_evaluation.status_code == 200, skipped_evaluation.text
        skipped_payload = skipped_evaluation.json()
        assert skipped_payload["passed"] is False
        assert "Verification is still required" in skipped_payload["summary"]
        assert "Run at least one dynamic verifier" in skipped_payload["next_step"]

        before_restart = client.get("/memory/summary", params={"session_id": session_id})
        assert before_restart.status_code == 200, before_restart.text
        before_snapshot = before_restart.json()
        before_workspace = before_snapshot["memory"]["workspace"]
        before_next_hop = before_workspace["latest_training_next_hop"]

        assert before_snapshot["plan"]["id"] == plan_id
        assert any(
            card["card_id"] == card_id for card in before_snapshot["memory"]["training_card_candidates"]
        )
        assert before_snapshot["memory"]["active_training_card_routing"]["selected_card_id"] == card_id
        assert before_workspace["selected_card_status"] != "implemented"
        assert before_workspace["latest_learning_outcome"] == "verification_pending"
        assert before_next_hop["status"] == "verification_required"

        app.state.runtime.evaluator_service = EvaluatorService(
            pipeline=EvaluationPipeline(runner=_DeterministicRunner())
        )
        evaluated = client.post("/evaluate/current-file", json=evaluation_request)
        assert evaluated.status_code == 200, evaluated.text
        assert evaluated.json()["passed"] is True

        before_restart = client.get("/memory/summary", params={"session_id": session_id})
        assert before_restart.status_code == 200, before_restart.text
        before_snapshot = before_restart.json()
        before_workspace = before_snapshot["memory"]["workspace"]
        before_handoff = before_workspace["latest_training_handoff"]
        before_next_hop = before_workspace["latest_training_next_hop"]
        handoff_id = before_handoff["handoff_id"]

        assert before_snapshot["plan"]["id"] == plan_id
        assert before_handoff["card_id"] == card_id
        assert before_handoff["learning_phase"] == "verify"
        assert before_handoff["verification_state"] == "verified"
        assert before_handoff["evidence"][0]["verified"] is True
        assert before_next_hop["status"] == "reflection_required"
        assert before_next_hop["handoff_id"] == handoff_id
        evidence_id = before_handoff["evidence"][0]["id"]
        plan_stage_id = before_snapshot["plan"]["current_stage_id"]

    rebuilt_app = create_app(settings)
    with TestClient(rebuilt_app) as rebuilt_client:
        restored = rebuilt_client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert restored.status_code == 200, restored.text
        restored_snapshot = restored.json()
        restored_memory = restored_snapshot["memory"]
        restored_workspace = restored_memory["workspace"]
        restored_handoff = restored_workspace["latest_training_handoff"]

        assert restored_snapshot["plan"]["id"] == plan_id
        assert restored_snapshot["plan"]["current_stage_id"] == plan_stage_id
        assert restored_memory["active_training_card_routing"]["selected_card_id"] == card_id
        assert any(
            card["card_id"] == card_id for card in restored_memory["training_card_candidates"]
        )
        assert restored_handoff["handoff_id"] == handoff_id
        assert restored_handoff["learning_phase"] == "verify"
        assert restored_handoff["evidence"][0]["id"] == evidence_id
        assert restored_handoff["evidence"][0]["verified"] is True
        assert restored_workspace["latest_training_next_hop"]["status"] == "reflection_required"
        assert restored_workspace["latest_training_next_hop"]["handoff_id"] == handoff_id

        reflected = rebuilt_client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_id,
                "card_id": card_id,
                "handoff_id": handoff_id,
                "reflection": "The current-file check proved that normalization happens before search branching.",
            },
        )
        assert reflected.status_code == 200, reflected.text
        assert reflected.json()["workspace"]["latest_training_handoff"]["learning_phase"] == "reflect"
        assert reflected.json()["workspace"]["latest_training_next_hop"]["status"] == "return_required"

        returned = rebuilt_client.post(
            "/training/return",
            json={"workspace_id": workspace_id, "card_id": card_id, "handoff_id": handoff_id},
        )
        assert returned.status_code == 200, returned.text
        returned_workspace = returned.json()["workspace"]
        assert returned_workspace["latest_training_handoff"]["learning_phase"] == "return"
        assert returned_workspace["latest_training_handoff"]["status"] == "completed"
        assert returned_workspace["selected_card_status"] == "implemented"
        assert returned_workspace["latest_training_next_hop"]["status"] == "continued_in_chat"

        completed = rebuilt_client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert completed.status_code == 200, completed.text
        evidence_queue = completed.json()["memory"]["evidence_queue"]["pending"]
        assert any(
            item["source_card_id"] == card_id and item["verified"] is True
            for item in evidence_queue
        )
