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


def test_leaf_only_card_target_matches_nested_project_file(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-leaf-card-file"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Leaf binding test"},
        ).json()["session_id"]
        runtime = client.app.state.runtime
        card = TrainingCardCandidateSnapshot(
            card_id="card-leaf",
            card_type="practice",
            status="active",
            title="Lock boundary",
            files_to_touch=["`queue_lock.py`"],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(
            workspace,
            selected_card_id=card.card_id,
            canonical_project_path=str(tmp_path),
        )
        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=EvaluationReport(
                passed=True,
                summary="ok",
                next_step="Reflect",
                reflection="",
                dynamic_checks=[
                    EvaluationCheck(id="pytest", label="pytest", status="passed", detail="1 passed")
                ],
            )
        )
        accepted = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "file_path": str(tmp_path / "src" / "queue_lock.py"),
                "language_id": "python",
                "content": "x = 1\n",
            },
        )
        assert accepted.status_code == 200, accepted.text
        runtime.evaluator_service.evaluate_current_file.assert_called_once()
        rejected = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "file_path": str(tmp_path / "src" / "other.py"),
                "language_id": "python",
                "content": "x = 1\n",
            },
        )
        assert rejected.status_code == 409, rejected.text


def test_leaf_target_outside_project_is_rejected(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-outside-leaf"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Outside leaf test"},
        ).json()["session_id"]
        runtime = client.app.state.runtime
        project = tmp_path / "project"
        project.mkdir()
        card = TrainingCardCandidateSnapshot(
            card_id="card-outside-leaf",
            card_type="practice",
            status="active",
            title="Outside",
            files_to_touch=["queue_lock.py"],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(
            workspace, selected_card_id=card.card_id, canonical_project_path=str(project)
        )
        response = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "file_path": str(tmp_path / "outside" / "queue_lock.py"),
                "language_id": "python",
                "content": "x = 1\n",
            },
        )
        assert response.status_code == 409, response.text


def test_relative_target_outside_project_is_rejected(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-outside-relative"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Outside relative test"},
        ).json()["session_id"]
        runtime = client.app.state.runtime
        project = tmp_path / "project"
        project.mkdir()
        card = TrainingCardCandidateSnapshot(
            card_id="card-outside-relative",
            card_type="practice",
            status="active",
            title="Outside",
            files_to_touch=["src/queue_lock.py"],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(
            workspace, selected_card_id=card.card_id, canonical_project_path=str(project)
        )
        response = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "file_path": str(tmp_path / "outside" / "src" / "queue_lock.py"),
                "language_id": "python",
                "content": "x = 1\n",
            },
        )
        assert response.status_code == 409, response.text


def test_skipped_card_cannot_record_current_file_evidence(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-skipped-verify"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Skipped verify"},
        ).json()["session_id"]
        runtime = client.app.state.runtime
        project = tmp_path / "project"
        target = project / "src" / "queue_lock.py"
        target.parent.mkdir(parents=True)
        target.write_text("x = 1\n", encoding="utf-8")
        card = TrainingCardCandidateSnapshot(
            card_id="card-skipped-verify",
            card_type="practice",
            status="active",
            title="Skipped verify",
            files_to_touch=[str(target)],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(
            workspace,
            selected_card_id=card.card_id,
            canonical_project_path=str(project),
        )
        runtime.memory_service.transition_card_status(
            workspace, card.card_id, "skipped", reason="test skip"
        )
        before = len(runtime.memory_service._structured_for(workspace)._evidence_items)
        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=EvaluationReport(
                passed=True,
                summary="ok",
                next_step="",
                reflection="",
                dynamic_checks=[
                    EvaluationCheck(id="pytest", label="pytest", status="passed", detail="1 passed")
                ],
            )
        )
        response = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "file_path": str(target),
                "language_id": "python",
                "content": target.read_text(encoding="utf-8"),
            },
        )
        assert response.status_code == 200, response.text
        assert runtime.memory_service.get_card(workspace, card.card_id).status == "skipped"
        after = len(runtime.memory_service._structured_for(workspace)._evidence_items)
        assert after == before


def test_leaf_target_without_project_root_is_rejected(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-leaf-no-project"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Leaf no project"},
        ).json()["session_id"]
        runtime = client.app.state.runtime
        card = TrainingCardCandidateSnapshot(
            card_id="card-leaf-no-project",
            card_type="practice",
            status="active",
            title="Leaf no project",
            files_to_touch=["queue_lock.py"],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id)
        response = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "file_path": str(tmp_path / "outside" / "queue_lock.py"),
                "language_id": "python",
                "content": "x = 1\n",
            },
        )
        assert response.status_code == 409, response.text


def test_manual_reading_card_raw_and_snapshot_agree_through_return(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace = "ws-manual-reading"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Manual reading"},
        ).json()["session_id"]
        runtime = client.app.state.runtime
        target = tmp_path / "src" / "queue_lock.py"
        target.parent.mkdir(parents=True)
        target.write_text("import threading\n", encoding="utf-8")
        card = TrainingCardCandidateSnapshot(
            card_id="card-manual-reading",
            card_type="practice",
            status="active",
            title="梳理 queue_lock.py 的加锁边界",
            learning_family="code",
            learning_subtype="reading",
            files_to_touch=[str(target)],
            problem_statement="记录锁相关符号和行号。不要先改生产代码。",
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(
            workspace,
            selected_card_id=card.card_id,
            canonical_project_path=str(tmp_path),
        )
        response = client.post(
            "/training/practice-return",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "card_id": card.card_id,
                "passed": True,
                "summary": "源码笔记：_lock 在第 3 行；with 在第 6 行；异常路径由 with 释放。",
                "next_step": "Record one reflection.",
                "focus_area": "queue_lock",
                "evidence_source": "learner_return",
            },
        )
        assert response.status_code == 200, response.text
        card_after = runtime.memory_service.get_card(workspace, card.card_id)
        assert card_after is not None
        assert card_after.status == "answered"
        raw = runtime.memory_service._structured_for(workspace)._workspace["latest_training_handoff"]
        snapshot = runtime.memory_service.snapshot(workspace).workspace["latest_training_handoff"]
        assert raw["learning_phase"] == "verify"
        assert raw["verification_state"] == "self_reported"
        assert snapshot["learning_phase"] == raw["learning_phase"]
        assert snapshot["verification_state"] == raw["verification_state"]
        evidence = [
            item
            for item in runtime.memory_service._structured_for(workspace)._evidence_items.values()
            if item.source_card_id == card.card_id
        ]
        assert evidence
        assert all(not item.verified for item in evidence)
        assert any(item.verification_source == "self_reported" for item in evidence)

        reflected = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "card_id": card.card_id,
                "handoff_id": raw["handoff_id"],
                "reflection": "我把获取、释放和异常路径分别对应到了具体行号。",
            },
        )
        assert reflected.status_code == 200, reflected.text
        after_reflect = runtime.memory_service.snapshot(workspace).workspace["latest_training_handoff"]
        assert after_reflect["learning_phase"] == "reflect"
        assert after_reflect["reflection"]

        returned = client.post(
            "/training/return",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "card_id": card.card_id,
                "handoff_id": raw["handoff_id"],
            },
        )
        assert returned.status_code == 200, returned.text
        after_return = runtime.memory_service.snapshot(workspace).workspace["latest_training_handoff"]
        assert after_return["learning_phase"] == "return"
        assert after_return["status"] == "completed"


def test_legacy_self_reported_try_handoff_can_reflect(tmp_path: Path) -> None:
    from app.training.handoff import TrainingHandoffGenerator, TrainingPhase

    with build_client(tmp_path) as client:
        workspace = "ws-legacy-manual-reflect"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Legacy manual"},
        ).json()["session_id"]
        runtime = client.app.state.runtime
        card = TrainingCardCandidateSnapshot(
            card_id="card-legacy-manual",
            card_type="practice",
            status="answered",
            title="梳理 queue_lock.py 的加锁边界",
            learning_family="code",
            learning_subtype="reading",
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(
            workspace, selected_card_id=card.card_id, canonical_project_path=str(tmp_path)
        )
        generator = runtime.memory_service._training_handoff_generator(workspace)
        handoff = generator.build_handoff_record(card, {}, response_language="en-US")
        handoff.phase = TrainingPhase.TRY
        generator._sync_handoff_verification_state(handoff, "self_reported")
        structured = runtime.memory_service._structured_for(workspace)
        structured.update_workspace(
            latest_training_handoff=TrainingHandoffGenerator._handoff_payload(handoff),
            selected_card_id=card.card_id,
            selected_card_status="answered",
        )
        runtime.memory_service._persist_structured(workspace)

        reflected = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "card_id": card.card_id,
                "handoff_id": handoff.handoff_id,
                "reflection": "迁移后的自我报告复盘。",
            },
        )
        assert reflected.status_code == 200, reflected.text
        after = runtime.memory_service.snapshot(workspace).workspace["latest_training_handoff"]
        assert after["learning_phase"] == "reflect"
        assert after["verification_state"] == "self_reported"

        returned = client.post(
            "/training/return",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "card_id": card.card_id,
                "handoff_id": handoff.handoff_id,
            },
        )
        assert returned.status_code == 200, returned.text
        final = runtime.memory_service.snapshot(workspace).workspace["latest_training_handoff"]
        assert final["learning_phase"] == "return"
        assert final["status"] == "completed"
        assert final["handoff_status"] == "self_reported"
        assert (
            runtime.memory_service.snapshot(workspace).workspace["latest_learning_outcome"]
            == "self_reported"
        )
