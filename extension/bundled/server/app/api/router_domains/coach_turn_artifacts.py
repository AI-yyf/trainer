"""Suggested actions, coaching artifacts, turn summaries, message support, and assistant metadata."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Sequence

from ...core.models import (
    CoachArtifact,
    CoachingState,
    CoachTurnSummary,
    LearningPlan,
    PlanStage,
    SessionMessageRequest,
    TaskSpec,
    TurnRequest,
    WorkbenchSnapshot,
)
from ...llm.provider_service import (
    ProviderService,
)
from ...llm.resource_message_parts import build_resource_display_parts
from ...memory.workspace_recovery import (
    coach_focus_runtime_from_snapshot,
    leftover_formal_plan_is_live_for_fill,
    live_coach_focus_area,
    live_coach_stage_label,
    live_plan_update_heading,
    live_plan_update_persist_chrome,
    live_task_heading,
    live_task_label,
    live_task_suggested_reason,
    live_task_suggested_title,
)
from ...workspace.classifier import (
    is_code_like_current_file,
)
from .. import coach_support
from .._helpers import (
    localized_text,
    normalized_object_mapping,
    prefers_chinese,
)
from .._singleflight import (
    claim_session_request_singleflight as claim_session_request_singleflight,
)
from .._singleflight import (
    fail_session_request_singleflight as fail_session_request_singleflight,
)
from .._singleflight import (
    publish_session_request_singleflight as publish_session_request_singleflight,
)
from ..coach_language_alignment import (
    language_aligned_context_list,
    language_aligned_context_text,
)
from ..coach_text_sanitizer import (
    strip_visible_next_step_prefix,
)
from ..router_support import (
    _attach_requested_workspace_files as _attach_requested_workspace_files,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    _resolve_agent_loop_enabled as _resolve_agent_loop_enabled,
)
from ..router_support import (
    overlay_session_response_honesty_stamps as overlay_session_response_honesty_stamps,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from ._base import RouterDomainBase
from .constants import (
    PROVIDER_REPLY_STOP_REASONS,
    coach_summary_scenarios,
)


class CoachTurnArtifactsDomainMixin(RouterDomainBase):
    """Suggested actions, coaching artifacts, turn summaries, message support, and assistant metadata."""

    def infer_action_type(self, label: str) -> str:
        lowered = label.lower()
        if "plan" in lowered or "\u8ba1\u5212" in label:
            return "plan"
        if "next task" in lowered or "\u4e0b\u4e00\u9898" in label:
            return "next_task"
        if "review" in lowered or "\u8bc4\u5ba1" in label or "fix" in lowered or "\u4fee\u590d" in label:
            return "retry_review" if "again" in lowered or "\u91cd\u65b0" in label else "review"
        if "task" in lowered or "\u4efb\u52a1" in label or "practice" in lowered or "\u8bad\u7ec3\u9898" in label:
            return "task"
        return "hint"

    def teaching_strategy_context_from_snapshot(self, snapshot: WorkbenchSnapshot) -> dict[str, str] | None:
        adaptation = snapshot.memory.coaching_adaptation if snapshot.memory else None
        if adaptation is None:
            return None
        return {
            "challenge_level": adaptation.challenge_level,
            "hint_depth": adaptation.hint_depth,
            "review_urgency": adaptation.review_urgency,
            "explanation_mode": adaptation.explanation_mode,
            "next_step_bias": adaptation.next_step_bias,
        }

    def action_defaults(self, 
        action: str,
        response_language: str | None,
        *,
        scenario: str | None = None,
        focus_area: str | None = None,
    ) -> dict[str, str | None]:
        if action == "plan":
            return {
                "artifact_kind": "plan_update",
                "rationale": localized_text(
                    "Use this when the next move needs sequencing around the current focus, not more explanation.",
                    "\u5f53\u4f60\u73b0\u5728\u66f4\u9700\u8981\u56f4\u7ed5\u5f53\u524d\u805a\u7126\u70b9\u6392\u987a\u5e8f\uff0c\u800c\u4e0d\u662f\u7ee7\u7eed\u89e3\u91ca\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                    response_language,
                ),
                "prompt": localized_text(
                    "Break this into a tighter plan around the current stage and the next visible slice.",
                    "\u56f4\u7ed5\u5f53\u524d\u9636\u6bb5\u548c\u4e0b\u4e00\u4e2a\u53ef\u89c1\u5207\u7247\uff0c\u628a\u8fd9\u4ef6\u4e8b\u62c6\u6210\u66f4\u7d27\u7684\u8ba1\u5212\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "next_task":
            return {
                "artifact_kind": "next_step",
                "rationale": localized_text(
                    "Use this when you want the coach to pick the next thin implementation slice for the current lane.",
                    "当你想围绕当前主线直接得到下一小步的实现练习时，用这个。",
                    response_language,
                ),
                "prompt": localized_text(
                    "Choose the next thin task from my current project, current focus, and weak spots.",
                    "\u7ed3\u5408\u6211\u5f53\u524d\u7684 project\u3001\u5f53\u524d\u805a\u7126\u70b9\u548c\u8584\u5f31\u70b9\uff0c\u7ed9\u6211\u4e0b\u4e00\u9053\u6700\u8584\u7684\u8bad\u7ec3\u9898\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "retry_review":
            return {
                "artifact_kind": "review",
                "rationale": localized_text(
                    "Use this after you land a patch and want the next review loop to stay priority-ordered.",
                    "\u5f53\u4f60\u5df2\u7ecf\u843d\u4e0b\u4e00\u7248 patch\uff0c\u60f3\u8ba9\u4e0b\u4e00\u8f6e review \u7ee7\u7eed\u4fdd\u6301\u4f18\u5148\u7ea7\u987a\u5e8f\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                    response_language,
                ),
                "prompt": localized_text(
                    "Review again after the latest patch and show the next highest-leverage remaining issue.",
                    "\u57fa\u4e8e\u6700\u65b0\u7684 patch \u91cd\u65b0 review\uff0c\u5e76\u6307\u51fa\u4e0b\u4e00\u4e2a\u6700\u5173\u952e\u7684\u5269\u4f59\u95ee\u9898\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "review":
            return {
                "artifact_kind": "review",
                "rationale": localized_text(
                    "Use this when code or diagnostics need a coach-led, priority-ordered fix path.",
                    "\u5f53 code \u6216 diagnostics \u9700\u8981\u4e00\u6761\u7531 Coach \u4e3b\u5bfc\u3001\u6309\u4f18\u5148\u7ea7\u6392\u5e8f\u7684\u4fee\u590d\u8def\u5f84\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                    response_language,
                ),
                "prompt": localized_text(
                    "Review the current implementation and name the first fix before widening scope.",
                    "review \u5f53\u524d\u5b9e\u73b0\uff0c\u5e76\u5728\u6269\u5927\u8303\u56f4\u524d\u5148\u70b9\u51fa\u7b2c\u4e00\u4e2a\u4f18\u5148\u4fee\u590d\u70b9\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "task":
            artifact_kind = (
                "project_idea"
                if scenario == "project_idea"
                else "project_source"
                if scenario == "project_sourcing"
                else "task"
            )
            return {
                "artifact_kind": artifact_kind,
                "rationale": localized_text(
                    "Use this when you want to turn the current focus into one thin exercise instead of broad discussion.",
                    "\u5f53\u4f60\u60f3\u628a\u5f53\u524d\u805a\u7126\u70b9\u6536\u675f\u6210\u4e00\u9053\u5f88\u8584\u7684\u8bad\u7ec3\u9898\uff0c\u800c\u4e0d\u662f\u7ee7\u7eed\u6cdb\u8c08\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                    response_language,
                ),
                "prompt": localized_text(
                    "Turn this into one focused implementation exercise with clear verification and a tight review loop.",
                    "\u628a\u8fd9\u91cc\u6536\u675f\u6210\u4e00\u9053\u805a\u7126\u7684\u5b9e\u73b0\u9898\uff0c\u5e76\u7ed9\u51fa\u6e05\u695a\u7684\u9a8c\u8bc1\u65b9\u5f0f\u548c\u7d27\u51d1\u7684 review loop\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "hint" and scenario == "onboarding":
            return {
                "artifact_kind": "idea_implementation",
                "rationale": localized_text(
                    "Stay with conversation and the first-look next. Do not generate a plan, card, or task yet.",
                    "先顺着对话和第一眼判断的下一步走，先不要生成计划、卡片或任务。",
                    response_language,
                ),
                "prompt": localized_text(
                    "Continue from the first-look next. Do not generate a plan, card, or task.",
                    "顺着第一眼判断的下一步继续。不要生成计划、卡片或任务。",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        return {
            "artifact_kind": "principle" if scenario == "principle" else "idea_implementation",
            "rationale": localized_text(
                "Use this when you want a smaller coaching nudge tied to the exact code boundary, not a full branch of work.",
                "\u5f53\u4f60\u53ea\u9700\u8981\u4e00\u4e2a\u8d34\u7740\u5177\u4f53 code \u8fb9\u754c\u7684\u5c0f\u63d0\u793a\uff0c\u800c\u4e0d\u662f\u65b0\u5f00\u4e00\u6761\u4efb\u52a1\u5206\u652f\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                response_language,
            ),
            "prompt": localized_text(
                "Give me a smaller hint grounded in the current code, current focus, and goal.",
                "\u7ed3\u5408\u5f53\u524d code\u3001\u5f53\u524d\u805a\u7126\u70b9\u548c\u76ee\u6807\uff0c\u7ed9\u6211\u4e00\u4e2a\u66f4\u5c0f\u7684\u63d0\u793a\u3002",
                response_language,
            ),
            "focus_area": focus_area,
        }

    def structured_suggested_actions(self, 
        labels: Sequence[str | dict[str, str]],
        *,
        response_language: str | None = None,
        scenario: str | None = None,
        focus_area: str | None = None,
    ) -> list[dict[str, object]]:
        actions: list[dict[str, object]] = []
        for label_item in labels:
            if isinstance(label_item, dict):
                label = str(label_item.get("label", "")).strip()
                explicit_action = str(label_item.get("action", "")).strip() or None
            else:
                label = str(label_item).strip()
                explicit_action = None
            if not label:
                continue
            self.action_id_counter += 1
            action = explicit_action or self.infer_action_type(label)
            defaults = self.action_defaults(
                action,
                response_language,
                scenario=scenario,
                focus_area=focus_area,
            )
            actions.append(
                {
                    "id": f"suggested-{self.action_id_counter}",
                    "label": label,
                    "action": action,
                    "rationale": defaults["rationale"],
                    "artifact_kind": defaults["artifact_kind"],
                    "prompt": defaults["prompt"],
                    "focus_area": defaults["focus_area"],
                }
            )
        return actions

    def coach_artifact_title(self, 
        scenario: str,
        response_language: str | None,
        *,
        task: TaskSpec | None = None,
        plan: LearningPlan | None = None,
        evaluation_summary: str | None = None,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
    ) -> str:
        if scenario == "idea_implementation":
            return localized_text(
                "Implementation path",
                "实现路径",
                response_language,
            )
        if scenario == "onboarding":
            return localized_text(
                "Coach intake",
                "\u6559\u7ec3\u521d\u6b21\u4e86\u89e3",
                response_language,
            )
        if scenario == "project_idea":
            return localized_text(
                "Training opportunity",
                "训练机会",
                response_language,
            )
        if scenario == "project_adaptation":
            return localized_text(
                "Adaptation boundary",
                "\u6539\u9020\u8fb9\u754c",
                response_language,
            )
        if scenario == "project_sourcing":
            return localized_text(
                "Source recommendation",
                "\u9879\u76ee\u6765\u6e90\u5efa\u8bae",
                response_language,
            )
        if scenario == "principle":
            return localized_text(
                "Principle to hold onto",
                "\u6838\u5fc3\u539f\u7406",
                response_language,
            )
        if scenario == "review":
            return localized_text(
                "Review focus",
                "评审重点",
                response_language,
            )
        if scenario == "plan":
            return live_plan_update_heading(
                plan=plan,
                runtime=runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot),
                existing=runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot),
                fallback=localized_text("Plan update", "\u8ba1\u5212\u66f4\u65b0", response_language),
            )
        if scenario in {"task", "next_task"}:
            leftover_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
            return live_task_heading(
                plan=plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title if task else "",
                fallback=localized_text("Practice task", "训练任务", response_language),
            )
        return localized_text("Coach note", "\u6559\u7ec3\u63d0\u793a", response_language)

    def stateful_focus_area(self, 
        task: TaskSpec | None,
        plan: LearningPlan | None,
        evaluation=None,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
    ) -> str | None:
        resolved_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
        focus = live_coach_focus_area(
            plan=plan,
            task=task,
            evaluation=evaluation,
            runtime=resolved_runtime,
            existing=resolved_runtime,
        )
        return focus or None

    def live_stage_object_label(self, 
        plan: LearningPlan | None,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
        stage: PlanStage | None = None,
    ) -> str:
        resolved_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
        return live_coach_stage_label(
            plan=plan,
            runtime=resolved_runtime,
            existing=resolved_runtime,
            stage_title=str(getattr(stage, "title", "") or "") if stage is not None else "",
        )

    def artifact_payload(self, 
        *,
        kind: str,
        title: str,
        summary: str,
        content: str | None = None,
        bullets: list[str] | None = None,
        teaser: str | None = None,
        recommended_action: str | None = None,
        rationale: str | None = None,
        focus_area: str | None = None,
        verification: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return CoachArtifact.model_validate(
            {
                "kind": kind,
                "title": title,
                "summary": summary,
                "content": content,
                "bullets": [item for item in bullets or [] if item],
                "teaser": teaser,
                "recommended_action": recommended_action,
                "rationale": rationale,
                "focus_area": focus_area,
                "verification": [item for item in verification or [] if item],
                "metadata": metadata or {},
            }
        ).model_dump()

    def render_artifact_content(self, 
        *,
        title: str,
        summary: str,
        bullets: list[str] | None = None,
        verification: list[str] | None = None,
        rationale: str | None = None,
        metadata: dict[str, object] | None = None,
        response_language: str | None = None,
        extras: list[str] | None = None,
    ) -> str:
        bullet_lines = [f"- {item}" for item in (bullets or []) if item]
        verification_lines = [f"- {item}" for item in (verification or []) if item]
        sections: list[str] = [f"## {title}", summary]

        if bullet_lines:
            sections.extend(
                [
                    "",
                    localized_text("### Action path", "### \u63a8\u8fdb\u8def\u5f84", response_language),
                    *bullet_lines,
                ]
            )

        if verification_lines:
            sections.extend(
                [
                    "",
                    localized_text("### Verify", "### \u9a8c\u8bc1\u65b9\u5f0f", response_language),
                    *verification_lines,
                ]
            )

        if rationale:
            sections.extend(
                [
                    "",
                    localized_text("### Why this matters", "### \u4e3a\u4ec0\u4e48\u8fd9\u6837\u63a8\u8fdb", response_language),
                    rationale,
                ]
            )

        coach_focus = metadata.get("coach_focus") if isinstance(metadata, dict) else None
        if isinstance(coach_focus, dict):
            current_focus = coach_focus.get("current_focus")
            next_step = coach_focus.get("next_step")
            review_rhythm = coach_focus.get("review_rhythm")
            focus_rows = [
                (
                    localized_text("Current focus", "\u5f53\u524d\u805a\u7126\u70b9", response_language),
                    current_focus,
                ),
                (
                    localized_text("Next step", "\u4e0b\u4e00\u6b65", response_language),
                    next_step,
                ),
                (
                    localized_text("Review rhythm", "\u590d\u76d8\u8282\u594f", response_language),
                    review_rhythm,
                ),
            ]
            focus_rows = [(label, value) for label, value in focus_rows if isinstance(value, str) and value]
            if focus_rows:
                sections.extend(
                    [
                        "",
                        localized_text("### Coach focus", "### \u6559\u7ec3\u89c6\u89d2", response_language),
                        f"| {localized_text('Field', '\u5b57\u6bb5', response_language)} | {localized_text('Detail', '\u5185\u5bb9', response_language)} |",
                        "| --- | --- |",
                        *[f"| {label} | {value} |" for label, value in focus_rows],
                    ]
                )

        background_mode = metadata.get("background_mode") if isinstance(metadata, dict) else None
        due_at = metadata.get("due_at") if isinstance(metadata, dict) else None
        if background_mode == "embedded" or due_at:
            notes: list[str] = []
            if background_mode == "embedded":
                notes.append(
                    localized_text(
                        "Background research stays embedded in this coaching turn.",
                        "\u540e\u53f0 research \u4fdd\u6301\u5d4c\u5165\u5728\u5f53\u524d\u6559\u7ec3\u56de\u5408\u91cc\u3002",
                        response_language,
                    )
                )
            if isinstance(due_at, str) and due_at:
                notes.append(
                    localized_text(
                        f"Follow-up review due: {due_at}",
                        f"\u540e\u7eed\u590d\u4e60\u5230\u671f\u65f6\u95f4\uff1a{due_at}",
                        response_language,
                    )
                )
            if notes:
                sections.extend(
                    [
                        "",
                        localized_text("### Notes", "### \u5907\u6ce8", response_language),
                        *[f"- {note}" for note in notes],
                    ]
                )

        if extras:
            sections.extend(["", *[extra for extra in extras if extra]])

        return "\n".join(section for section in sections if section is not None).strip()

    def exercise_lines(self, 
        exercise_prompt: dict[str, object] | None,
        response_language: str | None,
    ) -> list[str]:
        if not isinstance(exercise_prompt, dict):
            return []
        prompt = str(exercise_prompt.get("prompt", "") or "").strip()
        success_signal = str(exercise_prompt.get("success_signal", "") or "").strip()
        fallback_step = str(exercise_prompt.get("fallback_step", "") or "").strip()
        raw_constraints = exercise_prompt.get("constraints", [])
        constraints = [
            str(item).strip()
            for item in raw_constraints
            if str(item).strip()
        ] if isinstance(raw_constraints, list) else []
        lines: list[str] = []
        if prompt:
            lines.append(
                localized_text("### Try it now", "### \u73b0\u5728\u8bd5\u7740\u505a", response_language)
            )
            lines.append(prompt)
        if success_signal:
            lines.extend(
                [
                    "",
                    localized_text("### Success signal", "### \u6210\u529f\u4fe1\u53f7", response_language),
                    f"- {success_signal}",
                ]
            )
        if fallback_step:
            lines.extend(
                [
                    "",
                    localized_text("### If this still feels too big", "### \u5982\u679c\u8fd8\u662f\u592a\u5927", response_language),
                    fallback_step,
                ]
            )
        if constraints:
            lines.extend(
                [
                    "",
                    localized_text("### Keep these boundaries", "### \u5148\u5b88\u4f4f\u8fd9\u4e9b\u8fb9\u754c", response_language),
                    *[f"- {item}" for item in constraints[:3]],
                ]
            )
        return lines

    def build_turn_summary(self, 
        *,
        snapshot: WorkbenchSnapshot,
        scenario: str,
        learner_signal: str,
        artifacts: dict[str, object],
        suggested_actions: list[dict[str, object]],
        coach_context: dict[str, object] | None = None,
        response_language: str | None = None,
    ) -> CoachTurnSummary:
        coaching_state = snapshot.coaching_state or CoachingState()
        evaluation = snapshot.evaluation
        active_stage = None
        if snapshot.plan:
            active_stage = next(
                (
                    stage
                    for stage in snapshot.plan.stages
                    if stage.id == snapshot.plan.current_stage_id or stage.status == "active"
                ),
                snapshot.plan.stages[0] if snapshot.plan.stages else None,
            )
        failing_checks: list[str] = []
        if evaluation:
            failing_checks = [
                check.label
                for check in [*evaluation.static_checks, *evaluation.dynamic_checks, *evaluation.semantic_checks]
                if check.status in {"failed", "warning"}
            ]
        artifact_kinds = [str(kind) for kind in artifacts.keys()]
        suggested_action_types = [str(item.get("action", "")) for item in suggested_actions if item.get("action")]
        active_thread = snapshot.memory.active_thread
        active_thread_scenario = (
            str(active_thread.scenario or "").strip()
            if active_thread is not None
            else ""
        )
        history_mode = (
            str(coach_context.get("history_mode") or "").strip().lower()
            if isinstance(coach_context, dict)
            else ""
        )
        fresh_lane = history_mode == "fresh_lane" or (
            bool(active_thread_scenario)
            and scenario != "general"
            and active_thread_scenario != scenario
        )
        suppress_review_signals = fresh_lane and not self.fresh_lane_keeps_review_signals(scenario)
        summary_text = coaching_state.summary or snapshot.memory.current_focus
        next_step_text = coaching_state.next_step
        thread_decision = coaching_state.decision or ""
        thread_blocker = coaching_state.blocker or ""
        thread_teaching_note = coaching_state.teaching_note or ""
        thread_confidence = coaching_state.confidence or ""
        thread_evidence: list[str] = []
        if not fresh_lane and active_thread is not None:
            if not thread_decision:
                thread_decision = active_thread.decision
            if not thread_blocker:
                thread_blocker = active_thread.blocker
            if not thread_teaching_note:
                thread_teaching_note = active_thread.teaching_note
            if not thread_confidence:
                thread_confidence = active_thread.confidence
        evidence_sources = [coaching_state.evidence]
        if not fresh_lane and active_thread is not None:
            evidence_sources.append(active_thread.evidence)
        for source in evidence_sources:
            for item in source or []:
                text = str(item or "").strip()
                if text and text not in thread_evidence:
                    thread_evidence.append(text)
                if len(thread_evidence) >= 4:
                    break
            if len(thread_evidence) >= 4:
                break
        due_review = (
            None
            if suppress_review_signals
            else snapshot.memory.due_reviews[0] if snapshot.memory.due_reviews else None
        )
        teaching_mode = {
            "onboarding": "coach",
            "review": "review",
            "plan": "plan",
            "task": "practice",
            "next_task": "practice",
            "principle": "principle",
            "project_sourcing": "practice",
        }.get(scenario, "coach")
        emotional_tone = {
            "blocked": "supportive",
            "uncertain": "supportive",
            "curious": "challenging",
            "steady": "steady",
        }.get(learner_signal, "steady")
        if snapshot.tone_decision:
            emotional_tone = {
                "steady": "steady",
                "encouraging": "supportive",
                "concise_rescue": "supportive",
                "reflective": "challenging",
            }.get(snapshot.tone_decision.tone, emotional_tone)
        top_teaching_observation = (
            ""
            if fresh_lane
            else snapshot.memory.teaching_observations[0] if snapshot.memory.teaching_observations else ""
        )
        review_note = localized_text(
            (
                f"Review rhythm: after this slice lands, revisit '{due_review.concept}' through one narrow patch."
                if due_review
                else "Review rhythm: finish this slice, verify it, then decide whether to expand."
            ),
            (
                f"\u590d\u76d8\u8282\u594f\uff1a\u8fd9\u4e00\u6b65\u843d\u5730\u540e\uff0c\u518d\u56f4\u7ed5\u300c{due_review.concept}\u300d\u505a\u4e00\u6b21\u5f88\u7a84\u7684 patch \u5f0f\u56de\u770b\u3002"
                if due_review
                else "\u590d\u76d8\u8282\u594f\uff1a\u5148\u5b8c\u6210\u8fd9\u4e00\u5c0f\u6b65\u5e76\u9a8c\u8bc1\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u7ee7\u7eed\u5c55\u5f00\u3002"
            ),
            response_language,
        )
        if scenario == "idea_implementation":
            summary_text = localized_text(
                "Current focus: turn the idea into one thin, verifiable patch before widening scope.",
                "当前聚焦点：先把这个想法收成一个很小、可验证的 patch，再扩大范围。",
                response_language,
            )
        elif scenario == "onboarding":
            summary_text = localized_text(
                "Current focus: first understand your goal, current level, and project situation before choosing the coaching lane.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u5148\u7406\u89e3\u4f60\u7684\u76ee\u6807\u3001\u5f53\u524d\u6c34\u5e73\u548c project \u5904\u5883\uff0c\u518d\u4e00\u8d77\u5b9a\u6559\u7ec3\u4e3b\u7ebf\u3002",
                response_language,
            )
            first_look_next = self.first_look_recommended_next_from_snapshot(snapshot)
            next_step_text = first_look_next or localized_text(
                "Clarify the first lane, the current blocker, and the rhythm you want the coach to keep.",
                "\u5148\u660e\u786e\u7b2c\u4e00\u6761\u4e3b\u7ebf\u3001\u5f53\u524d\u5361\u70b9\uff0c\u4ee5\u53ca\u4f60\u5e0c\u671b Coach \u4fdd\u6301\u7684\u8282\u594f\u3002",
                response_language,
            )
        elif scenario == "project_sourcing":
            summary_text = localized_text(
                "Current focus: choose one outside project that is realistic enough to train on immediately.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u9009\u4e00\u4e2a\u73b0\u5b9e\u53ef\u7528\u3001\u80fd\u7acb\u523b\u62ff\u6765\u8bad\u7ec3\u7684\u5916\u90e8 project \u6765\u6e90\u3002",
                response_language,
            )
            next_step_text = localized_text(
                "Pick the smallest credible source, filter out setup-heavy repos, then ask the coach to extract the first task from it.",
                "\u5148\u6311\u6700\u53ef\u4fe1\u4e14\u6700\u5c0f\u7684\u6765\u6e90\uff0c\u8fc7\u6ee4\u6389\u642d\u5efa\u6210\u672c\u8fc7\u9ad8\u7684 repo\uff0c\u518d\u8ba9 Coach \u4ece\u91cc\u9762\u63d0\u70bc\u7b2c\u4e00\u9053\u4efb\u52a1\u3002",
                response_language,
            )
        first_look_next = self.first_look_recommended_next_from_snapshot(snapshot)
        live_task_title = (
            str(
                snapshot.current_task.title
                or snapshot.current_task.natural_language_goal
                or ""
            ).strip()
            if snapshot.current_task is not None
            else ""
        )
        if (
            first_look_next
            and not live_task_title
            and scenario in {"onboarding", "general"}
        ):
            next_step_text = first_look_next
        if scenario in {"review", "task", "next_task", "plan"} and not suppress_review_signals:
            summary_text = f"{summary_text} {review_note}".strip()
        if scenario in {"idea_implementation", "project_adaptation", "principle"} and not suppress_review_signals:
            next_step_text = f"{next_step_text} {review_note}".strip()
        next_step_text = strip_visible_next_step_prefix(next_step_text)
        return CoachTurnSummary.model_validate(
            {
                "scenario": scenario if scenario in coach_summary_scenarios else "general",
                "learner_signal": learner_signal,
                "summary": summary_text,
                "next_step": next_step_text,
                "encouragement": coaching_state.encouragement,
                "teaching_mode": teaching_mode,
                "emotional_tone": emotional_tone,
                "review_rhythm": "" if suppress_review_signals else snapshot.memory.review_rhythm,
                "teaching_observation": top_teaching_observation,
                "intervention_strategy": coaching_state.intervention_strategy,
                "teaching_goal": coaching_state.teaching_goal,
                "resume_thread": coaching_state.resume_thread,
                "decision": thread_decision,
                "blocker": thread_blocker,
                "teaching_note": thread_teaching_note,
                "confidence": thread_confidence,
                "evidence": thread_evidence,
                "support_strategy": coaching_state.support_strategy,
                "decision_reason": ""
                if suppress_review_signals
                else snapshot.teaching_decision.reason if snapshot.teaching_decision else "",
                "tone": snapshot.tone_decision.tone if snapshot.tone_decision else "steady",
                "verbosity_bias": snapshot.tone_decision.verbosity_bias if snapshot.tone_decision else "medium",
                "active_stage": self.live_stage_object_label(
                    snapshot.plan,
                    snapshot=snapshot,
                    stage=active_stage,
                )
                or None,
                "active_task": live_plan_update_persist_chrome(
                    plan=snapshot.plan,
                    runtime=coach_focus_runtime_from_snapshot(snapshot),
                    existing=coach_focus_runtime_from_snapshot(snapshot),
                    stage_title=active_stage.title if active_stage else "",
                    task_title=snapshot.current_task.title if snapshot.current_task else "",
                )["active_task"]
                or None,
                "due_review_count": 0 if suppress_review_signals else len(snapshot.memory.due_reviews),
                "review_queue_summary": "" if suppress_review_signals else snapshot.review_queue_summary,
                "failing_checks": failing_checks,
                "artifact_kinds": artifact_kinds,
                "suggested_action_types": suggested_action_types,
                "background_mode": "embedded",
            }
        )

    def coach_focus_bundle(self, 
        *,
        memory,
        response_language: str | None,
        scenario: str,
        coaching_state: CoachingState | None,
        message: str | None = None,
        task: TaskSpec | None = None,
        plan: LearningPlan | None = None,
        grounding_context: dict[str, object] | None = None,
        snapshot: WorkbenchSnapshot | None = None,
    ) -> dict[str, object]:
        bundle_stage = None
        if plan:
            bundle_stage = next(
                (
                    stage
                    for stage in plan.stages
                    if stage.id == plan.current_stage_id or stage.status == "active"
                ),
                plan.stages[0] if plan.stages else None,
            )
        persist_chrome = live_plan_update_persist_chrome(
            plan=plan,
            runtime=coach_focus_runtime_from_snapshot(snapshot),
            existing=coach_focus_runtime_from_snapshot(snapshot),
            stage_title=bundle_stage.title if bundle_stage else "",
            task_title=task.title if task else "",
        )
        stage_focus = persist_chrome["stage_focus"] or None
        task_focus = persist_chrome["active_task"] or None
        scenario_focus = self.canonical_focus_for_scenario(scenario, response_language) or ""
        turn_focus_hint = self.resolve_turn_focus_hint(
            user_message=message,
            task_focus=task_focus,
            stage_focus=stage_focus,
        )
        preserve_active_thread = self.should_preserve_active_thread_for_turn(
            scenario,
            memory.active_thread,
            message=message,
            grounding_context=grounding_context,
        )
        fresh_lane = not preserve_active_thread and (scenario != "general" or bool(turn_focus_hint))
        suppress_review_signals = fresh_lane and not self.fresh_lane_keeps_review_signals(scenario)
        lane_focus = (
            turn_focus_hint
            or scenario_focus
            or task_focus
            or stage_focus
            or (coaching_state.summary if coaching_state else "")
        )
        due_review_concepts = {
            str(getattr(item, "concept", "") or "").strip().lower()
            for item in getattr(memory, "due_reviews", []) or []
        }
        synthetic_due_reviews = bool(due_review_concepts) and due_review_concepts.issubset(
            {"new-workspace", "plan-discipline", "resource-grounding"}
        )
        relationship_stage = "active" if (
            memory.active_thread
            or memory.learning_outcomes
            or (memory.due_reviews and not synthetic_due_reviews)
        ) else "intake"
        if scenario == "onboarding":
            relationship_stage = "intake"
        elif fresh_lane:
            relationship_stage = "intake"
        first_turn_priority = (
            "orient, reassure, clarify learner goal and choose one coaching lane"
            if relationship_stage == "intake"
            else ""
        )
        if fresh_lane:
            first_turn_priority = "re-anchor on the newly requested coaching lane and keep the first move compact"
        strategy_preference_summary = ""
        teaching_strategy_effectiveness = getattr(memory, "teaching_strategy_effectiveness", []) or []
        if teaching_strategy_effectiveness and not fresh_lane:
            top_strategy = teaching_strategy_effectiveness[0]
            if isinstance(top_strategy, dict):
                focus_label = top_strategy.get("focus_area") or top_strategy.get("scenario") or "current lane"
                strategy_preference_summary = (
                    f"{focus_label}: {top_strategy.get('success_count')}/{top_strategy.get('total_count')} useful outcomes with "
                    f"{top_strategy.get('challenge_level')}/{top_strategy.get('hint_depth')}/"
                    f"{top_strategy.get('explanation_mode')}/{top_strategy.get('next_step_bias')}"
                )
        recent_teaching_signals: list[str] = []
        workspace = getattr(memory, "workspace", {}) or {}
        if not fresh_lane:
            for candidate in (
                workspace.get("latest_turn_teaching_signal") if isinstance(workspace, dict) else None,
                memory.teaching_observations[0] if getattr(memory, "teaching_observations", []) else None,
            ):
                normalized = str(candidate or "").strip()
                if normalized and normalized not in recent_teaching_signals:
                    recent_teaching_signals.append(normalized)
        current_focus = memory.current_focus
        review_rhythm = memory.review_rhythm
        if (
            not review_rhythm
            and scenario in {"next_task", "review", "review_reflection"}
            and memory.due_reviews
        ):
            due_concept = str(memory.due_reviews[0].concept or "current review").strip()
            review_rhythm = localized_text(
                f"Review '{due_concept}' before opening another lane.",
                f"先回看「{due_concept}」，再开启新的主线。",
                response_language,
            )
        teaching_observations = list(memory.teaching_observations[:3])
        recent_wins = list(memory.recent_wins[:2])
        if fresh_lane:
            current_focus = lane_focus or current_focus
            if suppress_review_signals:
                review_rhythm = ""
            teaching_observations = []
            recent_wins = []
        elif not current_focus and coaching_state:
            current_focus = coaching_state.summary
        visible_current_focus = self.guided_focus_display_value(
            current_focus,
            scenario=scenario,
            response_language=response_language,
        )
        visible_review_rhythm = (
            language_aligned_context_text(review_rhythm, response_language) or str(review_rhythm or "").strip()
        )
        visible_next_step = strip_visible_next_step_prefix(
            language_aligned_context_text(
                coaching_state.next_step if coaching_state else "",
                response_language,
            )
            or (coaching_state.next_step if coaching_state else "")
        )
        visible_strategy_preference_summary = language_aligned_context_text(
            strategy_preference_summary,
            response_language,
        ) or strategy_preference_summary
        return {
            "current_focus": visible_current_focus,
            "review_rhythm": visible_review_rhythm,
            "next_step": visible_next_step,
            "active_stage": stage_focus,
            "active_task": task_focus,
            "scenario": scenario,
            "relationship_stage": relationship_stage,
            "first_turn_priority": first_turn_priority,
            "strategy_preference_summary": visible_strategy_preference_summary,
            "teaching_observations": language_aligned_context_list(
                teaching_observations,
                response_language,
            ),
            "recent_wins": language_aligned_context_list(
                recent_wins,
                response_language,
            ),
            "recent_teaching_signals": language_aligned_context_list(
                recent_teaching_signals[:2],
                response_language,
            ),
            "due_review_count": len(memory.due_reviews),
            "language": response_language or "en-US",
        }

    def summarize_support_categories(self, 
        categories: list[str],
        response_language: str | None,
    ) -> str | None:
        normalized = [item.strip() for item in categories if item and item.strip()]
        if not normalized:
            return None
        if prefers_chinese(response_language):
            if len(normalized) == 1:
                return f"\u53c2\u8003\u4e86{normalized[0]}"
            return f"\u53c2\u8003\u4e86{'\u3001'.join(normalized[:-1])}\u548c{normalized[-1]}"
        if len(normalized) == 1:
            return f"Used {normalized[0]}"
        if len(normalized) == 2:
            return f"Used {normalized[0]} and {normalized[1]}"
        return f"Used {', '.join(normalized[:-1])}, and {normalized[-1]}"

    def describe_request_attachment_delivery(self, 
        request: TurnRequest | SessionMessageRequest,
        coaching_service: ProviderService,
        *,
        use_agent_loop: bool,
    ) -> dict[str, object]:
        attachments_payload = [attachment.model_dump() for attachment in request.attachments]
        return coaching_service.describe_attachment_delivery(
            attachments=attachments_payload,
            protocol=getattr(coaching_service._config, "protocol", None) if coaching_service._config else None,
            use_agent_loop=use_agent_loop,
        )

    def normalize_attachment_delivery_payload(self, 
        value: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        attachments_present = bool(value.get("attachments_present"))
        raw_image_count = value.get("image_attachment_count")
        image_attachment_count = raw_image_count if isinstance(raw_image_count, int) else 0
        attachments_delivered_to_model = bool(value.get("attachments_delivered_to_model"))
        attachments_delivery_path = str(value.get("attachments_delivery_path") or "").strip() or "not_sent"
        attachments_delivery_reason = str(value.get("attachments_delivery_reason") or "").strip()
        if not attachments_present or image_attachment_count <= 0:
            return None
        return {
            "attachments_present": attachments_present,
            "image_attachment_count": image_attachment_count,
            "attachments_delivered_to_model": attachments_delivered_to_model,
            "attachments_delivery_path": attachments_delivery_path,
            "attachments_delivery_reason": attachments_delivery_reason,
        }

    def apply_attachment_delivery_metadata(self, 
        metadata: dict[str, object],
        attachment_delivery: dict[str, object] | None,
    ) -> None:
        normalized = self.normalize_attachment_delivery_payload(attachment_delivery)
        if not normalized:
            return
        metadata.update(normalized)

    def attachment_delivery_line(self, 
        attachment_delivery: dict[str, object] | None,
        *,
        response_language: str | None,
    ) -> str | None:
        normalized = self.normalize_attachment_delivery_payload(attachment_delivery)
        if not normalized:
            return None
        raw_image_attachment_count = normalized.get("image_attachment_count")
        image_attachment_count = (
            raw_image_attachment_count
            if isinstance(raw_image_attachment_count, int)
            else 0
        )
        if image_attachment_count <= 0:
            return None
        attachments_delivered_to_model = bool(normalized.get("attachments_delivered_to_model"))
        attachments_delivery_reason = str(normalized.get("attachments_delivery_reason") or "").strip()
        count_label = localized_text(
            f"{image_attachment_count} image attachment{'s' if image_attachment_count != 1 else ''}",
            f"{image_attachment_count} \u5f20\u56fe\u7247\u9644\u4ef6",
            response_language,
        )
        if attachments_delivered_to_model:
            return localized_text(
                f"{count_label} reached the model as image input.",
                f"{count_label} \u5df2\u4f5c\u4e3a\u56fe\u50cf\u8f93\u5165\u53d1\u9001\u7ed9\u6a21\u578b\u3002",
                response_language,
            )
        reason_suffix = localized_text(
            "The current coach turn could not send images to the model.",
            "\u5f53\u524d\u8fd9\u8f6e\u6559\u7ec3\u5bf9\u8bdd\u8fd8\u4e0d\u80fd\u628a\u56fe\u7247\u53d1\u9001\u7ed9\u6a21\u578b\u3002",
            response_language,
        )
        if attachments_delivery_reason == "agent_loop_disabled":
            reason_suffix = localized_text(
                "This turn stayed on the plain reply path, so images were not forwarded to the model.",
                "",
                response_language,
            )
        elif attachments_delivery_reason == "vision_not_available":
            reason_suffix = localized_text(
                "The current provider turn is not vision-ready, so images were not forwarded to the model.",
                "",
                response_language,
            )
        elif attachments_delivery_reason == "tools_not_available":
            reason_suffix = localized_text(
                "This provider turn was not running on the tool-enabled coach path, so images were not forwarded to the model.",
                "",
                response_language,
            )
        elif attachments_delivery_reason == "non_image_attachments_not_supported":
            reason_suffix = localized_text(
                "Attached files are not forwarded to the model in this coach turn yet.",
                "\u5f53\u524d\u8fd9\u8f6e\u6559\u7ec3\u5bf9\u8bdd\u8fd8\u4e0d\u4f1a\u628a\u6587\u4ef6\u9644\u4ef6\u76f4\u63a5\u53d1\u9001\u7ed9\u6a21\u578b\u3002",
                response_language,
            )
        return localized_text(
            f"{count_label} did not reach the model. {reason_suffix}",
            f"{count_label} \u6ca1\u6709\u9001\u8fbe\u6a21\u578b\u3002{reason_suffix}",
            response_language,
        )

    def build_message_support(self, 
        request: TurnRequest | SessionMessageRequest,
        coach_turn: dict[str, object] | None = None,
        attachment_delivery: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        response_language = request.response_language
        current_file = request.current_file
        coach_context = (
            normalized_object_mapping(coach_turn.get("coach_context"))
            if isinstance(coach_turn, dict)
            else None
        ) or {}
        coach_scenario = str(coach_turn.get("scenario") or "").strip() if isinstance(coach_turn, dict) else ""
        if coach_scenario == "function_guidance" and not is_code_like_current_file(
            self.normalize_current_file_payload(current_file)
        ):
            current_file = None
        categories: list[str] = []
        lines: list[str] = []

        def push_category(value: str) -> None:
            normalized = value.strip()
            if normalized and normalized not in categories:
                categories.append(normalized)

        def push_line(value: str | None) -> None:
            normalized = str(value or "").strip()
            if normalized and normalized not in lines:
                lines.append(normalized)

        if current_file:
            current_file_name = str(current_file.path or "").replace("\\", "/").rsplit("/", 1)[-1]
            if current_file_name:
                push_category(localized_text("the current file", "\u5f53\u524d\u6587\u4ef6", response_language))
                push_line(
                    localized_text(
                        f"Current file: {current_file_name}",
                        f"\u5f53\u524d\u6587\u4ef6\uff1a{current_file_name}",
                        response_language,
                    )
                )
            if current_file.selection_range:
                push_category(localized_text("the current selection", "\u5f53\u524d\u9009\u533a", response_language))
                push_line(
                    localized_text(
                        f"Selection: {current_file.selection_range}",
                        f"\u9009\u533a\uff1a{current_file.selection_range}",
                        response_language,
                    )
                )
            diagnostics = current_file.diagnostics or []
            if diagnostics:
                push_category(localized_text("recent diagnostics", "\u6700\u8fd1\u8bca\u65ad", response_language))
                push_line(
                    localized_text(
                        f"Diagnostics: {len(diagnostics)} item(s)",
                        f"\u8bca\u65ad\uff1a{len(diagnostics)} \u9879",
                        response_language,
                    )
                )
            related_files = current_file.related_files or []
            related_names: list[str] = []
            for item in related_files[:3]:
                path_value = item.get("path")
                normalized = str(path_value or "").replace("\\", "/").rsplit("/", 1)[-1]
                if normalized:
                    related_names.append(normalized)
            if related_names:
                push_category(localized_text("related files", "\u76f8\u5173\u6587\u4ef6", response_language))
                push_line(
                    localized_text(
                        f"Related files: {', '.join(related_names)}",
                        f"\u76f8\u5173\u6587\u4ef6\uff1a{'\u3001'.join(related_names)}",
                        response_language,
                    )
                )

        requested_resources = coach_context.get("requested_resources")
        if isinstance(requested_resources, list) and requested_resources:
            resource_titles: list[str] = []
            for item in requested_resources[:3]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("name") or item.get("id") or "").strip()
                if title:
                    resource_titles.append(title)
            if resource_titles:
                push_category(localized_text("attached resources", "\u9644\u5e26\u8d44\u6599", response_language))
                push_line(
                    localized_text(
                        f"Attached resources: {', '.join(resource_titles)}",
                        f"\u9644\u5e26\u8d44\u6599\uff1a{'\u3001'.join(resource_titles)}",
                        response_language,
                    )
                )
        external_references = coach_context.get("external_references")
        if not isinstance(external_references, list) or not external_references:
            external_references = coach_context.get("resource_fragments")
        if isinstance(external_references, list) and external_references:
            first_reference = external_references[0]
            if isinstance(first_reference, dict):
                snippet = str(first_reference.get("snippet") or "").strip()
                source = str(first_reference.get("source") or "").strip()
                trust = first_reference.get("trust_score")
                if snippet:
                    push_category(localized_text("external grounding", "\u5916\u90e8\u53c2\u8003", response_language))
                    suffix = ""
                    if source:
                        suffix = localized_text(
                            f" (source: {source})",
                            f"\uff08\u6765\u6e90\uff1a{source}\uff09",
                            response_language,
                        )
                    if trust is not None:
                        suffix += localized_text(
                            f" [trust {trust}]",
                            "",
                            response_language,
                        )
                    push_line(
                        localized_text(
                            f"Referenced material: {snippet}{suffix}",
                            f"\u53c2\u8003\u8d44\u6599\uff1a{snippet}{suffix}",
                            response_language,
                        )
                    )

        memory_parts: list[str] = []
        current_focus = str(coach_context.get("current_focus") or "").strip()
        if current_focus:
            memory_parts.append(
                localized_text(
                    f"focus on {current_focus[:72]}",
                    f"\u6cbf\u7740\u5f53\u524d\u805a\u7126\u70b9\u7ee7\u7eed\uff1a{current_focus[:48]}",
                    response_language,
                )
            )
        review_rhythm = str(coach_context.get("review_rhythm") or "").strip()
        if review_rhythm:
            memory_parts.append(
                localized_text(
                    f"review rhythm: {review_rhythm[:72]}",
                    f"\u590d\u4e60\u8282\u594f\uff1a{review_rhythm[:48]}",
                    response_language,
                )
            )
        due_review_count = coach_context.get("due_review_count")
        if isinstance(due_review_count, int) and due_review_count > 0:
            memory_parts.append(
                localized_text(
                    f"{due_review_count} due review item(s)",
                    f"{due_review_count} \u9879\u5f85\u590d\u4e60",
                    response_language,
                )
            )
        if memory_parts:
            push_category(localized_text("long-term memory", "长期记忆", response_language))
            push_line(
                localized_text(
                    f"Memory kept in view: {'; '.join(memory_parts)}",
                    f"\u8fd9\u6b21\u4e5f\u5e26\u4e0a\u4e86\u957f\u671f\u8bb0\u5fc6\uff1a{'\uff1b'.join(memory_parts)}",
                    response_language,
                )
            )

        attachment_line = self.attachment_delivery_line(
            attachment_delivery,
            response_language=response_language,
        )
        if attachment_line:
            push_category(localized_text("attached images", "\u56fe\u7247\u9644\u4ef6", response_language))
            push_line(attachment_line)

        preview = self.summarize_support_categories(categories, response_language)
        if not preview and not lines:
            return None
        return {
            "preview": preview or localized_text("Used supporting context", "\u53c2\u8003\u4e86\u8865\u5145\u4e0a\u4e0b\u6587", response_language),
            "lines": lines[:6],
        }

    def normalize_agent_tool_arguments(self, value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw_arguments": raw}
            if isinstance(parsed, dict):
                return parsed
            return {"_raw_arguments": parsed}
        if value is None:
            return {}
        return {"_raw_arguments": value}

    def localized_agent_tool_label(self, 
        tool_name: str,
        response_language: str | None,
    ) -> str:
        labels = {
            "project_read": ("project inspection", "代码检视"),
            "project_verify": ("project verification", "练习与诊断核验"),
            "library_read": ("library search", "资料库检索"),
            "library_write": ("library update", "资料库更新"),
            "library_exec": ("library script", "资料库批处理"),
            "web_fetch": ("web research", "联网检索"),
            "learning_inspect": ("learning state check", "学习档案核对"),
            "learning_action": ("learning state update", "学习动作执行"),
            "search_resources": ("resource search", "资料搜索"),
            "read_workspace_file": ("file read", "代码读取"),
            "list_workspace_files": ("file listing", "文件浏览"),
            "recall_memory": ("memory recall", "记忆回看"),
            "record_learning_note": ("note save", "学习记录"),
            "inspect_plan": ("plan check", "计划核对"),
            "generate_training_card": ("training card", "训练卡生成"),
            "run_diagnostics": ("diagnostics", "诊断检查"),
            "coach_finalize": ("wrap-up", "收束"),
        }
        english, chinese = labels.get(tool_name, (tool_name.replace("_", " ").strip() or tool_name, tool_name))
        return localized_text(english, chinese, response_language)

    def unique_text_items(self, values: list[str] | None, *, limit: int = 3) -> list[str]:
        items: list[str] = []
        for raw_value in values or []:
            normalized = str(raw_value or "").strip()
            if not normalized or normalized in items:
                continue
            items.append(normalized)
            if len(items) >= limit:
                break
        return items

    def coach_turn_summary_text(self, 
        turn_summary: CoachTurnSummary | dict[str, object] | None,
        field: str,
    ) -> str:
        if isinstance(turn_summary, CoachTurnSummary):
            return str(getattr(turn_summary, field, "") or "").strip()
        if isinstance(turn_summary, dict):
            return str(turn_summary.get(field) or "").strip()
        return ""

    def build_next_step_hint(self, 
        *,
        snapshot: WorkbenchSnapshot,
        response_language: str | None,
        current_step: str = "",
        why_now: str = "",
        verify_method: list[str] | None = None,
        coach_turn: dict[str, object] | None = None,
        agent_meta: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        raw_coach_context = coach_turn.get("coach_context") if isinstance(coach_turn, dict) else None
        coach_context = normalized_object_mapping(raw_coach_context) or {}
        raw_turn_summary = coach_turn.get("coach_turn") if isinstance(coach_turn, dict) else None
        turn_summary: CoachTurnSummary | dict[str, object] | None = (
            raw_turn_summary
            if isinstance(raw_turn_summary, CoachTurnSummary)
            else normalized_object_mapping(raw_turn_summary)
        )
        active_stage = self.active_plan_stage(snapshot.plan)
        active_thread = snapshot.memory.active_thread
        coaching_state = snapshot.coaching_state
        resolved_scenario = (
            self.coach_turn_summary_text(turn_summary, "scenario")
            or str(getattr(coaching_state, "scenario", "") or "").strip()
            or "general"
        )
        preserve_active_thread = self.should_preserve_active_thread_for_scenario(
            resolved_scenario,
            active_thread,
        )
        if not preserve_active_thread:
            active_thread = None
        active_thread_focus = str(getattr(active_thread, "focus_area", "") or "").strip()
        active_thread_summary = str(getattr(active_thread, "summary", "") or "").strip()
        active_thread_next_step = str(getattr(active_thread, "next_step", "") or "").strip()
        evaluation = snapshot.evaluation
        task = snapshot.current_task
        implementation_guide = snapshot.implementation_guide
        review_item = snapshot.memory.due_reviews[0] if snapshot.memory.due_reviews else None
        verify_items = self.unique_text_items(verify_method)
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        if (
            not verify_items
            and snapshot.plan
            and leftover_formal_plan_is_live_for_fill(
                plan=snapshot.plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
        ):
            verify_items = self.unique_text_items(list(snapshot.plan.verify_method))
        if not verify_items and task:
            verify_items = self.unique_text_items(list(task.verification_strategy))

        title = str(current_step or "").strip()
        reason = str(why_now or "").strip()
        agent_next_step = str(agent_meta.get("next_step") or "").strip() if isinstance(agent_meta, dict) else ""
        agent_summary = str(agent_meta.get("summary") or "").strip() if isinstance(agent_meta, dict) else ""
        turn_next_step = self.coach_turn_summary_text(turn_summary, "next_step")
        turn_summary_value = self.coach_turn_summary_text(turn_summary, "summary")
        action = "task"
        source = "plan"
        continue_in = "plan"
        # Leftover plan_runtime current_step without a formal plan is pressure-only.
        # Do not mint a plan/task next-step hint from it (tight budget / urgency must not invent a live task).
        if title and snapshot.plan is None:
            title = ""

        if agent_next_step:
            title = agent_next_step
            source = "agent_loop"
            continue_in = "coach"
            if not reason:
                reason = agent_summary
        elif title:
            if evaluation and title == evaluation.next_step.strip():
                source = "evaluation"
                action = "review"
                continue_in = "coach"
            elif implementation_guide and title == implementation_guide.current_step.strip():
                source = "implementation_guide"
            elif active_thread_next_step and title == active_thread_next_step:
                source = "active_thread"
                continue_in = "coach"
                if active_thread_summary and active_thread_summary != title:
                    reason = active_thread_summary
            elif coaching_state and title == coaching_state.next_step.strip():
                source = "coaching_state"
                continue_in = "coach"
            elif turn_next_step and title == turn_next_step:
                source = "coach_turn"
                continue_in = "coach"
            elif task and title in {task.natural_language_goal.strip(), task.title.strip()}:
                source = "task"
        elif turn_next_step:
            title = turn_next_step
            source = "coach_turn"
            continue_in = "coach"
            reason = reason or turn_summary_value
        elif active_thread_next_step:
            title = active_thread_next_step
            source = "active_thread"
            continue_in = "coach"
            reason = reason or active_thread_summary
        elif coaching_state and coaching_state.next_step.strip():
            title = coaching_state.next_step.strip()
            source = "coaching_state"
            continue_in = "coach"
            reason = reason or coaching_state.summary.strip()
        elif evaluation and evaluation.next_step.strip():
            title = evaluation.next_step.strip()
            source = "evaluation"
            action = "review"
            continue_in = "coach"
            reason = reason or evaluation.summary.strip()
        elif task and task.natural_language_goal.strip():
            title = task.natural_language_goal.strip()
            source = "task"
            leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
            reason = live_task_suggested_reason(
                plan=snapshot.plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                reason=reason,
                task_title=task.title,
            )
        elif review_item:
            review_concept = str(getattr(review_item, "concept", "") or "").strip()
            review_reason = str(getattr(review_item, "reason", "") or "").strip()
            review_hint = str(getattr(review_item, "task_hint", "") or "").strip()
            if review_concept:
                title = localized_text(
                    f"Revisit {review_concept} before widening scope.",
                    "",
                    response_language,
                )
            else:
                title = localized_text(
                    "Run one quick review pass before widening scope.",
                    "",
                    response_language,
                )
            source = "review"
            action = "review"
            continue_in = "training"
            reason = reason or review_reason
            if review_hint:
                verify_items = self.unique_text_items([*verify_items, review_hint])

        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        title = live_task_suggested_title(
            plan=snapshot.plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            title=title.strip(),
            goal=task.natural_language_goal if task else "",
            task_title=task.title if task else "",
        )
        # Orphaned runtime current_step (no formal plan) must not become a
        # plan/task-shaped next-step hint under pressure / urgency.
        if snapshot.plan is None and title:
            orphaned_step = str(
                leftover_runtime.get("current_step")
                or leftover_runtime.get("currentStep")
                or ""
            ).strip() if isinstance(leftover_runtime, dict) else ""
            if orphaned_step and title == orphaned_step:
                return None
        if not title:
            return None

        reason = live_task_suggested_reason(
            plan=snapshot.plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            reason=reason,
            task_title=task.title if task else "",
        )
        live_task_focus = live_task_label(
            plan=snapshot.plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=task.title if task else "",
        )
        live_stage_focus = live_coach_stage_label(
            plan=snapshot.plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            stage_title=str(getattr(active_stage, "title", "") or "").strip() if active_stage else "",
        )

        focus_area = ""
        for candidate in (
            active_thread_focus,
            str(coach_context.get("current_focus") or "").strip(),
            snapshot.memory.current_focus,
            live_task_focus,
            live_stage_focus,
        ):
            normalized = str(candidate or "").strip()
            if normalized:
                focus_area = normalized
                break

        if title == active_thread_next_step and active_thread_summary and active_thread_summary != title:
            reason = active_thread_summary

        summary_candidates = [
            reason,
            agent_summary if agent_summary != title else "",
            turn_summary_value if turn_summary_value != title else "",
            active_thread_summary if active_thread_summary != title else "",
            str(coaching_state.summary or "").strip()
            if coaching_state and coaching_state.summary.strip() != title
            else "",
            str(evaluation.summary or "").strip()
            if evaluation and evaluation.summary.strip() != title and source == "evaluation"
            else "",
        ]
        summary_text = next((item for item in summary_candidates if item), "")
        if not summary_text and verify_items:
            summary_text = localized_text(
                f"Keep this slice narrow and verify it with: {verify_items[0]}",
                f"先把这一小步做稳，再用这条验证它：{verify_items[0]}",
                response_language,
            )
        elif not summary_text and focus_area:
            summary_text = localized_text(
                f"Stay on {focus_area} until this step is verified.",
                f"\u5148\u6cbf\u7740\u300c{focus_area}\u300d\u8fd9\u6761\u4e3b\u7ebf\u63a8\u8fdb\uff0c\u9a8c\u8bc1\u901a\u8fc7\u540e\u518d\u6269\u5c55\u3002",
                response_language,
            )
        elif not summary_text:
            summary_text = localized_text(
                "Keep this next move small enough to verify before widening scope.",
                "",
                response_language,
            )

        prompt = localized_text(
            f'Guide me through "{title}" and keep it to this one small step.',
            f'\u8bf7\u56f4\u7ed5\u300c{title}\u300d\u7ee7\u7eed\u6307\u5bfc\u6211\uff0c\u5148\u53ea\u505a\u8fd9\u4e00\u5c0f\u6b65\u3002',
            response_language,
        )
        if action == "review":
            prompt = localized_text(
                f"Review my result against {title} once I try it.",
                f"\u6211\u5c1d\u8bd5\u5b8c\u300c{title}\u300d\u540e\uff0c\u8bf7\u5e2e\u6211\u505a\u4e00\u8f6e\u590d\u76d8\u3002",
                response_language,
            )

        hint_payload: dict[str, object] = {
            "title": title,
            "recommended_action": action,
            "source": source,
            "continue_in": continue_in,
        }
        if summary_text and summary_text != title:
            hint_payload["summary"] = summary_text
        if focus_area:
            hint_payload["focus_area"] = focus_area
        if prompt:
            hint_payload["prompt"] = prompt
        if verify_items:
            hint_payload["verification"] = verify_items[:3]
        resume_thread = str(coach_context.get("resume_thread") or "").strip()
        if not resume_thread and agent_next_step:
            coach_context_summary = str(coach_context.get("summary") or "").strip()
            resume_thread = self.build_resume_thread_text(
                coach_context_summary or summary_text or agent_summary or title,
                title,
                response_language=response_language,
            )
        if resume_thread:
            hint_payload["resume_thread"] = resume_thread
        return hint_payload

    def build_resume_thread_text(self, 
        summary_text: str,
        next_step_text: str,
        *,
        response_language: str | None,
    ) -> str:
        summary_text = str(summary_text or "").strip()
        next_step_text = strip_visible_next_step_prefix(next_step_text)
        if not summary_text and not next_step_text:
            return ""
        if summary_text and summary_text[-1] not in ".!?\u3002\uff01\uff1f":
            summary_text = f"{summary_text}."
        if summary_text and next_step_text:
            return localized_text(
                f"Resume the live thread around {summary_text} Next: {next_step_text}",
                f"\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u7ee7\u7eed\uff1a{summary_text} \u4e0b\u4e00\u6b65\uff1a{next_step_text}",
                response_language,
            )
        if summary_text:
            return localized_text(
                f"Resume the live thread around {summary_text}",
                f"\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u7ee7\u7eed\uff1a{summary_text}",
                response_language,
            )
        return localized_text(
            f"Resume the live thread. Next: {next_step_text}",
            f"\u7ee7\u7eed\u5f53\u524d\u4e3b\u7ebf\u3002\u4e0b\u4e00\u6b65\uff1a{next_step_text}",
            response_language,
        )

    def build_agent_message_parts(self, 
        agent_meta: dict[str, object] | None,
        *,
        response_language: str | None,
    ) -> list[dict[str, object]]:
        if not isinstance(agent_meta, dict):
            return []
        raw_events = agent_meta.get("tool_events")
        if not isinstance(raw_events, list) or not raw_events:
            return []

        parts: list[dict[str, object]] = []
        for index, item in enumerate(raw_events, start=1):
            if not isinstance(item, dict):
                continue
            event_type = str(item.get("type") or "").strip()
            call_id = str(
                item.get("id")
                or item.get("call_id")
                or item.get("tool_call_id")
                or item.get("name")
                or f"tool-{index}"
            )
            step = item.get("step") if isinstance(item.get("step"), int) else None
            if event_type == "tool_call":
                parts.append(
                    {
                        "type": "tool_call",
                        "id": call_id,
                        "name": str(item.get("name") or "tool"),
                        "status": "called",
                        "args": self.normalize_agent_tool_arguments(item.get("arguments")),
                        "step": step,
                    }
                )
                continue
            if event_type == "tool_result":
                result_payload = item.get("result")
                tool_name = str(item.get("name") or item.get("tool_name") or "").strip()
                error_text: str | None = None
                if isinstance(result_payload, dict) and result_payload.get("error"):
                    error_text = str(result_payload["error"])
                elif item.get("ok") is False:
                    error_text = localized_text(
                        "Tool execution failed.",
                        "",
                        response_language,
                    )
                part: dict[str, object] = {
                    "type": "tool_result",
                    "callId": call_id,
                    "result": result_payload,
                    "step": step,
                }
                if tool_name:
                    part["name"] = tool_name
                is_practice_verify = (
                    isinstance(result_payload, dict)
                    and (
                        tool_name == "verify_practice_current_file"
                        or (
                            tool_name == "project_verify"
                            and str(result_payload.get("action") or "verify_practice").strip().lower()
                            == "verify_practice"
                            and "passed" in result_payload
                        )
                    )
                )
                if is_practice_verify and isinstance(result_payload, dict):
                    part["displayKind"] = "practice_verification"
                    if result_payload.get("status"):
                        part["status"] = str(result_payload["status"])
                    if "passed" in result_payload:
                        part["passed"] = bool(result_payload.get("passed"))
                    if result_payload.get("path"):
                        part["path"] = str(result_payload["path"])
                    if result_payload.get("summary"):
                        part["summary"] = str(result_payload["summary"])
                    next_step_value = result_payload.get("next_step") or result_payload.get("nextStep")
                    if next_step_value:
                        part["nextStep"] = str(next_step_value)
                if error_text:
                    part["error"] = error_text
                parts.append(part)
        # Successful library/web reads become visible passage + citation parts.
        # Failed or empty results produce nothing, so the transcript can never
        # show a citation the tool did not return.
        parts.extend(
            build_resource_display_parts(
                raw_events,
                response_language=response_language,
            )
        )
        return parts

    def build_agent_finalize_artifact(self, 
        agent_meta: dict[str, object] | None,
        *,
        requires_confirmation: bool = False,
    ) -> dict[str, object] | None:
        if not isinstance(agent_meta, dict):
            return None
        next_step_text = str(agent_meta.get("next_step") or "").strip()
        summary_text = str(agent_meta.get("summary") or "").strip()
        decision_text = str(agent_meta.get("decision") or "").strip()
        blocker_text = str(agent_meta.get("blocker") or "").strip()
        teaching_note_text = str(
            agent_meta.get("teaching_note") or agent_meta.get("teachingNote") or ""
        ).strip()
        resume_thread_text = str(
            agent_meta.get("resume_thread") or agent_meta.get("resumeThread") or ""
        ).strip()
        confidence_text = str(agent_meta.get("confidence") or "").strip()
        evidence_items: list[str] = []
        raw_evidence = agent_meta.get("evidence")
        if isinstance(raw_evidence, list):
            for item in raw_evidence:
                text = str(item).strip()
                if text:
                    evidence_items.append(text)
                if len(evidence_items) >= 3:
                    break
        if not next_step_text:
            return None
        artifact_entry: dict[str, object] = {
            "kind": "next_step",
            "title": next_step_text,
            "recommended_action": "task",
        }
        if summary_text and summary_text != next_step_text:
            artifact_entry["summary"] = summary_text
        metadata: dict[str, object] = {}
        if decision_text:
            metadata["decision"] = decision_text
        if blocker_text:
            metadata["blocker"] = blocker_text
        if teaching_note_text:
            metadata["teaching_note"] = teaching_note_text
        if resume_thread_text:
            metadata["resume_thread"] = resume_thread_text
        if confidence_text:
            metadata["confidence"] = confidence_text
        if evidence_items:
            metadata["evidence"] = evidence_items
            artifact_entry["verification"] = evidence_items
        # Grounding downgrade carrier (§2.5⑤): the webview renders the next-step
        # card as "confirm before acting" from this metadata; the turn's
        # downgraded flag and the agent_meta stamp both light it up.
        require_confirmation = bool(requires_confirmation) or bool(
            agent_meta.get("next_step_requires_confirmation")
            or agent_meta.get("nextStepRequiresConfirmation")
        )
        if require_confirmation:
            metadata["next_step_requires_confirmation"] = True
        grounding_outcome_text = str(agent_meta.get("grounding_outcome") or "").strip()
        if grounding_outcome_text:
            metadata["grounding_outcome"] = grounding_outcome_text
        if metadata:
            artifact_entry["metadata"] = metadata
        return artifact_entry

    def merge_agent_finalize_into_coach_turn(self, 
        coach_turn_data: dict[str, object] | None,
        *,
        summary: object = None,
        next_step: object = None,
        blocker: object = None,
        resume_thread: object = None,
        decision: object = None,
        teaching_note: object = None,
        confidence: object = None,
        evidence: object = None,
    ) -> dict[str, object] | None:
        if not isinstance(coach_turn_data, dict):
            return coach_turn_data

        normalized_summary = str(summary or "").strip()
        normalized_next_step = strip_visible_next_step_prefix(next_step)
        normalized_blocker = str(blocker or "").strip()
        normalized_resume_thread = str(resume_thread or "").strip()
        normalized_decision = str(decision or "").strip()
        normalized_teaching_note = str(teaching_note or "").strip()
        normalized_confidence = str(confidence or "").strip()
        normalized_evidence: list[str] = []
        if isinstance(evidence, list):
            for item in evidence:
                text = str(item or "").strip()
                if text and text not in normalized_evidence:
                    normalized_evidence.append(text)
                if len(normalized_evidence) >= 4:
                    break
        if not any(
            (
                normalized_summary,
                normalized_next_step,
                normalized_blocker,
                normalized_resume_thread,
                normalized_decision,
                normalized_teaching_note,
                normalized_confidence,
                normalized_evidence,
            )
        ):
            return coach_turn_data

        merged = dict(coach_turn_data)
        context_payload = normalized_object_mapping(merged.get("coach_context")) or {}
        fresh_lane = str(context_payload.get("history_mode") or "").strip().lower() == "fresh_lane"
        active_thread = (
            {} if fresh_lane else normalized_object_mapping(context_payload.get("active_thread")) or {}
        )

        scenario = (
            str(merged.get("scenario") or "").strip()
            or str(context_payload.get("scenario") or "").strip()
            or str(active_thread.get("scenario") or "").strip()
        )
        focus_area = (
            str(active_thread.get("focus_area") or "").strip()
            or str(context_payload.get("coach_anchor") or "").strip()
            or str(context_payload.get("current_focus") or "").strip()
            or str(context_payload.get("active_task") or "").strip()
            or str(context_payload.get("active_stage") or "").strip()
        )
        if scenario:
            active_thread["scenario"] = scenario
        if focus_area:
            active_thread["focus_area"] = focus_area
        suppress_review_signals = fresh_lane and not self.fresh_lane_keeps_review_signals(scenario)
        if fresh_lane:
            for stale_key in ("decision", "blocker", "teaching_note", "confidence", "resume_thread", "evidence"):
                context_payload.pop(stale_key, None)
        if suppress_review_signals:
            context_payload["review_rhythm"] = ""
            context_payload["review_queue_summary"] = ""
            context_payload["due_reviews"] = []
            context_payload["due_review_count"] = 0
        if normalized_summary:
            active_thread["summary"] = normalized_summary
            context_payload["summary"] = normalized_summary
        if normalized_next_step:
            active_thread["next_step"] = normalized_next_step
            context_payload["next_step"] = normalized_next_step
        if normalized_blocker:
            active_thread["blocker"] = normalized_blocker
            context_payload["blocker"] = normalized_blocker
        if normalized_resume_thread:
            context_payload["resume_thread"] = normalized_resume_thread
        if normalized_decision:
            active_thread["decision"] = normalized_decision
            context_payload["decision"] = normalized_decision
        if normalized_teaching_note:
            active_thread["teaching_note"] = normalized_teaching_note
            context_payload["teaching_note"] = normalized_teaching_note
        if normalized_confidence:
            active_thread["confidence"] = normalized_confidence
            context_payload["confidence"] = normalized_confidence
        if normalized_evidence:
            active_thread["evidence"] = normalized_evidence
            context_payload["evidence"] = normalized_evidence
        if active_thread:
            context_payload["active_thread"] = active_thread
        if context_payload:
            merged["coach_context"] = context_payload

        turn_summary = merged.get("coach_turn")
        if isinstance(turn_summary, CoachTurnSummary):
            summary_update: dict[str, object] = {}
            if fresh_lane:
                summary_update.update(
                    {
                        "teaching_observation": "",
                        "resume_thread": "",
                        "decision": "",
                        "blocker": "",
                        "teaching_note": "",
                        "confidence": "",
                        "evidence": [],
                        "decision_reason": "",
                    }
                )
            if suppress_review_signals:
                summary_update.update(
                    {
                        "review_rhythm": "",
                        "due_review_count": 0,
                        "review_queue_summary": "",
                    }
                )
            if normalized_summary:
                summary_update["summary"] = normalized_summary
            if normalized_next_step:
                summary_update["next_step"] = normalized_next_step
            if normalized_resume_thread:
                summary_update["resume_thread"] = normalized_resume_thread
            if normalized_decision:
                summary_update["decision"] = normalized_decision
            if normalized_blocker:
                summary_update["blocker"] = normalized_blocker
            if normalized_teaching_note:
                summary_update["teaching_note"] = normalized_teaching_note
            if normalized_confidence:
                summary_update["confidence"] = normalized_confidence
            if normalized_evidence:
                summary_update["evidence"] = normalized_evidence
            if summary_update:
                merged["coach_turn"] = turn_summary.model_copy(update=summary_update)

        return merged

    def build_assistant_metadata(self, 
        request: TurnRequest | SessionMessageRequest,
        artifacts: dict[str, object],
        snapshot: WorkbenchSnapshot,
        summary: str | None = None,
        coach_turn: dict[str, object] | None = None,
        agent_meta: dict[str, object] | None = None,
        attachment_delivery: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response_language = request.response_language
        metadata: dict[str, object] = {
            "intent": request.intent if isinstance(request, TurnRequest) else "coach",
            "response_language": response_language or ("zh-CN" if prefers_chinese(response_language) else "en-US"),
        }
        if request.active_view:
            metadata["active_view"] = request.active_view
        if request.resource_ids:
            metadata["resource_ids"] = self.request_resource_ids(request)
        artifact_entries: list[dict[str, object]] = []
        for kind, artifact in artifacts.items():
            if isinstance(artifact, dict):
                title = artifact.get("title") or artifact.get("summary") or kind
                artifact_entry: dict[str, object] = {"kind": kind, "title": str(title)}
                if artifact.get("summary"):
                    artifact_entry["summary"] = str(artifact["summary"])
                if artifact.get("content"):
                    artifact_entry["content"] = str(artifact["content"])
                if artifact.get("recommended_action"):
                    artifact_entry["recommended_action"] = str(artifact["recommended_action"])
                if artifact.get("rationale"):
                    artifact_entry["rationale"] = str(artifact["rationale"])
                if artifact.get("focus_area"):
                    artifact_entry["focus_area"] = str(artifact["focus_area"])
                if isinstance(artifact.get("verification"), list):
                    artifact_entry["verification"] = [str(item) for item in artifact["verification"][:3]]
                if kind == "task":
                    constraints = artifact.get("constraints")
                    outputs = artifact.get("outputs") or artifact.get("verification_strategy")
                    if isinstance(constraints, list):
                        artifact_entry["bullets"] = [str(item) for item in constraints[:3]]
                    if isinstance(outputs, list):
                        artifact_entry["summary"] = ", ".join(str(item) for item in outputs[:2])
                elif kind == "plan":
                    phases = artifact.get("phases") or artifact.get("stages")
                    if isinstance(phases, list):
                        artifact_entry["summary"] = localized_text(
                            f"{len(phases)} stages",
                            "",
                            response_language,
                        )
                        artifact_entry["bullets"] = [
                            str((phase or {}).get("title", "")) for phase in phases[:3] if isinstance(phase, dict)
                        ]
                elif kind == "evaluation":
                    summary_text = artifact.get("summary")
                    next_step = artifact.get("next_step")
                    if summary_text:
                        artifact_entry["summary"] = str(summary_text)
                    if next_step:
                        artifact_entry["bullets"] = [str(next_step)]
                elif isinstance(artifact.get("bullets"), list):
                    artifact_entry["bullets"] = [str(item) for item in artifact["bullets"][:3]]
                if isinstance(artifact.get("metadata"), dict):
                    artifact_entry["metadata"] = artifact["metadata"]
                artifact_entries.append(artifact_entry)
        finalize_coach_turn_summary = (
            coach_turn.get("coach_turn") if isinstance(coach_turn, dict) else None
        )
        agent_finalize_artifact = self.build_agent_finalize_artifact(
            agent_meta,
            requires_confirmation=bool(
                isinstance(finalize_coach_turn_summary, CoachTurnSummary)
                and finalize_coach_turn_summary.requires_confirmation
            ),
        )
        if agent_finalize_artifact and not any(
            isinstance(entry, dict)
            and entry.get("kind") == "next_step"
            and (
                entry.get("title") == agent_finalize_artifact.get("title")
                or entry.get("summary") == agent_finalize_artifact.get("summary")
            )
            for entry in artifact_entries
        ):
            artifact_entries.append(agent_finalize_artifact)
        if artifact_entries:
            metadata["artifacts"] = artifact_entries
        if summary:
            metadata["context_note"] = summary
        effective_attachment_delivery = (
            attachment_delivery
            if isinstance(attachment_delivery, dict)
            else agent_meta
            if isinstance(agent_meta, dict)
            else None
        )
        self.apply_attachment_delivery_metadata(metadata, effective_attachment_delivery)
        support = self.build_message_support(request, coach_turn, effective_attachment_delivery)
        if support:
            metadata["support"] = support
        structured_signal = self.structured_plan_progress_signal(
            snapshot=snapshot,
            coach_turn=coach_turn,
        )
        verify_method_value = structured_signal.get("verify_method")
        verify_method = (
            [str(item).strip() for item in verify_method_value if str(item).strip()]
            if isinstance(verify_method_value, list)
            else None
        )
        next_step_hint = self.build_next_step_hint(
            snapshot=snapshot,
            response_language=response_language,
            current_step=str(structured_signal.get("current_step") or "").strip(),
            why_now=str(structured_signal.get("why_now") or "").strip(),
            verify_method=verify_method,
            coach_turn=coach_turn,
            agent_meta=agent_meta,
        )
        if next_step_hint:
            metadata["next_step_hint"] = next_step_hint
        coach_visible_status = coach_support.build_coach_visible_status(self.coach_support_deps,
            agent_meta,
            response_language=response_language,
        )
        agent_parts = self.build_agent_message_parts(
            agent_meta,
            response_language=response_language,
        )
        if coach_visible_status:
            metadata["coach_visible_status"] = coach_visible_status
            agent_parts = [coach_visible_status, *agent_parts]
        if agent_parts:
            metadata["parts"] = agent_parts
        if coach_turn:
            coach_context = coach_turn.get("coach_context")
            if isinstance(coach_context, dict):
                external_references = coach_context.get("external_references")
                if isinstance(external_references, list) and external_references:
                    composer_intent = coach_context.get("resource_composer_intent")
                    analysis = isinstance(composer_intent, dict) and composer_intent.get("mode") == "analyze"
                    metadata["external_references"] = external_references[:4 if analysis else 3]
                else:
                    resource_fragments = coach_context.get("resource_fragments")
                    if isinstance(resource_fragments, list) and resource_fragments:
                        metadata["external_references"] = resource_fragments[:3]
                    else:
                        background_references = coach_context.get("background_references")
                        recent_background_findings = coach_context.get("recent_background_findings")
                        if isinstance(background_references, list) and background_references:
                            metadata["external_references"] = background_references[:3]
                        elif isinstance(recent_background_findings, list) and recent_background_findings:
                            metadata["external_references"] = recent_background_findings[:3]
            turn_summary = coach_turn.get("coach_turn")
            coach_turn_metadata: dict[str, object] = {
                "scenario": str(coach_turn.get("scenario", "general")),
                "learner_signal": str(coach_turn.get("learner_signal", "steady")),
            }
            metadata["coach_turn"] = coach_turn_metadata
            if isinstance(turn_summary, CoachTurnSummary):
                coach_turn_metadata["summary"] = turn_summary.summary
                coach_turn_metadata["next_step"] = strip_visible_next_step_prefix(
                    turn_summary.next_step
                )
                coach_turn_metadata["review_queue_summary"] = turn_summary.review_queue_summary
                coach_turn_metadata["teaching_mode"] = turn_summary.teaching_mode
                coach_turn_metadata["emotional_tone"] = turn_summary.emotional_tone
                coach_turn_metadata["review_rhythm"] = turn_summary.review_rhythm
                coach_turn_metadata["teaching_observation"] = turn_summary.teaching_observation
                coach_turn_metadata["decision_reason"] = turn_summary.decision_reason
                coach_turn_metadata["decision"] = turn_summary.decision
                coach_turn_metadata["blocker"] = turn_summary.blocker
                coach_turn_metadata["teaching_note"] = turn_summary.teaching_note
                coach_turn_metadata["confidence"] = turn_summary.confidence
                coach_turn_metadata["evidence"] = turn_summary.evidence
                coach_turn_metadata["tone"] = turn_summary.tone
                coach_turn_metadata["verbosity_bias"] = turn_summary.verbosity_bias
            if isinstance(coach_context, dict):
                metadata["coach_focus"] = {
                    "current_focus": coach_context.get("current_focus"),
                    "review_rhythm": coach_context.get("review_rhythm"),
                    "next_step": coach_context.get("next_step"),
                    "next_step_hint": next_step_hint or coach_context.get("next_step_hint"),
                    "scenario": coach_context.get("scenario"),
                    "relationship_stage": coach_context.get("relationship_stage"),
                    "first_turn_priority": coach_context.get("first_turn_priority"),
                    "strategy_preference_summary": coach_context.get("strategy_preference_summary"),
                    "continuity_summary": coach_context.get("continuity_summary"),
                    "recent_teaching_signals": coach_context.get("recent_teaching_signals"),
                    "active_stage": coach_context.get("active_stage"),
                    "active_task": coach_context.get("active_task"),
                    "teaching_observations": coach_context.get("teaching_observations"),
                    "recent_wins": coach_context.get("recent_wins"),
                    "due_review_count": coach_context.get("due_review_count"),
                    "requested_resources": coach_context.get("requested_resources"),
                    "requested_resource_count": coach_context.get("requested_resource_count"),
                    "coach_defaults": coach_context.get("coach_defaults"),
                }
                if coach_context.get("pressure_blocks_live_object_mint") is True:
                    metadata["coach_focus"]["pressure_blocks_live_object_mint"] = True
                if coach_context.get("streak_blocks_live_object_mint") is True:
                    metadata["coach_focus"]["streak_blocks_live_object_mint"] = True
                if coach_context.get("closed_loop_return_blocks_task_mint") is True:
                    metadata["coach_focus"]["closed_loop_return_blocks_task_mint"] = True
                resume_thread = str(coach_context.get("resume_thread") or "").strip()
                if resume_thread:
                    coach_turn_metadata["resume_thread"] = resume_thread
        return metadata

    def agent_meta_coaching_state_update(self, 
        agent_meta: dict[str, object] | None,
        *,
        response_scenario: str,
    ) -> dict[str, object]:
        if not isinstance(agent_meta, dict):
            return {}
        stop_reason = str(agent_meta.get("stop_reason") or "").strip()
        if stop_reason not in {
            "coach_finalize",
            "empty_response",
            "formal_plan_commit_missing",
            "language_corruption",
            "language_corruption_recovered",
            *PROVIDER_REPLY_STOP_REASONS,
        }:
            return {}
        update: dict[str, object] = {
            "scenario": response_scenario or "general",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        for target_key, source_keys in {
            "summary": ("summary",),
            "next_step": ("next_step", "nextStep"),
            "resume_thread": ("resume_thread", "resumeThread"),
            "decision": ("decision",),
            "blocker": ("blocker",),
            "teaching_note": ("teaching_note", "teachingNote"),
            "confidence": ("confidence",),
        }.items():
            for source_key in source_keys:
                value = str(agent_meta.get(source_key) or "").strip()
                if value:
                    if target_key == "next_step":
                        value = strip_visible_next_step_prefix(value)
                    update[target_key] = value
                    break
        evidence: list[str] = []
        raw_evidence = agent_meta.get("evidence")
        if isinstance(raw_evidence, list):
            for item in raw_evidence:
                text = str(item or "").strip()
                if text and text not in evidence:
                    evidence.append(text)
                if len(evidence) >= 4:
                    break
        if evidence:
            update["evidence"] = evidence
        return {key: value for key, value in update.items() if value not in ("", [], None)}

    def apply_agent_meta_to_coaching_state(self, 
        snapshot: WorkbenchSnapshot,
        agent_meta: dict[str, object] | None,
        *,
        response_scenario: str,
    ) -> None:
        update = self.agent_meta_coaching_state_update(
            agent_meta,
            response_scenario=response_scenario,
        )
        if not update:
            return
        current_state = snapshot.coaching_state or CoachingState()
        snapshot.coaching_state = current_state.model_copy(update=update)
