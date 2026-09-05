from __future__ import annotations

import re

from ..core.models import (
    AffectState,
    LearnerState,
    MemorySnapshot,
    TeachingDecision,
    ToneDecision,
    UserProfile,
)


class AffectService:
    # Expanded keyword patterns for better detection
    FRUSTRATION_PATTERNS = [
        # English
        r"\bstuck\b", r"\bblocked\b", r"\boverwhelmed\b", r"\bfrustrated\b",
        r"\bcan't figure\b", r"\bnot working\b", r"\bbroken\b", r"\berror\b",
        r"\bhelp\b", r"\bstruggling\b", r"\bdifficult\b", r"\bimpossible\b",
        # Chinese
        r"卡住", r"崩了", r"搞不定", r"解决不了", r"不行", r"失败",
        r"错误", r"报错", r"崩溃", r"死了", r"挂了", r"出问题",
        r"怎么办", r"救命", r"求助", r"不会", r"不懂",
    ]

    CONFUSION_PATTERNS = [
        # English
        r"\bunclear\b", r"\bconfused\b", r"\bdon't understand\b",
        r"\bnot sure\b", r"\buncertain\b", r"\bwhat does\b",
        r"\bhow to\b", r"\bwhy\b", r"\bexplain\b",
        # Chinese
        r"不懂", r"不明白", r"不清楚", r"不确定", r"拿不准",
        r"什么意思", r"为什么", r"怎么", r"如何", r"解释一下",
    ]

    SUCCESS_PATTERNS = [
        # English
        r"\bworks\b", r"\bworking\b", r"\bfixed\b", r"\bsolved\b",
        r"\bdone\b", r"\bcompleted\b", r"\bsuccess\b", r"\bpass\b",
        r"\bgreat\b", r"\bawesome\b", r"\bthanks\b", r"\bthank you\b",
        # Chinese
        r"解决了", r"搞定了", r"完成了", r"成功了", r"好了",
        r"可以了", r"通过了", r"运行正常", r"没问题", r"谢谢",
        r"感谢", r"棒", r"不错", r"很好",
    ]

    def _detect_patterns(self, text: str, patterns: list[str]) -> int:
        """Count how many patterns match in the text."""
        count = 0
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                count += 1
        return count

    def _analyze_sentiment(self, message: str) -> dict[str, float]:
        """Analyze message sentiment using pattern matching."""
        lowered = message.lower()

        frustration_count = self._detect_patterns(lowered, self.FRUSTRATION_PATTERNS)
        confusion_count = self._detect_patterns(lowered, self.CONFUSION_PATTERNS)
        success_count = self._detect_patterns(lowered, self.SUCCESS_PATTERNS)

        # Calculate base scores from pattern counts
        frustration_score = min(1.0, frustration_count * 0.25 + confusion_count * 0.15)
        confidence_score = min(1.0, success_count * 0.2 + 0.3)
        confusion_score = min(1.0, confusion_count * 0.2)

        # Message length heuristic - very short messages might indicate frustration
        if len(message) < 10 and frustration_count > 0:
            frustration_score = max(frustration_score, 0.6)

        # Exclamation marks might indicate strong emotion
        if message.count("!") >= 2:
            if frustration_count > 0:
                frustration_score = min(1.0, frustration_score + 0.15)
            if success_count > 0:
                confidence_score = min(1.0, confidence_score + 0.1)

        return {
            "frustration": frustration_score,
            "confidence": confidence_score,
            "confusion": confusion_score,
        }

    def infer_state(
        self,
        *,
        message: str,
        learner_state: LearnerState,
        memory_snapshot: MemorySnapshot,
    ) -> AffectState:
        # Analyze message sentiment
        sentiment = self._analyze_sentiment(message)
        lowered_message = message.lower()
        explicit_overload_signal = bool(
            re.search(r"\b(?:stuck|blocked)\b", lowered_message)
            and re.search(r"\boverwhelmed\b", lowered_message)
        )

        # Start with learner's current state
        frustration = max(learner_state.frustration_level, sentiment["frustration"])
        confidence = learner_state.current_confidence

        # Boost confidence if success patterns detected
        if sentiment["confidence"] > 0.3:
            confidence = max(confidence, sentiment["confidence"])

        # Reduce confidence if confusion detected
        if sentiment["confusion"] > 0.3:
            confidence = min(confidence, max(0.2, confidence - sentiment["confusion"] * 0.3))

        momentum = 0.55
        active_thread = memory_snapshot.active_thread
        learning_outcomes = memory_snapshot.learning_outcomes if isinstance(memory_snapshot.learning_outcomes, list) else []
        latest_outcome = learning_outcomes[0] if learning_outcomes else None

        # Apply memory-based adjustments
        if memory_snapshot.recent_wins:
            confidence = max(confidence, 0.62)
            momentum = 0.7

        if memory_snapshot.due_review_count >= 2:
            frustration = max(frustration, 0.52)
            momentum = min(momentum, 0.45)
        if memory_snapshot.due_review_count >= 3:
            frustration = max(frustration, 0.63)
            confidence = min(confidence, 0.44)
            momentum = min(momentum, 0.36)
        if active_thread and active_thread.blocker:
            frustration = min(1.0, frustration + 0.08)
            momentum = min(momentum, 0.4)
        if memory_snapshot.top_weakness:
            frustration = min(1.0, frustration + 0.04)
        if active_thread and active_thread.verified_result:
            confidence = max(confidence, 0.58)
            momentum = max(momentum, 0.63)
        if memory_snapshot.recent_wins:
            confidence = max(confidence, 0.62)
            momentum = max(momentum, 0.7)
        if isinstance(latest_outcome, dict):
            outcome_name = str(latest_outcome.get("outcome", "") or "").strip().lower()
            repetition_count = int(latest_outcome.get("repetition_count", 1) or 1)
            if outcome_name in {"repeated_error", "evaluation", "task_abandoned", "blocked"}:
                frustration = min(1.0, frustration + (0.1 if repetition_count < 2 else 0.18))
                confidence = min(confidence, 0.4 if repetition_count < 2 else 0.32)
                momentum = min(momentum, 0.38 if repetition_count < 2 else 0.24)
            elif outcome_name in {"tests_passed", "code_landed", "concept_answered_correctly"}:
                confidence = max(confidence, 0.68 if outcome_name != "concept_answered_correctly" else 0.64)
                momentum = max(momentum, 0.72 if outcome_name != "concept_answered_correctly" else 0.66)
                frustration = max(0.08, frustration - 0.08)

        # Determine recovery signal
        if (
            frustration >= 0.84
            or explicit_overload_signal
            or (learner_state.needs_rescue and memory_snapshot.due_review_count >= 1)
        ):
            recovery_signal = "overloaded"
        elif frustration >= 0.58 or (
            active_thread is not None
            and bool(active_thread.blocker)
            and memory_snapshot.due_review_count > 0
        ):
            recovery_signal = "fragile"
        elif isinstance(latest_outcome, dict) and str(latest_outcome.get("outcome", "") or "").strip().lower() in {
            "tests_passed",
            "code_landed",
        } and memory_snapshot.due_review_count <= 1:
            recovery_signal = "recovering"
        elif confidence >= 0.6 and (
            bool(memory_snapshot.recent_wins)
            or (active_thread is not None and bool(active_thread.verified_result))
        ):
            recovery_signal = "recovering"
        else:
            recovery_signal = "steady"

        needs_reassurance = (
            frustration >= 0.65
            or learner_state.needs_rescue
            or recovery_signal in {"fragile", "overloaded"}
        )
        urgency = "high" if frustration >= 0.8 else "medium" if frustration >= 0.45 else "low"
        return AffectState(
            frustration_level=round(frustration, 2),
            confidence_level=round(confidence, 2),
            momentum_level=round(momentum, 2),
            needs_reassurance=needs_reassurance,
            urgency_level=urgency,
            recovery_signal=recovery_signal,
        )

    def decide_tone(
        self,
        *,
        profile: UserProfile | None,
        learner_state: LearnerState,
        teaching_decision: TeachingDecision,
        affect_state: AffectState,
    ) -> ToneDecision:
        answer_policy = profile.answer_policy if profile else "guided"
        tone = "steady"
        verbosity = "medium"
        acknowledge_progress = bool(affect_state.confidence_level >= 0.58)
        avoid_overwhelm = False

        if affect_state.recovery_signal == "overloaded" or affect_state.frustration_level >= 0.8 or learner_state.needs_rescue:
            tone = "concise_rescue"
            verbosity = "short"
            avoid_overwhelm = True
            acknowledge_progress = False
        elif affect_state.recovery_signal == "fragile":
            tone = "encouraging"
            verbosity = "short" if affect_state.urgency_level == "high" else "medium"
            avoid_overwhelm = True
        elif teaching_decision.mode in {"principle_explanation", "concept_teaching", "reflection"}:
            tone = "reflective"
            verbosity = "expanded" if affect_state.urgency_level == "low" else "medium"
        elif affect_state.needs_reassurance:
            tone = "encouraging"
            verbosity = "medium"
            avoid_overwhelm = True
        elif affect_state.recovery_signal == "recovering":
            tone = "encouraging"
            verbosity = "medium"
            acknowledge_progress = True
        elif answer_policy == "direct" or teaching_decision.mode == "direct_rescue":
            tone = "steady"
            verbosity = "short"
        elif learner_state.preferred_hint_depth == "expanded":
            verbosity = "expanded"

        return ToneDecision(
            tone=tone,
            verbosity_bias=verbosity,
            acknowledge_progress=acknowledge_progress,
            avoid_overwhelm=avoid_overwhelm,
        )
