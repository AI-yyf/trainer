"""Recognize feedback on an already returned, unchanged verified artifact."""

from __future__ import annotations

import ntpath
import re
from pathlib import Path
from typing import Any

from ..training.attempt_store import content_hash


def completed_return_feedback(runtime: Any, workspace_id: str, request: Any) -> bool:
    memory = runtime.memory_service.snapshot(workspace_id)
    workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
    handoff = workspace.get("latest_training_handoff")
    current_file = getattr(request, "current_file", None)
    store = runtime.attempt_store
    if not isinstance(handoff, dict) or current_file is None or store is None:
        return False
    title = str(handoff.get("card_title") or "").strip()
    card_id = str(handoff.get("card_id") or "").strip()
    message = str(getattr(request, "message", "") or "")
    if not title or not card_id or title not in message:
        return False
    if not any(term in message.lower() for term in ("评估", "复盘", "反馈", "review", "feedback", "reflection")):
        return False
    # The Return bridge includes past check results ("已重新执行"). Those
    # results are not a request to execute again; a later explicit request is.
    execution_request = re.sub(
        r"(?:已经|已|无需|不必|不要|不用)(?:再)?(?:重跑|重新验证|重新执行)",
        "", message.lower(),
    )
    execution_request = re.sub(
        r"\b(?:already|do not|don't|no need to)\s+(?:re-run|rerun|verify again)\b",
        "", execution_request,
    )
    if any(term in execution_request for term in ("重跑", "重新验证", "重新执行", "re-run", "rerun", "verify again")):
        return False
    if not (
        handoff.get("status") == "completed" and handoff.get("learning_phase") == "return"
        and handoff.get("verification_state") == "verified" and handoff.get("returned_at")
        and handoff.get("reflection")
    ):
        return False

    def canonical(value: str) -> str:
        return ntpath.normcase(ntpath.normpath(value)) if ntpath.splitdrive(value)[0] else str(Path(value).resolve())

    artifact_hash = content_hash(str(current_file.content or ""))
    file_path = canonical(str(current_file.path or ""))
    for attempt in reversed(store.list_attempts(workspace_id=workspace_id, card_id=card_id)):
        if attempt.get("status") != "returned" or attempt.get("file_hash") != artifact_hash:
            continue
        if canonical(str(attempt.get("file_path") or "")) != file_path:
            continue
        return any(
            item.get("is_current") is True and item.get("trust_level") == "controlled_check"
            and item.get("result") == "passed" and item.get("artifact_hash") == artifact_hash
            for item in store.list_evidence(attempt["attempt_id"])
        )
    return False
