from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from enum import Enum
from typing import Literal

from ..core.models import LearningPlan, ReviewQueueItem
from .models import MasteryRecord, ProgressRecord, ReflectionRecord, WeaknessRecord, utc_now
from .models import MemorySnapshot as LaneMemorySnapshot
from .workspace_recovery import (
    PLAN_RUNTIME_KEY,
    live_coach_stage_label,
    select_plan_runtime_for_scope,
)

ReviewQueueSource = Literal["weakness", "mastery", "reflection", "plan"]
ReviewQueueSeverity = Literal["low", "medium", "high"]
ReviewQueueSurfaceMode = Literal["due", "ahead", "digest"]


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _prefers_chinese(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("zh") or _contains_chinese(value)


def _prefers_explicit_non_chinese_locale(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized) and "-" in normalized and not normalized.startswith("zh")


def _localized_text(english: str, chinese: str, context: str = "") -> str:
    return chinese if _prefers_chinese(context) else english


class ReviewRating(Enum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class ReviewScheduler:
    _surface_rank = {"due": 0, "ahead": 1, "digest": 2}
    _severity_rank = {"high": 0, "medium": 1, "low": 2}
    _source_rank = {"reflection": 0, "weakness": 1, "mastery": 2, "plan": 3}

    def process_mastery_review(
        self,
        mastery: MasteryRecord,
        rating: ReviewRating | str,
    ) -> MasteryRecord:
        normalized_rating = self._normalize_rating(rating)
        now = utc_now()
        next_score = self._next_score(mastery.score, normalized_rating)
        next_confidence = self._next_confidence(mastery.confidence, normalized_rating)
        state = self._next_state(mastery, normalized_rating)
        interval_days = self._next_interval_days(normalized_rating, next_score)
        next_review_at = now + timedelta(days=interval_days)
        retrievability = self._estimate_retrievability(
            score=next_score,
            confidence=next_confidence,
            interval_days=interval_days,
            rating=normalized_rating,
        )
        return MasteryRecord(
            concept=mastery.concept,
            score=next_score,
            confidence=next_confidence,
            state=state,
            retrievability=retrievability,
            due_date=next_review_at,
            updated_at=now,
            next_review_at=next_review_at,
        )

    def derive_due_reviews(
        self,
        *,
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot,
        weakness_records: list[WeaknessRecord],
    ) -> list[ReviewQueueItem]:
        now = utc_now()
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        review_cadence = str(workspace.get("review_cadence") or "").strip() or "steady"
        reminder_mode = str(workspace.get("review_reminder_mode") or "").strip() or "due"
        horizon_days = self._review_horizon_days(review_cadence, reminder_mode)
        language_context = self._language_context(
            lane_snapshot,
            self._workspace_value(lane_snapshot, "summary"),
            self._workspace_value(lane_snapshot, "focus_area"),
        )
        mastery_map = {item.concept.strip(): item.score for item in lane_snapshot.mastery if item.concept.strip()}
        active_thread = workspace.get("active_thread")
        if not isinstance(active_thread, dict):
            active_thread = {}
        active_thread_scenario = str(active_thread.get("scenario") or "").strip()
        active_thread_focus = str(active_thread.get("focus_area") or "").strip()
        active_thread_next_step = str(active_thread.get("next_step") or "").strip()
        active_thread_blocker = str(active_thread.get("blocker") or "").strip()
        active_thread_verified = str(active_thread.get("verified_result") or "").strip()
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area")
        latest_next_step = self._workspace_value(lane_snapshot, "next_step")
        latest_review_note = str(workspace.get("latest_coach_review_note") or "").strip()
        latest_scenario = self._workspace_value(lane_snapshot, "scenario")
        latest_progress = lane_snapshot.progress[0] if lane_snapshot.progress else None
        active_stage = self._active_stage(plan)
        delay_live_thread_reviews = self._should_delay_live_thread_reviews(
            lane_snapshot=lane_snapshot,
            latest_scenario=latest_scenario,
            latest_review_note=latest_review_note,
            active_thread_focus=active_thread_focus,
            active_thread_next_step=active_thread_next_step,
            active_thread_blocker=active_thread_blocker,
            active_thread_verified=active_thread_verified,
        )

        due_items: list[ReviewQueueItem] = []

        for weakness in weakness_records:
            if weakness.next_review_at and not self._within_horizon(
                weakness.next_review_at,
                now=now,
                horizon_days=horizon_days + (1 if weakness.severity >= 3 else 0),
            ):
                continue
            focus_area = self._choose_focus_area(
                active_thread_focus,
                latest_focus_area,
                weakness.concept,
            )
            linked_context = self._join_context(
                weakness.last_seen_context,
                weakness.latest_example,
                active_thread_next_step,
                latest_next_step,
                latest_review_note,
            )
            task_hint = self._weakness_task_hint(
                weakness=weakness,
                focus_area=focus_area,
                linked_context=linked_context,
                language_context=language_context or weakness.reason or focus_area,
            )
            interval_days = self._interval_days(
                due_at=weakness.next_review_at,
                fallback=self._weakness_interval_days(weakness.severity, weakness.recurrence_count),
                now=now,
            )
            due_items.append(
                self._make_item(
                    concept=weakness.concept,
                    reason=weakness.reason,
                    due_at=weakness.next_review_at,
                    source="weakness",
                    severity=self._severity_label(weakness.severity),
                    reminder_mode=reminder_mode,
                    review_cadence=review_cadence,
                    task_hint=task_hint,
                    focus_area=focus_area,
                    linked_context=linked_context,
                    interval_days=interval_days,
                    mastery_score=mastery_map.get(weakness.concept.strip()),
                    force_surface_mode="due" if active_thread_focus and focus_area == active_thread_focus else None,
                )
            )

        for mastery in lane_snapshot.mastery:
            if mastery.score >= 0.75 and mastery.next_review_at is None:
                continue
            if mastery.next_review_at and not self._within_horizon(
                mastery.next_review_at,
                now=now,
                horizon_days=horizon_days + (2 if mastery.score < 0.4 else 0),
            ):
                continue
            if mastery.next_review_at is None and mastery.score >= 0.6:
                continue
            focus_area = self._choose_focus_area(
                active_thread_focus,
                latest_focus_area,
                mastery.concept,
            )
            if delay_live_thread_reviews and self._matches_live_thread_focus(
                concept=mastery.concept,
                focus_area=focus_area,
                active_thread_focus=active_thread_focus,
                latest_focus_area=latest_focus_area,
            ):
                continue
            linked_context = self._join_context(
                active_thread_next_step,
                latest_next_step,
                active_thread_verified,
                active_thread_blocker,
            )
            task_hint = self._mastery_task_hint(
                mastery=mastery,
                focus_area=focus_area,
                linked_context=linked_context,
                language_context=language_context or mastery.concept,
            )
            interval_days = self._interval_days(
                due_at=mastery.next_review_at,
                fallback=self._mastery_interval_days(mastery.score),
                now=now,
            )
            due_items.append(
                self._make_item(
                    concept=mastery.concept,
                    reason=_localized_text(
                        "Revisit this concept through one small implementation move, not only explanation.",
                        "把这个概念放回一小段真实实现里再过一遍，不要只停留在解释层面。",
                        language_context or mastery.concept,
                    ),
                    due_at=mastery.next_review_at,
                    source="mastery",
                    severity="high" if mastery.score < 0.35 else "medium" if mastery.score < 0.55 else "low",
                    reminder_mode=reminder_mode,
                    review_cadence=review_cadence,
                    task_hint=task_hint,
                    focus_area=focus_area,
                    linked_context=linked_context,
                    interval_days=interval_days,
                    mastery_score=mastery.score,
                )
            )

        latest_reflection = lane_snapshot.reflections[-1] if lane_snapshot.reflections else None
        if latest_reflection and not delay_live_thread_reviews:
            due_items.append(
                self._reflection_item(
                    reflection=latest_reflection,
                    fallback_focus_area=latest_focus_area or active_thread_focus or "recent-reflection",
                    linked_context=self._join_context(
                        latest_next_step,
                        active_thread_next_step,
                        latest_review_note,
                    ),
                    reminder_mode=reminder_mode,
                    review_cadence=review_cadence,
                    language_context=language_context or latest_reflection.summary,
                    due_at=latest_reflection.created_at + timedelta(days=2),
                    severity="low",
                )
            )

        if not delay_live_thread_reviews and active_thread_focus and active_thread_next_step:
            active_thread_step = self._language_safe_dynamic_value(
                active_thread_next_step,
                language_context,
                fallback_english="the current next step",
                fallback_chinese="当前这一步",
            )
            due_items.append(
                self._make_item(
                    concept=active_thread_focus,
                    reason=_localized_text(
                        f"Stay on the live coaching thread and verify this next move before widening scope: {active_thread_step}",
                        f"先沿着当前这条训练主线把这一步验证掉，再考虑扩范围：{active_thread_step}",
                        language_context or active_thread_next_step or active_thread_focus,
                    ),
                    due_at=now + timedelta(hours=12),
                    source="reflection",
                    severity="high" if active_thread_blocker else "medium",
                    reminder_mode=reminder_mode,
                    review_cadence=review_cadence,
                    task_hint=self._thread_task_hint(
                        scenario=active_thread_scenario or latest_scenario,
                        focus_area=active_thread_focus,
                        step=active_thread_step,
                        language_context=language_context or active_thread_next_step,
                    ),
                    focus_area=active_thread_focus,
                    linked_context=self._join_context(
                        active_thread_next_step,
                        active_thread_blocker,
                        active_thread_verified,
                    ),
                    interval_days=1,
                    mastery_score=mastery_map.get(active_thread_focus),
                    force_surface_mode="due",
                )
            )
        elif not delay_live_thread_reviews and latest_focus_area and latest_next_step:
            latest_step = self._language_safe_dynamic_value(
                latest_next_step,
                language_context,
                fallback_english="the latest coach move",
                fallback_chinese="最近这一步",
            )
            due_items.append(
                self._make_item(
                    concept=latest_focus_area,
                    reason=_localized_text(
                        f"Re-check the latest coaching move by finishing or verifying: {latest_step}",
                        f"回到上一轮教练已经压好的这一步，先做完或验证它：{latest_step}",
                        language_context or latest_next_step or latest_focus_area,
                    ),
                    due_at=now + timedelta(days=1),
                    source="reflection",
                    severity="high" if latest_review_note else "medium",
                    reminder_mode=reminder_mode,
                    review_cadence=review_cadence,
                    task_hint=self._thread_task_hint(
                        scenario=latest_scenario,
                        focus_area=latest_focus_area,
                        step=latest_step,
                        language_context=language_context or latest_next_step,
                    ),
                    focus_area=latest_focus_area,
                    linked_context=self._join_context(latest_next_step, latest_review_note),
                    interval_days=1,
                    mastery_score=mastery_map.get(latest_focus_area),
                )
            )
        elif not delay_live_thread_reviews and latest_scenario and latest_next_step:
            scenario_step = self._language_safe_dynamic_value(
                latest_next_step,
                language_context,
                fallback_english="the current thread step",
                fallback_chinese="当前这一步",
            )
            due_items.append(
                self._make_item(
                    concept=latest_scenario.replace("_", "-"),
                    reason=_localized_text(
                        f"Return to the latest coach turn and verify this next move: {scenario_step}",
                        f"回到最近这一轮教练主线，先把这一步验证掉：{scenario_step}",
                        language_context or latest_next_step or latest_scenario,
                    ),
                    due_at=now + timedelta(days=1),
                    source="reflection",
                    severity="medium",
                    reminder_mode=reminder_mode,
                    review_cadence=review_cadence,
                    task_hint=self._thread_task_hint(
                        scenario=latest_scenario,
                        focus_area=latest_scenario.replace("_", " "),
                        step=scenario_step,
                        language_context=language_context or latest_next_step,
                    ),
                    focus_area=latest_scenario.replace("_", " "),
                    linked_context=latest_next_step,
                    interval_days=1,
                )
            )
        elif not delay_live_thread_reviews and latest_progress and latest_progress.next_step:
            due_items.append(
                self._progress_item(
                    progress=latest_progress,
                    reminder_mode=reminder_mode,
                    review_cadence=review_cadence,
                    language_context=language_context or latest_progress.next_step,
                    due_at=now + timedelta(days=1),
                    mastery_score=mastery_map.get((latest_progress.focus_area or latest_progress.lane).strip()),
                )
            )

        if active_stage and not any(item.source == "plan" for item in due_items):
            recovered_runtime = select_plan_runtime_for_scope(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                str(workspace.get("workspace_id") or "").strip(),
            )
            stage_label = live_coach_stage_label(
                plan=plan,
                runtime=recovered_runtime,
                existing=recovered_runtime,
                stage_title=active_stage.title,
            )
            if stage_label:
                due_items.append(
                    self._make_item(
                        concept=stage_label,
                        reason=_localized_text(
                            "After the next thin implementation slice lands, restate why this stage boundary still holds.",
                            "等下一个小切片落地后，回头确认一下这个阶段边界为什么还成立。",
                            language_context or stage_label,
                        ),
                        due_at=now + timedelta(days=2),
                        source="plan",
                        severity="medium",
                        reminder_mode=reminder_mode,
                        review_cadence=review_cadence,
                        task_hint=_localized_text(
                            f"After the patch lands, explain how it still fits inside '{stage_label}'.",
                            f"补丁落地后，再说明它为什么仍然属于「{stage_label}」这一阶段。",
                            language_context or stage_label,
                        ),
                        focus_area=stage_label,
                        linked_context=getattr(active_stage, "goal", "") or "",
                        interval_days=2,
                    )
                )

        ranked = self._dedupe_items(due_items, active_thread_focus)
        return self._finalize_items(
            ranked,
            reminder_mode=reminder_mode,
            active_thread_focus=active_thread_focus,
        )

    def derive_review_rhythm(
        self,
        *,
        due_reviews: list[ReviewQueueItem],
        lane_snapshot: LaneMemorySnapshot,
    ) -> str:
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        language_context = self._language_context(
            lane_snapshot,
            self._workspace_value(lane_snapshot, "summary"),
            self._workspace_value(lane_snapshot, "focus_area"),
        )
        review_cadence = str(workspace.get("review_cadence") or "").strip() or "steady"
        reminder_mode = str(workspace.get("review_reminder_mode") or "").strip() or "due"

        if not due_reviews:
            base = _localized_text(
                "Review rhythm: finish one visible move, verify it, then decide whether to expand or revisit.",
                "复习节奏：先完成一个看得见的小动作并验证它，再决定是继续展开还是回看。",
                language_context,
            )
            if review_cadence == "light":
                return _localized_text(
                    f"{base} Keep reminders quiet unless the thread starts drifting.",
                    f"{base} 提醒会更克制，除非这条主线开始跑偏。",
                    language_context,
                )
            if review_cadence == "active":
                return _localized_text(
                    f"{base} Check back quickly after the slice lands so momentum does not decay.",
                    f"{base} 这一步完成后尽快回看一次，别让节奏散掉。",
                    language_context,
                )
            return base

        counts = Counter(item.surface_mode for item in due_reviews)
        lead = due_reviews[0]
        lead_domain = self._review_domain(
            lead.focus_area,
            lead.linked_context,
            lead.reason,
            lead.task_hint,
            self._workspace_value(lane_snapshot, "scenario"),
        )
        lead_move_label = self._review_move_label(lead_domain, language_context)
        lead_target = self._language_safe_dynamic_value(
            lead.focus_area or lead.concept,
            language_context,
            fallback_english="the current focus",
            fallback_chinese="当前重点",
        )
        canonical_lead_target = self._canonical_domain_focus(lead_domain, language_context)
        if canonical_lead_target:
            lead_target = canonical_lead_target
        lead_hint = self._sanitize_context_for_language(lead.task_hint or lead.reason, language_context) or _localized_text(
            "the next smallest verifiable code move",
            "下一步最小且可验证的代码动作",
            language_context,
        )

        if counts.get("due", 0):
            base = _localized_text(
                f"Review rhythm: {counts['due']} review checkpoint(s) are due now. Start with '{lead_target}' by doing this {lead_move_label}: {lead_hint}",
                f"复习节奏：当前有 {counts['due']} 个点已经该回看了。先围绕「{lead_target}」做这一步{lead_move_label}：{lead_hint}",
                language_context or lead_target or lead_hint,
            )
        elif counts.get("ahead", 0):
            base = _localized_text(
                f"Review rhythm: nothing is late yet, but {counts['ahead']} checkpoint(s) should surface before you switch lanes. The closest one is '{lead_target}'; keep the next move as: {lead_hint}",
                f"复习节奏：虽然还没有真正逾期，但有 {counts['ahead']} 个点应该在你切线前先浮出来。离你最近的是「{lead_target}」；下一步先守住：{lead_hint}",
                language_context or lead_target or lead_hint,
            )
        else:
            base = _localized_text(
                f"Review rhythm: the next revisit can stay bundled for now. Keep '{lead_target}' in the next digest around this move: {lead_hint}",
                f"复习节奏：下一轮回看目前可以先合并处理。把「{lead_target}」放进下一次 digest，一起围绕这一步回看：{lead_hint}",
                language_context or lead_target or lead_hint,
            )

        if counts.get("digest", 0):
            base += _localized_text(
                f" {counts['digest']} lower-pressure review point(s) are bundled behind it so the main thread stays readable.",
                f" 另外还有 {counts['digest']} 个低压力回看点已经被收进后面的 digest，不会抢走主线。",
                language_context,
            )

        if reminder_mode == "ahead" and counts.get("ahead", 0):
            base += _localized_text(
                " These prompts should appear slightly before forgetting sets in.",
                " 这些提醒会略微提前出现，尽量在你忘掉之前接住。",
                language_context,
            )
        elif reminder_mode == "digest" and counts.get("digest", 0):
            base += _localized_text(
                " Adjacent follow-ups stay merged unless the pressure becomes urgent.",
                " 相邻回看点会尽量保持合并，除非压力已经升高到必须单独提醒。",
                language_context,
            )

        if review_cadence == "light":
            base += _localized_text(
                " Foreground only the highest-value revisit.",
                " 前台只抬出最值得现在处理的那一个。",
                language_context,
            )
        elif review_cadence == "active":
            base += _localized_text(
                " Once one slice is verified, bring the next revisit forward quickly.",
                " 一旦有一个切片验证完，就尽快把下一次回看提上来，保持热度。",
                language_context,
            )

        return base

    def _should_delay_live_thread_reviews(
        self,
        *,
        lane_snapshot: LaneMemorySnapshot,
        latest_scenario: str,
        latest_review_note: str,
        active_thread_focus: str,
        active_thread_next_step: str,
        active_thread_blocker: str,
        active_thread_verified: str,
    ) -> bool:
        if latest_scenario != "idea_implementation":
            return False
        if latest_review_note or active_thread_blocker or active_thread_verified:
            return False
        if not active_thread_focus or not active_thread_next_step:
            return False
        recent_messages = len(lane_snapshot.session.recent_messages) if lane_snapshot.session else 0
        if recent_messages > 2:
            return False
        if len(lane_snapshot.reflections) > 1:
            return False
        return True

    def _matches_live_thread_focus(
        self,
        *,
        concept: str,
        focus_area: str,
        active_thread_focus: str,
        latest_focus_area: str,
    ) -> bool:
        normalized_focus_candidates = {
            item.strip().lower()
            for item in (active_thread_focus, latest_focus_area)
            if item and item.strip()
        }
        if not normalized_focus_candidates:
            return False
        normalized_concept = concept.strip().lower()
        normalized_focus_area = focus_area.strip().lower()
        return (
            normalized_concept in normalized_focus_candidates
            or normalized_focus_area in normalized_focus_candidates
            or any(normalized_concept == f"{candidate}:next-step" for candidate in normalized_focus_candidates)
        )

    def _reflection_item(
        self,
        *,
        reflection: ReflectionRecord,
        fallback_focus_area: str,
        linked_context: str,
        reminder_mode: str,
        review_cadence: str,
        language_context: str,
        due_at: datetime,
        severity: ReviewQueueSeverity,
        ) -> ReviewQueueItem:
        reflection_summary = self._language_safe_dynamic_value(
            reflection.summary,
            language_context,
            fallback_english="the latest reflection",
            fallback_chinese="最近这次复盘",
        )
        reflection_hint = self._thread_task_hint(
            scenario=fallback_focus_area,
            focus_area=fallback_focus_area,
            step=reflection_summary,
            language_context=language_context or reflection.summary,
        )
        return self._make_item(
            concept=reflection.task_id or fallback_focus_area or "recent-reflection",
            reason=_localized_text(
                f"Use the latest reflection as a concrete recall prompt: {reflection_summary}",
                f"把最近这次复盘当作一个具体回看提示：{reflection_summary}",
                language_context or reflection.summary,
            ),
            due_at=due_at,
            source="reflection",
            severity=severity,
            reminder_mode=reminder_mode,
            review_cadence=review_cadence,
            task_hint=reflection_hint,
            focus_area=fallback_focus_area,
            linked_context=linked_context,
            interval_days=2,
        )

    def _progress_item(
        self,
        *,
        progress: ProgressRecord,
        reminder_mode: str,
        review_cadence: str,
        language_context: str,
        due_at: datetime,
        mastery_score: float | None,
    ) -> ReviewQueueItem:
        focus_area = (progress.focus_area or progress.lane).strip() or "tracked-progress"
        progress_step = self._language_safe_dynamic_value(
            progress.next_step,
            language_context,
            fallback_english="the latest tracked step",
            fallback_chinese="最近这一步",
        )
        progress_hint = self._thread_task_hint(
            scenario=progress.lane,
            focus_area=focus_area,
            step=progress_step,
            language_context=language_context or progress.next_step,
        )
        return self._make_item(
            concept=focus_area,
            reason=_localized_text(
                f"Resume the latest tracked progress by validating this next step: {progress_step}",
                f"沿着最近记录下来的这条进度继续，把这一步先验证掉：{progress_step}",
                language_context or progress.next_step,
            ),
            due_at=due_at,
            source="reflection",
            severity="medium",
            reminder_mode=reminder_mode,
            review_cadence=review_cadence,
            task_hint=progress_hint,
            focus_area=focus_area,
            linked_context=self._join_context(progress.next_step, progress.summary),
            interval_days=1,
            mastery_score=mastery_score,
        )

    def _make_item(
        self,
        *,
        concept: str,
        reason: str,
        due_at: datetime | None,
        source: ReviewQueueSource,
        severity: ReviewQueueSeverity,
        reminder_mode: str,
        review_cadence: str,
        task_hint: str,
        focus_area: str,
        linked_context: str,
        interval_days: int | None,
        mastery_score: float | None = None,
        force_surface_mode: ReviewQueueSurfaceMode | None = None,
    ) -> ReviewQueueItem:
        surface_mode = force_surface_mode or self._surface_mode(
            due_at=due_at,
            severity=severity,
            reminder_mode=reminder_mode,
            review_cadence=review_cadence,
            mastery_score=mastery_score,
        )
        return ReviewQueueItem(
            concept=concept,
            reason=reason,
            due_at=due_at.isoformat() if due_at else None,
            source=source,
            severity=severity,
            surface_mode=surface_mode,
            task_hint=task_hint,
            focus_area=focus_area,
            linked_context=linked_context,
            interval_days=interval_days,
            mastery_score=round(mastery_score, 3) if mastery_score is not None else None,
        )

    def _dedupe_items(
        self,
        items: list[ReviewQueueItem],
        active_thread_focus: str,
    ) -> list[ReviewQueueItem]:
        deduped: dict[str, ReviewQueueItem] = {}
        for item in items:
            key = self._dedupe_key(item)
            existing = deduped.get(key)
            if existing is None or self._item_sort_key(item, active_thread_focus) < self._item_sort_key(
                existing,
                active_thread_focus,
            ):
                deduped[key] = item
        return sorted(
            deduped.values(),
            key=lambda item: self._item_sort_key(item, active_thread_focus),
        )

    def _finalize_items(
        self,
        items: list[ReviewQueueItem],
        *,
        reminder_mode: str,
        active_thread_focus: str,
    ) -> list[ReviewQueueItem]:
        head = list(items[:4])
        if head and not any(item.source == "plan" for item in head):
            trailing_plan = next((item for item in items[4:] if item.source == "plan"), None)
            if trailing_plan is not None:
                head[-1] = trailing_plan

        resolved: list[ReviewQueueItem] = []
        for index, item in enumerate(head):
            next_item = item
            if reminder_mode == "digest" and index >= 1 and item.surface_mode != "due":
                next_item = item.model_copy(update={"surface_mode": "digest"})
            elif reminder_mode != "ahead" and index >= 2 and item.surface_mode == "ahead":
                next_item = item.model_copy(update={"surface_mode": "digest"})
            if active_thread_focus and next_item.focus_area == active_thread_focus and index == 0:
                next_item = next_item.model_copy(update={"surface_mode": "due"})
            resolved.append(next_item)
        return resolved

    def _item_sort_key(self, item: ReviewQueueItem, active_thread_focus: str) -> tuple[int, int, int, str, int, float]:
        return (
            0 if active_thread_focus and item.focus_area == active_thread_focus else 1,
            self._surface_rank.get(item.surface_mode, 1),
            self._severity_rank.get(item.severity, 1),
            item.due_at or "9999-12-31T00:00:00+00:00",
            self._source_rank.get(item.source, 4),
            item.mastery_score if item.mastery_score is not None else 1.0,
        )

    def _dedupe_key(self, item: ReviewQueueItem) -> str:
        focus = (item.focus_area or item.concept).strip().lower()
        concept = item.concept.strip().lower()
        if focus:
            return f"{item.source}:{focus}:{concept}"
        return f"{item.source}:{concept}"

    def _surface_mode(
        self,
        *,
        due_at: datetime | None,
        severity: ReviewQueueSeverity,
        reminder_mode: str,
        review_cadence: str,
        mastery_score: float | None,
    ) -> ReviewQueueSurfaceMode:
        if due_at is None:
            if severity == "high" or (mastery_score is not None and mastery_score < 0.4):
                return "due"
            return "digest" if reminder_mode == "digest" else "ahead" if reminder_mode == "ahead" else "due"

        now = utc_now()
        delta_days = (due_at - now).total_seconds() / 86400
        if delta_days <= 0:
            return "due"
        if delta_days <= 1 or severity == "high":
            return "due" if reminder_mode != "ahead" else "ahead"
        ahead_window = self._review_horizon_days(review_cadence, "ahead")
        if delta_days <= ahead_window:
            return "ahead"
        return "digest"

    def _review_horizon_days(self, review_cadence: str, reminder_mode: str) -> int:
        base = 2 if review_cadence == "light" else 4 if review_cadence == "active" else 3
        if reminder_mode == "ahead":
            return base + 1
        if reminder_mode == "digest":
            return base + 2
        return base

    def _within_horizon(
        self,
        due_at: datetime,
        *,
        now: datetime,
        horizon_days: int,
    ) -> bool:
        return due_at <= now + timedelta(days=horizon_days)

    def _interval_days(
        self,
        *,
        due_at: datetime | None,
        fallback: int,
        now: datetime,
    ) -> int:
        if due_at is None:
            return fallback
        delta_days = int(round((due_at - now).total_seconds() / 86400))
        return max(0, delta_days)

    def _weakness_interval_days(self, severity: int, recurrence_count: int) -> int:
        if severity >= 3 or recurrence_count >= 3:
            return 1
        if severity == 2:
            return 2
        return 4

    def _mastery_interval_days(self, score: float) -> int:
        if score < 0.35:
            return 1
        if score < 0.55:
            return 2
        return 4

    def _weakness_task_hint(
        self,
        *,
        weakness: WeaknessRecord,
        focus_area: str,
        linked_context: str,
        language_context: str,
    ) -> str:
        domain = self._review_domain(focus_area, linked_context, weakness.reason, language_context)
        if domain:
            return self._learn_first_review_hint(
                domain=domain,
                focus_area=focus_area,
                step_or_context=linked_context or weakness.reason,
                language_context=language_context,
            )
        safe_linked_context = self._sanitize_context_for_language(linked_context, language_context)
        if safe_linked_context:
            return _localized_text(
                f"Patch the concrete failure path around '{focus_area}' and prove this context no longer breaks: {safe_linked_context}",
                f"围绕「{focus_area}」把这个具体失败路径补掉，并证明下面这段上下文不再出错：{safe_linked_context}",
                language_context,
            )
        return _localized_text(
            f"Turn the repeated weakness in '{focus_area}' into one narrow patch with a visible check.",
            f"把「{focus_area}」这条反复出现的薄弱点压成一个很小的补丁，再配一个看得见的验证。",
            language_context,
        )

    def _mastery_task_hint(
        self,
        *,
        mastery: MasteryRecord,
        focus_area: str,
        linked_context: str,
        language_context: str,
    ) -> str:
        domain = self._review_domain(focus_area, linked_context, mastery.concept, language_context)
        if domain or mastery.score < 0.4:
            return self._learn_first_review_hint(
                domain=domain,
                focus_area=focus_area,
                step_or_context=linked_context or mastery.concept,
                language_context=language_context,
            )
        safe_linked_context = self._sanitize_context_for_language(linked_context, language_context)
        if safe_linked_context:
            return _localized_text(
                f"Touch '{focus_area}' again through this nearby context: {safe_linked_context}",
                f"把「{focus_area}」重新放回这段邻近上下文里再做一次：{safe_linked_context}",
                language_context,
            )
        return _localized_text(
            f"Reinforce '{focus_area}' with one tiny patch or one targeted verification step.",
            f"用一个很小的补丁或一次定向验证，再加固一下「{focus_area}」。",
            language_context,
        )

    def _review_domain(self, *values: str) -> str:
        blob = " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
        if not blob:
            return ""
        if any(
            token in blob
            for token in (
                "remote ssh",
                "remote workspace",
                "remote tunnel",
                "dev container",
                "devcontainer",
                "vscode remote",
                "credential mode",
                "workspace boundary",
                "远程",
                "工作区边界",
                "凭据",
                "主机",
            )
        ):
            return "remote_workspace"
        if any(
            token in blob
            for token in (
                "debug loop",
                "breakpoint",
                "launch.json",
                "debug console",
                "watch expression",
                "step into",
                "step over",
                "debug",
                "调试",
                "断点",
                "调用栈",
                "暂停",
            )
        ):
            return "debug_loop"
        if any(
            token in blob
            for token in (
                "function guidance",
                "function contract",
                "signature help",
                "hover",
                "go to definition",
                "peek definition",
                "call site",
                "parameter hint",
                "function signature",
                "function hint",
                "函数契约",
                "函数提示",
                "参数提示",
                "调用点",
                "签名提示",
                "定义",
            )
        ):
            return "function_guidance"
        if any(
            token in blob
            for token in (
                "language corruption",
                "provider blocked",
                "provider failure",
                "language probe",
                "语言损坏",
                "语言探测",
                "provider 故障",
                "provider 阻塞",
            )
        ):
            return "provider_blocked"
        return ""

    def _review_move_label(self, domain: str, language_context: str) -> str:
        if _prefers_chinese(language_context):
            return "学习动作" if domain in {"remote_workspace", "debug_loop", "function_guidance", "provider_blocked"} else "动作"
        return "next learning move" if domain in {"remote_workspace", "debug_loop", "function_guidance", "provider_blocked"} else "next move"

    def _canonical_domain_focus(self, domain: str, language_context: str) -> str:
        if domain == "remote_workspace":
            return _localized_text(
                "VS Code remote workspace",
                "VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a",
                language_context,
            )
        if domain == "debug_loop":
            return _localized_text(
                "VS Code debug loop",
                "VS Code \u8c03\u8bd5\u95ed\u73af",
                language_context,
            )
        if domain == "function_guidance":
            return _localized_text(
                "function contract reading",
                "\u51fd\u6570\u5951\u7ea6\u5224\u65ad",
                language_context,
            )
        return ""

    def _learn_first_review_hint(
        self,
        *,
        domain: str,
        focus_area: str,
        step_or_context: str,
        language_context: str,
    ) -> str:
        safe_focus = self._language_safe_dynamic_value(
            focus_area,
            language_context,
            fallback_english="the current topic",
            fallback_chinese="当前主题",
        )
        canonical_focus = self._canonical_domain_focus(domain, language_context)
        if canonical_focus:
            safe_focus = canonical_focus
        safe_context = self._sanitize_context_for_language(step_or_context, language_context)
        if domain == "remote_workspace":
            if safe_context:
                return _localized_text(
                    f"Re-state the real workspace boundary for '{safe_focus}', then verify one host, path, or credential fact through this step: {safe_context}",
                    f"先把「{safe_focus}」对应的真实工作区边界说清楚，再用这一步核对一个主机、路径或凭据事实：{safe_context}",
                    language_context,
                )
            return _localized_text(
                f"Re-state the real workspace boundary for '{safe_focus}', then verify one host/path fact and the safe credential mode before you change code.",
                f"先把「{safe_focus}」对应的真实工作区边界说清楚，再确认一个主机或路径事实，以及安全的 credential mode，然后再考虑改代码。",
                language_context,
            )
        if domain == "debug_loop":
            if safe_context:
                return _localized_text(
                    f"Shrink '{safe_focus}' back to one trustworthy debug loop, then name the first pause point and the single value you will inspect through this step: {safe_context}",
                    f"先把「{safe_focus}」收回一个可信的 debug loop，再结合这一步说明第一个暂停点和你只看的那个值：{safe_context}",
                    language_context,
                )
            return _localized_text(
                f"Shrink '{safe_focus}' back to one trustworthy debug loop: reproduce once, pause at the first state change, and inspect one value before editing.",
                f"先把「{safe_focus}」收回一个可信的 debug loop：稳定复现一次，在第一次状态变化处停住，只看一个值，再考虑编辑。",
                language_context,
            )
        if domain == "function_guidance":
            if safe_context:
                return _localized_text(
                    f"Anchor '{safe_focus}' to one live call site, then confirm hover, signature help, and definition through this context before you edit anything: {safe_context}",
                    f"先把「{safe_focus}」锚定到一个真实调用点上，再结合这段上下文按 hover、signature help、definition 的顺序确认它，确认完再动代码：{safe_context}",
                    language_context,
                )
            return _localized_text(
                f"Anchor '{safe_focus}' to one live call site, then confirm hover, signature help, and definition before you edit anything.",
                f"先把「{safe_focus}」锚定到一个真实调用点上，再按 hover、signature help、definition 的顺序确认它，确认完再动代码。",
                language_context,
            )
        if domain == "provider_blocked":
            return _localized_text(
                f"Keep the next revisit in explanation mode for '{safe_focus}': state one fact you can verify without depending on the provider, then bring back that evidence.",
                f"先把「{safe_focus}」这次回看保持在解释模式：先说出一个不依赖 provider 也能核对的事实，再带回这条证据。",
                language_context,
            )
        if safe_context:
            return _localized_text(
                f"Explain the weakest part of '{safe_focus}' in one concrete example, then verify it through this nearby context: {safe_context}",
                f"先用一个具体例子把「{safe_focus}」里最薄弱的部分讲清楚，再借助这段邻近上下文验证它：{safe_context}",
                language_context,
            )
        return _localized_text(
            f"Explain the weakest part of '{safe_focus}' in one concrete example before you turn it back into code.",
            f"先用一个具体例子把「{safe_focus}」里最薄弱的部分讲清楚，再把它重新放回代码里。",
            language_context,
        )

    def _thread_task_hint(
        self,
        *,
        scenario: str,
        focus_area: str,
        step: str,
        language_context: str,
    ) -> str:
        domain = self._review_domain(scenario, focus_area, step, language_context)
        if domain:
            return self._learn_first_review_hint(
                domain=domain,
                focus_area=focus_area,
                step_or_context=step,
                language_context=language_context,
            )
        return _localized_text(
            f"Turn the current thread into one visible patch or verification step: {step}",
            f"把当前主线收成一个可见的小补丁或验证步骤：{step}",
            language_context,
        )

    def _choose_focus_area(self, *values: str) -> str:
        for value in values:
            cleaned = value.strip()
            if cleaned:
                return cleaned
        return ""

    def _join_context(self, *parts: str) -> str:
        cleaned = [part.strip() for part in parts if part and part.strip()]
        joined = " | ".join(cleaned[:3])
        return joined[:220]

    def _severity_label(self, severity: int) -> ReviewQueueSeverity:
        if severity >= 3:
            return "high"
        if severity == 2:
            return "medium"
        return "low"

    def _normalize_rating(self, rating: ReviewRating | str) -> ReviewRating:
        if isinstance(rating, ReviewRating):
            return rating
        normalized = str(rating or "").strip().lower()
        return {
            "again": ReviewRating.AGAIN,
            "hard": ReviewRating.HARD,
            "good": ReviewRating.GOOD,
            "easy": ReviewRating.EASY,
        }.get(normalized, ReviewRating.GOOD)

    def _next_state(self, mastery: MasteryRecord, rating: ReviewRating) -> str:
        if rating == ReviewRating.AGAIN:
            return "relearning" if mastery.score >= 0.25 else "learning"
        if rating == ReviewRating.HARD:
            return "learning" if mastery.score < 0.55 else "review"
        return "review"

    def _next_score(self, score: float, rating: ReviewRating) -> float:
        delta = {
            ReviewRating.AGAIN: -0.18,
            ReviewRating.HARD: -0.05,
            ReviewRating.GOOD: 0.08,
            ReviewRating.EASY: 0.14,
        }[rating]
        return round(max(0.0, min(1.0, score + delta)), 3)

    def _next_confidence(self, confidence: float, rating: ReviewRating) -> float:
        delta = {
            ReviewRating.AGAIN: -0.12,
            ReviewRating.HARD: -0.04,
            ReviewRating.GOOD: 0.05,
            ReviewRating.EASY: 0.08,
        }[rating]
        return round(max(0.0, min(1.0, confidence + delta)), 3)

    def _next_interval_days(self, rating: ReviewRating, score: float) -> int:
        if rating == ReviewRating.AGAIN:
            return 1
        if rating == ReviewRating.HARD:
            return 2 if score < 0.5 else 3
        if rating == ReviewRating.EASY:
            return max(4, int(round(5 + score * 7)))
        return max(2, int(round(3 + score * 5)))

    def _estimate_retrievability(
        self,
        *,
        score: float,
        confidence: float,
        interval_days: int,
        rating: ReviewRating,
    ) -> float:
        base = 0.22 + score * 0.45 + confidence * 0.2
        interval_penalty = min(interval_days * 0.025, 0.25)
        rating_bonus = {
            ReviewRating.AGAIN: -0.08,
            ReviewRating.HARD: -0.02,
            ReviewRating.GOOD: 0.03,
            ReviewRating.EASY: 0.06,
        }[rating]
        return round(max(0.0, min(1.0, base - interval_penalty + rating_bonus)), 3)

    def _workspace_value(self, lane_snapshot: LaneMemorySnapshot, field: str) -> str:
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        active_thread = workspace.get("active_thread")
        if isinstance(active_thread, dict):
            active_value = str(active_thread.get(field) or "").strip()
            if active_value:
                return active_value
        direct_keys = {
            "summary": "latest_turn_summary",
            "focus_area": "latest_turn_focus_area",
            "next_step": "latest_turn_next_step",
            "scenario": "latest_turn_scenario",
        }
        direct_key = direct_keys.get(field)
        if direct_key:
            direct_value = str(workspace.get(direct_key) or "").strip()
            if direct_value:
                return direct_value
        session = lane_snapshot.session
        if session:
            if field == "summary" and session.rolling_summary.strip():
                return session.rolling_summary.strip()
            if field == "focus_area" and session.active_focus_area.strip():
                return session.active_focus_area.strip()
            if field == "next_step" and session.latest_next_step.strip():
                return session.latest_next_step.strip()
            if field == "scenario" and session.last_scenario.strip():
                return session.last_scenario.strip()
        return ""

    def _response_language(self, lane_snapshot: LaneMemorySnapshot) -> str:
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        response_language = str(workspace.get("response_language") or "").strip()
        if response_language:
            return response_language
        for preference in lane_snapshot.preferences:
            if preference.key not in {"response_language", "preferred_language"}:
                continue
            preferred = str(preference.value or "").strip()
            if preferred:
                return preferred
        return ""

    def _language_context(self, lane_snapshot: LaneMemorySnapshot, *fallbacks: str) -> str:
        response_language = self._response_language(lane_snapshot)
        if response_language:
            return response_language
        for fallback in fallbacks:
            cleaned = str(fallback or "").strip()
            if cleaned:
                return cleaned
        return ""

    def _sanitize_context_for_language(self, value: str, language_context: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned or not _prefers_explicit_non_chinese_locale(language_context):
            return cleaned
        parts = [part.strip() for part in cleaned.split("|")]
        filtered = [part for part in parts if part and not _contains_chinese(part)]
        if not filtered:
            return ""
        return " | ".join(filtered[:3])[:220]

    def _language_safe_dynamic_value(
        self,
        value: str,
        language_context: str,
        *,
        fallback_english: str,
        fallback_chinese: str,
    ) -> str:
        cleaned = self._sanitize_context_for_language(value, language_context)
        if cleaned:
            return cleaned
        return _localized_text(fallback_english, fallback_chinese, language_context)

    def _active_stage(self, plan: LearningPlan | None):
        if not plan or not plan.stages:
            return None
        return next(
            (stage for stage in plan.stages if stage.id == plan.current_stage_id or stage.status == "active"),
            plan.stages[0],
        )
