from __future__ import annotations

from datetime import datetime
from typing import Any

from ..core.models import EvidenceItem
from ..workspace.remote_identity import validate_remote_verification_artifact


def _time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def restore_return_artifact(
    workspace: dict[str, Any], items: dict[str, EvidenceItem],
) -> dict[str, EvidenceItem]:
    """Recover one previously stripped field from matching trusted persisted facts."""
    latest = workspace.get("latest_training_verification")
    handoff = workspace.get("latest_training_handoff")
    if not isinstance(latest, dict) or not isinstance(handoff, dict):
        return items
    card_id = latest.get("card_id")
    if (
        not card_id or latest.get("passed") is not True or handoff.get("card_id") != card_id
        or handoff.get("status") != "completed" or handoff.get("learning_phase") != "return"
        or handoff.get("verification_state") != "verified"
    ):
        return items
    project = str(workspace.get("canonical_project_path") or "")
    try:
        artifact = validate_remote_verification_artifact(latest.get("verification_artifact"), project)
        handoff_artifact = validate_remote_verification_artifact(handoff.get("verification_artifact"), project)
    except ValueError:
        return items
    if artifact != handoff_artifact:
        return items
    returned_at = _time(handoff.get("returned_at"))
    evidence = handoff.get("evidence")
    if not isinstance(evidence, list) or not handoff.get("return_summary"):
        return items
    trusted = [row for row in evidence if isinstance(row, dict)
               and row.get("card_id") == card_id and row.get("verified") is True
               and row.get("source") == "test_runner"
               and row.get("verification_source") == "test_runner"
               and row.get("content") == handoff.get("return_summary")]
    if len(trusted) != 1 or returned_at is None:
        return items
    verified_at = _time(trusted[0].get("verified_at"))
    if verified_at is None or verified_at > returned_at:
        return items
    matching = [item for item in items.values()
                if item.source_card_id == card_id and item.verified
                and item.source == "training_handoff_return"
                and item.workspace_id == workspace.get("workspace_id")
                and item.verification_source == "test_runner"
                and item.summary == handoff.get("return_summary")
                and (stamp := _time(item.timestamp)) is not None
                and verified_at <= stamp <= returned_at]
    if len(matching) != 1 or matching[0].verification_artifact is not None:
        return items
    original = matching[0]
    return {**items, original.id: original.model_copy(update={"verification_artifact": artifact})}
