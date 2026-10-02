from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.api.training_skill_evidence import persist_skill_projection
from app.core.models import EvaluationCheck, EvaluationReport, TrainingCardCandidateSnapshot
from app.training.attempt_store import content_hash
from app.training.skill_projection import project_skills
from tests.test_api import build_client


@pytest.mark.parametrize("trust", ["self_reported", "model_review", "static_analysis", ""])
@pytest.mark.parametrize("assistance", ["independent", "hint_level_2"])
def test_unexecuted_success_cannot_verify_capability(trust: str, assistance: str) -> None:
    dimension = project_skills([{
        "evidence_id": "self-report", "result": "passed", "is_current": True,
        "trust_level": trust, "assistance_level": assistance,
    }])["implementation"]
    assert dimension["state"] == "not_verified"
    assert dimension["verified_count"] == 0
    assert dimension["independent_attempt_count"] == 0
    assert dimension["evidence_ids"] == ["self-report"]


def test_card_bound_file_evaluation_updates_growth_and_resumes_verified_attempt(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-growth-verification"
        runtime = client.app.state.runtime
        session = client.post("/session/start", json={
            "workspace_id": workspace, "workspace_name": "Growth verification",
        }).json()["session_id"]
        path = str(tmp_path / "sample.py")
        source = "def test_boundary():\n    assert True\n"
        card = TrainingCardCandidateSnapshot(
            card_id="card-growth", card_type="practice", status="active", files_to_touch=[path],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id)
        attempt = runtime.attempt_store.start_attempt(
            workspace_id=workspace, card_id=card.card_id, file_path=path,
            assistance_level="hint_level_2", file_version=7,
        )
        runtime.evaluator_service.evaluate_current_file = MagicMock(return_value=EvaluationReport(
            passed=True, summary="1 test passed", next_step="Reflect", reflection="",
            dynamic_checks=[EvaluationCheck(id="pytest", label="pytest", status="passed", detail="1 passed")],
        ))
        payload = {
            "workspace_id": workspace, "session_id": session, "evaluation_source": "training",
            "training_card_id": card.card_id, "file_path": path, "content": source, "language_id": "python",
        }
        for _ in range(2):
            evaluated = client.post("/evaluate/current-file", json=payload)
            assert evaluated.status_code == 200, evaluated.text
            assert evaluated.json()["passed"] is True
        attempts = runtime.attempt_store.list_attempts(workspace_id=workspace, card_id=card.card_id)
        assert len(attempts) == 1
        evidence = runtime.attempt_store.list_evidence(attempt["attempt_id"])
        current = [item for item in evidence if item["is_current"]]
        assert len(current) == 1
        assert current[0]["artifact_hash"] == content_hash(source)
        assert current[0]["artifact_version"] == 7
        assert current[0]["trust_level"] == "controlled_check"
        assert current[0]["assistance_level"] == "hint_level_2"
        memory = client.get("/memory/summary", params={"session_id": session, "workspace_id": workspace}).json()
        projection = memory["memory"]["workspace"]["training_skill_projection"]["dimensions"]
        assert projection["implementation"]["state"] == "assisted"
        assert projection["implementation"]["verified_count"] == 1
        assert projection["transfer"]["state"] == "not_verified"
        reflected = client.post("/training/reflect", json={
            "workspace_id": workspace, "card_id": card.card_id,
            "reflection": "The focused test proved this boundary; transfer is not established.",
        })
        assert reflected.status_code == 200, reflected.text
        returned = client.post("/training/return", json={"workspace_id": workspace, "card_id": card.card_id})
        assert returned.status_code == 200, returned.text
        assert runtime.attempt_store.find_active_attempt(workspace, card.card_id) is None
        rechecked = client.post("/evaluate/current-file", json=payload)
        assert rechecked.status_code == 200, rechecked.text
        assert len(runtime.attempt_store.list_attempts(workspace_id=workspace, card_id=card.card_id)) == 1
        assert runtime.attempt_store.get_attempt(attempt["attempt_id"])["status"] == "returned"
        # Entering another card cannot wipe the workspace's earned evidence.
        another = runtime.attempt_store.start_attempt(workspace_id=workspace, card_id="new-card")
        refreshed = persist_skill_projection(runtime, workspace, another["attempt_id"])
        assert refreshed["implementation"]["state"] == "assisted"
        assert persist_skill_projection(runtime, "other-workspace", attempt["attempt_id"]) is None


def test_verified_attempt_is_resumed_until_explicit_return(tmp_path: Path) -> None:
    from app.training.attempt_store import AttemptStore

    store = AttemptStore(tmp_path / "attempts.db")
    original = store.start_attempt(workspace_id="ws", card_id="card", file_hash="hash", file_version=3)
    store.record_evidence(attempt_id=original["attempt_id"], artifact_hash="hash", result="passed")
    resumed = store.start_attempt(workspace_id="ws", card_id="card")
    assert resumed["attempt_id"] == original["attempt_id"]
    assert resumed["file_version"] == 3
    store.close_attempt(original["attempt_id"], workspace_id="ws")
    assert store.start_attempt(workspace_id="ws", card_id="card")["attempt_id"] != original["attempt_id"]


def test_self_report_cannot_supersede_same_artifact_controlled_check(tmp_path: Path) -> None:
    from app.training.attempt_store import AttemptStore

    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(workspace_id="ws", card_id="card", file_hash="hash")
    trusted = store.record_evidence(attempt_id=attempt["attempt_id"], artifact_hash="hash", result="passed")
    store.record_evidence(
        attempt_id=attempt["attempt_id"], artifact_hash="hash", result="passed", trust_level="self_reported",
    )
    evidence = store.list_evidence(attempt["attempt_id"])
    trusted_after = next(item for item in evidence if item["evidence_id"] == trusted["evidence_id"])
    assert trusted_after["is_current"] is True
    assert trusted_after["superseded_by_evidence_id"] is None
    assert store.get_attempt(attempt["attempt_id"])["status"] == "verified"
    projection = project_skills(evidence)["implementation"]
    assert projection["state"] == "independent"
    assert projection["verified_count"] == 1
