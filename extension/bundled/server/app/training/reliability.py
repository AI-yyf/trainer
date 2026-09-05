"""Authoritative training/handoff reliability transitions.

The webview host ack is not current truth. Persist this record on the workspace
and advance it through:

    intent → pending → executing → succeeded|failed → acked
                                          ↘ cancelled
    failed|cancelled → pending (recover)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

ReliabilityPhase = Literal[
    "intent",
    "pending",
    "executing",
    "succeeded",
    "failed",
    "acked",
    "cancelled",
]
ReliabilityOutcome = Literal["success", "failure", "cancelled", "timeout", ""]

RELIABILITY_PHASES: frozenset[str] = frozenset(
    {"intent", "pending", "executing", "succeeded", "failed", "acked", "cancelled"}
)
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "intent": frozenset({"pending", "cancelled"}),
    "pending": frozenset({"executing", "cancelled", "failed"}),
    "executing": frozenset({"succeeded", "failed", "cancelled"}),
    "succeeded": frozenset({"acked"}),
    "failed": frozenset({"pending"}),
    "cancelled": frozenset({"pending"}),
    "acked": frozenset({"pending"}),
}
IN_FLIGHT_PHASES: frozenset[str] = frozenset({"intent", "pending", "executing"})
SUCCESS_PHASES: frozenset[str] = frozenset({"succeeded", "acked"})
RECOVERABLE_PHASES: frozenset[str] = frozenset({"failed", "cancelled"})

DEFAULT_TIMEOUT_MS = 30_000
WORKSPACE_RELIABILITY_KEY = "latest_training_reliability"
WORKSPACE_SNAPSHOT_REVISION_KEY = "training_snapshot_revision"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_PHASE_BY_NAME: dict[str, ReliabilityPhase] = {
    "intent": "intent",
    "pending": "pending",
    "executing": "executing",
    "succeeded": "succeeded",
    "failed": "failed",
    "acked": "acked",
    "cancelled": "cancelled",
}


def normalize_phase(value: str | None) -> ReliabilityPhase | None:
    return _PHASE_BY_NAME.get((value or "").strip().lower().replace("-", "_"))


def can_transition(current: str, nxt: str) -> bool:
    return nxt in ALLOWED_TRANSITIONS.get(current, frozenset())


def is_in_flight(phase: str | None) -> bool:
    return (phase or "") in IN_FLIGHT_PHASES


def is_authoritative_success(phase: str | None) -> bool:
    return (phase or "") in SUCCESS_PHASES


def parse_iso(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_expired(record: dict[str, Any], now: datetime | None = None) -> bool:
    if not is_in_flight(str(record.get("phase") or "")):
        return False
    timeout_at = parse_iso(str(record.get("timeout_at") or record.get("timeoutAt") or ""))
    if timeout_at is None:
        return False
    current = now or utc_now()
    if timeout_at.tzinfo is None:
        timeout_at = timeout_at.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current >= timeout_at


def same_identity(record: dict[str, Any], request_id: str, idempotency_key: str) -> bool:
    normalized_request = request_id.strip()
    normalized_key = idempotency_key.strip() or normalized_request
    record_request = str(record.get("request_id") or record.get("requestId") or "").strip()
    record_key = str(record.get("idempotency_key") or record.get("idempotencyKey") or "").strip()
    if normalized_request and record_request == normalized_request:
        return True
    return bool(normalized_key and record_key == normalized_key)


def should_replay(record: dict[str, Any] | None, request_id: str, idempotency_key: str) -> bool:
    if not record:
        return False
    if not same_identity(record, request_id, idempotency_key):
        return False
    return is_authoritative_success(str(record.get("phase") or ""))


def should_coalesce(
    record: dict[str, Any] | None,
    *,
    request_id: str,
    command_id: str,
    card_id: str,
    now: datetime | None = None,
) -> bool:
    if not record or not is_in_flight(str(record.get("phase") or "")) or is_expired(record, now):
        return False
    if same_identity(record, request_id, request_id):
        return True
    record_command = str(record.get("command_id") or record.get("commandId") or "")
    record_card = str(record.get("card_id") or record.get("cardId") or "")
    return record_command == command_id and record_card == card_id


def begin_record(
    *,
    request_id: str,
    command_id: str,
    card_id: str = "",
    handoff_id: str = "",
    idempotency_key: str = "",
    revision: int = 1,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    learning_phase: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    bounded_timeout = max(1_000, min(int(timeout_ms or DEFAULT_TIMEOUT_MS), 120_000))
    normalized_request = request_id.strip()
    if not normalized_request:
        normalized_request = f"training-reliability-{command_id}-{int(current.timestamp() * 1000)}"
    normalized_key = idempotency_key.strip() or normalized_request
    return {
        "request_id": normalized_request,
        "idempotency_key": normalized_key,
        "command_id": command_id,
        "card_id": card_id.strip(),
        "handoff_id": handoff_id.strip(),
        "phase": "intent",
        "revision": max(1, int(revision or 1)),
        "snapshot_revision": 0,
        "created_at": current.isoformat(),
        "updated_at": current.isoformat(),
        "acked_at": "",
        "timeout_at": (current + timedelta(milliseconds=bounded_timeout)).isoformat(),
        "cancel_requested": False,
        "outcome": "",
        "error": "",
        "recoverable": False,
        "recovery_action": "",
        "learning_phase": learning_phase.strip(),
    }


def transition(
    record: dict[str, Any],
    nxt: ReliabilityPhase,
    *,
    now: datetime | None = None,
    **patch: Any,
) -> dict[str, Any]:
    current = str(record.get("phase") or "")
    if not can_transition(current, nxt):
        raise ValueError(f"Training reliability cannot move from {current} to {nxt}.")
    updated = dict(record)
    updated.update({key: value for key, value in patch.items() if value is not None})
    updated["phase"] = nxt
    updated["updated_at"] = (now or utc_now()).isoformat()
    return updated


def expire_if_needed(record: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any] | None:
    if not record or not is_expired(record, now):
        return record
    return transition(
        record,
        "failed",
        now=now,
        outcome="timeout",
        error="Training persistence timed out.",
        recoverable=True,
        recovery_action="retry",
    )


def request_cancel(record: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    phase = str(record.get("phase") or "")
    if is_authoritative_success(phase):
        return dict(record)
    if phase in {"failed", "cancelled"}:
        updated = dict(record)
        updated["cancel_requested"] = True
        updated["updated_at"] = (now or utc_now()).isoformat()
        return updated
    cancelled = transition(
        record,
        "cancelled",
        now=now,
        cancel_requested=True,
        outcome="cancelled",
        error="Training persistence was cancelled.",
        recoverable=True,
        recovery_action="retry",
    )
    return cancelled


def recover_record(
    record: dict[str, Any],
    *,
    request_id: str,
    revision: int = 0,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    now: datetime | None = None,
) -> dict[str, Any]:
    phase = str(record.get("phase") or "")
    if phase not in RECOVERABLE_PHASES:
        raise ValueError("Only a failed or cancelled training request can be recovered.")
    current = now or utc_now()
    next_revision = revision if revision > 0 else int(record.get("revision") or 1) + 1
    bounded_timeout = max(1_000, min(int(timeout_ms or DEFAULT_TIMEOUT_MS), 120_000))
    recovered = transition(
        record,
        "pending",
        now=current,
        request_id=request_id.strip() or str(record.get("request_id") or ""),
        revision=next_revision,
        timeout_at=(current + timedelta(milliseconds=bounded_timeout)).isoformat(),
        cancel_requested=False,
        outcome="",
        error="",
        recoverable=False,
        recovery_action="",
        acked_at="",
    )
    return recovered


def mark_executing(record: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    phase = str(record.get("phase") or "")
    current = record
    if phase == "intent":
        current = transition(current, "pending", now=now)
        phase = "pending"
    if phase == "pending":
        return transition(current, "executing", now=now)
    if phase == "executing":
        return dict(current)
    raise ValueError(f"Training reliability cannot start executing from {phase}.")


def mark_succeeded(
    record: dict[str, Any],
    *,
    snapshot_revision: int,
    learning_phase: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    if record.get("cancel_requested") and not is_authoritative_success(str(record.get("phase") or "")):
        return request_cancel(record, now=now)
    if is_expired(record, now):
        expired = expire_if_needed(record, now)
        return expired or record
    succeeded = transition(
        record,
        "succeeded",
        now=now,
        outcome="success",
        error="",
        recoverable=False,
        recovery_action="",
        snapshot_revision=snapshot_revision,
        learning_phase=learning_phase or record.get("learning_phase") or "",
    )
    return mark_acked(succeeded, now=now)


def mark_failed(
    record: dict[str, Any],
    error: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if is_authoritative_success(str(record.get("phase") or "")):
        return dict(record)
    phase = str(record.get("phase") or "")
    current = record
    if phase == "intent":
        current = transition(current, "pending", now=now)
        current = transition(current, "executing", now=now)
    elif phase == "pending":
        current = transition(current, "executing", now=now)
    return transition(
        current,
        "failed",
        now=now,
        outcome="failure",
        error=error.strip() or "Training persistence failed.",
        recoverable=True,
        recovery_action="retry",
    )


def mark_acked(record: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = now or utc_now()
    return transition(record, "acked", now=current, acked_at=current.isoformat())


def as_workspace_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": str(record.get("request_id") or ""),
        "idempotency_key": str(record.get("idempotency_key") or ""),
        "command_id": str(record.get("command_id") or ""),
        "card_id": str(record.get("card_id") or ""),
        "handoff_id": str(record.get("handoff_id") or ""),
        "phase": str(record.get("phase") or ""),
        "revision": int(record.get("revision") or 1),
        "snapshot_revision": int(record.get("snapshot_revision") or 0),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
        "acked_at": str(record.get("acked_at") or ""),
        "timeout_at": str(record.get("timeout_at") or ""),
        "cancel_requested": bool(record.get("cancel_requested")),
        "outcome": str(record.get("outcome") or ""),
        "error": str(record.get("error") or ""),
        "recoverable": bool(record.get("recoverable")),
        "recovery_action": str(record.get("recovery_action") or ""),
        "learning_phase": str(record.get("learning_phase") or ""),
    }
