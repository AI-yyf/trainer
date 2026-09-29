"""Coaching-adaptation domain mixin for :class:`MemoryService`.

Weakness/review/teaching-observation/recent-wins/current-focus derivation,
memory-evidence assembly, lane context pressure, the coaching-adaptation
profile, and the ``_summarize_*`` lane summarizers plus thread/workspace
understanding snapshots. Methods are extracted verbatim from
``memory/service.py`` (pure code motion, zero behavior change); the shared
``MemoryService`` state they touch is declared under ``TYPE_CHECKING`` only
and is assigned in ``MemoryService.__init__`` or defined elsewhere on the
class.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

from ..core.models import (
    ActiveThreadSnapshot,
    CoachingAdaptationProfile,
    LearningPlan,
    MemorySnapshot,
    ResourceRecord,
    ReviewQueueItem,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from ..pedagogy.context_pressure import derive_context_pressure
from ..pedagogy.evidence_controls import (
    analyze_learning_evidence,
    pedagogy_evidence_confidence,
    profile_kwargs_from_controls,
    refresh_controls_after_strategy,
    resolve_pedagogy_controls,
)
from .models import (
    MemorySnapshot as LaneMemorySnapshot,
)
from .models import PreferenceRecord, WeaknessRecord
from .onboarding_extraction import _contains_chinese
from .transfer_skills import (
    describe_transfer_skill_state,
    normalize_transfer_skill_state_record,
)
from .workspace_recovery import (
    AFFECT_STATE_KEY,
    CURRENT_TASK_KEY,
    PLAN_RUNTIME_KEY,
    live_coach_focus_area,
    live_coach_stage_label,
    live_plan_snapshot_persist_chrome,
    normalize_latest_affect_state,
    normalize_latest_current_task,
    select_plan_runtime_for_pressure,
    select_plan_runtime_for_scope,
)

if TYPE_CHECKING:
    from .review_scheduler import ReviewScheduler


def _localized_memory_text(en: str, zh: str, context: str = "") -> str:
    normalized_context = context.strip().lower()
    if normalized_context.startswith("zh"):
        return zh
    return zh if _contains_chinese(context) else en


_GENERIC_FOCUS_DISPLAY_LABELS = {
    "implementation": ("implementation slice", "实现切片"),
}


def _display_focus_label(focus: str, context: str = "") -> str:
    cleaned = focus.strip()
    if not cleaned:
        return ""
    localized = _GENERIC_FOCUS_DISPLAY_LABELS.get(cleaned.lower())
    if localized is None:
        return cleaned
    return _localized_memory_text(localized[0], localized[1], context or cleaned)


def _focus_looks_like_request_sentence(value: str) -> bool:
    cleaned = str(value or "").strip()
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if lowered.startswith(
        (
            "teach me ",
            "help me ",
            "show me ",
            "tell me ",
            "walk me through ",
            "guide me ",
            "how to ",
            "please ",
        )
    ):
        return True
    return len(cleaned.split()) >= 7 and cleaned.endswith((".", "?", "。", "？"))


def _guided_lane_focus_label(scenario: str, context: str = "") -> str:
    normalized = str(scenario or "").strip().lower()
    if normalized == "remote_workspace":
        return _localized_memory_text(
            "VS Code remote workspace",
            "VS Code 远程工作区",
            context,
        )
    if normalized == "debug_loop":
        return _localized_memory_text(
            "VS Code debug loop",
            "VS Code 调试闭环",
            context,
        )
    if normalized == "function_guidance":
        return _localized_memory_text(
            "function contract reading",
            "\u51fd\u6570\u5951\u7ea6\u5224\u65ad",
            context,
        )
    return ""


def _workspace_language(workspace: dict[str, Any]) -> str:
    for key in ("response_language", "preferred_language"):
        language = str(workspace.get(key) or "").strip()
        if language:
            return language
    return ""


def _memory_language_context(workspace: dict[str, Any], *fallbacks: str) -> str:
    language = _workspace_language(workspace)
    if language:
        return language
    for value in fallbacks:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _strip_visible_next_step_prefix(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?i)^(?:next(?: step)?\s*:\s*)+", "", cleaned).strip()
    cleaned = re.sub(r"^(?:\u4e0b\u4e00\u6b65[:\uff1a]\s*)+", "", cleaned).strip()
    return cleaned


def _normalize_text_items(values: Any, *, limit: int = 4) -> list[str]:
    if not isinstance(values, list):
        return []
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in items:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    return items


_SYNTHETIC_BOOTSTRAP_CONCEPTS = {
    "new-workspace",
    "plan-discipline",
    "resource-grounding",
}


class CoachingAdaptationMixin:
    """Hosts the coaching-adaptation/evidence-summarization methods of ``MemoryService``."""

    if TYPE_CHECKING:
        # Shared MemoryService collaborators used by the methods below.
        _apply_preferred_strategy_bias: Callable[..., Any]
        _preferred_strategy_record: Callable[..., Any]
        _review_scheduler: ReviewScheduler
        _strategy_preference_evidence: Callable[..., Any]
        _workspace_memory_toggles: Callable[..., Any]
        snapshot: Callable[..., Any]

    def _derive_weakness_records(
        self,
        resources: list[ResourceRecord],
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot | None = None,
    ) -> list[WeaknessRecord]:
        derived = list(lane_snapshot.weaknesses if lane_snapshot else [])
        if resources and not derived:
            derived.append(
                WeaknessRecord(
                    concept="resource-grounding",
                    reason="Resource grounding coverage needs verification",
                    severity=1,
                )
            )
        if plan and not plan.frozen:
            derived.append(
                WeaknessRecord(
                    concept="plan-discipline",
                    reason="Plan still mutable; freeze milestones after alignment",
                    severity=1,
                )
            )
        if not derived:
            derived.append(
                WeaknessRecord(
                    concept="new-workspace",
                    reason="Start with one tiny review-oriented move before opening a broader lane.",
                    severity=2,
                )
            )
        return derived

    def _transfer_skill_observation(self, lane_snapshot: LaneMemorySnapshot) -> str:
        record = normalize_transfer_skill_state_record(lane_snapshot.workspace.get("latest_transfer_state"))
        if not record:
            return ""
        language = str(lane_snapshot.workspace.get("response_language") or "")
        copy = describe_transfer_skill_state(record["state"], record["concept"], language)
        return f"{copy['why']} {copy['next']}".strip()

    def _prepend_transfer_review(
        self,
        due_reviews: list[ReviewQueueItem],
        lane_snapshot: LaneMemorySnapshot,
    ) -> list[ReviewQueueItem]:
        transfer = normalize_transfer_skill_state_record(lane_snapshot.workspace.get("latest_transfer_state"))
        review = lane_snapshot.workspace.get("latest_transfer_review")
        if not transfer or transfer.get("state") != "transferable" or not isinstance(review, dict):
            return due_reviews
        concept = str(review.get("concept") or transfer.get("concept") or "").strip()
        reason = str(review.get("reason") or transfer.get("next") or "").strip()
        if not concept or not reason:
            return due_reviews
        if any(item.concept.strip().casefold() == concept.casefold() and "transfer" in str(item.linked_context or "") for item in due_reviews):
            return due_reviews
        return [
            ReviewQueueItem(
                concept=concept,
                reason=reason,
                source="plan",
                severity="medium",
                linked_context="transfer",
                focus_area=str(review.get("focus_area") or concept),
                task_hint=str(review.get("task_hint") or transfer.get("why") or ""),
            ),
            *due_reviews,
        ]

    def _derive_due_reviews(
        self,
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot,
        weakness_records: list[WeaknessRecord],
    ) -> list[ReviewQueueItem]:
        due_reviews = self._review_scheduler.derive_due_reviews(
            plan=plan,
            lane_snapshot=lane_snapshot,
            weakness_records=weakness_records,
        )
        active_thread = lane_snapshot.workspace.get("active_thread")
        if not self._is_provider_recovery_thread(active_thread) or not isinstance(active_thread, dict):
            return due_reviews

        focus_area = str(active_thread.get("focus_area") or "").strip()
        next_step = str(active_thread.get("next_step") or "").strip()
        if not focus_area or not next_step:
            return due_reviews

        # Keep historical review evidence visible, but never enqueue the provider-recovery thread itself.
        return [
            item
            for item in due_reviews
            if not (
                item.source == "reflection"
                and item.concept.strip() == focus_area
                and next_step in str(item.linked_context or "")
            )
        ]

    def _derive_teaching_observations(
        self,
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot,
        weakness_records: list[WeaknessRecord],
        *,
        language_context: str | None = None,
    ) -> list[str]:
        observations: list[str] = []
        language_context = language_context or _memory_language_context(
            lane_snapshot.workspace,
            self._workspace_value(lane_snapshot, "summary"),
            self._workspace_value(lane_snapshot, "focus_area"),
        )
        active_thread = lane_snapshot.workspace.get("active_thread")
        if isinstance(active_thread, dict):
            thread_focus = str(active_thread.get("focus_area") or "").strip()
            thread_next_step = _strip_visible_next_step_prefix(active_thread.get("next_step") or "")
            thread_blocker = str(active_thread.get("blocker") or "").strip()
            thread_verified = str(active_thread.get("verified_result") or "").strip()
            thread_decision = str(active_thread.get("decision") or "").strip()
            thread_teaching_note = str(active_thread.get("teaching_note") or "").strip()
            thread_confidence = str(active_thread.get("confidence") or "").strip()
            thread_evidence = _normalize_text_items(active_thread.get("evidence"), limit=2)
            if self._is_provider_recovery_thread(active_thread):
                if thread_focus and thread_next_step:
                    observations.append(
                        _localized_memory_text(
                            f"Keep the coaching thread parked on '{thread_focus}' and resume it after this recovery step: {thread_next_step}",
                            f"先把这条教练主线稳在「{thread_focus}」上，先完成这个恢复动作，再回来继续：{thread_next_step}",
                            language_context or thread_focus or thread_next_step,
                        )
                    )
                elif thread_focus:
                    observations.append(
                        _localized_memory_text(
                            f"Keep the coaching thread parked on '{thread_focus}' until the provider path is trustworthy again.",
                            f"先把这条教练主线稳在「{thread_focus}」上，等 provider 链路恢复可信后再继续。",
                            language_context or thread_focus or thread_blocker,
                        )
                    )
                if thread_blocker:
                    observations.append(
                        _localized_memory_text(
                            f"Provider recovery blocker: {thread_blocker}",
                            f"当前需要先解开的 provider 恢复卡点：{thread_blocker}",
                            language_context or thread_blocker,
                        )
                    )
                return observations[:2]
            if thread_focus and thread_next_step:
                observations.append(
                    _localized_memory_text(
                        f"Active thread is still '{thread_focus}'. The next reply should continue this exact move: {thread_next_step}",
                        f"当前还在沿着「{thread_focus}」这条主线推进，下一轮也应该继续接这一步：{thread_next_step}",
                        language_context or thread_focus or thread_next_step,
                    )
                )
            if thread_blocker:
                observations.append(
                    _localized_memory_text(
                        f"Current blocker to respect: {thread_blocker}",
                        f"当前需要尊重的卡点：{thread_blocker}",
                        language_context or thread_blocker,
                    )
                )
            if thread_verified:
                observations.append(
                    _localized_memory_text(
                        f"Last verified result to build on: {thread_verified}",
                        f"上一轮已经验证过、可以继续接着走的结果：{thread_verified}",
                        language_context or thread_verified,
                    )
                )
            if thread_decision:
                observations.append(
                    _localized_memory_text(
                        f"Latest finalized decision to preserve: {thread_decision}",
                        f"要继续保留的最终决定：{thread_decision}",
                        language_context or thread_decision,
                    )
                )
            if thread_teaching_note:
                observations.append(
                    _localized_memory_text(
                        f"Teaching note to preserve: {thread_teaching_note}",
                        f"要继续保留的教学提示：{thread_teaching_note}",
                        language_context or thread_teaching_note,
                    )
                )
            if thread_confidence:
                observations.append(
                    _localized_memory_text(
                        f"Coach confidence signal: {thread_confidence}",
                        f"教练置信信号：{thread_confidence}",
                        language_context or thread_confidence,
                    )
                )
            if thread_evidence:
                observations.append(
                    _localized_memory_text(
                        f"Evidence trail to reuse: {'; '.join(thread_evidence)}",
                        f"可继续复用的证据链：{'; '.join(thread_evidence)}",
                        language_context or thread_evidence[0],
                    )
                )
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area")
        latest_next_step = _strip_visible_next_step_prefix(
            self._workspace_value(lane_snapshot, "next_step")
        )
        latest_review_note = str(lane_snapshot.workspace.get("latest_coach_review_note") or "").strip()
        latest_scenario = self._workspace_value(lane_snapshot, "scenario")
        latest_preference = lane_snapshot.preferences[0] if lane_snapshot.preferences else None
        latest_decision = lane_snapshot.decisions[0] if lane_snapshot.decisions else None

        if latest_focus_area and latest_next_step:
            observations.append(
                _localized_memory_text(
                    f"The last coach turn already narrowed the work to '{latest_focus_area}'. Keep going on that same line with: {latest_next_step}",
                    f"上一轮已经把范围压到「{latest_focus_area}」，这一轮继续沿着同一条主线推进：{latest_next_step}",
                    language_context or latest_focus_area or latest_next_step,
                )
            )
        elif latest_scenario and latest_next_step:
            observations.append(
                _localized_memory_text(
                    f"Latest {latest_scenario.replace('_', ' ')} turn already has a concrete next move; keep following it before expanding scope.",
                    "最近这一轮已经有了一个清楚的下一步，在它落地前先不要扩范围。",
                    language_context or latest_next_step or latest_scenario,
                )
            )

        if latest_review_note and not self._is_synthetic_bootstrap_review_text(latest_review_note):
            observations.append(
                _localized_memory_text(
                    f"Recent coaching friction to preserve: {latest_review_note}",
                    f"最近需要继续盯住的训练摩擦点：{latest_review_note}",
                    language_context or latest_review_note,
                )
            )
        if latest_preference:
            observations.append(
                _localized_memory_text(
                    f"Remembered learner preference: {latest_preference.key} = {latest_preference.value}.",
                    f"已记住你的偏好：{latest_preference.key} = {latest_preference.value}。",
                    language_context or latest_preference.value,
                )
            )
        if latest_decision:
            observations.append(
                _localized_memory_text(
                    f"Latest coaching decision to preserve: {latest_decision.decision}",
                    f"最近这条教练判断要继续保留：{latest_decision.decision}",
                    language_context or latest_decision.decision,
                )
            )

        active_stage = self._active_stage(plan)
        if active_stage:
            workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
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
                observations.append(
                    _localized_memory_text(
                        f"Stay inside '{stage_label}' until one verifiable slice is complete.",
                        f"在拿到一个可验证结果之前，先别离开「{stage_label}」这个阶段。",
                        language_context or stage_label,
                    )
                )

        if weakness_records:
            concepts = ", ".join(record.concept for record in weakness_records[:2])
            observations.append(
                _localized_memory_text(
                    f"Repeated friction is clustering around {concepts}; keep the next step narrower than your first instinct.",
                    f"反复卡顿主要集中在 {concepts} 附近，这一轮下一步要比你第一反应再小一点。",
                    language_context or concepts,
                )
            )

        if lane_snapshot.reflections:
            observations.append(
                _localized_memory_text(
                    f"Recent reflection to reuse: {lane_snapshot.reflections[-1].summary}",
                    f"最近这条复盘值得继续拿来用：{lane_snapshot.reflections[-1].summary}",
                    language_context or lane_snapshot.reflections[-1].summary,
                )
            )

        if lane_snapshot.mastery:
            lowest = sorted(lane_snapshot.mastery, key=lambda item: item.score)[:1]
            if lowest:
                observations.append(
                    _localized_memory_text(
                        f"Keep revisiting {lowest[0].concept} through code, not only explanation.",
                        f"像「{lowest[0].concept}」这种薄弱概念，后面还要继续放回代码里练，不要只停在讲解上。",
                        language_context or lowest[0].concept,
                    )
                )

        if not observations:
            observations.append(
                _localized_memory_text(
                    "No repeated coaching pattern has solidified yet.",
                    "还没有形成特别稳定的训练模式，先继续沿着当前主线积累。",
                    language_context,
                )
            )

        return observations[:4]

    def _derive_recent_wins(
        self,
        plan: LearningPlan | None,
        resources: list[ResourceRecord],
        lane_snapshot: LaneMemorySnapshot,
    ) -> list[str]:
        wins: list[str] = []
        language_context = self._workspace_value(lane_snapshot, "summary") or self._workspace_value(
            lane_snapshot,
            "focus_area",
        )
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        toggles = self._workspace_memory_toggles(workspace)
        active_thread = lane_snapshot.workspace.get("active_thread")
        if isinstance(active_thread, dict):
            verified_result = str(active_thread.get("verified_result") or "").strip()
            if verified_result:
                wins.append(
                    _localized_memory_text(
                        f"Last verified result is still available as the next coaching anchor: {verified_result}",
                        f"上一次已经验证过的结果还在，可以直接作为下一轮继续推进的起点：{verified_result}",
                        language_context or verified_result,
                    )
                )
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area")
        latest_summary = self._workspace_value(lane_snapshot, "summary")
        latest_next_step = _strip_visible_next_step_prefix(
            self._workspace_value(lane_snapshot, "next_step")
        )
        latest_progress = lane_snapshot.progress[0] if lane_snapshot.progress else None

        if latest_focus_area and latest_next_step:
            wins.append(
                _localized_memory_text(
                    f"The latest coach turn already reduced '{latest_focus_area}' into a concrete next move you can act on now.",
                    f"上一轮已经把「{latest_focus_area}」压成了一个可以直接动手的下一步。",
                    language_context or latest_focus_area,
                )
            )
        elif latest_summary:
            wins.append(
                _localized_memory_text(
                    f"The coach already condensed the current thread into a usable summary: {latest_summary}",
                    f"教练已经把当前这条主线压成了一段可直接接续的摘要：{latest_summary}",
                    language_context or latest_summary,
                )
            )
        elif latest_progress:
            anchor = latest_progress.focus_area or latest_progress.lane
            wins.append(
                _localized_memory_text(
                    f"Trainer kept a reusable progress thread for {anchor}.",
                    f"教练已经为「{anchor}」保留了一条可继续接上的进度主线。",
                    language_context or anchor,
                )
            )

        active_stage = self._active_stage(plan)
        if active_stage:
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
                wins.append(
                    _localized_memory_text(
                        f"You already have a live stage to work inside: {stage_label}.",
                        f"你已经有一个正在推进的训练阶段：{stage_label}。",
                        language_context or stage_label,
                    )
                )

        if resources and toggles["resources"]:
            wins.append(
                _localized_memory_text(
                    "Workspace resources are available for grounded follow-up guidance.",
                    "当前工作区资料已经可用，后续回复可以更稳地贴着资料和代码继续推进。",
                    language_context,
                )
            )

        if lane_snapshot.reflections and toggles["decisions"]:
            wins.append(
                _localized_memory_text(
                    "A reflection trail now exists for future coaching loops.",
                    "现在已经积累了复盘轨迹，后续教练可以继续沿着你的真实训练过程来带。",
                    language_context,
                )
            )

        if not wins:
            wins.append(
                _localized_memory_text(
                    "The training workspace is ready for the first focused implementation loop.",
                    "当前工作区已经准备好开始第一轮聚焦实现了。",
                    language_context,
                )
            )

        return wins[:3]

    def _derive_current_focus(
        self,
        plan: LearningPlan | None,
        recent_summary: str,
        lane_snapshot: LaneMemorySnapshot | None = None,
        *,
        language_context: str | None = None,
    ) -> str:
        language_context = language_context or _memory_language_context(
            lane_snapshot.workspace if lane_snapshot else {},
            recent_summary,
        )
        active_thread = lane_snapshot.workspace.get("active_thread") if lane_snapshot else None
        if isinstance(active_thread, dict):
            thread_focus = str(active_thread.get("focus_area") or "").strip()
            thread_scenario = str(active_thread.get("scenario") or "").strip()
            thread_next_step = _strip_visible_next_step_prefix(active_thread.get("next_step") or "")
            thread_blocker = str(active_thread.get("blocker") or "").strip()
            thread_verified = str(active_thread.get("verified_result") or "").strip()
            if thread_focus:
                if _focus_looks_like_request_sentence(thread_focus):
                    guided_lane_focus = _guided_lane_focus_label(
                        thread_scenario,
                        language_context or thread_focus or thread_next_step or thread_blocker,
                    )
                    if guided_lane_focus:
                        thread_focus = guided_lane_focus
                visible_thread_focus = _display_focus_label(
                    thread_focus,
                    language_context or thread_focus or thread_next_step or thread_blocker,
                )
                if self._is_provider_recovery_thread(active_thread):
                    return _localized_memory_text(
                        f"Current coaching focus: keep '{visible_thread_focus}' parked until the provider path preserves the original sentence. Next step: {thread_next_step}"
                        if thread_next_step
                        else f"Current coaching focus: keep '{visible_thread_focus}' parked until the provider path preserves the original sentence.",
                        f"当前聚焦：先把「{visible_thread_focus}」这条主线稳住，等 provider 链路能完整保留原句后再继续。下一步：{thread_next_step}"
                        if thread_next_step
                        else f"当前聚焦：先把「{visible_thread_focus}」这条主线稳住，等 provider 链路能完整保留原句后再继续。",
                        language_context or visible_thread_focus or thread_next_step or thread_blocker,
                    )
                focus_line = _localized_memory_text(
                    f"Current coaching focus: continue '{visible_thread_focus}' and do not open a new lane before this next move lands: {thread_next_step}"
                    if thread_next_step
                    else f"Current coaching focus: continue '{visible_thread_focus}' before widening scope.",
                    f"当前聚焦：先沿着「{visible_thread_focus}」这条主线继续推进，在这一步落地前先不要新开分支。下一步是：{thread_next_step}"
                    if thread_next_step
                    else f"当前聚焦：先沿着「{visible_thread_focus}」继续推进，再考虑扩展范围。",
                    language_context or visible_thread_focus or thread_next_step,
                )
                if thread_blocker:
                    focus_line += _localized_memory_text(
                        f" Current blocker: {thread_blocker}",
                        f" 当前卡点：{thread_blocker}",
                        language_context or thread_blocker,
                    )
                elif thread_verified:
                    focus_line += _localized_memory_text(
                        f" Last verified result: {thread_verified}",
                        f" 上一次已验证结果：{thread_verified}",
                        language_context or thread_verified,
                    )
                return focus_line
        workspace = lane_snapshot.workspace if lane_snapshot and isinstance(lane_snapshot.workspace, dict) else {}
        recovered = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            str(workspace.get("workspace_id") or "").strip(),
        )
        persist_chrome = live_plan_snapshot_persist_chrome(
            plan=plan,
            runtime=recovered,
            existing=recovered,
        )
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area") if lane_snapshot else ""
        latest_focus_area = live_coach_focus_area(
            plan=plan,
            runtime=recovered,
            existing=recovered,
            candidate=latest_focus_area,
        )
        latest_next_step = (
            _strip_visible_next_step_prefix(self._workspace_value(lane_snapshot, "next_step"))
            if lane_snapshot
            else ""
        )
        latest_summary = self._workspace_value(lane_snapshot, "summary") if lane_snapshot else ""
        latest_progress = lane_snapshot.progress[0] if lane_snapshot and lane_snapshot.progress else None
        if latest_focus_area:
            visible_latest_focus = _display_focus_label(
                latest_focus_area,
                language_context or latest_focus_area or latest_next_step or latest_summary or recent_summary,
            )
            detail = latest_next_step or latest_summary or recent_summary
            if detail:
                return _localized_memory_text(
                    f"Current coaching focus: stay with '{visible_latest_focus}' and keep the next loop attached to this latest move: {detail}",
                    f"当前聚焦：继续围绕「{visible_latest_focus}」推进，下一轮也先贴着这一步来做：{detail}",
                    language_context or visible_latest_focus or detail,
                )
            return _localized_memory_text(
                f"Current coaching focus: stay with '{visible_latest_focus}' until the learner lands one visible, verifiable step.",
                f"当前聚焦：继续围绕「{visible_latest_focus}」推进，先落下一个明确可验证的小结果。",
                language_context or visible_latest_focus,
            )
        if latest_progress:
            detail = latest_progress.next_step or latest_progress.summary
            anchor = latest_progress.focus_area or latest_progress.lane
            visible_anchor = _display_focus_label(
                anchor,
                language_context or anchor or detail,
            )
            return _localized_memory_text(
                f"Current coaching focus: continue the tracked {latest_progress.lane} lane around "
                f"'{visible_anchor}' and keep the next loop attached to: {detail}",
                f"当前聚焦：继续沿着已跟踪的「{visible_anchor}」主线推进，下一轮先接着这一步来做：{detail}",
                language_context or visible_anchor or detail,
            )

        live_focus = persist_chrome["focus"] or persist_chrome["stage_title"]
        if live_focus:
            return _localized_memory_text(
                f"Current coaching focus: stay inside '{live_focus}', land one visible slice, "
                "and keep the next reply tied to the exact patch you can verify.",
                f"当前聚焦：先在「{live_focus}」这个阶段里落下一个清楚的小切片，下一轮继续贴着你能验证的那段改动来推进。",
                language_context or live_focus,
            )
        if recent_summary:
            return _localized_memory_text(
                "Current coaching focus: keep following the learner's latest concrete thread, "
                f"especially this signal from the recent loop: {recent_summary}",
                f"当前聚焦：继续顺着你最近这条最具体的主线往前走，特别注意这条信号：{recent_summary}",
                language_context,
            )
        return _localized_memory_text(
            "Current coaching focus: reduce the work to one verifiable move, then keep the next turn attached to that result.",
            "当前聚焦：先把事情压成一个可验证的小动作，下一轮也继续贴着这个结果来推进。",
            language_context,
        )

    def _derive_review_rhythm(
        self,
        due_reviews: list[ReviewQueueItem],
        lane_snapshot: LaneMemorySnapshot,
    ) -> str:
        return self._review_scheduler.derive_review_rhythm(
            due_reviews=due_reviews,
            lane_snapshot=lane_snapshot,
        )

    def _is_synthetic_bootstrap_concept(self, concept: str | None) -> bool:
        return str(concept or "").strip().lower() in _SYNTHETIC_BOOTSTRAP_CONCEPTS

    def _is_synthetic_bootstrap_review_text(self, text: str | None) -> bool:
        normalized = str(text or "").strip().lower()
        return bool(normalized) and any(
            token in normalized for token in _SYNTHETIC_BOOTSTRAP_CONCEPTS
        )

    def _visible_weakness_records(
        self,
        weakness_records: list[WeaknessRecord],
    ) -> list[WeaknessRecord]:
        return [
            record
            for record in weakness_records
            if not self._is_synthetic_bootstrap_concept(record.concept)
        ]

    def _visible_due_reviews(
        self,
        due_reviews: list[ReviewQueueItem],
    ) -> list[ReviewQueueItem]:
        return [
            item
            for item in due_reviews
            if not self._is_synthetic_bootstrap_concept(item.concept)
        ]

    def _active_stage(self, plan: LearningPlan | None):
        if not plan:
            return None
        for stage in plan.stages:
            if stage.id == plan.current_stage_id or stage.status == "active":
                return stage
        return plan.stages[0] if plan.stages else None

    def _severity_label(self, severity: int) -> str:
        if severity >= 3:
            return "high"
        if severity == 2:
            return "medium"
        return "low"

    def _derive_coach_anchor(
        self,
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot,
    ) -> str:
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        recovered = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            str(workspace.get("workspace_id") or "").strip(),
        )
        persist_chrome = live_plan_snapshot_persist_chrome(
            plan=plan,
            runtime=recovered,
            existing=recovered,
        )
        latest_focus_area = live_coach_focus_area(
            plan=plan,
            runtime=recovered,
            existing=recovered,
            candidate=self._workspace_value(lane_snapshot, "focus_area"),
        )
        if latest_focus_area:
            return latest_focus_area
        if lane_snapshot.progress:
            latest_progress = lane_snapshot.progress[0]
            progress_focus = live_coach_focus_area(
                plan=plan,
                runtime=recovered,
                existing=recovered,
                candidate=latest_progress.focus_area.strip() or latest_progress.lane.strip(),
            )
            if progress_focus:
                return progress_focus
        if persist_chrome["focus"] or persist_chrome["stage_title"]:
            return persist_chrome["focus"] or persist_chrome["stage_title"]
        if lane_snapshot.mastery:
            return sorted(lane_snapshot.mastery, key=lambda item: item.score)[0].concept
        return "implementation"

    def _derive_lowest_mastery_concepts(self, lane_snapshot: LaneMemorySnapshot) -> list[str]:
        if not lane_snapshot.mastery:
            return []
        ranked = sorted(
            lane_snapshot.mastery,
            key=lambda item: (item.score, item.updated_at),
        )
        concepts: list[str] = []
        for item in ranked:
            concept = item.concept.strip()
            if concept and ":next-step" not in concept and concept not in concepts:
                concepts.append(concept)
            if len(concepts) == 3:
                break
        return concepts

    def _derive_pace_signal(
        self,
        plan: LearningPlan | None,
        due_reviews: list[ReviewQueueItem],
        lane_snapshot: LaneMemorySnapshot,
    ) -> str:
        if len(due_reviews) >= 3:
            return "gentle"
        if any(item.surface_mode == "due" and item.severity == "high" for item in due_reviews):
            return "gentle"
        if plan and plan.cadence and "8" in plan.cadence and not due_reviews:
            return "intensive"
        if lane_snapshot.session and len(lane_snapshot.session.recent_messages) >= 6 and not due_reviews:
            return "steady"
        return "steady"

    def _normalize_focus_area(self, focus_area: str | None) -> str | None:
        if not focus_area:
            return None
        cleaned = focus_area.strip()
        if not cleaned:
            return None
        if cleaned.lower().startswith("current coaching focus:"):
            return None
        if len(cleaned.split()) > 8:
            return None
        return cleaned

    def _top_actionable_weakness(self, weakness_records: list[WeaknessRecord]) -> str:
        for record in weakness_records:
            if not self._is_synthetic_bootstrap_concept(record.concept):
                return record.concept
        return ""

    def _preferred_preference(self, lane_snapshot: LaneMemorySnapshot) -> PreferenceRecord | None:
        if not getattr(lane_snapshot, "preferences", None):
            return None
        ignored_keys = {
            "focus_area",
            "memory_scope",
            "working_set_mode",
            "review_cadence",
            "review_reminder_mode",
            "response_language",
            "answer_mode",
        }
        for preference in lane_snapshot.preferences:
            if preference.key not in ignored_keys:
                return preference
        return lane_snapshot.preferences[0]

    def _personal_transfer_observation(self, lane_snapshot: LaneMemorySnapshot) -> str:
        language_context = self._workspace_value(lane_snapshot, "summary") or self._workspace_value(
            lane_snapshot,
            "focus_area",
        )
        current_focus = self._workspace_value(lane_snapshot, "focus_area").strip().lower()

        for progress in lane_snapshot.progress:
            anchor = (progress.focus_area or progress.lane).strip()
            if not anchor or anchor.lower() == current_focus:
                continue
            detail = progress.next_step.strip() or progress.summary.strip()
            if not detail:
                continue
            return _localized_memory_text(
                f"Carry forward a reusable lesson from '{anchor}': {detail}",
                f"个人长期记忆里还有一条可以迁移过来的经验，来自「{anchor}」：{detail}",
                language_context or anchor or detail,
            )

        for decision in lane_snapshot.decisions:
            topic = decision.topic.strip()
            if not topic or topic.lower() == current_focus:
                continue
            detail = decision.next_step.strip() or decision.decision.strip()
            if not detail:
                continue
            return _localized_memory_text(
                f"Keep a reusable judgment from '{topic}' available: {detail}",
                f"个人长期记忆里保留着一条可复用判断，来自「{topic}」：{detail}",
                language_context or topic or detail,
            )

        return ""

    def memory_evidence(self, workspace_id: str, *, limit: int = 5) -> list[str]:
        snapshot = self.snapshot(workspace_id)
        return self._build_memory_evidence(snapshot, limit=limit)

    def _build_memory_evidence(self, snapshot: MemorySnapshot, *, limit: int) -> list[str]:
        evidence: list[str] = []

        if snapshot.active_thread:
            if snapshot.active_thread.verified_result:
                evidence.append(
                    _localized_memory_text(
                        f"Last verified result: {snapshot.active_thread.verified_result}",
                        f"上次已经验证过的结果：{snapshot.active_thread.verified_result}",
                        snapshot.active_thread.verified_result,
                    )
                )
            if snapshot.active_thread.blocker:
                evidence.append(
                    _localized_memory_text(
                        f"Current blocker: {snapshot.active_thread.blocker}",
                        f"当前卡点：{snapshot.active_thread.blocker}",
                        snapshot.active_thread.blocker,
                    )
                )
            if snapshot.active_thread.decision:
                evidence.append(
                    _localized_memory_text(
                        f"Latest finalized decision: {snapshot.active_thread.decision}",
                        f"最新最终决策：{snapshot.active_thread.decision}",
                        snapshot.active_thread.decision,
                    )
                )
            if snapshot.active_thread.teaching_note:
                evidence.append(
                    _localized_memory_text(
                        f"Teaching note: {snapshot.active_thread.teaching_note}",
                        f"教学提示：{snapshot.active_thread.teaching_note}",
                        snapshot.active_thread.teaching_note,
                    )
                )
            if snapshot.active_thread.confidence:
                evidence.append(
                    _localized_memory_text(
                        f"Coach confidence: {snapshot.active_thread.confidence}",
                        f"教练置信信号：{snapshot.active_thread.confidence}",
                        snapshot.active_thread.confidence,
                    )
                )
            if snapshot.active_thread.evidence:
                joined_evidence = "; ".join(snapshot.active_thread.evidence[:2])
                evidence.append(
                    _localized_memory_text(
                        f"Evidence trail: {joined_evidence}",
                        f"证据链：{joined_evidence}",
                        joined_evidence,
                    )
                )
            if snapshot.active_thread.focus_area and snapshot.active_thread.next_step:
                evidence.append(
                    _localized_memory_text(
                        f"Continue {snapshot.active_thread.focus_area} with this next move: {snapshot.active_thread.next_step}",
                        f"继续沿着「{snapshot.active_thread.focus_area}」推进，下一步是：{snapshot.active_thread.next_step}",
                        snapshot.active_thread.summary or snapshot.active_thread.next_step,
                    )
                )
            elif snapshot.active_thread.summary:
                evidence.append(snapshot.active_thread.summary)

        if snapshot.current_focus:
            evidence.append(snapshot.current_focus)

        goal = (
            snapshot.profile.long_term_goal
            if snapshot.profile and snapshot.profile.long_term_goal
            else snapshot.profile.long_term_goals[0]
            if snapshot.profile and snapshot.profile.long_term_goals
            else ""
        )
        if goal:
            evidence.append(
                _localized_memory_text(
                    f"Long-term goal: {goal}",
                    f"长期目标：{goal}",
                    goal,
                )
            )

        if snapshot.recent_wins:
            evidence.extend(snapshot.recent_wins[:1])

        if snapshot.teaching_observations:
            evidence.extend(snapshot.teaching_observations[:1])

        if snapshot.coaching_adaptation and snapshot.coaching_adaptation.summary:
            evidence.append(snapshot.coaching_adaptation.summary)

        if snapshot.teaching_assets:
            first_asset = snapshot.teaching_assets[0]
            summary = first_asset.summary.strip() or first_asset.title.strip()
            if summary:
                evidence.append(
                    _localized_memory_text(
                        f"Reusable teaching asset: {first_asset.kind} - {summary}",
                        f"可复用教学资产：{first_asset.kind} - {summary}",
                        summary,
                    )
                )

        if snapshot.due_reviews:
            for item in snapshot.due_reviews[:1]:
                evidence.append(
                    _localized_memory_text(
                        f"Due review: {item.concept} - {item.reason}",
                        f"待回看：{item.concept} - {item.reason}",
                        item.reason or item.concept,
                    )
                )

        deduped: list[str] = []
        seen: set[str] = set()
        for item in evidence:
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
            if len(deduped) >= limit:
                break
        return deduped

    def _context_pressure_from_lane(
        self,
        lane_snapshot: LaneMemorySnapshot,
        *,
        profile: UserProfile | dict[str, Any] | None = None,
        plan: LearningPlan | None = None,
        due_reviews: list[Any] | None = None,
        workspace_id: str = "",
    ):
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        scope_id = str(workspace_id or workspace.get("workspace_id") or "").strip()
        current_task = normalize_latest_current_task(
            workspace.get(CURRENT_TASK_KEY) or workspace.get("current_task") or workspace.get("currentTask"),
            scope_id,
        )
        affect_state = normalize_latest_affect_state(
            workspace.get(AFFECT_STATE_KEY) or workspace.get("affect_state") or workspace.get("affectState"),
            scope_id,
        )
        return derive_context_pressure(
            profile=profile if profile is not None else lane_snapshot.profile,
            workspace=workspace,
            plan=plan,
            plan_runtime=select_plan_runtime_for_pressure(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                scope_id,
            ),
            current_task=current_task,
            affect_state=affect_state,
            due_reviews=due_reviews,
            workspace_understanding=self._workspace_understanding_snapshot(lane_snapshot),
            session=lane_snapshot.session,
            preferences=list(getattr(lane_snapshot, "preferences", []) or []),
            workspace_id=scope_id,
        )

    def _derive_coaching_adaptation_profile(
        self,
        lane_snapshot: LaneMemorySnapshot,
        *,
        profile: UserProfile | None = None,
        plan: LearningPlan | None = None,
        due_reviews: list[Any] | None = None,
        workspace_id: str = "",
    ) -> CoachingAdaptationProfile | None:
        outcomes = list(getattr(lane_snapshot, "learning_outcomes", []) or [])
        signals = analyze_learning_evidence(outcomes)
        focus_anchor = self._workspace_value(lane_snapshot, "focus_area")
        language_context = self._workspace_value(lane_snapshot, "summary") or focus_anchor
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        transfer_record = normalize_transfer_skill_state_record(workspace.get("latest_transfer_state"))
        coach_defaults = workspace.get("coach_defaults")
        teaching_style = ""
        if isinstance(coach_defaults, dict):
            teaching_style = str(coach_defaults.get("teaching_style") or "")
        pressure = self._context_pressure_from_lane(
            lane_snapshot,
            profile=profile,
            plan=plan,
            due_reviews=due_reviews,
            workspace_id=workspace_id,
        )
        scope_id = str(workspace_id or workspace.get("workspace_id") or "").strip()
        persisted_task = normalize_latest_current_task(
            workspace.get(CURRENT_TASK_KEY) or workspace.get("current_task") or workspace.get("currentTask"),
            scope_id,
        )
        persisted_affect = normalize_latest_affect_state(
            workspace.get(AFFECT_STATE_KEY) or workspace.get("affect_state") or workspace.get("affectState"),
            scope_id,
        )
        persisted_plan_runtime = (
            None
            if plan is not None
            else select_plan_runtime_for_pressure(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                scope_id,
            )
        )
        has_outcomes = bool(outcomes)
        has_pressure = bool(
            persisted_task
            or persisted_affect
            or persisted_plan_runtime
            or pressure.time_budget != "normal"
            or pressure.task_urgency != "medium"
            or pressure.project_complexity != "moderate"
            or pressure.evidence
        )
        if not has_outcomes and not has_pressure:
            return None

        controls = resolve_pedagogy_controls(
            signals,
            transfer_scene_count=int((transfer_record or {}).get("scene_count") or 0),
            transfer_state=str((transfer_record or {}).get("state") or ""),
            user_preference=str(workspace.get("latest_user_feedback_kind") or ""),
            preferred_teaching_style=teaching_style,
            time_budget=pressure.time_budget,
            task_urgency=pressure.task_urgency,
            project_complexity=pressure.project_complexity,
            current_ability=str(workspace.get("current_ability") or ""),
            evidence_confidence=pedagogy_evidence_confidence(
                verified_success=bool(signals.verified_success),
                success_count=int(signals.success_count or 0),
                outcomes=outcomes,
            ),
        )

        latest_outcome_action = ""
        if outcomes:
            latest = outcomes[0]
            latest_outcome_action = str(
                getattr(latest, "action_type", "") or (latest.get("action_type") if isinstance(latest, dict) else "")
                or ""
            )
        current_scenario = self._workspace_value(lane_snapshot, "scenario") or latest_outcome_action
        preferred_strategy = self._preferred_strategy_record(
            lane_snapshot,
            scenario=current_scenario,
            focus_area=focus_anchor,
        )
        strategy_preference_applied = False
        challenge_level = controls.challenge_level
        hint_depth = controls.hint_depth
        review_urgency = controls.review_urgency
        explanation_mode = controls.explanation_mode
        next_step_bias = controls.next_step_bias
        evidence = list(signals.evidence)
        if preferred_strategy is not None and has_outcomes:
            (
                challenge_level,
                hint_depth,
                review_urgency,
                explanation_mode,
                next_step_bias,
            ), strategy_preference_applied = self._apply_preferred_strategy_bias(
                preferred_record=preferred_strategy,
                challenge_level=challenge_level,
                hint_depth=hint_depth,
                review_urgency=review_urgency,
                explanation_mode=explanation_mode,
                next_step_bias=next_step_bias,
                repeated_failure=signals.repeated_failure,
                abandoned=signals.abandoned,
            )
            if strategy_preference_applied:
                evidence.insert(
                    0,
                    self._strategy_preference_evidence(
                        preferred_strategy,
                        language_context=language_context,
                    ),
                )
                controls = refresh_controls_after_strategy(
                    controls,
                    challenge_level=challenge_level,
                    hint_depth=hint_depth,
                    review_urgency=review_urgency,
                    explanation_mode=explanation_mode,
                    next_step_bias=next_step_bias,
                )

        summary = ""
        if challenge_level == "lower":
            summary = _localized_memory_text(
                "Adaptive coaching: recent failures mean the next loop should shrink scope, deepen hints, and close one recovery check first.",
                "自适应教学：最近失败较多，下一轮应继续缩小范围、加深提示，并先收口一个恢复性验证。",
                language_context,
            )
        elif challenge_level == "raise":
            summary = _localized_memory_text(
                "Adaptive coaching: recent wins justify lighter hints, wider transfer, and a slightly stronger next challenge.",
                "自适应教学：最近已有连续进展，下一轮可以少给一点提示，更多强调迁移，并适度提高挑战。",
                language_context,
            )
        elif signals.concept_success:
            summary = _localized_memory_text(
                "Adaptive coaching: the learner recently explained the concept back correctly, so connect the next step to transfer in real code.",
                "自适应教学：最近概念反馈是正确的，下一轮应把理解迁回真实代码里做迁移练习。",
                language_context,
            )
        elif signals.success_count or signals.failure_count:
            summary = _localized_memory_text(
                "Adaptive coaching: keep the next step grounded in the latest outcome instead of reopening a broader lane.",
                "自适应教学：下一轮继续贴着最近的结果推进，不要重新打开更宽的话题分支。",
                language_context,
            )
        if strategy_preference_applied and preferred_strategy is not None:
            strategy_summary = self._strategy_preference_evidence(
                preferred_strategy,
                language_context=language_context,
            )
            summary = f"{summary} {strategy_summary}".strip() if summary else strategy_summary

        if not has_outcomes and has_pressure:
            for item in pressure.evidence:
                if item and item not in evidence:
                    evidence.append(item)
                if len(evidence) >= 4:
                    break
            if persisted_affect is not None:
                evidence.append(f"affect_urgency:{persisted_affect.get('urgency_level') or pressure.task_urgency}")
            if persisted_task is not None:
                task_label = str(persisted_task.get("title") or persisted_task.get("id") or "current task").strip()
                if task_label:
                    evidence.append(f"current_task:{task_label}")
            evidence = evidence[:4]
            if not summary:
                if pressure.task_urgency == "high" or pressure.time_budget == "tight" or pressure.project_complexity == "complex":
                    summary = _localized_memory_text(
                        "Adaptive coaching: keep the next slice short and stay on this project. No learning outcome yet, so this is not global mastery.",
                        "自适应教学：先把下一步收短，停在当前项目。还没有学习结果，所以这不是全局掌握。",
                        language_context,
                    )
                else:
                    summary = _localized_memory_text(
                        "Adaptive coaching: next step follows current time, urgency, and project scope. No learning outcome yet.",
                        "自适应教学：下一步先跟着当前的时间、紧迫度和项目范围走。还没有学习结果。",
                        language_context,
                    )

        if not summary and not evidence:
            return None

        return CoachingAdaptationProfile(
            **profile_kwargs_from_controls(controls, summary=summary, evidence=evidence)
        )

    def _summarize_preferences(self, lane_snapshot: LaneMemorySnapshot) -> str:
        latest = self._preferred_preference(lane_snapshot)
        if latest is None:
            return ""
        language_context = self._workspace_value(lane_snapshot, "summary") or latest.value
        return _localized_memory_text(
            f"Keep honoring the remembered preference {latest.key} = {latest.value}.",
            f"继续遵守已经记住的偏好：{latest.key} = {latest.value}。",
            language_context,
        )

    def _summarize_decisions(self, lane_snapshot: LaneMemorySnapshot) -> str:
        if not getattr(lane_snapshot, "decisions", None):
            return ""
        latest = lane_snapshot.decisions[0]
        language_context = self._workspace_value(lane_snapshot, "summary") or latest.decision
        return _localized_memory_text(
            f"Trainer retained a reusable coaching decision on {latest.topic}.",
            f"教练已经保留了一条可复用的判断，主题是：{latest.topic}。",
            language_context,
        )

    def _summarize_goal(self, goal: str, lane_snapshot: LaneMemorySnapshot) -> str:
        cleaned_goal = goal.strip()
        if not cleaned_goal:
            return ""
        language_context = self._workspace_value(lane_snapshot, "summary") or cleaned_goal
        return _localized_memory_text(
            f"Long-term goal still in view: {cleaned_goal}.",
            f"长期目标仍然在前面：{cleaned_goal}。",
            language_context,
        )

    def _summarize_latest_turn(self, lane_snapshot: LaneMemorySnapshot) -> str:
        latest_review_note = str(lane_snapshot.workspace.get("latest_coach_review_note") or "").strip()
        latest_next_step = _strip_visible_next_step_prefix(
            self._workspace_value(lane_snapshot, "next_step")
        )
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area")
        latest_scenario = self._workspace_value(lane_snapshot, "scenario")
        language_context = (
            self._workspace_value(lane_snapshot, "summary")
            or latest_review_note
            or latest_next_step
            or latest_focus_area
            or latest_scenario
        )
        if latest_review_note:
            return _localized_memory_text(
                f"Recent coaching friction to preserve: {latest_review_note}",
                f"最近需要继续盯住的训练摩擦点：{latest_review_note}",
                language_context,
            )
        if latest_focus_area and latest_next_step:
            return _localized_memory_text(
                f"The last coach turn already narrowed the work to '{latest_focus_area}'. Keep going on that same line and continue with: {latest_next_step}",
                f"上一轮已经把范围压到「{latest_focus_area}」，这一轮就沿着同一条主线继续：{latest_next_step}",
                language_context,
            )
        if latest_scenario and latest_next_step:
            return _localized_memory_text(
                f"Latest {latest_scenario.replace('_', ' ')} turn already has a concrete next move; keep following it before expanding scope.",
                "最近这一轮已经有了一个清楚的下一步，在它落地前先不要扩范围。",
                language_context,
            )
        return ""

    def _onboarding_blocker_summary(self, lane_snapshot: LaneMemorySnapshot) -> str:
        blocker = ""
        for key in ("current_blocker", "project_context"):
            candidate = next(
                (
                    item.value
                    for item in getattr(lane_snapshot, "preferences", [])
                    if item.key == key and str(item.value).strip()
                ),
                "",
            )
            if candidate:
                blocker = str(candidate).strip()
                break
        if not blocker:
            return ""
        language_context = self._workspace_value(lane_snapshot, "summary") or blocker
        return _localized_memory_text(
            f"Onboarding anchor still matters: {blocker}",
            f"首轮建联里提到的关键锚点仍然重要：{blocker}",
            language_context,
        )

    def _summarize_teaching_signal(self, lane_snapshot: LaneMemorySnapshot) -> str:
        if not getattr(lane_snapshot, "teaching_signals", None):
            return ""
        latest = lane_snapshot.teaching_signals[0]
        signal = latest.signal.strip()
        if not signal:
            return ""
        language_context = self._workspace_value(lane_snapshot, "summary") or signal
        focus = latest.source_focus.strip()
        if focus:
            return _localized_memory_text(
                f"Reusable teaching signal from '{focus}': {signal}",
                f"从「{focus}」这条主线里沉淀出一条可迁移的教学信号：{signal}",
                language_context,
            )
        return _localized_memory_text(
            f"Reusable teaching signal: {signal}",
            f"可迁移的教学信号：{signal}",
            language_context,
        )

    def _summarize_weakness_patterns(self, lane_snapshot: LaneMemorySnapshot) -> str:
        recurring = [
            item
            for item in getattr(lane_snapshot, "weaknesses", [])
            if item.recurrence_count >= 2
            and not self._is_synthetic_bootstrap_concept(item.concept)
        ]
        if not recurring:
            return ""
        recurring.sort(
            key=lambda item: (
                -item.recurrence_count,
                -item.severity,
                item.updated_at,
            ),
            reverse=False,
        )
        top = recurring[0]
        language_context = self._workspace_value(lane_snapshot, "summary") or top.reason or top.concept
        return _localized_memory_text(
            f"Recurring blocker pattern: {top.concept} has surfaced {top.recurrence_count} times. Latest example: {top.latest_example or top.reason}",
            f"稳定错误模式：{top.concept} 已经反复出现 {top.recurrence_count} 次。最近一次表现是：{top.latest_example or top.reason}",
            language_context,
        )

    @staticmethod
    def _is_provider_recovery_thread(
        active_thread: ActiveThreadSnapshot | dict[str, Any] | None,
    ) -> bool:
        if active_thread is None:
            return False
        if isinstance(active_thread, dict):
            recovery_state = str(active_thread.get("recovery_state") or "").strip().lower()
            blocker = str(active_thread.get("blocker") or "").strip().lower()
            next_step = str(active_thread.get("next_step") or "").strip().lower()
            teaching_note = str(active_thread.get("teaching_note") or "").strip().lower()
        else:
            recovery_state = ""
            blocker = str(active_thread.blocker or "").strip().lower()
            next_step = str(active_thread.next_step or "").strip().lower()
            teaching_note = str(active_thread.teaching_note or "").strip().lower()
        if recovery_state == "provider_or_local":
            return True
        combined = " ".join(part for part in (blocker, next_step, teaching_note) if part)
        return "provider" in combined and (
            "gateway" in combined
            or "question mark" in combined
            or "question marks" in combined
            or "english" in combined
            or "问号" in combined
            or "原句" in combined
        )

    def _summarize_progress(self, lane_snapshot: LaneMemorySnapshot) -> str:
        active_thread = lane_snapshot.workspace.get("active_thread")
        if isinstance(active_thread, dict):
            thread_verified = str(active_thread.get("verified_result") or "").strip()
            thread_blocker = str(active_thread.get("blocker") or "").strip()
            thread_focus = str(active_thread.get("focus_area") or "").strip()
            thread_next_step = _strip_visible_next_step_prefix(active_thread.get("next_step") or "")
            language_context = (
                self._workspace_value(lane_snapshot, "summary")
                or thread_verified
                or thread_blocker
                or thread_next_step
                or thread_focus
            )
            if thread_verified and thread_next_step:
                return _localized_memory_text(
                    f"Build from the verified result '{thread_verified}' and continue with: {thread_next_step}",
                    f"基于已经验证过的结果「{thread_verified}」继续推进，下一步是：{thread_next_step}",
                    language_context,
                )
            if thread_blocker and thread_next_step:
                return _localized_memory_text(
                    f"Current blocker is '{thread_blocker}'. Resolve it with: {thread_next_step}",
                    f"当前卡点是「{thread_blocker}」，先用这一步把它解开：{thread_next_step}",
                    language_context,
                )
            if thread_next_step:
                return _localized_memory_text(
                    f"Active thread next step: {thread_next_step}",
                    f"当前主线的下一步是：{thread_next_step}",
                    language_context,
                )
        if not getattr(lane_snapshot, "progress", None):
            return ""
        latest = lane_snapshot.progress[0]
        latest_next_step = _strip_visible_next_step_prefix(latest.next_step)
        language_context = self._workspace_value(lane_snapshot, "summary") or latest.summary or latest_next_step
        if latest_next_step:
            return _localized_memory_text(
                f"Latest saved progress: {latest_next_step}",
                f"最近记录下来的进度下一步是：{latest_next_step}",
                language_context or latest_next_step,
            )
        if latest.summary:
            return _localized_memory_text(
                f"Latest saved progress: {latest.summary}",
                f"最近记录下来的进度摘要是：{latest.summary}",
                language_context,
            )
        return ""

    def _active_thread_snapshot(
        self,
        lane_snapshot: LaneMemorySnapshot | None,
    ) -> ActiveThreadSnapshot | None:
        if lane_snapshot is None:
            return None
        candidate = lane_snapshot.workspace.get("active_thread")
        if not isinstance(candidate, dict):
            return None

        def _normalized(key: str) -> str:
            value = str(candidate.get(key) or "").strip()
            if key == "next_step":
                return _strip_visible_next_step_prefix(value)
            return value

        if not any(
            _normalized(field)
            for field in ("focus_area", "summary", "next_step", "blocker", "verified_result", "decision", "teaching_note", "confidence")
        ):
            return None
        evidence = _normalize_text_items(candidate.get("evidence"), limit=4)
        return ActiveThreadSnapshot(
            scenario=_normalized("scenario"),
            focus_area=_normalized("focus_area"),
            summary=_normalized("summary"),
            next_step=_normalized("next_step"),
            blocker=_normalized("blocker"),
            verified_result=_normalized("verified_result"),
            decision=_normalized("decision"),
            teaching_note=_normalized("teaching_note"),
            confidence=_normalized("confidence"),
            evidence=evidence,
            updated_at=_normalized("updated_at"),
        )

    def _workspace_understanding_snapshot(
        self,
        lane_snapshot: LaneMemorySnapshot | None,
    ) -> WorkspaceUnderstandingSnapshot | None:
        if lane_snapshot is None:
            return None
        candidate = lane_snapshot.workspace.get("workspace_understanding")
        if not isinstance(candidate, dict):
            return None
        try:
            snapshot = WorkspaceUnderstandingSnapshot.model_validate(candidate)
        except Exception:
            return None
        if not (
            snapshot.repo_summary
            or snapshot.entry_points
            or snapshot.feature_lanes
            or snapshot.risk_zones
            or snapshot.training_opportunities
            or snapshot.resource_brief
            or snapshot.first_look_summary is not None
        ):
            return None
        return snapshot

    def _workspace_value(self, lane_snapshot: LaneMemorySnapshot, field: str) -> str:
        preferred = str(lane_snapshot.workspace.get(f"latest_coach_{field}") or "").strip()
        if preferred:
            return preferred
        return str(lane_snapshot.workspace.get(f"latest_turn_{field}") or "").strip()
