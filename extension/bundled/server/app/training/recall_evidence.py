"""Record a real recall answer as capability evidence.

The answer key / grading belongs to the recall flow. This module only binds
that outcome to the existing AttemptStore evidence stream and the one Learner
State projection:

* an immediate answer never counts as delayed recall;
* an answer after a real retention interval advances ``delayed_recall``;
* a theory answer answered immediately can advance ``comprehension``;
* no answer ("done", "reviewed", "I understood") creates no recall evidence.

No parallel evidence store is introduced.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..training.attempt_store import content_hash
from ..training.skill_projection import DELAYED_RECALL_MIN_DAYS

if TYPE_CHECKING:
    from ..api.runtime import TrainerRuntime

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_recall_evidence(
    runtime: "TrainerRuntime",
    *,
    workspace_id: str,
    card_id: str,
    correct: bool,
    source: str,
    answer_mode: str = "",
    detail: str = "",
    assistance_level: str = "none",
    immediate_dimension: str = "comprehension",
    allow_missing_card: bool = False,
) -> dict[str, Any] | None:
    """Persist one answered recall as evidence.

    ``assistance_level`` must be explicit. The built-in flashcard/theory flows
    have no in-app hint path, so they record ``none``; a hinted recall records
    the hint level and cannot advance the independent rung.
    """
    workspace = str(workspace_id or "").strip()
    card = str(card_id or "").strip()
    if not workspace or not card:
        return None
    store = getattr(runtime, "attempt_store", None)
    memory = getattr(runtime, "memory_service", None)
    if store is None or memory is None:
        return None
    card_record = memory.get_card(workspace, card)
    scheduled: dict[str, Any] | None = None
    if card_record is None:
        if not allow_missing_card:
            return None
        # A theory drill has a stable drill/question identity but no training
        # card. It can still be a controlled comprehension check; it has no
        # FSRS card interval, so it must not claim delayed recall.
        scheduled = None
    else:
        try:
            scheduled = memory.schedule_training_card_recall(
                workspace,
                training_card_id=card,
                passed=correct,
            )
        except (RuntimeError, TypeError, ValueError):
            # Scheduling is an input to the evidence, not the recall answer
            # itself. A scheduler failure must not turn a recorded answer into
            # a fake success; the evidence below is recorded with no delay and
            # therefore cannot advance the delayed-recall ladder.
            logger.warning("recall FSRS scheduling failed", exc_info=True)
    try:
        delay_days = max(0.0, float((scheduled or {}).get("elapsed_days") or 0.0))
    except (TypeError, ValueError):
        delay_days = 0.0
    delayed = delay_days >= DELAYED_RECALL_MIN_DAYS
    dimension = "delayed_recall" if delayed else immediate_dimension
    evidence_kind = "recall" if dimension == "delayed_recall" else f"{source}_check"
    answer_hash = content_hash(
        f"recall|{workspace}|{card}|{source}|{answer_mode}|{delay_days:.4f}|{_now_iso()}"
    )
    attempt = store.start_recall_attempt(
        workspace_id=workspace,
        card_id=card,
        assistance_level=assistance_level,
    )
    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        caller_workspace_id=workspace,
        artifact_hash=answer_hash,
        result="passed" if correct else "failed",
        trust_level="controlled_check",
        runner_version=f"trainer-{source}",
        execution_location="session",
        dimension=dimension,
        evidence_kind=evidence_kind,
        recall_delay_days=delay_days if dimension == "delayed_recall" else None,
        failure_reason=None if correct else (detail or "The recall answer did not match the answer key."),
    )
    if evidence is None:
        return None
    # Imported lazily: this module is called while Training routes are already
    # loading the API package.
    from ..api.training_skill_evidence import persist_skill_projection

    persist_skill_projection(runtime, workspace, attempt["attempt_id"])
    return {
        "evidence_id": evidence.get("evidence_id"),
        "dimension": dimension,
        "delay_days": round(delay_days, 4),
        "delayed_recall": delayed,
        "scheduled": scheduled,
    }
