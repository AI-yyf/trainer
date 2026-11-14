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
            verification_scope="behavior",
            dynamic_checks=[EvaluationCheck(
                id="python-behavior", label="Behavior cases", status="passed", detail="2 cases passed",
            )],
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
        assert projection["delayed_recall"]["state"] == "not_verified"
        assert projection["delayed_recall"]["verified_count"] == 0
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
    attempt = store.start_attempt(
        workspace_id="ws", card_id="card", file_hash="hash", assistance_level="independent",
    )
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


def test_missing_assistance_is_unknown_and_never_advances_the_skill_ladder() -> None:
    dimension = project_skills([{
        "evidence_id": "legacy-controlled-check",
        "result": "passed",
        "is_current": True,
        "trust_level": "controlled_check",
        # assistance_level is absent in legacy/partial records.
    }])["implementation"]

    assert dimension["state"] == "not_verified"
    assert dimension["independent_attempt_count"] == 0
    assert dimension["independent_evidence_count"] == 0
    assert dimension["evidence"][0]["assistance_level"] == "unknown"

    explicit = project_skills([{
        "evidence_id": "independent-controlled-check",
        "result": "passed",
        "is_current": True,
        "trust_level": "controlled_check",
        "assistance_level": "independent",
    }])["implementation"]
    assert explicit["state"] == "independent"
    assert explicit["independent_attempt_count"] == 1


@pytest.mark.parametrize(
    ("source", "reference_id", "assistance", "passed", "result", "trust", "skill"),
    [
        (
            'if __name__ == "__main__":\n    print("solve_queue")\n',
            None, "independent", False, "partial", "static_analysis", "not_verified",
        ),
        (
            "def solve_queue(items: list[int]) -> int:\n    return len(items)\n",
            "", "independent", False, "execution_error", "static_analysis", "not_verified",
        ),
        (
            "def solve_queue(items: list[int]) -> int:\n    return 99\n",
            "", "independent", False, "execution_error", "static_analysis", "not_verified",
        ),
        (
            'if __name__ == "__main__":\n    print("solve_queue")\n',
            "test/count-items/v1", "independent", False, "failed", "controlled_check", "needs_review",
        ),
        (
            "def solve_queue(items: list[int]) -> int:\n    return 99\n",
            "test/count-items/v1", "independent", False, "failed", "controlled_check", "needs_review",
        ),
        (
            "def solve_queue(items: list[int]) -> int:\n    return len(items)\n",
            "test/count-items/v1", "hint_level_2", True, "passed", "controlled_check", "assisted",
        ),
        (
            "def solve_queue(items: list[int]) -> int:\n    return len(items)\n",
            "test/count-items/v1", None, True, "passed", "controlled_check", "not_verified",
        ),
        (
            "def solve_queue(items: list[int]) -> int:\n    return len(items)\n",
            "test/count-items/v1", "independent", True, "passed", "controlled_check", "independent",
        ),
        (
            "def solve_queue(items: list[int]) -> float:\n    return float(len(items))\n",
            "test/count-items/v1", "independent", True, "passed", "controlled_check", "independent",
        ),
        (
            "def solve_queue(items: list[int]) -> int:\n    return len(items)\n# fixture-static-error\n",
            "test/count-items/v1", "independent", False, "partial", "controlled_check", "not_verified",
        ),
    ],
)
def test_training_verification_checks_the_persisted_contract(
    tmp_path: Path, monkeypatch, source: str, reference_id: str | None, assistance: str | None,
    passed: bool, result: str, trust: str, skill: str,
) -> None:
    from app.evaluator.models import CheckResult, CheckStatus
    from app.evaluator.service import SubprocessCommandRunner, default_command_runner

    class BehaviorRunner:
        def run(self, command):
            if command.name == "ruff" and "fixture-static-error" in source:
                return CheckResult(name="ruff", status=CheckStatus.FAILED, summary="Fixture static error.")
            if command.name in {"python-behavior", "python-script"}:
                return SubprocessCommandRunner().run(command)
            return fallback.run(command)

    fallback = default_command_runner()
    monkeypatch.setattr("app.evaluator.service.default_command_runner", BehaviorRunner)
    with build_client(tmp_path) as client:
        workspace = "verified-contract"
        runtime = client.app.state.runtime
        session = client.post("/session/start", json={
            "workspace_id": workspace, "workspace_name": "Behavior verification",
        }).json()["session_id"]
        path = tmp_path / "solution.py"
        path.write_text(source)
        card = TrainingCardCandidateSnapshot.model_validate({
            "card_id": "card-queue", "card_type": "practice", "status": "active",
            "title": "Implement solve_queue", "target_skill": "count queued items",
            "files_to_touch": [str(path)], "expected_symbols": ["solve_queue"],
            "acceptance_criteria": ["Implement `solve_queue`; empty lists return 0."],
            "python_behavior_contract": {
                "function": "solve_queue",
                "reference_id": reference_id,
                "cases": [{"args": [[]], "expected": 0}, {"args": [[1, 2, 3]], "expected": 99 if reference_id == "" else 3}],
            } if reference_id is not None else None,
        })
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id)
        if assistance is not None:
            runtime.attempt_store.start_attempt(
                workspace_id=workspace, card_id=card.card_id, file_path=str(path),
                assistance_level=assistance,
            )
        response = client.post("/evaluate/current-file", json={
            "session_id": session, "workspace_id": workspace, "evaluation_source": "training",
            "training_phase": "verify", "training_card_id": card.card_id,
            "file_path": str(path), "content": source, "language_id": "python",
            "python_behavior_contract": {
                "function": "solve_queue",
                "cases": [{"args": [[]], "expected": 99}, {"args": [[1]], "expected": 99}],
            },
        })
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["passed"] is passed, report
        if reference_id == "":
            assert report["behavior_reference_pending"] is True
            assert report["verification_scope"] != "behavior"
            assert next(check for check in report["dynamic_checks"] if check["id"] == "python-behavior")["status"] == "warning"
        elif "fixture-static-error" in source:
            assert next(check for check in report["dynamic_checks"] if check["id"] == "python-behavior")["status"] == "passed"
        attempt = runtime.attempt_store.find_active_attempt(workspace, card.card_id)
        assert attempt is not None
        evidence = runtime.attempt_store.list_evidence(attempt["attempt_id"])
        assert len(evidence) == 1
        assert evidence[0]["result"] == result
        assert evidence[0]["trust_level"] == trust
        assert evidence[0]["assistance_level"] == (assistance or "unknown")
        memory = client.get("/memory/summary", params={"workspace_id": workspace}).json()["memory"]
        dimension = memory["workspace"]["training_skill_projection"]["dimensions"]["implementation"]
        assert dimension["state"] == skill
        assert bool(dimension["verified_count"]) is passed
        if reference_id == "":
            assert memory["workspace"]["latest_learning_outcome"] == "verification_pending"
            assert card.card_id not in memory["workspace"].get("latest_training_fsrs_states", {})


@pytest.mark.parametrize(
    ("version", "dimension", "old_policy"),
    [
        ("trainer-current-file-evaluator", "implementation", 1),
        ("trainer-current-file-evaluator-v2", "implementation", 1),
        ("trainer-current-file-evaluator-v3", "implementation", 3),
        ("trainer-flashcard", "delayed_recall", 2),
    ],
)
def test_startup_recomputes_legacy_overcredit(
    tmp_path: Path, version: str, dimension: str, old_policy: int,
) -> None:
    workspace = "legacy-verification"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        store = runtime.attempt_store
        attempt = store.start_attempt(
            workspace_id=workspace, card_id="card", file_hash="hash",
            assistance_level="independent",
        )
        evidence = store.record_evidence(
            attempt_id=attempt["attempt_id"], artifact_hash="hash",
            result="passed", trust_level="controlled_check",
            runner_version=version,
            dimension=dimension,
            recall_delay_days=2 if dimension == "delayed_recall" else None,
        )
        runtime.memory_service.update_workspace_state(workspace, training_skill_projection={
            "verification_policy_version": old_policy,
            "attempt_id": attempt["attempt_id"], "dimensions": {dimension: {"state": "independent"}},
        })

    with build_client(tmp_path) as client:
        memory = client.get("/memory/summary", params={"workspace_id": workspace}).json()["memory"]
        projection = memory["workspace"]["training_skill_projection"]
        assert projection["dimensions"][dimension]["verified_count"] == 0
        assert projection["dimensions"][dimension]["state"] != "independent"
        assert projection["dimensions"][dimension]["evidence"][0]["verification_recheck_required"]
        original = client.app.state.runtime.attempt_store.list_evidence(attempt["attempt_id"])
        assert original[0]["evidence_id"] == evidence["evidence_id"]
        assert original[0]["result"] == "passed"
