"""Thread/lane continuation rules, pedagogy snapshot projections, plan progress, and evaluation loops."""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass

from ...core.models import (
    AffectState,
    CoachTurnSummary,
    EvaluateCurrentFileRequest,
    EvaluateSnippetRequest,
    EvaluationCheck,
    EvaluationReport,
    ImplementationGuide,
    LearnerState,
    LearningPlan,
    PlanStage,
    PrincipleNotes,
    ProjectAdaptationGuide,
    ProjectIdea,
    ProjectSourceSuggestion,
    ReviewQueueItem,
    TaskSpec,
    TeachingDecision,
    TeachingKnowledgeAsset,
    ToneDecision,
    UserProfile,
    WorkbenchSnapshot,
)
from ...llm.training_review_context import active_training_review
from ...memory.models import utc_now
from ...memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    coach_focus_runtime_from_snapshot,
    leftover_formal_plan_is_live_for_fill,
    live_language_detection_hint,
    live_plan_lane_copy,
    live_plan_refresh_step_why,
    live_plan_update_persist_chrome,
    live_task_clean_step_candidates,
    live_task_focus_area,
    live_task_training_concepts,
    live_training_lane_copy,
    select_plan_runtime_for_scope,
)
from ...training.reliability import busy_marker
from .. import coach_support
from .._helpers import (
    contains_cjk_text,
    localized_text,
    looks_like_mojibake_text,
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
from ..coach_text_sanitizer import (
    normalize_visible_coach_text,
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
from ..training_skill_evidence import record_executed_training_evidence
from ._base import RouterDomainBase


class PedagogyAndEvaluationDomainMixin(RouterDomainBase):
    """Thread/lane continuation rules, pedagogy snapshot projections, plan progress, and evaluation loops."""

    def active_thread_scenario_value(self, active_thread: object | None) -> str:
        if active_thread is None:
            return ""
        if isinstance(active_thread, dict):
            return str(active_thread.get("scenario") or "").strip()
        return str(getattr(active_thread, "scenario", "") or "").strip()

    def message_requests_lane_continuation(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        compact = re.sub(r"[\s\.,!?:;\"'(){}\[\]/\\_-]+", "", lowered)
        if compact in {
            "continue",
            "continueplease",
            "pleasecontinue",
            "goon",
            "keepgoing",
            "carryon",
            "whatnext",
            "nextstep",
            "继续",
            "请继续",
            "继续吧",
            "继续一下",
            "继续一会",
            "继续这条线",
            "继续这一条线",
            "继续这个",
            "继续这一轮",
            "继续当前主线",
            "接着",
            "接着来",
            "接下来",
            "然后呢",
            "下一步",
            "下一步呢",
            "再往下",
        }:
            return True
        if re.search(r"\bcontinue(?:\s+\w+){0,4}\s+(?:lane|thread)\b", lowered):
            return True
        return any(
            marker in lowered
            for marker in (
                "same lane",
                "same thread",
                "current lane",
                "current thread",
                "live thread",
                "last step",
                "do not restart",
                "don't restart",
                "continue from the",
                "continue from there",
                "continue from that",
                "continue from last",
                "continue from the last",
                "continue from same",
                "continue the lane",
                "continue this lane",
                "pick up from there",
                "pick up from the",
                "stay on the same",
                "stay on that same",
                "keep this going",
                "keep it narrow",
            )
        )

    def message_is_relationship_reentry(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        compact = re.sub(r"[\s\.,!?:;\"'(){}\[\]/\\_\-，。！？、：；]+", "", lowered)
        return compact in {
            "hello",
            "hi",
            "hey",
            "hellotrainer",
            "hitrainer",
            "goodmorning",
            "goodafternoon",
            "goodevening",
            "你好",
            "您好",
            "嗨",
            "哈喽",
            "早上好",
            "下午好",
            "晚上好",
        }

    def message_keeps_existing_thread(self, message: str | None) -> bool:
        return self.message_requests_lane_continuation(message) or self.message_is_relationship_reentry(message)

    def normalize_active_view_name(self, active_view: str | None) -> str:
        normalized = str(active_view or "").strip().lower()
        return (
            normalized
            if normalized in {"coach", "plan", "resources", "training", "progress", "settings"}
            else ""
        )

    def active_view_owns_turn_lane(self, active_view: str | None) -> bool:
        return self.normalize_active_view_name(active_view) in {
            "plan",
            "resources",
            "training",
            "settings",
        }

    def extract_lane_continuation_step(self, text: str | None) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return ""
        lower_normalized = normalized.lower()
        case_insensitive_markers = (
            "if you stay here,",
            "if you continue here,",
            "next:",
        )
        for marker in case_insensitive_markers:
            index = lower_normalized.find(marker)
            if index >= 0:
                candidate = normalized[index + len(marker) :].strip(" ,:;\uFF0C\u3002\uFF1A")
                if candidate:
                    return candidate
        markers = (
            "\u5982\u679c\u7ee7\u7eed\u7559\u5728\u8fd9\u91cc\uff0c\u8bf7",
            "\u5982\u679c\u4f60\u7ee7\u7eed\u7559\u5728\u8fd9\u91cc\uff0c",
            "\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a",
            "\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\uff0c\u4e0b\u4e00\u6b65\uff1a",
            "\u7ee7\u7eed\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a",
            "\u7ee7\u7eed\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u63a8\u8fdb\uff0c\u4e0b\u4e00\u6b65\uff1a",
            "\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u7ee7\u7eed\u3002\u4e0b\u4e00\u6b65\uff1a",
            "\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u7ee7\u7eed\uff0c\u4e0b\u4e00\u6b65\uff1a",
            "\u4e0b\u4e00\u6b65\uff1a",
        )
        for marker in markers:
            index = normalized.find(marker)
            if index >= 0:
                candidate = normalized[index + len(marker) :].strip(" ,:;\uFF0C\u3002\uFF1A")
                if candidate:
                    return candidate
        lowered = normalized.lower()
        if (
            "switch provider or gateway" in lowered
            or "\u5148\u5207\u6362 provider \u6216 gateway" in normalized
            or "\u5148\u5207\u6362 provider / gateway" in normalized
        ):
            return ""
        return normalized

    def continuation_step_needs_local_repair(self, text: str | None) -> bool:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return True
        lowered = normalized.casefold()
        provider_blocker_fragments = (
            "switch provider or gateway",
            "continue this debug lesson in english first",
            "continue this lesson in english first",
            "continue this coaching turn in english first",
            "先切换 provider",
            "先用 english",
            "先用 english 完成",
            "先用 english 继续",
            "回来继续 coach thread",
            "继续 coach thread",
        )
        if any(fragment in lowered or fragment in normalized for fragment in provider_blocker_fragments):
            return True
        extracted = self.extract_lane_continuation_step(normalized)
        if not extracted:
            return True
        return extracted != normalized

    def generic_guided_review_fallback_needs_repair(self, text: str | None) -> bool:
        normalized = " ".join(str(text or "").split()).strip().lower()
        if not normalized:
            return False
        generic_fallbacks = (
            "ignore secondary issues and only name the first fix plus one verification.",
            "ignore secondary issues and only describe the first fix plus one verification.",
        )
        return any(fragment in normalized for fragment in generic_fallbacks)

    def resolve_local_continuation_step(self, 
        *,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        fallback_next_step: str,
    ) -> str:
        coach_context = coach_turn.get("coach_context")
        coach_active_thread = (
            coach_context.get("active_thread")
            if isinstance(coach_context, dict) and isinstance(coach_context.get("active_thread"), dict)
            else None
        )
        candidates: list[object] = []
        if snapshot.memory.active_thread:
            candidates.append(snapshot.memory.active_thread.next_step)
        if coach_active_thread is not None:
            candidates.append(coach_active_thread.get("next_step"))
        if snapshot.coaching_state:
            candidates.extend(
                [
                    snapshot.coaching_state.next_step,
                    snapshot.coaching_state.resume_thread,
                ]
            )
        candidates.extend([coach_turn.get("next_step"), fallback_next_step])
        for candidate in candidates:
            resolved = self.extract_lane_continuation_step(str(candidate or "").strip())
            if resolved and not self.continuation_step_needs_local_repair(resolved):
                return resolved
        return ""

    def local_continuation_step_for_scenario(self, 
        scenario: str,
        response_language: str | None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return localized_text(
                "Return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label.",
                "\u5728\u4f60\u5f53\u524d\u7684 VS Code \u7a97\u53e3\u91cc\uff0c\u5e26\u56de\u4e00\u4e2a\u80fd\u8bc1\u660e\u5de5\u4f5c\u533a\u843d\u70b9\u7684\u771f\u5b9e\u4fe1\u53f7\uff0c\u6bd4\u5982 Explorer \u91cc\u7684\u8def\u5f84\u3001\u7ec8\u7aef\u91cc\u7684 `pwd`\uff0c\u6216\u8005\u5de6\u4e0b\u89d2\u7684 remote host \u6807\u7b7e\u3002",
                response_language,
            )
        if normalized == "debug_loop":
            return localized_text(
                "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect.",
                "告诉我你会先停在哪个断点，以及准备先检查哪一个值、分支或 stack frame。",
                response_language,
            )
        if normalized == "function_guidance":
            return localized_text(
                "Give me the function name and one call site you can open right now.",
                "给我函数名，以及你现在就能打开的一个 call site。",
                response_language,
            )
        if normalized == "project_adaptation":
            return localized_text(
                "Tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "告诉我什么必须保持稳定、什么必须变化，以及你想先适配的第一条边界。",
                response_language,
            )
        return ""

    def inherit_active_thread_scenario_for_continuation(self, 
        resolved_scenario: str,
        *,
        message: str | None,
        active_thread: object | None,
    ) -> str:
        if resolved_scenario != "general":
            return resolved_scenario
        if not self.message_keeps_existing_thread(message):
            return resolved_scenario
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        if active_thread_scenario and active_thread_scenario != "general":
            return active_thread_scenario
        return resolved_scenario

    def preserve_requested_domain_scenario(self, 
        *,
        requested_scenario: str,
        decided_scenario: str,
    ) -> str:
        first_class_domain_scenarios = {
            "remote_workspace",
            "debug_loop",
            "function_guidance",
        }
        generic_teaching_scenarios = {
            "general",
            "review",
            "idea_implementation",
            "project_idea",
            "principle",
            "plan",
            "task",
            "next_task",
            "guided",
            "concept_teaching",
            "planning",
            "engineering_challenge",
            "principle_explanation",
        }
        if (
            requested_scenario in first_class_domain_scenarios
            and decided_scenario not in first_class_domain_scenarios
            and decided_scenario in generic_teaching_scenarios
        ):
            return requested_scenario
        if requested_scenario not in {
            "remote_workspace",
            "debug_loop",
            "function_guidance",
            "idea_implementation",
            "project_adaptation",
            "project_sourcing",
            "project_idea",
            "principle",
        }:
            return decided_scenario
        if decided_scenario in {requested_scenario, "onboarding"}:
            return decided_scenario
        if requested_scenario == "principle" and decided_scenario == "review":
            return decided_scenario
        if decided_scenario in {"general", "review"}:
            return requested_scenario
        return decided_scenario

    def should_preserve_active_thread_for_scenario(self, 
        resolved_scenario: str,
        active_thread: object | None,
    ) -> bool:
        if active_thread is None:
            return False
        active_thread_scenario = ""
        if isinstance(active_thread, dict):
            active_thread_scenario = str(active_thread.get("scenario") or "").strip()
        else:
            active_thread_scenario = str(getattr(active_thread, "scenario", "") or "").strip()
        if resolved_scenario == "general":
            return True
        if not active_thread_scenario:
            return True
        return active_thread_scenario == resolved_scenario

    def active_view_coaching_lane_override(self, 
        *,
        active_view: str | None,
        snapshot: WorkbenchSnapshot,
        response_language: str | None,
    ) -> tuple[str, str] | None:
        normalized = self.normalize_active_view_name(active_view)
        if not normalized or normalized == "coach":
            return None

        if normalized == "plan":
            plan = snapshot.plan
            active_stage = (
                next(
                    (
                        stage
                        for stage in plan.stages
                        if stage.id == plan.current_stage_id or stage.status == "active"
                    ),
                    plan.stages[0] if plan.stages else None,
                )
                if plan is not None
                else None
            )
            lane = live_plan_lane_copy(
                plan=plan,
                runtime=coach_focus_runtime_from_snapshot(snapshot),
                existing=coach_focus_runtime_from_snapshot(snapshot),
                stage_title=str(active_stage.title or "").strip() if active_stage else "",
            )
            stage_title = lane["label"]
            summary = localized_text(lane["en"], lane["zh"], response_language)
            next_step = localized_text(
                (
                    "Explain why this stage is now, what counts as done, and whether the current result is ready to become formal evidence."
                    if stage_title
                    else "Turn the goal into a formal plan with stage, why now, verify method, and the next smallest step."
                ),
                (
                    "先说明这一阶段为什么是现在、怎样算完成，以及当前结果是否已经够格变成正式 evidence。"
                    if stage_title
                    else "先把目标压成正式计划，至少说清阶段、why now、verify method 和下一步。"
                ),
                response_language,
            )
            return summary, next_step

        if normalized == "resources":
            summary = localized_text(
                "Current lane: stay inside Resources and decide the next material to open, download, or reorganize.",
                "当前先留在 Resources 这条主线上，决定下一份该打开、下载或整理的资料。",
                response_language,
            )
            next_step = localized_text(
                "Locate the most relevant material, decide whether it should be opened or downloaded next, then say where it belongs under sources, knowledge, or cards.",
                "先定位最相关的资料，判断它下一步该打开还是下载，再说明它应当归到 sources、knowledge 还是 cards。",
                response_language,
            )
            return summary, next_step

        if normalized == "training":
            review = active_training_review(snapshot.memory, normalized)
            if review is not None:
                summary = localized_text(
                    f"Current recall review: {review.title or review.focus_area}.",
                    f"当前复习：{review.title or review.focus_area}。",
                    response_language,
                )
                next_step = review.guardrail or review.next_self_implementation_rule
                return summary, next_step
            active_training_routing = getattr(snapshot.memory, "active_training_card_routing", None)
            active_card = (
                active_training_routing.selected_card
                if active_training_routing and active_training_routing.selected_card is not None
                else None
            )
            leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
            lane = live_training_lane_copy(
                plan=snapshot.plan,
                task=snapshot.current_task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=snapshot.current_task.title if snapshot.current_task else "",
                card_title=str(active_card.title or "").strip() if active_card else "",
            )
            summary = localized_text(lane["en"], lane["zh"], response_language)
            next_step = localized_text(
                (
                    "Stay inside Learn -> Try -> Verify -> Reflect -> Return. "
                    "Study the current card first, then answer the prompt or record one visible verification result."
                ),
                (
                    "先留在 Learn -> Try -> Verify -> Reflect -> Return 这条训练闭环里。"
                    "先学当前卡片，再回答题目或记录一条可见的验证结果。"
                ),
                response_language,
            )
            return summary, next_step

        if normalized == "settings":
            summary = localized_text(
                "Current lane: stay inside Settings and verify provider, model, protocol, and runtime truth.",
                "当前先留在 Settings 这条主线上，核对 provider、model、protocol 和 runtime 的真实状态。",
                response_language,
            )
            next_step = localized_text(
                "Check what is truly available now, what is degraded, and which exact configuration detail must be fixed before resuming teaching.",
                "先核对现在真正可用的能力、哪些地方处于降级状态，以及恢复教学前必须修好的那一项配置。",
                response_language,
            )
            return summary, next_step

        return None

    def should_preserve_active_thread_for_turn(self, 
        resolved_scenario: str,
        active_thread: object | None,
        *,
        message: str | None = None,
        grounding_context: dict[str, object] | None = None,
        active_view: str | None = None,
    ) -> bool:
        if self.resource_grounding_turn_prefers_fresh_lane(message, grounding_context):
            return False
        if self.active_view_owns_turn_lane(active_view):
            return False
        if resolved_scenario != "general" or message is None:
            return self.should_preserve_active_thread_for_scenario(
                resolved_scenario,
                active_thread,
            )
        if active_thread is None:
            return False
        return self.message_keeps_existing_thread(message)

    def should_preserve_relationship_continuity_for_turn(self, 
        memory,
        *,
        message: str | None = None,
        grounding_context: dict[str, object] | None = None,
        active_view: str | None = None,
    ) -> bool:
        if not self.message_keeps_existing_thread(message):
            return False
        if self.resource_grounding_turn_prefers_fresh_lane(message, grounding_context):
            return False
        if self.active_view_owns_turn_lane(active_view):
            return False
        return bool(
            getattr(memory, "active_thread", None)
            or getattr(memory, "learning_outcomes", [])
        )

    def summarize_review_queue(self, 
        due_reviews: list[ReviewQueueItem],
        response_language: str | None,
    ) -> str:
        if not due_reviews:
            return localized_text(
                "No immediate review item is due yet.",
                "暂时还没有必须立刻回看的复习项。",
                response_language,
            )
        if len(due_reviews) == 1:
            return localized_text(
                "One follow-up review is ready or due soon.",
                "有 1 个后续复习点已经就绪或即将到期。",
                response_language,
            )
        return localized_text(
            f"{len(due_reviews)} follow-up reviews are ready or due soon.",
            f"有 {len(due_reviews)} 个后续复习点已经就绪或即将到期。",
            response_language,
        )

    def apply_pedagogy_snapshot(self, 
        *,
        snapshot: WorkbenchSnapshot,
        learner_state: LearnerState | None,
        teaching_decision: TeachingDecision | None,
        affect_state: AffectState | None,
        tone_decision: ToneDecision | None,
        implementation_guide: ImplementationGuide | None = None,
        project_ideas: list[ProjectIdea] | None = None,
        project_adaptation_guide: ProjectAdaptationGuide | None = None,
        project_sources: list[ProjectSourceSuggestion] | None = None,
        principle_notes: PrincipleNotes | None = None,
        selected_teaching_assets: list[TeachingKnowledgeAsset] | None = None,
        exercise_prompt: dict[str, object] | None = None,
    ) -> None:
        snapshot.learner_state = learner_state
        snapshot.teaching_decision = teaching_decision
        snapshot.affect_state = affect_state
        snapshot.tone_decision = tone_decision
        snapshot.implementation_guide = implementation_guide
        snapshot.project_ideas = list(project_ideas or [])
        snapshot.project_adaptation_guide = project_adaptation_guide
        snapshot.project_sources = list(project_sources or [])
        snapshot.principle_notes = principle_notes
        snapshot.selected_teaching_assets = list(selected_teaching_assets or [])
        snapshot.exercise_prompt = dict(exercise_prompt) if exercise_prompt is not None else None
        workspace = dict(snapshot.memory.workspace) if isinstance(snapshot.memory.workspace, dict) else {}
        if exercise_prompt is not None:
            workspace["exercise_prompt"] = dict(exercise_prompt)
        else:
            workspace.pop("exercise_prompt", None)
        snapshot.memory.workspace = workspace

    def model_learner_state(self, payload: object) -> LearnerState | None:
        if payload is None:
            return None
        if isinstance(payload, LearnerState):
            return payload
        if is_dataclass(payload) and not isinstance(payload, type):
            payload = asdict(payload)
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            learner_signal = str(payload.get("learner_signal", "steady") or "steady")
            hint_depth = str(payload.get("preferred_hint_depth", "medium") or "medium")
            normalized_hint_depth = (
                "small"
                if hint_depth in {"guided", "small"}
                else "medium"
                if hint_depth in {"balanced", "medium"}
                else "expanded"
                if hint_depth in {"direct", "expanded"}
                else "medium"
            )
            return LearnerState.model_validate(
                {
                    "current_confidence": float(payload.get("current_confidence", 0.5) or 0.5),
                    "frustration_level": float(payload.get("frustration_level", 0.0) or 0.0),
                    "attempt_count_recent": int(payload.get("attempt_count_recent", 0) or 0),
                    "needs_rescue": bool(payload.get("needs_rescue", False)),
                    "needs_review": bool(payload.get("needs_review", False)),
                    "preferred_hint_depth": normalized_hint_depth,
                    "learner_signal": learner_signal
                    if learner_signal in {"steady", "blocked", "uncertain", "curious"}
                    else "steady",
                    "active_focus": str(payload.get("active_focus", "") or ""),
                    "evidence": [str(item) for item in payload.get("evidence", []) if str(item).strip()],
                }
            )
        return None

    def model_teaching_decision(self, payload: object) -> TeachingDecision | None:
        if payload is None:
            return None
        if isinstance(payload, TeachingDecision):
            return payload
        if is_dataclass(payload) and not isinstance(payload, type):
            payload = asdict(payload)
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            mode = str(payload.get("mode", "guided") or "guided")
            return TeachingDecision.model_validate(
                {
                    "mode": mode
                    if mode
                    in {
                        "onboarding",
                        "idea_implementation",
                        "project_idea_mining",
                        "project_adaptation",
                        "planning",
                        "concept_teaching",
                        "engineering_challenge",
                        "review_reflection",
                        "project_sourcing",
                        "principle_explanation",
                        "guided",
                        "scaffold",
                        "balanced",
                        "direct_rescue",
                        "challenge",
                        "reflection",
                    }
                    else "guided",
                    "reason": str(payload.get("reason", "") or ""),
                    "primary_goal": str(payload.get("primary_goal", "") or ""),
                    "lesson_shape": str(payload.get("lesson_shape", "") or ""),
                    "exercise_shape": str(payload.get("exercise_shape", "") or ""),
                    "teaching_strategy": str(payload.get("teaching_strategy", "") or ""),
                    "closing_move": str(payload.get("closing_move", "") or ""),
                    "artifact_priority": [
                        str(item) for item in payload.get("artifact_priority", []) if str(item).strip()
                    ],
                    "should_end_with_question": bool(payload.get("should_end_with_question", False)),
                    "should_generate_exercise": bool(payload.get("should_generate_exercise", False)),
                    "should_reveal_code": bool(payload.get("should_reveal_code", False)),
                    "should_produce_plan_artifact": bool(
                        payload.get("should_produce_plan_artifact", False)
                    ),
                    "should_trigger_deep_analysis": bool(
                        payload.get("should_trigger_deep_analysis", False)
                    ),
                    "should_focus_on_implementation_steps": bool(
                        payload.get("should_focus_on_implementation_steps", True)
                    ),
                    "turn_mode": str(payload.get("turn_mode", "") or ""),
                    "turn_source": str(payload.get("turn_source", "") or ""),
                    "turn_confidence": str(payload.get("turn_confidence", "") or ""),
                    "turn_allow_question": bool(payload.get("turn_allow_question", True)),
                    "turn_allow_formal_task": bool(payload.get("turn_allow_formal_task", False)),
                    "turn_allow_formal_plan": bool(payload.get("turn_allow_formal_plan", False)),
                    "turn_allow_review": bool(payload.get("turn_allow_review", False)),
                    "turn_may_interrupt": bool(payload.get("turn_may_interrupt", False)),
                    "tone_profile": str(payload.get("tone_profile", "steady") or "steady"),
                    "focus_area": str(
                        payload.get("focus_area") or payload.get("focusArea") or ""
                    ),
                }
            )
        return None

    def model_affect_state(self, payload: object) -> AffectState | None:
        if payload is None:
            return None
        if isinstance(payload, AffectState):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            urgency = str(payload.get("urgency_level", "medium") or "medium")
            return AffectState.model_validate(
                {
                    "frustration_level": float(payload.get("frustration_level", 0.0) or 0.0),
                    "confidence_level": float(payload.get("confidence_level", 0.5) or 0.5),
                    "momentum_level": float(payload.get("momentum_level", 0.5) or 0.5),
                    "needs_reassurance": bool(payload.get("needs_reassurance", False)),
                    "urgency_level": urgency if urgency in {"low", "medium", "high"} else "medium",
                    "recovery_signal": (
                        str(payload.get("recovery_signal", "steady") or "steady")
                        if str(payload.get("recovery_signal", "steady") or "steady")
                        in {"steady", "recovering", "fragile", "overloaded"}
                        else "steady"
                    ),
                }
            )
        return None

    def model_tone_decision(self, payload: object) -> ToneDecision | None:
        if payload is None:
            return None
        if isinstance(payload, ToneDecision):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            tone = str(payload.get("tone", "steady") or "steady")
            verbosity = str(payload.get("verbosity_bias", "medium") or "medium")
            return ToneDecision.model_validate(
                {
                    "tone": tone
                    if tone in {"steady", "encouraging", "concise_rescue", "reflective"}
                    else "steady",
                    "verbosity_bias": verbosity
                    if verbosity in {"short", "medium", "expanded"}
                    else "medium",
                    "acknowledge_progress": bool(payload.get("acknowledge_progress", False)),
                    "avoid_overwhelm": bool(payload.get("avoid_overwhelm", False)),
                }
            )
        return None

    def model_implementation_guide(self, payload: object) -> ImplementationGuide | None:
        if payload is None:
            return None
        if isinstance(payload, ImplementationGuide):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            return ImplementationGuide(
                idea_summary=str(payload.get("idea_summary", "") or ""),
                scope_boundary=str(payload.get("scope_boundary", "") or ""),
                mvp_definition=str(payload.get("mvp_definition", "") or ""),
                current_step=str(payload.get("current_step", "") or ""),
                next_steps=[str(item) for item in payload.get("next_steps", []) if str(item).strip()],
                validation_strategy=[
                    str(item) for item in payload.get("validation_strategy", []) if str(item).strip()
                ],
                open_questions=[str(item) for item in payload.get("open_questions", []) if str(item).strip()],
                codebase_entry_points=[
                    str(item) for item in payload.get("codebase_entry_points", []) if str(item).strip()
                ],
                risk_notes=[str(item) for item in payload.get("risk_notes", []) if str(item).strip()],
                teaching_goal=str(payload.get("teaching_goal", "") or ""),
                success_signal=str(payload.get("success_signal", "") or ""),
                fallback_step=str(payload.get("fallback_step", "") or ""),
            )
        return None

    def model_project_adaptation_guide(self, payload: object) -> ProjectAdaptationGuide | None:
        if payload is None:
            return None
        if isinstance(payload, ProjectAdaptationGuide):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            return ProjectAdaptationGuide(
                target_outcome=str(payload.get("target_outcome", "") or ""),
                current_constraints=[
                    str(item) for item in payload.get("current_constraints", []) if str(item).strip()
                ],
                affected_areas=[str(item) for item in payload.get("affected_areas", []) if str(item).strip()],
                preserve_areas=[str(item) for item in payload.get("preserve_areas", []) if str(item).strip()],
                first_migration_step=str(payload.get("first_migration_step", "") or ""),
                migration_sequence=[str(item) for item in payload.get("migration_sequence", []) if str(item).strip()],
                validation_checkpoints=[
                    str(item) for item in payload.get("validation_checkpoints", []) if str(item).strip()
                ],
                rollback_notes=[str(item) for item in payload.get("rollback_notes", []) if str(item).strip()],
            )
        return None

    def model_project_ideas(self, payload: object) -> list[ProjectIdea]:
        if not isinstance(payload, list):
            return []
        ideas: list[ProjectIdea] = []
        for item in payload:
            if hasattr(item, "__dict__"):
                item = item.__dict__
            if not isinstance(item, dict):
                continue
            idea_kind = str(item.get("idea_kind", "feature") or "feature")
            difficulty = str(item.get("difficulty", "small") or "small")
            ideas.append(
                ProjectIdea.model_validate(
                    {
                        "id": str(item.get("id", "") or ""),
                        "title": str(item.get("title", "") or ""),
                        "summary": str(item.get("summary", "") or ""),
                        "source_area": str(item.get("source_area", "") or ""),
                        "idea_kind": idea_kind
                        if idea_kind
                        in {"feature", "refactor", "test", "architecture", "developer_experience"}
                        else "feature",
                        "learning_value": str(item.get("learning_value", "") or ""),
                        "engineering_value": str(item.get("engineering_value", "") or ""),
                        "difficulty": difficulty if difficulty in {"small", "medium", "stretch"} else "small",
                        "suggested_scope": str(item.get("suggested_scope", "") or ""),
                        "first_step": str(item.get("first_step", "") or ""),
                        "acceptance_signals": [
                            str(signal)
                            for signal in item.get("acceptance_signals", [])
                            if str(signal).strip()
                        ],
                        "why_now": str(item.get("why_now", "") or ""),
                    }
                )
            )
        return ideas

    def model_project_sources(self, payload: object) -> list[ProjectSourceSuggestion]:
        if not isinstance(payload, list):
            return []

        def visible_text(value: object) -> str:
            return normalize_visible_coach_text(value) or str(value or "").strip()

        suggestions: list[ProjectSourceSuggestion] = []
        for item in payload:
            if hasattr(item, "__dict__"):
                item = item.__dict__
            if not isinstance(item, dict):
                continue
            source_kind = str(item.get("source_kind", "reference_repo") or "reference_repo")
            suggestions.append(
                ProjectSourceSuggestion.model_validate(
                    {
                        "title": visible_text(item.get("title")),
                        "source_kind": source_kind
                        if source_kind in {"reference_repo", "reference_impl", "training_repo"}
                        else "reference_repo",
                        "repo_hint": visible_text(item.get("repo_hint")),
                        "fit_reason": visible_text(item.get("fit_reason")),
                        "training_value": visible_text(item.get("training_value")),
                        "first_filter": visible_text(item.get("first_filter")),
                        "first_task": visible_text(item.get("first_task")),
                        "caution": visible_text(item.get("caution")),
                        "tags": [visible_text(tag) for tag in item.get("tags", []) if visible_text(tag)],
                        "source_url": str(item.get("source_url", "") or ""),
                        "retrieved_at": str(item.get("retrieved_at", "") or ""),
                        "trust_score": float(item.get("trust_score", 0.0) or 0.0),
                        "quality_flags": [
                            str(flag) for flag in item.get("quality_flags", []) if str(flag).strip()
                        ],
                    }
                )
            )
        return suggestions

    def model_principle_notes(self, payload: object) -> PrincipleNotes | None:
        if payload is None:
            return None
        if isinstance(payload, PrincipleNotes):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            return PrincipleNotes(
                current_principle=str(
                    payload.get("current_principle", "") or payload.get("principle", "") or ""
                ),
                why_it_matters=str(
                    payload.get("why_it_matters", "")
                    or payload.get("why_this_approach", "")
                    or ""
                ),
                common_mistake=str(
                    payload.get("common_mistake", "")
                    or payload.get("common_wrong_intuition", "")
                    or ""
                ),
                apply_now=str(
                    payload.get("apply_now", "") or payload.get("follow_up_exercise", "") or ""
                ),
                transfer_targets=[
                    str(item) for item in (
                        payload.get("transfer_targets")
                        or payload.get("related_checks")
                        or []
                    ) if str(item).strip()
                ],
                concrete_anchor=str(payload.get("concrete_anchor", "") or ""),
                transferable_lesson=str(
                    payload.get("transferable_lesson", "") or payload.get("transfer_lesson", "") or ""
                ),
                related_checks=[
                    str(item) for item in payload.get("related_checks", []) if str(item).strip()
                ],
                source_asset_title=str(payload.get("source_asset_title", "") or ""),
            )
        return None

    def active_plan_stage(self, plan: LearningPlan | None) -> PlanStage | None:
        if plan is None:
            return None
        return next(
            (
                stage
                for stage in plan.stages
                if stage.id == plan.current_stage_id or stage.status == "active"
            ),
            plan.stages[0] if plan.stages else None,
        )

    def attach_plan_runtime_status(self, 
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        response_language: str | None,
        profile: UserProfile | None,
        coach_turn: dict[str, object] | None = None,
        agent_meta: dict[str, object] | None = None,
    ) -> dict[str, object]:
        previous = (
            snapshot.plan_runtime_status
            if isinstance(snapshot.plan_runtime_status, dict)
            else {}
        )
        built = coach_support.build_plan_runtime_status(self.coach_support_deps,
            workspace_id=workspace_id,
            snapshot=snapshot,
            response_language=response_language,
            profile=profile,
            coach_turn=coach_turn,
            agent_meta=agent_meta,
        )
        # Preserve explainable verify advance across hydrate rebuilds.
        prior_advance = previous.get("verify_plan_advance")
        if isinstance(prior_advance, dict) and prior_advance:
            built["verify_plan_advance"] = dict(prior_advance)
        elif (
            isinstance(built.get("verify_plan_advance"), dict)
            and built.get("verify_plan_advance")
        ):
            pass
        # Refresh rebuilds plan_runtime_status; keep leftover-not-live recovered stamp
        # (or re-evaluate) so /session/message + /turn (+ streams) still surface them.
        # Same drop risk as pressure_blocks_live_object_mint on coach_context refresh.
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        live_for_attach = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
            plan=snapshot.plan or leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )
        if leftover_plan is not None and not live_for_attach:
            built["recovered"] = True
            leftover_id = str(
                getattr(leftover_plan, "id", "")
                or getattr(leftover_plan, "plan_id", "")
                or ""
            ).strip()
            status_plan_id = str(built.get("plan_id") or built.get("planId") or "").strip()
            if leftover_id and status_plan_id == leftover_id:
                built["plan_id"] = None
                built.pop("planId", None)
        elif (
            previous.get("recovered") is True
            and not live_for_attach
            and snapshot.plan is None
        ):
            built["recovered"] = True
        return built

    def structured_plan_progress_signal(self, 
        *,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object] | None,
    ) -> dict[str, object]:
        if snapshot.plan is None:
            return {}

        current_step = ""
        why_now = ""
        verify_method: list[str] = []
        blocked_reason = ""
        next_after_current = ""

        raw_coach_context = coach_turn.get("coach_context") if isinstance(coach_turn, dict) else None
        coach_context = normalized_object_mapping(raw_coach_context) or {}
        active_thread = normalized_object_mapping(coach_context.get("active_thread")) or {}
        turn_summary = coach_turn.get("coach_turn") if isinstance(coach_turn, dict) else None
        artifacts = coach_turn.get("artifacts") if isinstance(coach_turn, dict) else None

        if snapshot.project_adaptation_guide and snapshot.project_adaptation_guide.first_migration_step:
            guide = snapshot.project_adaptation_guide
            current_step = guide.first_migration_step
            why_now = guide.target_outcome or str(coach_context.get("summary") or "").strip()
            verify_method = [item for item in guide.validation_checkpoints[:3] if item]
            next_after_current = (
                guide.migration_sequence[0]
                if guide.migration_sequence
                else snapshot.plan.next_after_current
            )
        elif snapshot.project_sources:
            top_source = snapshot.project_sources[0]
            current_step = normalize_visible_coach_text(top_source.first_task) or top_source.first_task
            why_now = normalize_visible_coach_text(
                top_source.fit_reason or top_source.training_value or top_source.repo_hint
            ) or (top_source.fit_reason or top_source.training_value or top_source.repo_hint)
            verify_method = [
                normalize_visible_coach_text(item) or item
                for item in [top_source.first_filter, top_source.caution]
                if item
            ][:2]
            next_after_current = snapshot.plan.next_after_current
        elif snapshot.project_ideas:
            top_idea = snapshot.project_ideas[0]
            current_step = top_idea.first_step or ""
            why_now = top_idea.why_now or top_idea.summary
            verify_method = [item for item in top_idea.acceptance_signals[:3] if item]
            next_after_current = snapshot.plan.next_after_current
        elif snapshot.implementation_guide:
            guide = snapshot.implementation_guide
            current_step = guide.current_step or ""
            why_now = guide.mvp_definition or guide.idea_summary or guide.teaching_goal
            verify_method = [item for item in guide.validation_strategy[:3] if item]
            next_after_current = (
                guide.next_steps[0]
                if guide.next_steps
                else guide.fallback_step
                if guide.fallback_step
                else snapshot.plan.next_after_current
            )
            blocked_reason = guide.fallback_step or ""
        elif snapshot.principle_notes and snapshot.principle_notes.apply_now:
            principle = snapshot.principle_notes
            current_step = principle.apply_now
            why_now = principle.why_it_matters or principle.current_principle
            verify_method = [item for item in principle.related_checks[:3] if item]
            next_after_current = (
                principle.transfer_targets[0]
                if principle.transfer_targets
                else snapshot.plan.next_after_current
            )

        if isinstance(coach_context, dict):
            if not current_step:
                current_step = str(coach_context.get("next_step") or "").strip()
            if not why_now:
                why_now = str(coach_context.get("summary") or "").strip()
            blocked_reason = (
                str(active_thread.get("blocker") or blocked_reason).strip()
                if isinstance(active_thread, dict)
                else blocked_reason
            )

        exercise_prompt = snapshot.exercise_prompt if isinstance(snapshot.exercise_prompt, dict) else None
        if exercise_prompt:
            verify_candidates = [
                str(exercise_prompt.get("success_signal") or "").strip(),
                *[
                    str(item).strip()
                    for item in exercise_prompt.get("constraints", [])
                    if str(item).strip()
                ][:2],
            ]
            verify_method = [item for item in [*verify_method, *verify_candidates] if item]
            if not blocked_reason:
                blocked_reason = str(exercise_prompt.get("fallback_step") or "").strip()

        if isinstance(turn_summary, CoachTurnSummary):
            if not current_step:
                current_step = turn_summary.next_step.strip()
            if not why_now:
                why_now = turn_summary.summary.strip()

        if isinstance(artifacts, dict):
            plan_artifact = (
                artifacts.get("plan_update")
                or artifacts.get("idea_implementation")
                or artifacts.get("project_adaptation")
                or artifacts.get("project_idea")
                or artifacts.get("project_source")
                or artifacts.get("principle")
            )
            if isinstance(plan_artifact, dict):
                verification = plan_artifact.get("verification")
                if isinstance(verification, list) and verification:
                    verify_method = [
                        str(item).strip()
                        for item in [*verify_method, *verification]
                        if str(item).strip()
                    ]
                if not why_now:
                    why_now = str(plan_artifact.get("rationale") or "").strip()
                if not next_after_current:
                    next_after_current = str(plan_artifact.get("teaser") or "").strip()

        verify_method = list(dict.fromkeys(item for item in verify_method if item))
        refresh_runtime = coach_focus_runtime_from_snapshot(snapshot)
        refresh = live_plan_refresh_step_why(
            plan=snapshot.plan,
            runtime=refresh_runtime,
            existing=refresh_runtime,
            current_step=current_step,
            why_now=why_now,
            next_after_current=next_after_current,
            stage_title=getattr(self.active_plan_stage(snapshot.plan), "title", "") if snapshot.plan else "",
            task_title=snapshot.current_task.title if snapshot.current_task else "",
            stage_goal=getattr(self.active_plan_stage(snapshot.plan), "goal", "") if snapshot.plan else "",
        )
        payload = {
            "current_step": refresh["current_step"],
            "why_now": refresh["why_now"],
            "verify_method": verify_method,
            "blocked_reason": blocked_reason,
            "next_after_current": refresh["next_after_current"],
        }
        return {key: value for key, value in payload.items() if value}

    def plan_progress_signal(self, 
        *,
        snapshot: WorkbenchSnapshot,
        reply_content: str,
        coach_turn: dict[str, object] | None,
    ) -> dict[str, object]:
        plan = snapshot.plan
        if plan is None:
            return {}
        active_stage = self.active_plan_stage(plan)
        turn_summary = coach_turn.get("coach_turn") if coach_turn else None
        next_step = ""
        blocker = ""
        reason = ""
        if isinstance(turn_summary, CoachTurnSummary):
            next_step = turn_summary.next_step.strip()
        coach_context = coach_turn.get("coach_context") if coach_turn else None
        if isinstance(coach_context, dict):
            next_step = str(coach_context.get("next_step") or next_step).strip()
            reason = str(coach_context.get("summary") or "").strip()
            blocker = str(coach_context.get("active_thread", {}).get("blocker") if isinstance(coach_context.get("active_thread"), dict) else "").strip()

        lowered_reply = reply_content.lower()
        blocked = any(token in lowered_reply for token in ("blocked", "\u5361\u4f4f", "\u4e0d\u4f1a", "\u6ca1\u6cd5", "\u95ee\u9898"))
        completed = any(token in lowered_reply for token in ("done", "\u5b8c\u6210", "\u5df2\u9a8c\u8bc1", "\u901a\u8fc7", "ok", "success"))
        plan_update = plan.model_copy(deep=True)

        if active_stage:
            persist_chrome = live_plan_update_persist_chrome(
                plan=plan,
                runtime=coach_focus_runtime_from_snapshot(snapshot),
                existing=coach_focus_runtime_from_snapshot(snapshot),
                stage_title=active_stage.title,
                task_title=snapshot.current_task.title if snapshot.current_task else "",
                stage_goal=active_stage.goal,
            )
            if blocked and blocker:
                plan_update.blocked_reason = blocker
                plan_update.current_step = next_step or persist_chrome["next_step"]
                plan_update.why_now = reason or persist_chrome["why_now"]
            elif completed and next_step:
                plan_update.blocked_reason = ""
                plan_update.current_step = next_step
                plan_update.why_now = reason or plan.why_now or "The current slice is ready to move forward."
                plan_update.next_after_current = next_step
            else:
                if next_step:
                    plan_update.current_step = next_step
                    plan_update.next_after_current = next_step
                if reason:
                    plan_update.why_now = reason
            refresh = live_plan_refresh_step_why(
                plan=plan,
                runtime=coach_focus_runtime_from_snapshot(snapshot),
                existing=coach_focus_runtime_from_snapshot(snapshot),
                current_step=plan_update.current_step,
                why_now=plan_update.why_now,
                next_after_current=plan_update.next_after_current,
                stage_title=active_stage.title,
                task_title=snapshot.current_task.title if snapshot.current_task else "",
                stage_goal=active_stage.goal,
            )
            plan_update.current_step = refresh["current_step"]
            plan_update.why_now = refresh["why_now"]
            plan_update.next_after_current = refresh["next_after_current"]
        if "verify" in lowered_reply or "\u9a8c\u8bc1" in reply_content:
            verify_lines = [
                line.strip("-\u2022?\t")
                for line in reply_content.splitlines()
                if "verify" in line.lower() or "\u9a8c\u8bc1" in line
            ]
            if verify_lines:
                plan_update.verify_method = [line for line in verify_lines if line]

        plan_update.updated_at = utc_now().isoformat()
        return plan_update.model_dump()

    def update_snapshot_plan_from_turn(self, 
        *,
        state,
        reply_content: str,
        coach_turn: dict[str, object] | None,
        allow_formal_plan_mutation: bool = False,
    ) -> None:
        if not allow_formal_plan_mutation:
            return
        current_plan = self.runtime.repository.get_latest_plan(state.workspace_id)
        if current_plan is None:
            return
        leftover_runtime = self.leftover_runtime_for_workspace(state.workspace_id)[1]
        if not leftover_formal_plan_is_live_for_fill(
            plan=current_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            return
        # save_formal_plan already committed. Do not rewrite leftover identity from reply prose.
        state.snapshot.plan = current_plan

    def task_training_concepts(self, 
        task: TaskSpec | None,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        plan: LearningPlan | None = None,
        runtime: dict[str, object] | None = None,
    ) -> list[str]:
        if task is None:
            return []
        leftover_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        raw_concepts = metadata.get("concepts")
        concepts = (
            [str(item).strip() for item in raw_concepts if str(item).strip()]
            if isinstance(raw_concepts, list)
            else []
        )
        return live_task_training_concepts(
            plan=plan if plan is not None else (snapshot.plan if snapshot is not None else None),
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            concepts=concepts,
            task_title=task.title,
        )

    def live_current_task_focus(self, 
        snapshot: WorkbenchSnapshot | None,
        *,
        fallback: str = "",
        runtime: dict[str, object] | None = None,
    ) -> str:
        leftover_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
        task = snapshot.current_task if snapshot is not None else None
        return live_task_focus_area(
            plan=snapshot.plan if snapshot is not None else None,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=task.title if task else "",
            fallback=fallback,
        )

    def evaluation_outcome_name(self, report, *, repeated_failure: bool = False) -> str:
        failed_checks = [
            check.label
            for check in [*report.static_checks, *report.dynamic_checks, *report.semantic_checks]
            if check.status == "failed"
        ]
        if report.passed and any(check.label == "pytest" for check in report.dynamic_checks if check.status == "passed"):
            return "tests_passed"
        if report.passed:
            return "code_landed"
        if failed_checks:
            return "repeated_error" if repeated_failure else "evaluation"
        return "evaluation"

    def report_learning_payload(self, report) -> tuple[list[str], list[str], list[str]]:
        checks = [*report.static_checks, *report.dynamic_checks, *report.semantic_checks]
        failed_checks = [check.label for check in checks if check.status == "failed"]
        learning_checks = [check.label for check in checks if check.status in {"failed", "warning"}]
        missing_requirements: list[str] = []
        for check in checks:
            if check.status not in {"failed", "warning"} or not check.detail:
                continue
            if check.label != "semantic-review":
                continue
            detail_lines = [
                line.strip()
                for line in str(check.detail).splitlines()
                if line.strip()
            ]
            detail_lines = [
                line
                for line in detail_lines
                if line.lower() != "implementation still misses requirement signals."
            ]
            missing_requirements.extend(detail_lines)
        deduped_missing: list[str] = []
        seen_missing: set[str] = set()
        for item in missing_requirements:
            lowered = item.lower()
            if lowered in seen_missing:
                continue
            seen_missing.add(lowered)
            deduped_missing.append(item)
        return failed_checks, learning_checks, deduped_missing

    def training_practice_blocked_report(self, 
        request: EvaluateSnippetRequest,
        response_language: str | None = None,
    ) -> EvaluationReport:
        zh = prefers_chinese(response_language)
        blocked_next_step = (
            "Use Verify current file so Trainer can read the active IDE file and diagnostics."
            if not zh
            else "请使用“验证当前文件”，让 Trainer 读取活动 IDE 文件和诊断信息。"
        )
        return EvaluationReport(
            task_spec_id=request.task_spec_id,
            summary=(
                "Training practice verification needs current IDE file evidence before the card can complete."
                if not zh
                else "训练练习验证需要当前 IDE 文件证据，卡片才能完成。"
            ),
            static_checks=[
                EvaluationCheck(
                    id="current-file-required",
                    label="Current file required",
                    status="failed",
                    detail=(
                        "Training practice verification requires the active IDE file and diagnostics. "
                        "Snippet-only verification cannot complete this practice card."
                    )
                    if not zh
                    else (
                        "训练练习验证需要活动 IDE 文件和诊断信息。"
                        "仅凭代码片段验证无法完成这张练习卡。"
                    ),
                )
            ],
            dynamic_checks=[],
            semantic_checks=[],
            next_step=blocked_next_step,
            reflection=(
                "Snippet-only practice verification cannot complete a training practice card."
                if not zh
                else "仅凭代码片段的练习验证无法完成训练练习卡。"
            ),
            passed=False,
        )

    def report_has_executed_pass(self, report: EvaluationReport) -> bool:
        return any(
            str(getattr(check, "status", "") or "").strip().lower() == "passed"
            for check in report.dynamic_checks
        )

    def record_training_practice_evaluation(self, 
        *,
        workspace_id: str,
        state,
        request: EvaluateCurrentFileRequest | EvaluateSnippetRequest,
        report: EvaluationReport,
        evidence_source: str,
    ) -> None:
        if str(request.evaluation_source or "").strip().lower() != "training":
            return
        training_card_id = str(request.training_card_id or "").strip()
        if not training_card_id:
            return
        training_card = self.runtime.memory_service.get_card(workspace_id, training_card_id)
        if training_card is None:
            return
        # Capture the return context before the evaluation body advances the
        # card phase: a returned card is cross-context transfer evidence.
        return_context = (
            str(getattr(training_card, "learning_phase", "") or "").strip().lower()
            == "return"
        )
        # Leftover-not-live still returns the evaluation report; do not FSRS or persist status.
        if not self.training_card_is_live_for_verify(workspace_id, training_card_id):
            return
        live_request_title = (
            str(getattr(training_card, "title", "") or "").strip()
            or str(request.training_card_title or "").strip()
        )
        focus_area = (
            str(getattr(training_card, "focus_area", "") or "").strip()
            or "practice verification"
        )
        failed_checks, _, missing_requirements = self.report_learning_payload(report)
        evaluation_workspace = self.runtime.memory_service.record_training_practice_evaluation_result(
            workspace_id=workspace_id,
            card_id=training_card_id,
            card_title=live_request_title,
            passed=bool(report.passed),
            summary=str(report.summary or ""),
            next_step=str(report.next_step or ""),
            focus_area=focus_area,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
            evidence_source=evidence_source,
            verified_by_evaluator=bool(report.passed) and self.report_has_executed_pass(report),
        )
        if busy_marker(evaluation_workspace) is not None:
            # Another training save held the workspace slot, so this evaluation
            # never reached the card. Do not record execution evidence for a
            # result the card did not accept.
            return
        if isinstance(request, EvaluateCurrentFileRequest):
            record_executed_training_evidence(
                self.runtime,
                workspace_id=workspace_id,
                request=request,
                report=report,
                returned_card=return_context,
            )
        phase = str(getattr(request, "training_phase", "") or "").strip().lower()
        # Explicit Verify may record AGAIN on failure; without a phase, keep
        # the legacy pass-only rule because Try shares this endpoint.
        if phase == "verify" or (not phase and bool(report.passed)):
            self.runtime.memory_service.schedule_live_training_card_fsrs_after_verify(
                workspace_id,
                training_card_id=training_card_id,
                passed=bool(report.passed),
            )
        self.persist_training_card_to_sandbox(workspace_id, training_card, mark_current=True)
        self.persist_training_evaluation_note_to_sandbox(
            workspace_id=workspace_id,
            card=training_card,
            passed=bool(report.passed),
            summary=str(report.summary or ""),
            next_step=str(report.next_step or ""),
            focus_area=focus_area,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
            evidence_source=evidence_source,
        )

    def workspace_response_language(self, workspace_id: str) -> str | None:
        """Learner language stored with the workspace (settings gear is canonical)."""
        try:
            memory = self.runtime.memory_service.snapshot(workspace_id)
        except Exception:
            return None
        workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
        saved = str(workspace.get("response_language") or "").strip()
        return saved or None

    def evaluation_failure_family(self, 
        *,
        focus_area: str,
        failed_checks: list[str],
        missing_requirements: list[str],
    ) -> str:
        normalized_focus = focus_area.strip().lower() or "evaluation"
        normalized_checks = sorted({item.strip().lower() for item in failed_checks if item and item.strip()})
        normalized_missing = sorted({item.strip().lower() for item in missing_requirements if item and item.strip()})
        return " :: ".join(
            [
                normalized_focus,
                ",".join(normalized_checks) or "no-checks",
                ",".join(normalized_missing) or "no-missing",
            ]
        )

    def evaluation_requires_verification(self, report) -> bool:
        dynamic_checks = list(getattr(report, "dynamic_checks", []) or [])
        if any(str(check.status).strip().lower() == "passed" for check in dynamic_checks):
            return False
        summary_text = " ".join(
            part for part in [str(report.summary or ""), str(report.next_step or "")] if part
        ).lower()
        # Bilingual on purpose: the evaluator now localizes these sentences for
        # zh learners, and the honesty rule (no dynamic verifier ran) must hold
        # in every language.
        if any(
            phrase in summary_text
            for phrase in (
                "verification is still required",
                "run at least one dynamic verifier",
                "verify current file",
                "current ide file evidence",
                "current-file evidence",
                "仍需验证",
                "动态验证器",
                "验证当前文件",
                "当前 ide 文件证据",
                "当前文件证据",
            )
        ):
            return True
        return any(
            str(check.status).strip().lower() in {"skipped", "pending"}
            for check in dynamic_checks
        )

    def persist_evaluation_learning_loop(self, 
        *,
        workspace_id: str,
        state,
        report,
        action_type: str,
        fallback_focus_area: str,
    ) -> None:
        task = state.snapshot.current_task
        bound_to_task = bool(task and report.task_spec_id and report.task_spec_id == task.id)
        concepts = self.task_training_concepts(
            state.snapshot.current_task,
            snapshot=state.snapshot,
            plan=state.snapshot.plan,
        ) if bound_to_task else []
        focus_area = (
            self.live_current_task_focus(state.snapshot, fallback=fallback_focus_area)
            if bound_to_task else fallback_focus_area
        )
        if not concepts and focus_area:
            concepts = [focus_area]
        if self.evaluation_requires_verification(report):
            self.runtime.memory_service.record_learning_outcome(
                workspace_id=workspace_id,
                concepts=concepts,
                outcome="verification_pending",
                summary=report.summary,
                checks=[],
                missing_requirements=[],
                action_type=action_type,
                repetition_count=1,
                focus_area=focus_area,
                scenario="review_reflection",
                verified_result="",
                blocked_reason=report.next_step,
                selected_teaching_asset_ids=[
                    item.id
                    for item in state.snapshot.selected_teaching_assets
                    if getattr(item, "id", "")
                ],
                teaching_strategy_context=self.teaching_strategy_context_from_snapshot(state.snapshot),
                verified_by_evaluator=False,
                bind_evidence_to_current_plan=bound_to_task,
            )
            return
        failed_checks, learning_checks, missing_requirements = self.report_learning_payload(report)
        self.runtime.memory_service.record_evaluation_feedback(
            workspace_id=workspace_id,
            concepts=concepts,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
        )
        existing_outcomes = self.runtime.memory_service.snapshot(workspace_id).learning_outcomes
        failure_family = self.evaluation_failure_family(
            focus_area=focus_area,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
        )
        same_family_count = sum(
            1
            for item in existing_outcomes[:8]
            if str(item.get("outcome", "")).strip().lower() in {"evaluation", "repeated_error"}
            and self.evaluation_failure_family(
                focus_area=str(item.get("concept", "") or focus_area),
                failed_checks=[str(value) for value in item.get("checks", []) if str(value).strip()],
                missing_requirements=[
                    str(value) for value in item.get("missing_requirements", []) if str(value).strip()
                ],
            )
            == failure_family
        )
        repetition_count = same_family_count + 1
        repeated_failure = repetition_count >= 2
        selected_teaching_asset_ids = [
            item.id
            for item in state.snapshot.selected_teaching_assets
            if getattr(item, "id", "")
        ]
        self.runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=concepts,
            outcome=self.evaluation_outcome_name(report, repeated_failure=repeated_failure),
            summary=report.summary,
            checks=learning_checks,
            missing_requirements=missing_requirements,
            action_type=action_type,
            repetition_count=repetition_count,
            focus_area=focus_area,
            scenario="review_reflection",
            verified_result=report.summary if report.passed else "",
            blocked_reason=report.next_step if not report.passed else "",
            selected_teaching_asset_ids=selected_teaching_asset_ids,
            teaching_strategy_context=self.teaching_strategy_context_from_snapshot(state.snapshot),
            verified_by_evaluator=bool(report.passed) and self.report_has_executed_pass(report),
            bind_evidence_to_current_plan=bound_to_task,
        )

    def advance_plan_after_evaluation(self, 
        *,
        workspace_id: str,
        state,
        report,
    ) -> None:
        def stamp_verify_plan_advance(
            *,
            advanced: bool,
            what: str,
            why: str,
            next_step: str,
            plan_id: str = "",
        ) -> None:
            existing = (
                state.snapshot.plan_runtime_status
                if isinstance(state.snapshot.plan_runtime_status, dict)
                else {}
            )
            status = dict(existing)
            status["verify_plan_advance"] = {
                "advanced": advanced,
                "what": what,
                "why": why,
                "next": next_step,
                "plan_id": plan_id or None,
            }
            state.snapshot.plan_runtime_status = status
            self.runtime.memory_service.persist_verify_plan_advance_stamp(
                workspace_id,
                status["verify_plan_advance"],
            )

        task = state.snapshot.current_task
        if task is None or not report.task_spec_id or report.task_spec_id != task.id:
            stamp_verify_plan_advance(
                advanced=False,
                what="Plan progress unchanged",
                why="This file evaluation is not bound to the current formal task.",
                next_step=str(report.next_step or "").strip(),
                plan_id=str(getattr(state.snapshot.plan, "id", "") or ""),
            )
            return
        if self.evaluation_requires_verification(report):
            stamp_verify_plan_advance(
                advanced=False,
                what="Plan progress unchanged",
                why="Evaluator still requires a dynamic verifier before plan progress can move.",
                next_step=str(report.next_step or "").strip(),
            )
            return
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        plan = leftover_plan or state.snapshot.plan or self.runtime.repository.get_latest_plan(workspace_id)
        # Lock window: the revision this request based its advance decision on.
        plan_revision_at_load = (
            self.head_plan_revision(workspace_id, plan.id) if plan is not None else 0
        )
        if plan is None:
            stamp_verify_plan_advance(
                advanced=False,
                what="No live formal plan",
                why="Evaluator-acked project evidence was recorded, but no formal plan is bound to advance.",
                next_step=str(report.next_step or "").strip(),
            )
            return
        if not leftover_formal_plan_is_live_for_fill(
            plan=plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            carried = str(
                (leftover_runtime or {}).get("plan_id")
                or (leftover_runtime or {}).get("planId")
                or ""
            ).strip()
            formal = str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip()
            stamp_verify_plan_advance(
                advanced=False,
                what="Plan progress unchanged",
                why=(
                    "Recovered plan_runtime identity does not match the formal plan "
                    f"(runtime plan_id={carried or 'none'}, formal plan_id={formal or 'none'})."
                ),
                next_step="Resume or re-bind the live plan before verify can advance it.",
                plan_id=formal,
            )
            return
        memory_snapshot = self.runtime.memory_service.snapshot(workspace_id)
        existing_outcomes = memory_snapshot.learning_outcomes
        workspace = memory_snapshot.workspace if isinstance(memory_snapshot.workspace, dict) else {}
        recovered_runtime = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            workspace_id,
        )
        failed_checks, _learning_checks, missing_requirements = self.report_learning_payload(report)
        focus_area = self.live_current_task_focus(state.snapshot, fallback="evaluation")
        failure_family = self.evaluation_failure_family(
            focus_area=focus_area,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
        )
        same_family_count = sum(
            1
            for item in existing_outcomes[:8]
            if str(item.get("outcome", "")).strip().lower() in {"evaluation", "repeated_error"}
            and self.evaluation_failure_family(
                focus_area=str(item.get("concept", "") or focus_area),
                failed_checks=[str(value) for value in item.get("checks", []) if str(value).strip()],
                missing_requirements=[
                    str(value) for value in item.get("missing_requirements", []) if str(value).strip()
                ],
            )
            == failure_family
        )
        repetition_count = same_family_count + (0 if report.passed else 1)
        if report.passed:
            updated = self.runtime.planner_service.advance_plan_after_success(
                plan,
                state.snapshot.current_task,
                passed=True,
                verified_result=report.summary,
                summary=report.summary,
                next_step=report.next_step,
                runtime=recovered_runtime,
                existing=recovered_runtime,
            )
        else:
            updated = self.runtime.planner_service.replan_after_failure(
                plan,
                state.snapshot.current_task,
                blocker=report.next_step,
                summary=report.summary,
                next_step=report.next_step,
                repeated_failure=repetition_count >= 2,
                focus_area=focus_area,
                runtime=recovered_runtime,
                existing=recovered_runtime,
            )
        if updated is None:
            stamp_verify_plan_advance(
                advanced=False,
                what="Plan progress unchanged",
                why="Planner returned no updated plan after evaluation.",
                next_step=str(report.next_step or "").strip(),
                plan_id=str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip(),
            )
            return
        state.snapshot.plan = updated
        formal_id = str(getattr(updated, "id", "") or getattr(updated, "plan_id", "") or "").strip()
        if updated.model_dump() != plan.model_dump():
            self.save_plan_or_conflict(
                workspace_id, updated, expected_revision=plan_revision_at_load
            )
            self.persist_plan_to_sandbox(workspace_id, updated, reason="evaluation")
        synced = self.runtime.memory_service.persist_plan_runtime_advance_after_verify(
            workspace_id,
            updated,
            request_id=formal_id,
        )
        state.snapshot.memory = self.runtime.memory_service.snapshot(workspace_id)
        response_language = None
        if isinstance(state.snapshot.memory.workspace, dict):
            response_language = str(
                state.snapshot.memory.workspace.get("response_language") or ""
            ).strip() or None
        rebuilt = self.attach_plan_runtime_status(
            workspace_id=workspace_id,
            snapshot=state.snapshot,
            response_language=response_language,
            profile=state.snapshot.profile,
        )
        state.snapshot.plan_runtime_status = rebuilt
        if synced is None:
            stamp_verify_plan_advance(
                advanced=False,
                what="Formal plan updated without runtime sync",
                why=(
                    "Evaluator advanced the formal plan, but recovered plan_runtime could not "
                    "be synced fail-closed to the same plan_id."
                ),
                next_step=str(getattr(updated, "current_step", "") or report.next_step or "").strip(),
                plan_id=formal_id,
            )
            return
        stamp_verify_plan_advance(
            advanced=True,
            what=str(getattr(updated, "current_step", "") or "").strip(),
            why=str(getattr(updated, "why_now", "") or report.summary or "").strip(),
            next_step=str(getattr(updated, "next_after_current", "") or report.next_step or "").strip(),
            plan_id=formal_id,
        )

    def clean_active_thread_task(self, 
        task: TaskSpec,
        response_language: str | None,
        active_thread: object | None,
        *,
        plan: LearningPlan | None = None,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
    ) -> TaskSpec:
        if task.metadata.get("source") != "active_thread":
            return task

        def _thread_text(key: str) -> str:
            if active_thread is None:
                return ""
            if isinstance(active_thread, dict):
                return str(active_thread.get(key) or "").strip()
            return str(getattr(active_thread, key, "") or "").strip()

        def _first_clean_step() -> str:
            leftover_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
            candidates = live_task_clean_step_candidates(
                plan=plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                next_step=_thread_text("next_step"),
                goal=task.natural_language_goal,
                task_title=task.title,
            )
            for candidate in candidates:
                text = normalize_visible_coach_text(candidate)
                if not text:
                    continue
                if prefers_chinese(response_language):
                    provider_index = text.find("\u5148\u5207\u6362 provider")
                    if provider_index >= 0:
                        return text[provider_index:].strip(" \t\r\n:：。") + "\u3002"
                    if contains_cjk_text(text) and not looks_like_mojibake_text(text):
                        return text
                    continue
                if not looks_like_mojibake_text(text):
                    return text
            return localized_text(
                "Return to the current coaching thread and verify one small next move.",
                "\u5148\u5207\u6362 provider \u6216 gateway\uff0c\u518d\u56de\u5230\u5f53\u524d\u6559\u7ec3\u4e3b\u7ebf\u505a\u4e00\u4e2a\u5c0f\u9a8c\u8bc1\u3002",
                response_language,
            )

        needs_cleanup = any(
            looks_like_mojibake_text(value)
            for value in (
                task.title,
                task.natural_language_goal,
                *task.outputs,
                *task.constraints,
                *task.verification_strategy,
            )
        )
        if not prefers_chinese(response_language) and not needs_cleanup:
            return task

        focus = self.display_focus_label(
            _thread_text("focus_area")
            or (str(task.metadata.get("concepts", [""])[0]) if task.metadata.get("concepts") else ""),
            response_language,
        )
        next_step = _first_clean_step()
        if prefers_chinese(response_language):
            return task.model_copy(
                update={
                    "title": f"\u7ee7\u7eed\uff1a{focus}",
                    "natural_language_goal": (
                        "\u6cbf\u7740\u5f53\u524d\u6559\u7ec3\u4e3b\u7ebf\u7ee7\u7eed\u63a8\u8fdb\uff1a"
                        f"{next_step}"
                    ),
                    "inputs": ["\u5f53\u524d project context", "\u5f53\u524d\u6587\u4ef6\uff08\u5982\u679c\u76f8\u5173\uff09"],
                    "outputs": [
                        "\u4e00\u4e2a\u56f4\u7ed5\u5f53\u524d\u4e3b\u7ebf\u7684\u5c0f\u4fee\u6539",
                        "\u4e00\u4e2a\u5feb\u901f\u9a8c\u8bc1\u7ed3\u679c",
                    ],
                    "constraints": ["\u8fd9\u4e00\u6b65\u843d\u5730\u524d\uff0c\u4e0d\u8981\u6269\u5927\u8303\u56f4\u3002"],
                    "verification_strategy": [
                        "\u8865\u4e01\u843d\u5730\u540e\uff0c\u53ea\u9a8c\u8bc1\u5f53\u524d\u4e3b\u7ebf\u8fd9\u4e00\u6b65\u662f\u5426\u6210\u7acb\u3002"
                    ],
                }
            )
        return task.model_copy(
            update={
                "title": f"Continue: {focus}",
                "natural_language_goal": (
                    "Stay on the current coaching thread and finish one small verifiable move: "
                    f"{next_step}"
                ),
                "outputs": [
                    "One focused change on the active thread",
                    "One quick verification result",
                ],
                "constraints": ["Do not widen scope before this move lands."],
                "verification_strategy": [
                    "After the patch lands, verify only this active-thread step."
                ],
            }
        )

    def preview_coach_context(self, 
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        profile: UserProfile | None,
        response_language: str | None,
        answer_mode: str | None,
        scenario: str | None,
        learner_signal: str | None,
    ) -> dict[str, object]:
        preview = snapshot.model_copy(deep=True)
        preview.profile = profile
        preview.memory = self.runtime.memory_service.snapshot(workspace_id)
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        language_hint = live_language_detection_hint(
            plan=snapshot.plan,
            task=snapshot.current_task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            hint=snapshot.current_task.natural_language_goal if snapshot.current_task else "",
            goal=snapshot.current_task.natural_language_goal if snapshot.current_task else "",
            task_title=snapshot.current_task.title if snapshot.current_task else "",
        )
        resolved_response_language = self.effective_response_language(
            workspace_id,
            response_language,
            language_hint or None,
        )
        resolved_answer_mode = self.effective_answer_mode(
            workspace_id,
            answer_mode,
            profile,
            message=snapshot.messages[-1].content if snapshot.messages else None,
        )
        coach_support.hydrate_snapshot(self.coach_support_deps,
            preview,
            response_language=resolved_response_language,
            answer_mode=resolved_answer_mode,
            scenario=scenario,
            learner_signal=learner_signal,
            message=snapshot.messages[-1].content if snapshot.messages else None,
            session_workspace_id=workspace_id,
        )
        return coach_support.build_coach_context(self.coach_support_deps, 
            preview,
            response_language=resolved_response_language,
            message=snapshot.messages[-1].content if snapshot.messages else None,
        )
