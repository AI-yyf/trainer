"""Active card routing service (§13.27).

Deterministic multi-factor scoring algorithm that selects the ONE current
training card from a pool of candidates.  Every decision is explainable:
each candidate gets a score breakdown, blocked candidates carry explicit
reasons, and the result includes ``why_this_card`` and ``why_not_others``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..core.models import (
    ActiveCardSelectionResult,
    BlockedCandidateDetail,
    TrainingCardCandidateSnapshot,
    TrainingCardScoreFactors,
)
from ..memory.workspace_recovery import live_training_card_title, live_training_why_this_card
from ..pedagogy.material_recommendation import (
    apply_material_bias_to_factors,
    routing_from_learner_state,
)

if TYPE_CHECKING:
    from ..core.event_ledger import EventLedgerService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Factor weights — sum to 1.0
# ---------------------------------------------------------------------------

FACTOR_WEIGHTS: dict[str, float] = {
    "plan_relevance": 0.19,
    "blocking_power": 0.17,
    "evidence_gap": 0.17,
    "recency_need": 0.12,
    "resource_trust": 0.08,
    "difficulty_fit": 0.10,
    "project_fit": 0.08,
    "transfer_value": 0.04,
    "recovery_priority": 0.05,
}

FACTOR_LABELS: dict[str, str] = {
    "plan_relevance": "plan relevance",
    "blocking_power": "blocking power",
    "evidence_gap": "evidence gap",
    "recency_need": "review timing",
    "resource_trust": "resource trust",
    "difficulty_fit": "difficulty fit",
    "project_fit": "project fit",
    "transfer_value": "transfer value",
    "recovery_priority": "recovery priority",
}

PRACTICE_FIRST_FLASH_PENALTY = 1.2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float) -> float:
    """Clamp a factor value to [0.0, 1.0]."""
    if not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _has_content(value: str | None) -> bool:
    """Check that a string field has non-empty content."""
    return bool(value and value.strip())


def _has_list_content(value: list | None) -> bool:
    """Check that a list field has non-empty content."""
    return bool(value and len(value) > 0)


def _has_dict_content(value: dict | None) -> bool:
    """Check that a dict field has non-empty content."""
    return bool(value and len(value) > 0)


def _topic_tokens(card: TrainingCardCandidateSnapshot) -> set[str]:
    """Build a small topic signature used to pair practice and flash cards."""
    tokens: set[str] = set()
    for raw in (card.scenario_pack, card.target_skill, card.focus_area):
        cleaned = str(raw or "").strip().lower()
        if cleaned:
            tokens.add(cleaned)
    return tokens


def _shares_learning_topic(
    left: TrainingCardCandidateSnapshot,
    right: TrainingCardCandidateSnapshot,
) -> bool:
    left_tokens = _topic_tokens(left)
    right_tokens = _topic_tokens(right)
    return bool(left_tokens and right_tokens and left_tokens & right_tokens)


def _is_pending_practice_card(card: TrainingCardCandidateSnapshot) -> bool:
    return card.card_type == "practice" and card.status not in {
        "implemented",
        "reviewed",
        "fed_back",
        "archived",
        "skipped",
    }


def _practice_first_score_adjustment(
    card: TrainingCardCandidateSnapshot,
    practice_anchors: list[TrainingCardCandidateSnapshot],
) -> float:
    """Prefer learn-first practice before same-topic flash follow-ups."""
    if card.card_type != "flash":
        return 0.0
    if card.created_from in {"review_due", "dependency_mastery"}:
        return 0.0
    for practice_card in practice_anchors:
        if practice_card.card_id == card.card_id:
            continue
        if _shares_learning_topic(card, practice_card):
            return -PRACTICE_FIRST_FLASH_PENALTY
    return 0.0


def _prefer_same_topic_practice_candidate(
    eligible: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Hard-prefer pending same-topic practice before flash follow-ups."""
    if not eligible:
        return None
    top_entry = eligible[0]
    top_card = top_entry["card"]
    if top_card.card_type != "flash":
        return None
    for entry in eligible:
        candidate = entry["card"]
        if candidate.card_type != "practice":
            continue
        if not _is_pending_practice_card(candidate):
            continue
        if _shares_learning_topic(top_card, candidate):
            return entry
    return None


def _recency_sort_value(card: TrainingCardCandidateSnapshot) -> float:
    """Prefer the most recently updated/generated card when scores tie."""
    for raw in (card.updated_at, card.created_at):
        cleaned = str(raw or "").strip()
        if not cleaned:
            continue
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return 0.0


def _leftover_runtime_from_plan_state(
    plan_state: dict[str, Any] | None,
) -> tuple[Any, dict[str, Any], str]:
    state = plan_state if isinstance(plan_state, dict) else {}
    leftover_runtime = state.get("leftover_runtime")
    runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
    leftover_task_title = str(state.get("leftover_task_title") or "").strip()
    return state.get("leftover_plan"), runtime, leftover_task_title


def _live_routed_card_title(plan_state: dict[str, Any] | None, card_title: str) -> str:
    leftover_plan, leftover_runtime, leftover_task_title = _leftover_runtime_from_plan_state(
        plan_state
    )
    if leftover_plan is None and not leftover_runtime:
        return card_title
    return live_training_card_title(
        plan=leftover_plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        task_title=leftover_task_title,
        card_title=card_title,
    )


def _live_routed_why_now(plan_state: dict[str, Any] | None, why_now: str) -> str:
    leftover_plan, leftover_runtime, leftover_task_title = _leftover_runtime_from_plan_state(
        plan_state
    )
    if leftover_plan is None and not leftover_runtime:
        return why_now
    return live_training_why_this_card(
        plan=leftover_plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        task_title=leftover_task_title,
        card_title="",
        why_now=why_now,
        kind="current",
    )


# ---------------------------------------------------------------------------
# Blocking conditions
# ---------------------------------------------------------------------------

def _infer_blockers(card: TrainingCardCandidateSnapshot) -> list[str]:
    """Return reasons a card should be blocked from selection."""
    reasons: list[str] = []

    # Untrusted/stale source without explicit acknowledgment
    if card.trust_state in ("untrusted", "stale") and not card.trust_acknowledged:
        reasons.append("resource is not trusted or fresh enough")

    # Practice cards require problem_statement, deliverable, validation_method
    if card.card_type == "practice":
        if not _has_content(card.problem_statement):
            reasons.append("practice problem_statement is missing")
        if not _has_content(card.deliverable):
            reasons.append("practice deliverable is missing")
        if not _has_content(card.validation_method):
            reasons.append("practice validation_method is missing")

    # Flash cards require expected_answer (standard_answer) and hint_ladder
    if card.card_type == "flash":
        if not _has_content(card.expected_answer):
            reasons.append("flash reference answer is missing")
        if not _has_list_content(card.hint_ladder):
            reasons.append("flash hint_ladder is missing")

    # Uncertain project context blocks project-specific practice cards
    if card.requires_project_context and not card.project_context_ready:
        if card.card_type == "practice":
            reasons.append("project context is not ready for practice card")

    # No title at all — card is malformed
    if not _has_content(card.title):
        reasons.append("card title is missing")

    return reasons


# ---------------------------------------------------------------------------
# Factor scoring
# ---------------------------------------------------------------------------

def _compute_factors(
    card: TrainingCardCandidateSnapshot,
    learner_state: dict[str, Any],
    plan_state: dict[str, Any],
) -> TrainingCardScoreFactors:
    """Compute all 9 weighted score factors for a single card.

    Each factor is in [0.0, 1.0].  The algorithm is deterministic and
    purely rule-based — no ML, no randomness.
    """

    # --- plan_relevance (0.19) ---
    # Does the card map to the active plan stage?
    plan_relevance = 0.3  # baseline
    active_stage_id = plan_state.get("active_stage_id", "")
    active_stage_skills = plan_state.get("active_stage_skills", [])
    if isinstance(active_stage_skills, list) and card.target_skill:
        if card.target_skill in active_stage_skills:
            plan_relevance = 1.0
        else:
            plan_relevance = 0.4
    if card.plan_links and active_stage_id:
        if active_stage_id in card.plan_links:
            plan_relevance = 1.0
    if card.created_from == "plan":
        plan_relevance = max(plan_relevance, 0.85)
    if not plan_state:
        plan_relevance = 0.5  # no plan context, neutral

    # --- blocking_power (0.17) ---
    # Does this card represent an unresolved blocker to progression?
    blocking_power = 0.2  # baseline
    if card.created_from == "dependency_mastery":
        blocking_power = 0.9  # unmastered prerequisite blocks advancement
    if card.created_from == "practice_feedback":
        blocking_power = max(blocking_power, 0.6)
    blockers = learner_state.get("active_blockers", [])
    if isinstance(blockers, list) and card.target_skill:
        if card.target_skill in blockers:
            blocking_power = 1.0

    # --- evidence_gap (0.17) ---
    # What evidence is missing?  Cards targeting knowledge gaps score higher.
    evidence_gap = 0.3
    weaknesses = learner_state.get("weaknesses", [])
    if isinstance(weaknesses, list) and card.focus_area:
        if card.focus_area in weaknesses:
            evidence_gap = 0.9
        elif card.target_skill and card.target_skill in weaknesses:
            evidence_gap = 0.85
    if card.created_from == "conversation":
        evidence_gap = max(evidence_gap, 0.5)  # conversation gaps are moderate evidence gaps
    if card.created_from == "resource":
        evidence_gap = max(evidence_gap, 0.5)

    # --- recency_need (0.12) ---
    # Due review or recent errors boost this factor.
    recency_need = 0.2
    if card.created_from == "review_due":
        recency_need = 1.0
    if card.created_from == "practice_feedback":
        recency_need = max(recency_need, 0.8)
    recent_errors = learner_state.get("recent_errors", [])
    if isinstance(recent_errors, list) and card.focus_area:
        if card.focus_area in recent_errors:
            recency_need = max(recency_need, 0.85)

    # --- resource_trust (0.08) ---
    # Source credibility.  Directly from trust_state if available.
    resource_trust = 0.5  # baseline neutral
    if card.trust_state == "trusted":
        resource_trust = 1.0
    elif card.trust_state == "fresh":
        resource_trust = 0.8
    elif card.trust_state == "unknown":
        resource_trust = 0.5
    elif card.trust_state == "stale":
        resource_trust = 0.3
    elif card.trust_state == "untrusted":
        resource_trust = 0.0
    # Cards not from resource sources get moderate trust
    if card.created_from not in ("resource",):
        resource_trust = 0.6

    # --- difficulty_fit (0.10) ---
    # Does the card difficulty match the learner's state?
    difficulty_fit = 0.5
    learner_level = learner_state.get("difficulty_preference", "medium")
    card_difficulty = card.difficulty or "medium"
    diff_map = {"easy": 1, "medium": 2, "hard": 3}
    learner_idx = diff_map.get(str(learner_level), 2)
    card_idx = diff_map.get(str(card_difficulty), 2)
    # Perfect match = 1.0, off by 1 = 0.6, off by 2 = 0.2
    gap = abs(learner_idx - card_idx)
    if gap == 0:
        difficulty_fit = 1.0
    elif gap == 1:
        difficulty_fit = 0.6
    else:
        difficulty_fit = 0.2
    # If learner is blocked/frustrated, prefer easy cards
    if learner_state.get("needs_rescue"):
        if card_difficulty == "easy":
            difficulty_fit = 1.0
        elif card_difficulty == "medium":
            difficulty_fit = 0.5
        else:
            difficulty_fit = 0.1

    # --- project_fit (0.08) ---
    # Does this card belong to the current project training lane?
    project_fit = 0.5
    active_project = plan_state.get("active_project_id", "")
    if card.project_id and active_project:
        if card.project_id == active_project:
            project_fit = 1.0
        else:
            project_fit = 0.3  # different project, deprioritize
    elif card.project_id and not active_project:
        project_fit = 0.3  # card wants a project but we don't have one
    elif not card.project_id:
        project_fit = 0.6  # cross-project card, moderate

    # --- transfer_value (0.04) ---
    # Cross-project benefit.
    transfer_value = 0.3
    if card.created_from == "resource":
        transfer_value = 0.8  # resource knowledge transfers well
    if card.knowledge_type in ("engineering_concept", "principle"):
        transfer_value = max(transfer_value, 0.7)
    if card.focus_area and card.created_from == "conversation":
        transfer_value = max(transfer_value, 0.5)

    # --- recovery_priority (0.05) ---
    # Post-failure recovery card.
    recovery_priority = 0.1
    if card.created_from == "recovery":
        recovery_priority = 1.0
    if card.created_from == "practice_feedback":
        recovery_priority = max(recovery_priority, 0.7)
    if learner_state.get("needs_rescue") and card.difficulty == "easy":
        recovery_priority = max(recovery_priority, 0.8)

    routing = routing_from_learner_state(learner_state)
    difficulty_fit, project_fit, transfer_value, recovery_priority = apply_material_bias_to_factors(
        created_from=str(card.created_from or ""),
        difficulty=str(card.difficulty or "medium"),
        project_id=str(card.project_id or ""),
        active_project_id=str(active_project or ""),
        knowledge_type=str(card.knowledge_type or ""),
        routing=routing,
        difficulty_fit=difficulty_fit,
        project_fit=project_fit,
        transfer_value=transfer_value,
        recovery_priority=recovery_priority,
    )

    return TrainingCardScoreFactors(
        plan_relevance=_clamp(plan_relevance),
        blocking_power=_clamp(blocking_power),
        evidence_gap=_clamp(evidence_gap),
        recency_need=_clamp(recency_need),
        resource_trust=_clamp(resource_trust),
        difficulty_fit=_clamp(difficulty_fit),
        project_fit=_clamp(project_fit),
        transfer_value=_clamp(transfer_value),
        recovery_priority=_clamp(recovery_priority),
    )


def _weighted_score(factors: TrainingCardScoreFactors) -> float:
    """Compute weighted sum of factors. Returns value in [0, 100]."""
    total = 0.0
    for key, weight in FACTOR_WEIGHTS.items():
        total += getattr(factors, key, 0.0) * weight
    # Scale to 0-100 range for readability
    return round(total * 100, 1)


def _top_factor_labels(factors: TrainingCardScoreFactors, limit: int = 3) -> list[str]:
    """Return labels for the strongest scoring factors."""
    factor_values = {
        key: getattr(factors, key, 0.0)
        for key in FACTOR_WEIGHTS
    }
    sorted_keys = sorted(factor_values, key=lambda k: factor_values[k], reverse=True)
    return [FACTOR_LABELS.get(k, k) for k in sorted_keys[:limit]]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CardRouterService:
    """Selects the ONE active training card from a pool of candidates.

    The algorithm is deterministic and testable:
    1. Compute blockers for each candidate.
    2. Compute weighted score factors for each unblocked candidate.
    3. Rank by weighted score (ties broken by recovery_priority, then card_id).
    4. Return the top candidate with full explainability.
    """

    def __init__(self, event_ledger: EventLedgerService | None = None) -> None:
        self._event_ledger = event_ledger

    def select_active_card(
        self,
        candidates: list[TrainingCardCandidateSnapshot],
        learner_state: dict[str, Any],
        plan_state: dict[str, Any],
        *,
        pure_conversation_mode: bool = False,
        fallback_action: str = "",
        next_after_completion: str = "",
    ) -> ActiveCardSelectionResult:
        """Select the best active card from *candidates*.

        Parameters
        ----------
        candidates:
            List of card candidate snapshots to evaluate.
        learner_state:
            Dict with learner context: weaknesses, recent_errors, difficulty_preference,
            needs_rescue, active_blockers, etc.
        plan_state:
            Dict with plan context: active_stage_id, active_stage_skills,
            active_project_id, etc.
        pure_conversation_mode:
            When True, skip active card selection entirely.
        fallback_action:
            Override for the fallback action message.
        next_after_completion:
            Override for the next-after-completion message.

        Returns
        -------
        ActiveCardSelectionResult with full explainability.
        """
        # Step 1: Pure conversation mode — no active card
        if pure_conversation_mode:
            return self._empty_result(
                candidates=candidates,
                learner_state=learner_state,
                plan_state=plan_state,
                pure_conversation_mode=True,
                fallback_action=fallback_action,
                next_after_completion=next_after_completion,
            )

        # Step 2: Identify blocked candidates
        blocked_details: list[BlockedCandidateDetail] = []
        blocked_ids: set[str] = set()

        for card in candidates:
            card_id = card.card_id or ""
            reasons = _infer_blockers(card)
            if reasons:
                blocked_ids.add(card_id)
                blocked_details.append(BlockedCandidateDetail(
                    card_id=card_id,
                    card_type=card.card_type,
                    title=card.title or "(untitled)",
                    reasons=reasons,
                ))

        # Step 3: Score eligible candidates
        eligible_practice_anchors = [
            card
            for card in candidates
            if (card.card_id or "") not in blocked_ids and _is_pending_practice_card(card)
        ]
        eligible: list[dict[str, Any]] = []
        for card in candidates:
            card_id = card.card_id or ""
            if card_id in blocked_ids:
                continue
            factors = _compute_factors(card, learner_state, plan_state)
            score = round(
                _weighted_score(factors)
                + _practice_first_score_adjustment(card, eligible_practice_anchors),
                1,
            )
            eligible.append({
                "card": card,
                "card_id": card_id,
                "score": score,
                "factors": factors,
            })

        # Step 4: Sort — score desc, then recovery_priority desc, then card_id asc
        eligible.sort(
            key=lambda e: (
                -e["score"],
                -e["factors"].recovery_priority,
                -_recency_sort_value(e["card"]),
                e["card_id"],
            )
        )

        if not eligible:
            return self._empty_result(
                candidates=candidates,
                learner_state=learner_state,
                plan_state=plan_state,
                pure_conversation_mode=False,
                fallback_action=fallback_action,
                next_after_completion=next_after_completion,
                blocked_details=blocked_details,
            )

        # Step 5: Select the top candidate
        selected = _prefer_same_topic_practice_candidate(eligible) or eligible[0]
        selected_card = selected["card"]
        selected_score = selected["score"]
        selected_factors = selected["factors"]
        ordered_eligible = [selected, *[entry for entry in eligible if entry is not selected]]

        # Build why_this_card
        top_labels = _top_factor_labels(selected_factors)
        routing = routing_from_learner_state(learner_state)
        live_title = _live_routed_card_title(plan_state, selected_card.title or "")
        gated_why_now = _live_routed_why_now(plan_state, selected_card.why_now or "")
        why_this_card = (
            gated_why_now
            or f"{live_title or 'Selected card'} is active because "
            f"{', '.join(top_labels)} are the strongest signals."
        )
        if not gated_why_now and routing.rank_reason and routing.rank_reason not in why_this_card:
            why_this_card = f"{why_this_card} {routing.rank_reason}".strip()

        # Build why_not_others
        why_not_others: list[str] = []
        for entry in ordered_eligible[1:4]:
            gap = round(selected_score - entry["score"], 1)
            other_title = _live_routed_card_title(plan_state, entry["card"].title or "") or "(untitled)"
            other_strongest = _top_factor_labels(entry["factors"], 1)
            strong_label = other_strongest[0] if other_strongest else "score"
            why_not_others.append(
                f"{other_title} scored {gap} point(s) lower; "
                f"strongest signal was {strong_label}."
            )
        for blocked in blocked_details[:4]:
            reason = blocked.reasons[0] if blocked.reasons else "blocked"
            blocked_title = _live_routed_card_title(plan_state, blocked.title) or "(untitled)"
            why_not_others.append(
                f"{blocked_title} was blocked: {reason}."
            )

        default_fallback = (
            "If this card stalls, return to coach chat with the exact "
            "blocker and verification output."
        )
        default_next = (
            "Record the attempt, update evidence, then route the next "
            "practice or flash card."
        )
        selected_next_after_completion = (
            selected_card.next_after_completion.strip()
            if _has_content(selected_card.next_after_completion)
            else ""
        )

        result = ActiveCardSelectionResult(
            selected_card=selected_card,
            selected_card_id=selected["card_id"] or None,
            selection_score=selected_score,
            score_factors=selected_factors,
            why_this_card=why_this_card,
            why_not_others=why_not_others,
            blocked_candidates=blocked_details,
            fallback_action=fallback_action or default_fallback,
            next_after_completion=selected_next_after_completion
            or next_after_completion
            or routing.next_step
            or default_next,
            candidate_count=len(candidates),
            eligible_count=len(eligible),
        )

        # §13.21 Record active card selection event
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "active_card_selected",
                actor="system",
                scope="card",
                source_chain=["card_router"],
                payload_ref={
                    "selected_card_id": selected["card_id"],
                    "selection_score": selected_score,
                    "candidate_count": len(candidates),
                    "eligible_count": len(eligible),
                    "blocked_count": len(blocked_details),
                },
                before_state_ref={},
                after_state_ref={
                    "selected_card_id": selected["card_id"],
                    "score": selected_score,
                },
                reversibility="reversible",
                audit_note=f"Active card selected: {selected['card_id']} with score {selected_score}",
            )

        return result

    def _empty_result(
        self,
        candidates: list[TrainingCardCandidateSnapshot],
        learner_state: dict[str, Any],
        plan_state: dict[str, Any],
        *,
        pure_conversation_mode: bool = False,
        fallback_action: str = "",
        next_after_completion: str = "",
        blocked_details: list[BlockedCandidateDetail] | None = None,
    ) -> ActiveCardSelectionResult:
        """Build an empty result when no eligible card can be selected."""
        blocked = blocked_details or []
        why = (
            "Training is paused because the user is in pure conversation mode."
            if pure_conversation_mode
            else "No eligible training card can be activated yet."
        )
        why_not = [
            f"{_live_routed_card_title(plan_state, b.title) or '(untitled)'}: {b.reasons[0]}"
            for b in blocked
        ]
        return ActiveCardSelectionResult(
            selected_card_id=None,
            selection_score=0.0,
            why_this_card=why,
            why_not_others=why_not,
            blocked_candidates=blocked,
            fallback_action=fallback_action or (
                "Stay in coach chat and clarify the next training card."
            ),
            next_after_completion=next_after_completion or (
                "Create an eligible practice or flash card before advancing mastery."
            ),
            candidate_count=len(candidates),
            eligible_count=0,
        )
