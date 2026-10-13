"""Training-reliability domain mixin for :class:`MemoryService`.

Request replay/coalesce/cancel/recover lifecycle for live training saves —
the ``training.reliability`` record persisted under the workspace's
``latest_training_reliability`` key. Methods are extracted verbatim from
``memory/service.py`` (pure code motion, zero behavior change); the shared
``MemoryService`` state they touch is declared under ``TYPE_CHECKING`` only
and is assigned in ``MemoryService.__init__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ..training.reliability import (
    TRAINING_RELIABILITY_DEDUPE_KEY,
    WORKSPACE_RELIABILITY_KEY,
    WORKSPACE_SNAPSHOT_REVISION_KEY,
    as_workspace_record,
    begin_record,
    dedupe_entry_for,
    expire_if_needed,
    is_in_flight,
    mark_executing,
    mark_failed,
    mark_succeeded,
    record_dedupe_entry,
    recover_record,
    request_cancel,
    should_coalesce,
    should_replay,
    training_dedupe_key,
)

if TYPE_CHECKING:
    from .service import StructuredMemoryService


class TrainingReliabilityMixin:
    """Hosts the training-reliability domain methods of ``MemoryService``."""

    if TYPE_CHECKING:
        # Shared MemoryService collaborators used by the methods below.
        def _resolve_workspace_for_write(self, workspace_id: str | None) -> str: ...
        def _structured_for(self, workspace_id: str) -> StructuredMemoryService: ...
        def _persist_structured(self, workspace_id: str) -> None: ...
        def _iter_structured_workspaces(self) -> list[tuple[str, StructuredMemoryService]]: ...

    def _load_training_reliability(self, structured: StructuredMemoryService) -> dict[str, Any] | None:
        payload = structured._workspace.get(WORKSPACE_RELIABILITY_KEY)
        return dict(payload) if isinstance(payload, dict) else None

    def _load_training_dedupe(self, structured: StructuredMemoryService) -> dict[str, Any]:
        payload = structured._workspace.get(TRAINING_RELIABILITY_DEDUPE_KEY)
        return dict(payload) if isinstance(payload, dict) else {}

    def _save_training_reliability(
        self,
        workspace_id: str,
        structured: StructuredMemoryService,
        record: dict[str, Any],
        dedupe: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot_revision = int(record.get("snapshot_revision") or 0)
        fields: dict[str, Any] = {
            WORKSPACE_RELIABILITY_KEY: as_workspace_record(record),
            WORKSPACE_SNAPSHOT_REVISION_KEY: snapshot_revision or None,
        }
        if dedupe is not None:
            fields[TRAINING_RELIABILITY_DEDUPE_KEY] = dedupe
        workspace = structured.update_workspace(
            workspace_id=workspace_id,
            **fields,
        )
        self._persist_structured(workspace_id)
        return dict(workspace)

    def _cancel_raced_work(
        self,
        record: dict[str, Any],
        structured: StructuredMemoryService,
    ) -> bool:
        """Did a cancel for this same work land on the slot while work ran?

        The local record snapshot cannot see a cancel that was persisted while
        ``work()`` was executing, so the finish line checks the slot — but only
        when the slot still belongs to the same work identity (request id or
        idempotency key), never a neighbouring request's record.
        """
        persisted = self._load_training_reliability(structured)
        if not isinstance(persisted, dict):
            return False
        same_request = str(persisted.get("request_id") or "") == str(record.get("request_id") or "")
        same_key = str(persisted.get("idempotency_key") or "") == str(
            record.get("idempotency_key") or ""
        )
        if not (same_request or same_key):
            return False
        if bool(persisted.get("cancel_requested")):
            return True
        return str(persisted.get("phase") or "") == "cancelled"

    def latest_training_reliability(self, workspace_id: str) -> dict[str, Any] | None:
        structured = self._structured_for(self._resolve_workspace_for_write(workspace_id))
        record = expire_if_needed(self._load_training_reliability(structured))
        if record is None:
            return None
        if record != self._load_training_reliability(structured):
            self._save_training_reliability(workspace_id, structured, record)
        return as_workspace_record(record)

    def cancel_training_reliability(
        self,
        workspace_id: str,
        *,
        request_id: str,
        command_id: str = "",
        card_id: str = "",
    ) -> dict[str, Any]:
        resolved = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved)
        record = expire_if_needed(self._load_training_reliability(structured))
        if record is None:
            raise LookupError("No training reliability request is available to cancel.")
        if request_id.strip() and str(record.get("request_id") or "") != request_id.strip():
            if command_id and str(record.get("command_id") or "") != command_id:
                raise LookupError("The cancel request does not match the current training save.")
            if card_id and str(record.get("card_id") or "") != card_id:
                raise LookupError("The cancel request does not match the current training card.")
        cancelled = request_cancel(record)
        return self._save_training_reliability(resolved, structured, cancelled)

    def recover_training_reliability(
        self,
        workspace_id: str,
        *,
        request_id: str,
        revision: int = 0,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        resolved = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved)
        record = expire_if_needed(self._load_training_reliability(structured))
        if record is None:
            raise LookupError("No training reliability request is available to recover.")
        recovered = recover_record(
            record,
            request_id=request_id,
            revision=revision,
            timeout_ms=timeout_ms,
        )
        return self._save_training_reliability(resolved, structured, recovered)

    def expire_training_reliability(self, workspace_id: str) -> dict[str, Any]:
        resolved = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved)
        record = expire_if_needed(self._load_training_reliability(structured))
        if record is None:
            raise LookupError("No training reliability request is available to expire.")
        return self._save_training_reliability(resolved, structured, record)

    def expire_in_flight_training_reliability_at_startup(self) -> list[str]:
        """Expire in-flight training saves orphaned by a previous process.

        A sidecar restart orphans every intent/pending/executing record: the
        process that could complete — or honestly fail — that work is gone.
        Left alone, the stale ``executing`` record lingers on the workspace
        until its timeout elapses (the recorded "延迟可见" defect), so the
        startup sweep transitions it immediately to an honest failed/
        recoverable state. Only in-flight phases are touched: a succeeded or
        acked record is never rewritten, and nothing here fabricates success —
        a retry re-runs the body under its idempotency key, which the
        body-level dedupe ledger keeps from double-recording.
        """
        expired: list[str] = []
        for workspace_id, structured in list(self._iter_structured_workspaces()):
            record = self._load_training_reliability(structured)
            if record is None or not is_in_flight(str(record.get("phase") or "")):
                continue
            # _iter_structured_workspaces yields detached instances for
            # repository-loaded workspaces; writing through such a copy would
            # be discarded when _persist_structured re-loads the cached
            # instance. Discover here, mutate through the live instance.
            live_structured = self._structured_for(workspace_id)
            live_record = self._load_training_reliability(live_structured) or record
            failed = mark_failed(
                live_record,
                "Training persistence was interrupted by a sidecar restart.",
            )
            self._save_training_reliability(workspace_id, live_structured, failed)
            expired.append(workspace_id)
        return expired

    def run_training_reliability(
        self,
        workspace_id: str | None,
        *,
        request_id: str,
        command_id: str,
        card_id: str = "",
        handoff_id: str = "",
        idempotency_key: str = "",
        revision: int = 0,
        timeout_ms: int = 30_000,
        cancel: bool = False,
        learning_phase: str = "",
        work: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        resolved = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved)
        existing = expire_if_needed(self._load_training_reliability(structured))
        if existing is not None and existing != self._load_training_reliability(structured):
            self._save_training_reliability(resolved, structured, existing)
            structured = self._structured_for(resolved)

        if cancel:
            if existing is None:
                raise LookupError("No training reliability request is available to cancel.")
            cancelled = request_cancel(existing)
            return self._save_training_reliability(resolved, structured, cancelled)

        if should_replay(existing, request_id, idempotency_key):
            return dict(structured._workspace)

        if should_coalesce(
            existing,
            request_id=request_id,
            command_id=command_id,
            card_id=card_id,
        ):
            return dict(structured._workspace)

        # Body-level idempotency (2026-10-14): the single-slot replay window
        # ends when a neighbouring training save replaces the slot, and a
        # resent key whose in-flight record timed out falls into the recover
        # path — both used to re-execute a body that had already persisted
        # durably (the recorded duplicate host-evidence defect). A ledgered
        # SUCCESS is final: replay the current workspace, never re-run. A
        # ledgered FAILURE keeps the recover path open for a genuine retry.
        dedupe_key = training_dedupe_key(request_id, idempotency_key)
        executed = dedupe_entry_for(
            self._load_training_dedupe(structured), dedupe_key
        )
        if executed is not None and str(executed.get("outcome") or "") == "success":
            return dict(structured._workspace)

        if existing is not None and str(existing.get("phase") or "") in {"failed", "cancelled"}:
            if (
                str(existing.get("command_id") or "") == command_id
                and str(existing.get("card_id") or "") == card_id
            ):
                record = recover_record(
                    existing,
                    request_id=request_id or str(existing.get("request_id") or ""),
                    revision=revision,
                    timeout_ms=timeout_ms,
                )
            else:
                record = begin_record(
                    request_id=request_id,
                    command_id=command_id,
                    card_id=card_id,
                    handoff_id=handoff_id,
                    idempotency_key=idempotency_key,
                    revision=revision or 1,
                    timeout_ms=timeout_ms,
                    learning_phase=learning_phase,
                )
        else:
            record = begin_record(
                request_id=request_id,
                command_id=command_id,
                card_id=card_id,
                handoff_id=handoff_id,
                idempotency_key=idempotency_key,
                revision=revision or 1,
                timeout_ms=timeout_ms,
                learning_phase=learning_phase,
            )

        record = mark_executing(record)
        self._save_training_reliability(resolved, structured, record)

        try:
            result = work()
        except Exception as exc:
            structured = self._structured_for(resolved)
            failed = mark_failed(record, str(exc))
            failed_dedupe = record_dedupe_entry(
                self._load_training_dedupe(structured),
                dedupe_key,
                outcome="failure",
            )
            self._save_training_reliability(resolved, structured, failed, dedupe=failed_dedupe)
            raise

        structured = self._structured_for(resolved)
        next_snapshot = int(structured._workspace.get(WORKSPACE_SNAPSHOT_REVISION_KEY) or 0) + 1
        latest_handoff = structured._workspace.get("latest_training_handoff")
        persisted_phase = learning_phase
        if isinstance(latest_handoff, dict):
            persisted_phase = str(latest_handoff.get("learning_phase") or persisted_phase)
        finished = mark_succeeded(
            record,
            snapshot_revision=next_snapshot,
            learning_phase=persisted_phase,
            cancel_after=self._cancel_raced_work(record, structured),
        )
        success_dedupe = record_dedupe_entry(
            self._load_training_dedupe(structured),
            dedupe_key,
            outcome="success",
            snapshot_revision=next_snapshot,
        )
        workspace = self._save_training_reliability(resolved, structured, finished, dedupe=success_dedupe)
        if isinstance(result, dict):
            merged = dict(result)
            merged[WORKSPACE_RELIABILITY_KEY] = workspace.get(WORKSPACE_RELIABILITY_KEY)
            merged[WORKSPACE_SNAPSHOT_REVISION_KEY] = workspace.get(WORKSPACE_SNAPSHOT_REVISION_KEY)
            merged[TRAINING_RELIABILITY_DEDUPE_KEY] = workspace.get(TRAINING_RELIABILITY_DEDUPE_KEY)
            return merged
        return workspace
