from __future__ import annotations

from datetime import timedelta

from app.core.models import LearningPlan, PlanStage
from app.memory.models import WeaknessRecord, utc_now
from app.memory.review_scheduler import ReviewScheduler
from app.memory.service import StructuredMemoryService


def contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def build_lane_snapshot(
    *,
    response_language: str = "en-US",
    latest_turn_summary: str = "Keep the startup thread narrow.",
    latest_turn_focus_area: str = "startup wiring",
    latest_turn_next_step: str = "Patch the config branch and rerun the focused check.",
):
    structured = StructuredMemoryService()
    structured.update_workspace(
        latest_turn_summary=latest_turn_summary,
        latest_turn_focus_area=latest_turn_focus_area,
        latest_turn_next_step=latest_turn_next_step,
        latest_coach_review_note="The config branch still fails before boot completes.",
        review_cadence="active",
        review_reminder_mode="ahead",
        response_language=response_language,
        active_thread={
            "focus_area": latest_turn_focus_area,
            "next_step": latest_turn_next_step,
            "blocker": "The config branch still fails before boot completes.",
            "verified_result": "Boot succeeds until config load.",
        },
    )
    structured.update_mastery(latest_turn_focus_area, delta=0.15, confidence=0.7, review_after_days=1)
    structured.update_mastery("config validation", delta=0.05, confidence=0.6, review_after_days=3)
    structured.schedule_mastery_review(
        latest_turn_focus_area, next_review_at=utc_now() + timedelta(days=1)
    )
    structured.schedule_mastery_review(
        "config validation", next_review_at=utc_now() + timedelta(days=3)
    )
    structured.record_weakness(
        latest_turn_focus_area,
        "The config branch still fails before boot completes.",
        severity=3,
        review_after_days=1,
        context="server/app/bootstrap.py",
    )
    structured.add_reflection(
        "startup-checkpoint",
        "Re-state the boot boundary before widening scope.",
        ["Patch the config branch and rerun the focused check."],
    )
    return structured.snapshot()


def build_plan() -> LearningPlan:
    return LearningPlan(
        id="plan-review",
        title="Coach-first trainer",
        summary="Keep the current lane attached to one real patch.",
        stages=[
            PlanStage(
                id="stage-practice",
                title="Practice",
                goal="Deepen startup review rhythm",
                outcomes=["Land one visible startup patch"],
                status="active",
            )
        ],
        cadence="8 hours per week",
        current_stage_id="stage-practice",
    )


def test_review_scheduler_derives_due_ahead_and_digest_items() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot()
    plan = build_plan()
    weakness_records = [
        WeaknessRecord(
            concept="startup wiring",
            reason="The config branch still fails before boot completes.",
            severity=3,
            recurrence_count=2,
            latest_example="Patch the config branch and rerun the focused check.",
            last_seen_context="server/app/bootstrap.py",
            updated_at=utc_now(),
            next_review_at=utc_now() + timedelta(hours=12),
        )
    ]

    reviews = scheduler.derive_due_reviews(
        plan=plan,
        lane_snapshot=lane_snapshot,
        weakness_records=weakness_records,
    )

    assert reviews
    assert reviews[0].focus_area == "startup wiring"
    assert reviews[0].surface_mode in {"due", "ahead"}
    assert reviews[0].task_hint
    assert reviews[0].linked_context
    assert reviews[0].interval_days is not None
    assert any(item.source == "plan" for item in reviews)


def test_review_scheduler_review_rhythm_mentions_real_training_pressure() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot()
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="startup wiring",
                reason="The config branch still fails before boot completes.",
                severity=3,
                recurrence_count=2,
                latest_example="Patch the config branch and rerun the focused check.",
                last_seen_context="server/app/bootstrap.py",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    rhythm = scheduler.derive_review_rhythm(
        due_reviews=reviews,
        lane_snapshot=lane_snapshot,
    )

    assert "startup wiring" in rhythm.lower() or "startup wiring" in rhythm
    assert "code move" not in rhythm.lower()


def test_review_scheduler_remote_workspace_hints_stay_learn_first() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        latest_turn_summary="Keep the remote boundary grounded in one real host fact.",
        latest_turn_focus_area="VS Code remote workspace",
        latest_turn_next_step="Verify one host label and the safe credential mode before editing.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="VS Code remote workspace",
                reason="The remote boundary is still blurry.",
                severity=3,
                recurrence_count=2,
                latest_example="Verify one host label and the safe credential mode before editing.",
                last_seen_context="remote-ssh",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    assert reviews
    assert any("workspace boundary" in item.task_hint.lower() for item in reviews)
    assert all("code move" not in item.task_hint.lower() for item in reviews)


def test_review_scheduler_debug_loop_hints_stay_learn_first() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        latest_turn_summary="Shrink the debug loop back to one trustworthy pause point.",
        latest_turn_focus_area="VS Code debug loop",
        latest_turn_next_step="Reproduce once, pause at the first state change, and inspect one value.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="VS Code debug loop",
                reason="The learner keeps widening scope before the first breakpoint.",
                severity=3,
                recurrence_count=2,
                latest_example="Reproduce once, pause at the first state change, and inspect one value.",
                last_seen_context="launch.json",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    assert reviews
    assert any("debug loop" in item.task_hint.lower() for item in reviews)
    assert all("code move" not in item.task_hint.lower() for item in reviews)


def test_review_scheduler_function_guidance_hints_stay_learn_first() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        latest_turn_summary="Read the function boundary before touching the module.",
        latest_turn_focus_area="VS Code function guidance",
        latest_turn_next_step="Anchor on one call site, then check hover, signature help, and definition.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="VS Code function guidance",
                reason="The learner edits unfamiliar functions before reading the contract.",
                severity=3,
                recurrence_count=2,
                latest_example="Anchor on one call site, then check hover, signature help, and definition.",
                last_seen_context="src/app.ts",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    assert reviews
    assert any(
        "hover" in item.task_hint.lower() and "signature help" in item.task_hint.lower()
        for item in reviews
    )
    assert all("code move" not in item.task_hint.lower() for item in reviews)


def test_review_scheduler_prefers_explicit_en_us_over_chinese_workspace_text() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        response_language="en-US",
        latest_turn_summary="先围绕 dependency injection 保持这一条主线。",
        latest_turn_focus_area="dependency injection",
        latest_turn_next_step="先把 provider branch 补成一个可验证的小改动。",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="dependency injection",
                reason="这里的 provider branch 还没有被验证。",
                severity=3,
                recurrence_count=2,
                latest_example="先把 provider branch 补成一个可验证的小改动。",
                last_seen_context="server/app/main.py",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    rhythm = scheduler.derive_review_rhythm(
        due_reviews=reviews,
        lane_snapshot=lane_snapshot,
    )

    assert reviews
    assert reviews[0].task_hint
    assert not contains_chinese(reviews[0].task_hint)
    assert rhythm.startswith("Review rhythm:")
    assert not contains_chinese(rhythm)


def test_review_scheduler_prefers_explicit_zh_cn_over_english_workspace_text() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        response_language="zh-CN",
        latest_turn_summary="Keep the dependency injection lane narrow.",
        latest_turn_focus_area="dependency injection",
        latest_turn_next_step="Patch the provider branch and rerun the focused check.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="dependency injection",
                reason="The provider branch still is not verified.",
                severity=3,
                recurrence_count=2,
                latest_example="Patch the provider branch and rerun the focused check.",
                last_seen_context="server/app/main.py",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    rhythm = scheduler.derive_review_rhythm(
        due_reviews=reviews,
        lane_snapshot=lane_snapshot,
    )

    assert reviews
    assert reviews[0].task_hint
    assert contains_chinese(reviews[0].task_hint)
    assert contains_chinese(rhythm)


def test_chinese_review_queue_drops_english_evaluator_prose() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        response_language="zh-CN",
        latest_turn_summary="Widen the scope only after the verified result is preserved.",
        latest_turn_next_step="Widen the scope only after the verified result is preserved.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[],
    )
    assert reviews
    for item in reviews:
        haystack = " ".join(
            str(getattr(item, field, "") or "")
            for field in ("concept", "reason", "task_hint", "focus_area", "linked_context")
        )
        assert "Widen the scope only after the verified result is preserved" not in haystack
    assert any("当前这一步" in item.task_hint or "当前这一步" in item.reason for item in reviews)


def test_language_safe_dynamic_value_falls_back_for_english_prose_in_chinese() -> None:
    scheduler = ReviewScheduler()
    assert scheduler._language_safe_dynamic_value(  # pyright: ignore[reportAttributeAccessIssue]
        "Widen the scope only after the verified result is preserved.",
        "zh-CN",
        fallback_english="the current next step",
        fallback_chinese="当前这一步",
    ) == "当前这一步"


def test_review_scheduler_skips_heuristic_mastery_without_recall_evidence() -> None:
    scheduler = ReviewScheduler()
    structured = StructuredMemoryService()
    structured.update_mastery("unrecalled concept", delta=0.2, review_after_days=1)
    snapshot = structured.snapshot()

    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=snapshot,
        weakness_records=[],
    )

    assert all(item.concept != "unrecalled concept" for item in reviews)


def test_later_score_update_preserves_the_fsrs_owned_due_date() -> None:
    structured = StructuredMemoryService()
    structured.update_mastery("fsrs concept", delta=0.2, review_after_days=1)
    due = utc_now() + timedelta(days=9)
    structured.schedule_mastery_review("fsrs concept", next_review_at=due)
    scheduled = structured._mastery["fsrs concept"]
    assert scheduled.review_source == "fsrs"
    assert scheduled.next_review_at == due

    structured.update_mastery("fsrs concept", delta=0.1, review_after_days=2)
    updated = structured._mastery["fsrs concept"]
    assert updated.review_source == "fsrs"
    assert updated.next_review_at == due
    assert updated.score == scheduled.score + 0.1


def test_due_items_mark_fsrs_recall_vs_no_recall_evidence() -> None:
    scheduler = ReviewScheduler()
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=build_lane_snapshot(),
        weakness_records=[
            WeaknessRecord(
                concept="startup wiring",
                reason="The config branch still fails before boot completes.",
                severity=3,
                recurrence_count=2,
                latest_example="Patch the config branch and rerun the focused check.",
                last_seen_context="server/app/bootstrap.py",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    mastery_items = [item for item in reviews if item.source == "mastery"]
    assert mastery_items
    assert all(item.evidence_basis == "fsrs_recall" for item in mastery_items)
    assert all(
        item.evidence_basis == "no_recall_evidence"
        for item in reviews
        if item.source != "mastery"
    )
