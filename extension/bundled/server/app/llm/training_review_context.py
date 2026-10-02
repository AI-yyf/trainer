"""Keep the active recall review separate from the previous coding exercise."""

from __future__ import annotations

from typing import Any

from ..core.models import MemorySnapshot, ReviewArtifactSnapshot

_PREVIOUS_PRACTICE_KEYS = {
    "active_training_card_routing", "training_card_candidates", "training_event_ledger",
    "latest_training_handoff", "latest_training_next_hop", "live_training_selection",
    "latest_learning_verified_result", "latest_learning_blocker", "latest_learning_followup",
    "selected_card_id", "selected_card_type", "selected_card_title", "selected_card_status",
}


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
        return context
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
