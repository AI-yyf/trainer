"""Server-owned goal sessions.

A goal records a continuous capability focus, its real learning activities and
the resume position. It is deliberately not a mastery score: finishing a goal
ends the focus, it never promotes competency or rewrites evidence.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from ..core.event_ledger import EVENT_GOAL_ARCHIVED, EVENT_GOAL_COMPLETED
from ..core.models import GoalActivity, GoalSession, LearningPlan, utc_now_iso

if TYPE_CHECKING:
    from ..core.event_ledger import EventLedgerService
from ..db.repository import TrainerRepository

logger = logging.getLogger(__name__)

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
# An explicit "set a goal" request is unambiguous, even when the title uses
# "能够/会" instead of the learning verbs below.
_ZH_EXPLICIT_GOAL = re.compile(
    r"^(?:请)?(?:帮我|给我|为我)?(?:设定|设置|定下|定为|立下|立)"
    r"(?:一个|个)?(?:长期|阶段|学习|能力|成长)?(?:的)?目标\s*[:：,，]?\s*(?P<title>.+)$"
)
_EN_EXPLICIT_GOAL = re.compile(
    r"^(?:please\s+)?(?:help\s+me\s+)?(?:set|create|define|establish)\s+"
    r"(?:a|an|my)?\s*(?:long-term|learning|capability|growth)?\s*goal\s*[:,\-]?\s*(?P<title>.+)$",
    re.IGNORECASE,
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

    explicit_goal = _ZH_EXPLICIT_GOAL.match(raw) or _EN_EXPLICIT_GOAL.match(raw)
    if explicit_goal:
        title = _clean_candidate_title(explicit_goal.group("title"))
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
    def __init__(
        self,
        repository: TrainerRepository,
        *,
        max_activities: int = 40,
        event_ledger: "EventLedgerService | None" = None,
    ) -> None:
        self.repository = repository
        self.max_activities = max(1, int(max_activities))
        self.event_ledger = event_ledger

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
                if goal.status in {"active", "paused"} and self._same_title(goal.title, normalized)
            ),
            None,
        )
        if same_title is not None:
            if same_title.status == "active":
                return same_title
            if source == "coach_detected":
                return same_title
            if existing is not None and existing.goal_id != same_title.goal_id:
                self._mutate(existing, lambda goal: self._transition_open_goal(goal, "paused"))
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
            self._mutate(existing, lambda goal: self._transition_open_goal(goal, "paused"))

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
        self._record_goal_event(
            "goal_started",
            workspace_id=scope,
            goal_id=goal.goal_id,
            idempotency_key=f"goal_started:{goal.goal_id}",
            payload={"goal_id": goal.goal_id, "title": goal.title, "source": source},
        )
        return goal

    def pause(self, workspace_id: str, goal_id: str | None = None) -> GoalSession | None:
        target = self._target(workspace_id, goal_id)
        if target is None or target.status != "active":
            return target
        return self._mutate(target, lambda goal: self._transition_open_goal(goal, "paused"))

    def resume(self, workspace_id: str, goal_id: str | None = None) -> GoalSession | None:
        target = self._target(workspace_id, goal_id)
        if target is None or target.status != "paused":
            return target
        # One active focus: pausing siblings keeps the UI and Coach unambiguous.
        for other in self.list(workspace_id):
            if other.goal_id != target.goal_id and other.status == "active":
                self._mutate(other, lambda goal: self._transition_open_goal(goal, "paused"))
        return self._mutate(target, lambda goal: self._transition_open_goal(goal, "active"))

    def complete(self, workspace_id: str, goal_id: str | None = None) -> GoalSession | None:
        return self._finish(workspace_id, goal_id, "completed")

    def archive(self, workspace_id: str, goal_id: str | None = None) -> GoalSession | None:
        return self._finish(workspace_id, goal_id, "archived")

    def _finish(
        self, workspace_id: str, goal_id: str | None, status: Literal["completed", "archived"],
    ) -> GoalSession | None:
        target = self._target(workspace_id, goal_id)
        if target is None:
            return None
        finished = self._mutate(target, lambda goal: self._transition_open_goal(goal, status))
        if finished is not None and finished.status == status:
            event_type = EVENT_GOAL_COMPLETED if status == "completed" else EVENT_GOAL_ARCHIVED
            payload = {"title": finished.title}
            if finished.completion_basis:
                payload["completion_basis"] = finished.completion_basis
            self._record_goal_event(
                event_type,
                workspace_id=workspace_id,
                goal_id=finished.goal_id,
                idempotency_key=f"{event_type}:{finished.goal_id}",
                payload=payload,
            )
        return finished

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
        if not candidate or any(
            goal.status in {"archived", "completed"} and self._same_title(goal.title, candidate)
            for goal in self.list(workspace_id)
        ):
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

        Only active goals can accumulate activities. A repeated ``event_key`` is
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

        ledger_activity: GoalActivity | None = None

        def mutate(target: GoalSession) -> bool:
            nonlocal ledger_activity
            if target.status != "active":
                return False
            if key:
                ledger_activity = next(
                    (activity for activity in target.activities if activity.event_key == key), None,
                )
                if ledger_activity is not None:
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
            ledger_activity = activity
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

        updated = self.repository.mutate_goal(workspace_id, goal.goal_id, mutate)
        if updated is not None and ledger_activity is not None:
            fingerprint = key or f"{kind}:{ledger_activity.summary[:80]}:{ledger_activity.occurred_at}"
            self._record_goal_event(
                "goal_activity_recorded",
                workspace_id=workspace_id,
                goal_id=goal.goal_id,
                idempotency_key=f"goal_activity:{goal.goal_id}:{fingerprint}",
                payload={
                    "goal_id": goal.goal_id,
                    "kind": ledger_activity.kind,
                    "result": ledger_activity.result,
                    "activity_id": ledger_activity.activity_id,
                },
            )
        return updated

    def _record_goal_event(
        self,
        event_type: str,
        *,
        workspace_id: str,
        goal_id: str,
        idempotency_key: str = "",
        payload: dict[str, str] | None = None,
    ) -> None:
        """Append a goal lifecycle fact to the unified ledger (best effort).

        The ledger is optional (embedded/test runtimes); failures must never
        block the goal mutation that already persisted.
        """
        if self.event_ledger is None:
            return
        try:
            self.event_ledger.record_event(
                event_type,
                actor="system",
                scope="goal",
                project_id=workspace_id,
                workspace_id=workspace_id,
                source_chain=["goal_service"],
                payload_ref={"goal_id": goal_id, **(payload or {})},
                reversibility="reversible",
                audit_note=f"Goal {goal_id}: {event_type}",
                idempotency_key=idempotency_key,
            )
        except Exception:
            logger.exception("Could not append %s for goal %s", event_type, goal_id)

    def recompute_goal_from_ledger(
        self,
        workspace_id: str,
        goal_id: str,
    ) -> dict | None:
        """Recompute the goal projection from effective ledger events (重算).

        Replays goal_started / goal_activity_recorded / goal_completed entries
        for this goal in ledger order — reversed events are already excluded by
        ``effective_entries`` — and returns the reconstructed projection:

        ``{goal_id, workspace_id, title, source, status, activities,
        activity_count, completed}``

        Returns None when the ledger has no record of this goal. This is the
        audit-side recomputation: the persisted GoalSession remains the
        day-to-day truth; the ledger replay proves the persisted state is
        derivable from the event history alone.
        """
        if self.event_ledger is None:
            return None
        effective = [
            entry
            for entry in self.event_ledger.effective_entries(project_id=workspace_id)
            if entry.payload_ref.get("goal_id") == goal_id
            and entry.event_type in {
                "goal_started",
                "goal_activity_recorded",
                EVENT_GOAL_COMPLETED,
                EVENT_GOAL_ARCHIVED,
            }
        ]
        if not effective:
            return None
        projection: dict = {
            "goal_id": goal_id,
            "workspace_id": workspace_id,
            "title": "",
            "source": "",
            "status": "active",
            "activities": [],
            "activity_count": 0,
            "completed": False,
        }
        for entry in effective:
            payload = entry.payload_ref
            if entry.event_type == "goal_started":
                projection["title"] = str(payload.get("title") or "")
                projection["source"] = str(payload.get("source") or "")
            elif entry.event_type == "goal_activity_recorded":
                projection["activities"].append({
                    "kind": str(payload.get("kind") or ""),
                    "result": str(payload.get("result") or ""),
                })
                projection["activity_count"] += 1
            elif entry.event_type == EVENT_GOAL_COMPLETED:
                projection["status"] = "completed"
                projection["completed"] = True
                projection["completion_basis"] = payload.get("completion_basis")
            elif entry.event_type == EVENT_GOAL_ARCHIVED:
                projection["status"] = "archived"
        return projection

    def _target(
        self,
        workspace_id: str,
        goal_id: str | None,
    ) -> GoalSession | None:
        if goal_id and str(goal_id).strip():
            return self.get(workspace_id, str(goal_id))
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
    def _transition_open_goal(
        goal: GoalSession,
        status: Literal["active", "paused", "completed", "archived"],
    ) -> bool:
        if goal.status not in {"active", "paused"} or goal.status == status:
            return False
        goal.status = status
        now = utc_now_iso()
        goal.updated_at = now
        if status == "completed":
            goal.completed_at = now
            goal.completion_basis = "user_confirmed"
        elif status == "archived":
            goal.archived_at = now
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
        if goal.status not in {"active", "paused"}:
            return False
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
