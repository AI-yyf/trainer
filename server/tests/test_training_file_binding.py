from pathlib import Path
from unittest.mock import MagicMock

from app.core.models import EvaluationCheck, EvaluationReport, TrainingCardCandidateSnapshot
from tests.test_api import build_client


def test_unrelated_file_cannot_verify_live_card_and_saved_contract_wins(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-exact-card-file"
        session = client.post("/session/start", json={"workspace_id": workspace, "workspace_name": "Binding test"}).json()["session_id"]
        runtime = client.app.state.runtime
        target = str(tmp_path / "nested" / "sample.py")
        card = TrainingCardCandidateSnapshot(
            card_id="card-file-bound", card_type="practice", status="active", title="Test mutability",
            files_to_touch=[target], acceptance_criteria=["Use `test_mutability` to prove the boundary"],
            expected_symbols=["test_mutability"], learner_deliverables=["Implement `test_mutability`"],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id)
        runtime.evaluator_service.evaluate_current_file = MagicMock(return_value=EvaluationReport(
            passed=True, summary="Current target passed", next_step="Reflect", reflection="",
            dynamic_checks=[EvaluationCheck(id="pytest", label="pytest", status="passed", detail="1 passed")],
        ))
        payload = {
            "workspace_id": workspace, "session_id": session, "evaluation_source": "training",
            "training_card_id": card.card_id, "file_path": str(tmp_path / "other" / "sample.py"),
            "language_id": "python", "content": "def test_mutability():\n    assert True\n",
            "acceptance_criteria": ["Use `anything`"], "expected_symbols": ["anything"],
        }
        rejected = client.post("/evaluate/current-file", json=payload)
        assert rejected.status_code == 409
        runtime.evaluator_service.evaluate_current_file.assert_not_called()
        assert runtime.memory_service.get_card(workspace, card.card_id).status == "active"
        payload["file_path"] = target
        accepted = client.post("/evaluate/current-file", json=payload)
        assert accepted.status_code == 200, accepted.text
        request = runtime.evaluator_service.evaluate_current_file.call_args.args[0]
        assert request.acceptance_criteria == card.acceptance_criteria
        assert request.expected_symbols == card.expected_symbols
        assert request.learner_deliverables == card.learner_deliverables


def test_relative_target_is_resolved_against_managed_project(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-relative-card-file"
        session = client.post("/session/start", json={"workspace_id": workspace, "workspace_name": "Relative binding test"}).json()["session_id"]
        runtime = client.app.state.runtime
        card = TrainingCardCandidateSnapshot(card_id="card-relative", card_type="practice", status="active",
            files_to_touch=["nested/sample.py"])
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id,
            canonical_project_path=str(tmp_path))
        runtime.evaluator_service.evaluate_current_file = MagicMock(return_value=EvaluationReport(
            passed=False, summary="Needs real tests", next_step="Add test", reflection="",
        ))
        response = client.post("/evaluate/current-file", json={
            "workspace_id": workspace, "session_id": session, "evaluation_source": "training",
            "training_card_id": card.card_id, "file_path": str(tmp_path / "nested" / "sample.py"),
            "language_id": "python", "content": "x = 1\n",
        })
        assert response.status_code == 200, response.text
        runtime.evaluator_service.evaluate_current_file.assert_called_once()
