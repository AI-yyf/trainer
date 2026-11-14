"""Keep the active recall review separate from the previous coding exercise."""

from __future__ import annotations

import re
from typing import Any

from ..core.models import MemorySnapshot, ReviewArtifactSnapshot

_PREVIOUS_PRACTICE_KEYS = {
    "active_training_card_routing", "training_card_candidates", "training_event_ledger",
    "latest_training_handoff", "latest_training_next_hop", "live_training_selection",
    "latest_learning_verified_result", "latest_learning_blocker", "latest_learning_followup",
    "selected_card_id", "selected_card_type", "selected_card_title", "selected_card_status",
}
_RECALL_FOLLOWUP = re.compile(
    r"(?:刚(?:刚)?|这次|本次|上次|刚才).{0,12}(?:复习|回忆|闪卡)|"
    r"(?:just (?:finished|completed|answered)|(?:this|last|my))\b.{0,55}\b(?:review|recall|flashcard)",
    re.I,
)


def _card_implementation_evidence(memory: MemorySnapshot, card_id: str) -> dict[str, str] | None:
    projection = memory.workspace.get("training_skill_projection")
    dimensions = projection.get("dimensions") if isinstance(projection, dict) else None
    implementation = dimensions.get("implementation") if isinstance(dimensions, dict) else None
    rows = implementation.get("evidence") if isinstance(implementation, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or row.get("card_id") != card_id:
            continue
        if row.get("trust_level") != "controlled_check" or row.get("verification_recheck_required"):
            continue
        verdict = row.get("result")
        if verdict in {"passed", "failed"}:
            return {"result": str(verdict), "assistance": str(row.get("assistance_level") or "unknown")}
    return None


def active_training_review(
    memory: MemorySnapshot, active_view: str | None,
) -> ReviewArtifactSnapshot | None:
    mode = str(memory.workspace.get("latest_training_submode") or "").replace("_", "-")
    artifact = memory.review_artifact
    if (active_view == "training" and mode in {"review", "review-queue"}
            and artifact is not None and artifact.status != "archived"):
        return artifact
    return None


def apply_training_review_context(
    context: dict[str, Any], memory: MemorySnapshot, active_view: str | None,
) -> dict[str, Any]:
    artifact = active_training_review(memory, active_view)
    if artifact is None:
        message = str(context.get("learner_message") or "")
        if not _RECALL_FOLLOWUP.search(message) or not memory.recent_flash_attempts:
            return context
        attempt = memory.recent_flash_attempts[0]
        card = next((card for card in memory.training_card_candidates if card.card_id == attempt.card_id), None)
        if card is None or not card.question.strip():
            return context
        return {
            **context,
            "recent_recall_result": {
                "card_id": card.card_id,
                "title": card.title,
                "question": card.question,
                "correct": attempt.correct,
                "answer_mode": attempt.answer_mode,
                "detail": attempt.detail,
                "implementation": _card_implementation_evidence(memory, card.card_id),
            },
        }
    result = dict(context)
    result.update({
        "current_focus": artifact.focus_area,
        "summary": artifact.summary,
        "next_step": artifact.guardrail or artifact.next_self_implementation_rule,
        "next_step_hint": artifact.guardrail or artifact.next_self_implementation_rule,
        "first_turn_priority": (
            "Evaluate only this recall's prompt and answer; ignore old coding checks. "
            "A recorded review is self-reported recall, not a passed file check or a coding handoff. "
            "Do not reuse "
            "the previous practice card's requirements, outputs, or verification status."
        ),
        "review_artifact": artifact.model_dump(mode="json"),
        "review_evidence_scope": "self_reported_recall",
        "active_task": None,
        "exercise_prompt": None,
        "implementation_guide": None,
        "project_adaptation_guide": None,
        "coaching_state": None,
        "teaching_decision": None,
        "teaching_mode_strategy": {},
        "coaching_adaptation": None,
        "plan_runtime_recovery": None,
        "active_thread": None,
        "continuity_summary": "",
        "history_mode": "fresh_lane",
        "active_stage": None,
        "current_file_name": None,
        "review_rhythm": "",
        "review_queue_summary": "",
        "due_reviews": [],
        "due_review_count": 0,
        "top_weakness": "",
        "weak_spots": [],
        "failing_checks": [],
        "memory_evidence": [],
        "recent_teaching_signals": [],
        "teaching_observations": [],
        "recalled_memory_summary": "",
    })
    previous_memory = context.get("memory")
    if isinstance(previous_memory, dict):
        cleaned = {key: value for key, value in previous_memory.items()
                   if key not in _PREVIOUS_PRACTICE_KEYS}
        workspace = cleaned.get("workspace")
        if isinstance(workspace, dict):
            cleaned["workspace"] = {key: value for key, value in workspace.items()
                                    if key not in _PREVIOUS_PRACTICE_KEYS}
        cleaned["current_focus"] = artifact.focus_area
        cleaned["active_thread"] = None
        cleaned["review_artifact"] = artifact.model_dump(mode="json")
        cleaned.update({
            "review_rhythm": "", "review_queue_summary": "", "due_reviews": [],
            "due_review_count": 0, "weaknesses": [], "top_weakness": "",
            "recent_summary": "", "recent_wins": [], "memory_evidence": [],
            "recent_teaching_signals": [], "teaching_observations": [],
            "learning_outcomes": [], "coaching_adaptation": None,
        })
        result["memory"] = cleaned
    for key in _PREVIOUS_PRACTICE_KEYS:
        result.pop(key, None)
    result["coach_focus"] = {"current_focus": artifact.focus_area, "summary": artifact.summary,
                             "next_step": artifact.guardrail, "active_task": None}
    return result
