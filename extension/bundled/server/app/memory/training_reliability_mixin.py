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
    WORKSPACE_RELIABILITY_KEY,
    WORKSPACE_SNAPSHOT_REVISION_KEY,
    as_workspace_record,
    begin_record,
    expire_if_needed,
    mark_executing,
    mark_failed,
    mark_succeeded,
    recover_record,
    request_cancel,
    should_coalesce,
    should_replay,
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

    def _load_training_reliability(self, structured: StructuredMemoryService) -> dict[str, Any] | None:
        payload = structured._workspace.get(WORKSPACE_RELIABILITY_KEY)
        return dict(payload) if isinstance(payload, dict) else None

    def _save_training_reliability(
        self,
        workspace_id: str,
        structured: StructuredMemoryService,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_revision = int(record.get("snapshot_revision") or 0)
        workspace = structured.update_workspace(
            workspace_id=workspace_id,
            **{
                WORKSPACE_RELIABILITY_KEY: as_workspace_record(record),
                WORKSPACE_SNAPSHOT_REVISION_KEY: snapshot_revision or None,
            },
        )
        self._persist_structured(workspace_id)
        return dict(workspace)

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
            self._save_training_reliability(resolved, structured, failed)
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
        )
        workspace = self._save_training_reliability(resolved, structured, finished)
        if isinstance(result, dict):
            merged = dict(result)
            merged[WORKSPACE_RELIABILITY_KEY] = workspace.get(WORKSPACE_RELIABILITY_KEY)
            merged[WORKSPACE_SNAPSHOT_REVISION_KEY] = workspace.get(WORKSPACE_SNAPSHOT_REVISION_KEY)
            return merged
        return workspace
