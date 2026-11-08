"""Server-owned goal sessions.

A goal records a continuous capability focus, its real learning activities and
the resume position. It is deliberately not a mastery score: finishing a goal
ends the focus, it never promotes competency or rewrites evidence.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from ..core.models import GoalActivity, GoalSession, LearningPlan, utc_now_iso
from ..db.repository import TrainerRepository

_ZH_INTENT_PREFIX = re.compile(
    r"(?:我(?:真的|真心|一直|很|想|打算)?(?:要|想|希望|打算)|帮我|请帮我|我想要)"
)
_ZH_LEARNING_VERB = re.compile(
    r"(?:真正|认真)?(?:学会|学懂|掌握|搞懂|弄懂|系统(?:地)?学习|系统学|从零(?:开始)?学习|从头(?:开始)?学)"
)
_ZH_PLAN_REQUEST = re.compile(
    r"^(?:请)?帮我(?:制定|规划|设计|安排)(?:一个|一份|一套)?"
    r"(?P<body>.+?)(?:的)?(?:学习|成长|能力)?(?:路线|计划|路径|方案)$"
)
_EN_INTENT = re.compile(
    r"^(?:please\s+)?(?:i\s+(?:really\s+|truly\s+)?(?:want|would like|need|hope|plan)\s+to|"
    r"help me)\s+(?P<verb>learn|master|get good at|become good at|study)\s+(?P<title>.+)$",
    re.IGNORECASE,
)
_EN_SYSTEMATIC = re.compile(
    r"^(?:i\s+(?:want|would like|need)\s+to\s+)?(?:systematically|from scratch)\s+"
    r"(?:learn|study|master)\s+(?P<title>.+)$",
    re.IGNORECASE,
)
_TITLE_PREFIX = re.compile(r"^(?:学习|掌握|关于|针对|how to|about)\s+", re.IGNORECASE)
_TITLE_SUFFIX = re.compile(r"(?:的)?(?:学习)?(?:路线|计划|路径|方案)$")


def normalize_goal_title(value: str) -> str:
    """Collapse whitespace and strip conversational punctuation, bounded."""
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    cleaned = cleaned.strip("。.!！?？:：;；,，、 \t\"'“”‘’")
    return cleaned[:160]


_TITLE_REQUEST_CLAUSE = re.compile(
    r"[，,。;；]\s*(?=(?:请|先|帮我|给我|告诉我|并|然后|再|以及|please\b|and\b))",
    re.IGNORECASE,
)


def _clean_candidate_title(value: str) -> str:
    title = normalize_goal_title(value)
    # "实现 PPO Clip，请先判断我该从哪里开始" -> "实现 PPO Clip"
    title = _TITLE_REQUEST_CLAUSE.split(title, maxsplit=1)[0]
    previous = None
    while title and title != previous:
        previous = title
        title = _TITLE_PREFIX.sub("", title)
        title = _TITLE_SUFFIX.sub("", title).strip()
    return normalize_goal_title(title)


def detect_goal_candidate(message: str) -> str | None:
    """Return a goal title only for an explicit capability-learning statement.

    Ordinary questions, explanations and chat never match. The caller still
    decides whether to persist the candidate.
    """
    raw = normalize_goal_title(message)
    if len(raw) < 4 or raw.startswith("/"):
        return None

    plan_match = _ZH_PLAN_REQUEST.match(raw)
    if plan_match:
        title = _clean_candidate_title(plan_match.group("body"))
        if len(title) >= 2:
            return title

    verb_match = _ZH_LEARNING_VERB.search(raw)
    if verb_match and _ZH_INTENT_PREFIX.search(raw[: verb_match.start()]):
        title = _clean_candidate_title(raw[verb_match.end() :])
        if len(title) >= 2:
            return title

    for pattern in (_EN_INTENT, _EN_SYSTEMATIC):
        match = pattern.match(raw)
        if not match:
            continue
        title = _clean_candidate_title(match.group("title"))
        if len(title) >= 2:
            return title
    return None


def _active_plan_position(plan: LearningPlan | None) -> tuple[str | None, str | None, str]:
    if plan is None:
        return None, None, ""
    stage_id = (getattr(plan, "current_stage_id", None) or "").strip() or None
    stages = list(getattr(plan, "stages", None) or [])
    stage = next(
        (item for item in stages if stage_id and getattr(item, "id", "") == stage_id),
        None,
    ) or next((item for item in stages if getattr(item, "status", "") == "active"), None)
    position = ""
    if stage is not None:
        stage_id = str(getattr(stage, "id", "") or "").strip() or stage_id
        position = str(getattr(stage, "title", "") or getattr(stage, "goal", "") or "").strip()
    if not position:
        position = str(getattr(plan, "current_step", "") or "").strip()
    plan_id = str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip() or None
    return plan_id, stage_id, position[:160]


class GoalService:
    def __init__(self, repository: TrainerRepository, *, max_activities: int = 40) -> None:
        self.repository = repository
        self.max_activities = max(1, int(max_activities))

    def current(self, workspace_id: str) -> GoalSession | None:
        scope = (workspace_id or "").strip()
        return self.repository.get_current_goal(scope) if scope else None

    def get(self, workspace_id: str, goal_id: str) -> GoalSession | None:
        scope = (workspace_id or "").strip()
        key = (goal_id or "").strip()
        return self.repository.get_goal(scope, key) if scope and key else None

    def list(self, workspace_id: str) -> list[GoalSession]:
        scope = (workspace_id or "").strip()
        return self.repository.list_goals(scope) if scope else []

    def start(
        self,
        *,
        workspace_id: str,
        title: str,
        session_id: str | None = None,
        concept: str = "",
        capability: str = "",
        source: Literal["user_explicit", "coach_detected", "plan_stage"] = "user_explicit",
        plan: LearningPlan | None = None,
    ) -> GoalSession:
        scope = (workspace_id or "").strip()
        normalized = normalize_goal_title(title)
        if not scope:
            raise ValueError("workspace_id_required")
        if not normalized:
            raise ValueError("goal_title_required")
        if source not in {"user_explicit", "coach_detected", "plan_stage"}:
            raise ValueError("unsupported_goal_source")

        plan_id, stage_id, position = _active_plan_position(plan)
        existing = self.current(scope)
        same_title = next(
            (
                goal
                for goal in self.list(scope)
                if goal.status != "completed" and self._same_title(goal.title, normalized)
            ),
            None,
        )
        if same_title is not None:
            if same_title.status == "active":
                return same_title
            if source == "coach_detected":
                return same_title
            if existing is not None and existing.goal_id != same_title.goal_id:
                self._mutate(existing, lambda goal: self._set_status(goal, "paused"))
            return self._mutate(
                same_title,
                lambda goal: self._refresh_identity(
                    goal,
                    session_id=session_id,
                    plan_id=plan_id,
                    stage_id=stage_id,
                    position=position,
                    status="active",
                ),
            ) or same_title
        if existing is not None and existing.status == "active":
            if source == "coach_detected":
                # Observed learning intent never replaces an explicit focus.
                return existing
            self._mutate(existing, lambda goal: self._set_status(goal, "paused"))

        now = utc_now_iso()
        goal = GoalSession(
            goalId=f"goal-{uuid4().hex[:12]}",
            workspaceId=scope,
            sessionId=session_id,
            title=normalized,
            concept=normalize_goal_title(concept) or normalized,
            capability=normalize_goal_title(capability),
            planId=plan_id,
            stageId=stage_id,
            status="active",
            source=source,
            currentPosition=position,
            startedAt=now,
            updatedAt=now,
        )
        self.repository.save_goal(scope, goal)
        return goal

    def pause(self, workspace_id: str, goal_id: str | None = None) -> GoalSession | None:
        target = self._target(workspace_id, goal_id)
        if target is None or target.status != "active":
            return target
        return self._mutate(target, lambda goal: self._set_status(goal, "paused"))

    def resume(self, workspace_id: str, goal_id: str | None = None) -> GoalSession | None:
        target = self._target(workspace_id, goal_id, include_completed=False)
        if target is None or target.status == "completed":
            return target
        # One active focus: pausing siblings keeps the UI and Coach unambiguous.
        for other in self.list(workspace_id):
            if other.goal_id != target.goal_id and other.status == "active":
                self._mutate(other, lambda goal: self._set_status(goal, "paused"))
        if target.status == "active":
            return target
        return self._mutate(target, lambda goal: self._set_status(goal, "active"))

    def complete(self, workspace_id: str, goal_id: str | None = None) -> GoalSession | None:
        target = self._target(workspace_id, goal_id, include_completed=False)
        if target is None or target.status == "completed":
            return target
        return self._mutate(target, lambda goal: self._set_status(goal, "completed"))

    def observe_turn(
        self,
        *,
        workspace_id: str,
        message: str,
        intent: str = "coach",
        active_view: str | None = None,
        goal_mode: bool = False,
        goal_text: str | None = None,
        session_id: str | None = None,
        plan: LearningPlan | None = None,
    ) -> GoalSession | None:
        """Persist an explicit goal, or conservatively detect one on plain chat."""
        current = self.current(workspace_id)
        if goal_mode:
            title = normalize_goal_title(goal_text or "")
            if title:
                return self.start(
                    workspace_id=workspace_id,
                    title=title,
                    session_id=session_id,
                    source="user_explicit",
                    plan=plan,
                )
            return current
        if current is not None:
            return current
        if str(intent or "coach").strip().lower() != "coach":
            return None
        if str(active_view or "coach").strip().lower() not in {"coach", ""}:
            return None
        candidate = detect_goal_candidate(message)
        if not candidate:
            return None
        return self.start(
            workspace_id=workspace_id,
            title=candidate,
            session_id=session_id,
            concept=candidate,
            source="coach_detected",
            plan=plan,
        )

    def record_activity(
        self,
        *,
        workspace_id: str,
        kind: Literal["evaluation", "training_attempt", "verification", "review"],
        summary: str = "",
        result: Literal["passed", "failed", "pending", "completed", "unknown"] = "unknown",
        concept: str = "",
        evidence_refs: list[str] | None = None,
        event_key: str = "",
        occurred_at: str | None = None,
    ) -> GoalSession | None:
        """Append one real learning activity to the active goal.

        Paused/completed goals are not advanced. A repeated ``event_key`` is
        idempotent so retries and multi-window replays cannot inflate counts.
        """
        goal = self.current(workspace_id)
        if goal is None or goal.status != "active":
            return goal
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in {"evaluation", "training_attempt", "verification", "review"}:
            raise ValueError("unsupported_goal_activity_kind")
        allowed_results: dict[
            str,
            Literal["passed", "failed", "pending", "completed", "unknown"],
        ] = {
            "passed": "passed",
            "failed": "failed",
            "pending": "pending",
            "completed": "completed",
            "unknown": "unknown",
        }
        normalized_result = allowed_results.get(
            str(result or "unknown").strip().lower(),
            "unknown",
        )
        refs = [str(item).strip() for item in (evidence_refs or []) if str(item).strip()]
        key = str(event_key or "").strip()
        key = f"{normalized_kind}:{key}" if key else ""

        def mutate(target: GoalSession) -> bool:
            if key and any(activity.event_key == key for activity in target.activities):
                return False
            prior_refs = {
                ref
                for activity in target.activities
                for ref in activity.evidence_refs
            }
            activity = GoalActivity(
                activityId=f"activity-{uuid4().hex[:12]}",
                kind=kind,
                summary=normalize_goal_title(summary)[:120],
                result=normalized_result,
                concept=normalize_goal_title(concept),
                occurredAt=occurred_at or utc_now_iso(),
                evidenceRefs=refs,
                eventKey=key,
            )
            target.activities.append(activity)
            target.activities = target.activities[-self.max_activities :]
            target.activity_count += 1
            target.evidence_count += len({ref for ref in refs if ref not in prior_refs})
            target.latest_activity = activity
            target.last_activity_at = activity.occurred_at
            if activity.summary:
                target.current_position = activity.summary
            target.updated_at = activity.occurred_at
            return True

        return self.repository.mutate_goal(workspace_id, goal.goal_id, mutate)

    def _target(
        self,
        workspace_id: str,
        goal_id: str | None,
        *,
        include_completed: bool = True,
    ) -> GoalSession | None:
        if goal_id and str(goal_id).strip():
            goal = self.get(workspace_id, str(goal_id))
            if goal is not None and (include_completed or goal.status != "completed"):
                return goal
            return None
        return self.current(workspace_id)

    def _mutate(
        self,
        goal: GoalSession,
        mutate: Callable[[GoalSession], bool],
    ) -> GoalSession | None:
        return self.repository.mutate_goal(goal.workspace_id, goal.goal_id, mutate)

    @staticmethod
    def _same_title(left: str, right: str) -> bool:
        return normalize_goal_title(left).casefold() == normalize_goal_title(right).casefold()

    @staticmethod
    def _set_status(
        goal: GoalSession,
        status: Literal["active", "paused", "completed"],
    ) -> bool:
        if goal.status == status:
            return False
        goal.status = status
        now = utc_now_iso()
        goal.updated_at = now
        if status == "completed":
            goal.completed_at = now
        elif status == "active":
            goal.completed_at = None
        return True

    @staticmethod
    def _refresh_identity(
        goal: GoalSession,
        *,
        session_id: str | None,
        plan_id: str | None,
        stage_id: str | None,
        position: str,
        status: Literal["active", "paused", "completed"],
    ) -> bool:
        changed = False
        if session_id and goal.session_id != session_id:
            goal.session_id = session_id
            changed = True
        if plan_id and goal.plan_id != plan_id:
            goal.plan_id = plan_id
            changed = True
        if stage_id and goal.stage_id != stage_id:
            goal.stage_id = stage_id
            changed = True
        if position and goal.current_position != position:
            goal.current_position = position
            changed = True
        if status == "active" and goal.status != "active":
            goal.status = "active"
            goal.completed_at = None
            changed = True
        if changed:
            goal.updated_at = utc_now_iso()
        return changed
