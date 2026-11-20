"""Unified Library Root storage truth: every learner store lives under <LibraryRoot>."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import LearningPlan, PlanStage, TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.main import create_app
from app.resources.library import LIBRARY_DIRECTORY_NAME
from tests.test_browser_capture import _pair_browser, _readonly_response, minimal_pdf


def _build_client(trainer_root: Path) -> TestClient:
    runtime_dir = trainer_root / ".trainer" / "runtime"
    settings = AppSettings(
        app_name="Trainer Unified Library Root Test",
        host="127.0.0.1",
        port=8765,
        data_dir=runtime_dir,
        database_name="trainer.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    return TestClient(create_app(settings))


def test_all_data_resources_and_memory_stay_under_library_root(
    tmp_path: Path, monkeypatch
) -> None:
    trainer_root = tmp_path / "library-root"
    trainer_root.mkdir(parents=True)
    project_dir = tmp_path / "user-code-repo"
    project_dir.mkdir(parents=True)
    # Seed a normal source file inside the user's repository; Trainer must never
    # write Trainer libraries, canonical Markdown, or databases into this repo.
    (project_dir / "main.py").write_text("def retry():\n    pass\n", encoding="utf-8")

    pdf_url = "https://files.example.com/papers/idempotency.pdf"
    pdf_body = minimal_pdf(["Idempotent retry guarantees exactly-once effects."])
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(pdf_body, url, "application/pdf"),
    )

    with _build_client(trainer_root) as client:
        runtime = client.app.state.runtime
        provisioning = runtime.provision_project_adoption(
            workspace_id="workspace-unified",
            root_path=str(trainer_root),
            project_path=str(project_dir),
            project_name="user-code-repo",
        )
        context_id = provisioning.context_id
        runtime.memory_service.update_workspace_state(
            context_id,
            workspace_trusted=True,
            remote_name="",
            is_remote_workspace=False,
        )

        started = client.post(
            "/session/start",
            json={
                "workspace_id": context_id,
                "workspace_name": "user-code-repo",
                "workspace_path": str(project_dir),
                "workspace_trusted": True,
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        # 1. Memory + Goal + Formal Plan
        runtime.memory_service.update_global_memory(
            preferences={"explanation_style": "do_first"},
            long_term_goals=["Understand retry idempotency"],
        )
        runtime.memory_service.record_learning_outcome(
            workspace_id=context_id,
            concepts=["idempotency"],
            outcome="partial",
            summary="Needs retry idempotency check.",
        )
        goal = runtime.goal_service.start(
            workspace_id=context_id,
            title="Master retry idempotency",
            session_id=session_id,
        )
        assert goal.goal_id
        plan = LearningPlan(
            id=provisioning.project_plan_id,
            title="Idempotency Plan",
            summary="Learn safe retries",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Basics",
                    goal="Understand idempotent retry",
                    outcomes=["Identify duplicate write"],
                    status="active",
                )
            ],
            currentStageId="stage-1",
            currentStep="Read retry()",
        )
        runtime.repository.save_plan_with_revision(context_id, plan, expected_revision=None)

        # 2. Training Card + Attempt + Evidence
        card = TrainingCardCandidateSnapshot(
            card_id="card-idemp",
            title="Make retry idempotent",
            card_type="practice",
            status="active",
            learning_phase="try",
            expected_answer="Use an idempotency key.",
        )
        runtime.memory_service.upsert_card(context_id, card)
        attempt = runtime.attempt_store.start_attempt(workspace_id=context_id, card_id=card.card_id)
        evidence = runtime.attempt_store.record_evidence(
            attempt_id=attempt["attempt_id"],
            artifact_hash="hash-retry-1",
            result="passed",
            trust_level="controlled_check",
            dimension="implementation",
        )
        assert evidence is not None

        # 3. Resource upload + index (canonical Markdown)
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": context_id,
                "session_id": session_id,
                "name": "Retry Notes",
                "kind": "markdown",
                "source": "retry-notes.md",
                "content": "# Retry Notes\n\nIdempotent operations tolerate duplicate requests.\n",
                "content_encoding": "utf-8",
            },
        )
        assert upload.status_code == 200, upload.text
        indexed = client.post(
            "/resource/index",
            json={"workspace_id": context_id, "resource_id": upload.json()["id"]},
        )
        assert indexed.status_code == 200, indexed.text
        md_rel = indexed.json()["canonical_markdown_path"]
        assert md_rel.startswith(f"{LIBRARY_DIRECTORY_NAME}/.trainer-resources/markdown/")
        assert (trainer_root / md_rel).is_file()

        # 4. Browser pairing + PDF capture download to library root
        credential = _pair_browser(client, context_id)
        captured = client.post(
            "/resources/capture",
            headers={"Authorization": f"Bearer {credential}"},
            json={
                "workspace_id": context_id,
                "url": pdf_url,
                "kind": "pdf",
                "title": "Idempotency Paper",
                "download": True,
            },
        )
        assert captured.status_code == 200, captured.text
        assert (trainer_root / LIBRARY_DIRECTORY_NAME / "Idempotency Paper.pdf").read_bytes() == pdf_body
        assert (trainer_root / captured.json()["canonical_markdown_path"]).is_file()

        # 5. Research Brief asset
        brief_resp = client.post(
            "/resource/research-brief",
            json={
                "title": "Idempotency Brief",
                "contextId": context_id,
                "brief": {
                    "researchGoal": "Understand retry keys",
                    "keyQuestions": ["What breaks non-idempotent retries?"],
                    "findings": [
                        {
                            "statement": "Idempotent operations tolerate duplicate requests.",
                            "claimStatus": "sourced",
                            "sourceRefs": [
                                {
                                    "kind": "resource",
                                    "ref": upload.json()["id"],
                                    "label": "Retry Notes",
                                    "metadata": {"resource_id": upload.json()["id"]},
                                }
                            ],
                        }
                    ],
                },
            },
        )
        assert brief_resp.status_code == 200, brief_resp.text

        # 6. Storage truth verification
        truth_resp = client.get(
            "/workspace/storage-truth",
            params={"workspace_id": context_id},
        )
        assert truth_resp.status_code == 200, truth_resp.text
        truth = truth_resp.json()
        assert truth["library_root"] == str(trainer_root.resolve())
        assert truth["all_under_library_root"] is True, truth
        assert truth["outside_library_root"] == []
        assert truth["secrets_in_keychain_only"] is True

        for store_path in truth["stores"].values():
            if store_path:
                assert Path(store_path).resolve().is_relative_to(trainer_root.resolve())

        runtime_dir = trainer_root / ".trainer" / "runtime"
        assert (runtime_dir / "trainer.db").is_file()
        assert (runtime_dir / "research.db").is_file()
        assert (runtime_dir / "qdrant").is_dir()
        assert (runtime_dir / "browser_bridge.json").is_file()
        assert (trainer_root / LIBRARY_DIRECTORY_NAME).is_dir()

        # Zero pollution in user code repository
        assert [p.name for p in project_dir.iterdir()] == ["main.py"]
        assert not (project_dir / LIBRARY_DIRECTORY_NAME).exists()
        assert not (project_dir / ".trainer").exists()
