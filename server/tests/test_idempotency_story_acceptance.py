"""Contract §10 Idempotency acceptance story under ONE unified <LibraryRoot>.

Exercises the continuous three-day journey across controlled clock (`TRAINER_TEST_NOW`)
and a full FastAPI `create_app()` restart against real SQLite + filesystem stores:
  - Monday T0: project adoption under single <LibraryRoot>, zero repo pollution,
    resource upload + index to canonical Markdown, write-tool refusal + silent-plan
    refusal, self-reported vs host-trusted `controlled_check`, atomic ledger+evidence,
    SHA-256 hash staleness & re-verification, typing-quiet proactive whisper cue.
  - Thursday T0 + 3d: cross-context transfer -> `repeat_verified`, FSRS interval gain.
  - Day 17 (T0 + 17d) after full sidecar restart: 14-day delayed recall -> `repeat_verified`,
    zero persistence loss across reload, zero banned learner-facing vocabulary, zero repo pollution.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.llm.tools import PROJECT_WRITE_TOOL_NAMES, ToolContext, _handle_save_formal_plan
from app.main import create_app
from app.resources.library import LIBRARY_DIRECTORY_NAME
from app.training.fsrs_scheduler import FSRSTrainerCardScheduler, TrainingRating
from app.training.skill_projection import project_skills

BANNED_LEARNER_TERMS = (
    "fsrs",
    "sidecar",
    "telemetry",
    "workbench",
    "attestation",
    "handoff",
)


def _settings(trainer_root: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Idempotency Acceptance Story",
        host="127.0.0.1",
        port=8765,
        data_dir=trainer_root / ".trainer" / "runtime",
        database_name="trainer.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _build_client(trainer_root: Path) -> TestClient:
    return TestClient(create_app(_settings(trainer_root)))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _collect_all_evidence(store, *, workspace_id: str) -> list[dict]:
    records: list[dict] = []
    for attempt in store.list_attempts(workspace_id=workspace_id):
        records.extend(store.list_evidence(attempt["attempt_id"]))
    return records


def _assert_zero_repo_pollution(project_repo: Path) -> None:
    top_entries = sorted(p.name for p in project_repo.iterdir())
    assert top_entries == ["payments.py"], f"Unexpected files in code repo: {top_entries}"
    assert not (project_repo / LIBRARY_DIRECTORY_NAME).exists()
    assert not (project_repo / ".trainer").exists()


async def test_idempotency_story_single_library_root_across_controlled_clock_and_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trainer_root = tmp_path / "library-root"
    trainer_root.mkdir(parents=True)
    project_repo = tmp_path / "payments-service"
    project_repo.mkdir(parents=True)

    code_v1 = (
        "def charge(order_id: str, key: str, seen: dict[str, dict]) -> dict:\n"
        "    if key in seen:\n"
        "        return seen[key]\n"
        "    result = {'order_id': order_id, 'status': 'charged'}\n"
        "    seen[key] = result\n"
        "    return result\n"
    )
    code_v2 = (
        "def charge(order_id: str, key: str, seen: dict[str, dict]) -> dict:\n"
        "    if not key:\n"
        "        raise ValueError('idempotency key required')\n"
        "    if key in seen:\n"
        "        return seen[key]\n"
        "    result = {'order_id': order_id, 'status': 'charged'}\n"
        "    seen[key] = result\n"
        "    return result\n"
    )
    target_file = project_repo / "payments.py"
    target_file.write_text(code_v1, encoding="utf-8")
    hash_v1 = _sha256(code_v1)
    hash_v2 = _sha256(code_v2)

    # ── Monday T0 ──────────────────────────────────────────────────────────
    t0 = "2026-11-23T09:00:00Z"
    monkeypatch.setenv("TRAINER_TEST_NOW", t0)

    with _build_client(trainer_root) as client:
        runtime = client.app.state.runtime
        provisioning = runtime.provision_project_adoption(
            workspace_id="ws-idempotency",
            root_path=str(trainer_root),
            project_path=str(project_repo),
            project_name="payments-service",
        )
        context_id = provisioning.context_id

        started = client.post(
            "/session/start",
            json={
                "workspace_id": context_id,
                "workspace_name": "payments-service",
                "workspace_path": str(project_repo),
                "workspace_trusted": True,
                "profile": {
                    "long_term_goal": "Master HTTP retry idempotency",
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        # 1. Resource upload + index writes canonical Markdown only under <LibraryRoot>
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": context_id,
                "session_id": session_id,
                "name": "HTTP Idempotency Notes",
                "kind": "markdown",
                "source": "http-idempotency.md",
                "content": "# HTTP Idempotency\n\nSame key replays stored outcome without double charge.\n",
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

        # 2. Storage truth & zero repo pollution
        truth_resp = client.get("/workspace/storage-truth", params={"workspace_id": context_id})
        assert truth_resp.status_code == 200, truth_resp.text
        truth = truth_resp.json()
        assert truth["library_root"] == str(trainer_root.resolve())
        assert truth["all_under_library_root"] is True, truth
        assert truth["outside_library_root"] == []
        assert truth["secrets_in_keychain_only"] is True
        _assert_zero_repo_pollution(project_repo)

        # 3. Coach write-tool refusal + silent formal-plan refusal
        for blocked_tool in ("write_file", "edit_file", "apply_patch", "execute_command"):
            assert blocked_tool in PROJECT_WRITE_TOOL_NAMES
        assert "write_sandbox_file" not in PROJECT_WRITE_TOOL_NAMES

        plan_guard = await _handle_save_formal_plan(
            ToolContext(
                runtime=runtime,
                workspace_id=context_id,
                session_id=session_id,
                extra={"formal_plan_mutation": False},
            ),
            {"goal": "Silently alter formal plan"},
        )
        assert plan_guard["ok"] is False
        assert plan_guard["error"] == "formal_plan_mutation_required"

        # 4. Practice card + self-reported evidence never elevates capability
        card_impl = TrainingCardCandidateSnapshot(
            card_id="card-idempotency-impl",
            title="Guard duplicate charge with idempotency key",
            card_type="practice",
            status="active",
            review_state="saved",
            learning_phase="try",
            expected_answer="Check seen[key] before charging.",
        )
        runtime.memory_service.upsert_card(context_id, card_impl)

        start_v1 = client.post(
            "/training/attempt/start",
            json={
                "workspace_id": context_id,
                "card_id": card_impl.card_id,
                "file_path": str(target_file),
                "file_hash": hash_v1,
                "assistance_level": "independent",
            },
        )
        assert start_v1.status_code == 200, start_v1.text
        attempt_1 = start_v1.json()["attempt"]
        attempt_1_id = attempt_1["attempt_id"]

        self_rep = client.post(
            "/training/attempt/evidence",
            json={
                "attempt_id": attempt_1_id,
                "workspace_id": context_id,
                "artifact_hash": hash_v1,
                "result": "passed",
                "dimension": "implementation",
            },
        )
        assert self_rep.status_code == 200, self_rep.text
        assert self_rep.json()["evidence"]["trust_level"] == "self_reported"
        skills_after_self = project_skills(_collect_all_evidence(runtime.attempt_store, workspace_id=context_id))
        assert skills_after_self["implementation"]["state"] == "not_verified"

        # 5. Host-trusted controlled_check advances implementation -> independent & writes ledger atomically
        controlled_v1 = runtime.attempt_store.record_evidence(
            attempt_id=attempt_1_id,
            caller_workspace_id=context_id,
            artifact_hash=hash_v1,
            result="passed",
            trust_level="controlled_check",
            dimension="implementation",
        )
        assert controlled_v1 is not None
        ledger_events = [
            e
            for e in runtime.event_ledger.all_entries()
            if e.project_id == context_id and e.event_type == "training_evidence_recorded"
        ]
        assert any(
            e.payload_ref.get("evidence_id") == controlled_v1["evidence_id"]
            for e in ledger_events
        )
        skills_after_v1 = project_skills(_collect_all_evidence(runtime.attempt_store, workspace_id=context_id))
        assert skills_after_v1["implementation"]["state"] == "independent"

        # 6. File edit changes SHA-256 -> old evidence becomes stale (`is_current == False`);
        #    re-verifying against hash_v2 marks the new evidence current.
        target_file.write_text(code_v2, encoding="utf-8")
        upd_resp = client.post(
            "/training/attempt/update",
            json={
                "attempt_id": attempt_1_id,
                "workspace_id": context_id,
                "file_path": str(target_file),
                "file_hash": hash_v2,
            },
        )
        assert upd_resp.status_code == 200, upd_resp.text
        evidence_list_stale = runtime.attempt_store.list_evidence(attempt_1_id)
        assert all(item["is_current"] is False for item in evidence_list_stale)

        controlled_v2 = runtime.attempt_store.record_evidence(
            attempt_id=attempt_1_id,
            caller_workspace_id=context_id,
            artifact_hash=hash_v2,
            result="passed",
            trust_level="controlled_check",
            dimension="implementation",
        )
        assert controlled_v2 is not None
        evidence_list_fresh = runtime.attempt_store.list_evidence(attempt_1_id)
        current_ids = [item["evidence_id"] for item in evidence_list_fresh if item["is_current"]]
        assert current_ids == [controlled_v2["evidence_id"]]

        # Complete attempt_1 so later transfer/recall attempts allocate distinct attempts cleanly.
        runtime.attempt_store.update_attempt(attempt_1_id, workspace_id=context_id, status="completed")

        # 7. Weakness + live diagnostic whisper respects active typing and avoids banned jargon
        structured = runtime.memory_service.structured_for_workspace(context_id)
        structured.record_weakness(
            "idempotency",
            "idempotency key validation missing empty check",
            severity=2,
            review_after_days=3,
        )
        runtime.memory_service._persist_structured(context_id)

        typing_whisper = client.post(
            "/proactive/evaluate",
            json={
                "session_id": session_id,
                "workspace_id": context_id,
                "diagnostics": ["ValueError: idempotency key empty edge case uncovered"],
                "learner_actively_typing": True,
                "record": True,
                "now": t0,
            },
        )
        assert typing_whisper.status_code == 200
        assert typing_whisper.json()["should_nudge"] is False
        assert typing_whisper.json()["reason"] == "learner_typing"

        idle_whisper = client.post(
            "/proactive/evaluate",
            json={
                "session_id": session_id,
                "workspace_id": context_id,
                "diagnostics": ["ValueError: idempotency key empty edge case uncovered"],
                "learner_actively_typing": False,
                "record": True,
                "now": t0,
            },
        )
        assert idle_whisper.status_code == 200
        whisper_data = idle_whisper.json()
        assert whisper_data["should_nudge"] is True
        assert whisper_data["kind"] == "diagnostic_weakness"
        lowered_whisper = whisper_data["message"].lower()
        for banned in BANNED_LEARNER_TERMS:
            assert banned not in lowered_whisper

        # Schedule initial FSRS card at T0
        fsrs_scheduler = FSRSTrainerCardScheduler()
        fsrs_scheduler.create_card(card_impl.card_id, "idempotency")
        first_review = fsrs_scheduler.process_review(card_impl.card_id, TrainingRating.GOOD)
        assert first_review.next_due > first_review.next_due.replace(year=2000)

        # ── Thursday T1 = T0 + 3d ──────────────────────────────────────────
        t1 = "2026-11-26T09:00:00Z"
        monkeypatch.setenv("TRAINER_TEST_NOW", t1)

        second_review = fsrs_scheduler.process_review(card_impl.card_id, TrainingRating.GOOD)
        assert second_review.new_interval >= first_review.new_interval
        assert second_review.new_stability >= first_review.new_stability

        transfer_a = runtime.attempt_store.start_attempt(
            workspace_id=context_id,
            card_id="card-idempotency-transfer-1",
            file_hash="transfer-hash-a",
            assistance_level="independent",
        )
        runtime.attempt_store.record_evidence(
            attempt_id=transfer_a["attempt_id"],
            caller_workspace_id=context_id,
            artifact_hash="transfer-hash-a",
            result="passed",
            trust_level="controlled_check",
            dimension="transfer",
            scenario="payment-webhook",
            environment="async-worker",
            constraints="at-least-once-delivery",
        )
        runtime.attempt_store.update_attempt(transfer_a["attempt_id"], workspace_id=context_id, status="completed")

        transfer_b = runtime.attempt_store.start_attempt(
            workspace_id=context_id,
            card_id="card-idempotency-transfer-2",
            file_hash="transfer-hash-b",
            assistance_level="independent",
        )
        runtime.attempt_store.record_evidence(
            attempt_id=transfer_b["attempt_id"],
            caller_workspace_id=context_id,
            artifact_hash="transfer-hash-b",
            result="passed",
            trust_level="controlled_check",
            dimension="transfer",
            scenario="checkout-timeout-retry",
            environment="multi-region-queue",
            constraints="concurrent-duplicate-post",
        )
        runtime.attempt_store.update_attempt(transfer_b["attempt_id"], workspace_id=context_id, status="completed")

        skills_t1 = project_skills(_collect_all_evidence(runtime.attempt_store, workspace_id=context_id))
        assert skills_t1["transfer"]["state"] == "repeat_verified"

    # ── Day 17 T2 = T0 + 17d (after full create_app restart) ───────────────
    t2 = "2026-12-10T09:00:00Z"
    monkeypatch.setenv("TRAINER_TEST_NOW", t2)

    with _build_client(trainer_root) as restarted_client:
        restarted_runtime = restarted_client.app.state.runtime

        # Resources, canonical Markdown, weaknesses, and ledger survived restart
        restarted_truth = restarted_client.get(
            "/workspace/storage-truth",
            params={"workspace_id": context_id},
        )
        assert restarted_truth.status_code == 200
        assert restarted_truth.json()["all_under_library_root"] is True
        assert restarted_truth.json()["outside_library_root"] == []
        assert (trainer_root / md_rel).is_file()
        assert any(
            w.concept == "idempotency"
            for w in restarted_runtime.memory_service.weakness_records(context_id)
        )

        # Record 14-day delayed recall across two independent verified recall attempts
        recall_a = restarted_runtime.attempt_store.start_attempt(
            workspace_id=context_id,
            card_id="card-idempotency-recall-1",
            file_hash="recall-hash-1",
            assistance_level="independent",
        )
        restarted_runtime.attempt_store.record_evidence(
            attempt_id=recall_a["attempt_id"],
            caller_workspace_id=context_id,
            artifact_hash="recall-hash-1",
            result="passed",
            trust_level="controlled_check",
            dimension="delayed_recall",
            evidence_kind="delayed_recall",
            recall_delay_days=14.0,
            recall_rating="good",
        )
        restarted_runtime.attempt_store.update_attempt(
            recall_a["attempt_id"], workspace_id=context_id, status="completed"
        )

        recall_b = restarted_runtime.attempt_store.start_attempt(
            workspace_id=context_id,
            card_id="card-idempotency-recall-2",
            file_hash="recall-hash-2",
            assistance_level="independent",
        )
        restarted_runtime.attempt_store.record_evidence(
            attempt_id=recall_b["attempt_id"],
            caller_workspace_id=context_id,
            artifact_hash="recall-hash-2",
            result="passed",
            trust_level="controlled_check",
            dimension="delayed_recall",
            evidence_kind="delayed_recall",
            recall_delay_days=14.0,
            recall_rating="easy",
        )
        restarted_runtime.attempt_store.update_attempt(
            recall_b["attempt_id"], workspace_id=context_id, status="completed"
        )

        skills_t2 = project_skills(
            _collect_all_evidence(restarted_runtime.attempt_store, workspace_id=context_id)
        )
        assert skills_t2["implementation"]["state"] == "independent"
        assert skills_t2["transfer"]["state"] == "repeat_verified"
        assert skills_t2["delayed_recall"]["state"] == "repeat_verified"

        ledger_after_restart = [
            e
            for e in restarted_runtime.event_ledger.all_entries()
            if e.project_id == context_id and e.event_type == "training_evidence_recorded"
        ]
        assert len(ledger_after_restart) >= 6
        _assert_zero_repo_pollution(project_repo)
