from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock, Thread
from time import perf_counter
from typing import Any, Callable, Literal
from uuid import uuid4

from ..core.models import utc_now_iso

ProjectAdoptionJobStatus = Literal[
    "queued",
    "running",
    "completed",
    "interrupted",
    "retry_required",
]

_SKIPPED_DIRECTORIES = {
    ".git",
    "node_modules",
    ".trainer",
    ".venv",
    "venv",
    "__pycache__",
    ".hypothesis",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyre",
    ".cache",
    ".tox",
    ".eggs",
    ".idea",
    ".gitlab",
    ".svn",
    ".hg",
    ".next",
    ".nuxt",
    ".output",
    ".gradle",
    ".dart_tool",
    ".cargo",
    ".rustup",
    ".terraform",
}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@dataclass(frozen=True, slots=True)
class ProjectAdoptionJobRecord:
    job_id: str
    workspace_id: str
    discovery_id: str
    project_path: str
    project_name: str
    root_id: str | None
    root_path: str
    context_id: str | None
    status: ProjectAdoptionJobStatus
    progress: float
    progress_message: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    inventory_path: str | None = None
    inventory: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    retry_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "workspace_id": self.workspace_id,
            "discovery_id": self.discovery_id,
            "project_path": self.project_path,
            "project_name": self.project_name,
            "root_id": self.root_id,
            "root_path": self.root_path,
            "context_id": self.context_id,
            "status": self.status,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "inventory_path": self.inventory_path,
            "inventory": self.inventory,
            "result": self.result,
            "retry_reason": self.retry_reason,
        }
        return payload


class ProjectAdoptionIndexService:
    """Persist and run a bounded project adoption inventory job."""

    def __init__(
        self,
        *,
        max_files: int = 1_500,
        max_directories: int = 500,
        max_seconds: float = 2.5,
    ) -> None:
        self.max_files = max_files
        self.max_directories = max_directories
        self.max_seconds = max_seconds
        self._lock = Lock()
        self._active_jobs: set[str] = set()
        self._records: dict[str, ProjectAdoptionJobRecord] = {}

    def start(
        self,
        *,
        job_id: str | None = None,
        workspace_id: str,
        discovery_id: str,
        project_path: str,
        project_name: str,
        root_id: str | None,
        root_path: str,
        context_id: str | None,
        finalize: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> ProjectAdoptionJobRecord:
        normalized_job_id = str(job_id or "").strip() or f"project-adoption-{uuid4().hex[:12]}"
        now = utc_now_iso()
        record = ProjectAdoptionJobRecord(
            job_id=normalized_job_id,
            workspace_id=workspace_id,
            discovery_id=discovery_id,
            project_path=project_path,
            project_name=project_name,
            root_id=root_id,
            root_path=root_path,
            context_id=context_id,
            status="queued",
            progress=0.0,
            progress_message="Queued for background adoption indexing.",
            created_at=now,
            updated_at=now,
        )
        self._store(record)
        worker = Thread(
            target=self._run_job,
            kwargs={
                "job_id": normalized_job_id,
                "finalize": finalize,
            },
            daemon=True,
            name=f"project-adoption-{normalized_job_id}",
        )
        # Mark it active before starting the thread so an immediate status poll
        # cannot mistake a just-queued job for one left behind by a restart.
        with self._lock:
            self._active_jobs.add(normalized_job_id)
        try:
            worker.start()
        except RuntimeError as exc:
            with self._lock:
                self._active_jobs.discard(normalized_job_id)
            return self._update(
                record,
                status="retry_required",
                progress_message="Trainer could not start the adoption worker; retry the project adoption.",
                retry_reason=str(exc),
            )
        return record

    def get(self, *, root_path: str, job_id: str) -> ProjectAdoptionJobRecord | None:
        normalized_job_id = str(job_id or "").strip()
        normalized_root_path = str(root_path or "").strip()
        if not normalized_job_id:
            return None
        if not normalized_root_path:
            return None
        with self._lock:
            cached = self._records.get(normalized_job_id)
            active = normalized_job_id in self._active_jobs
        if cached is not None:
            if cached.root_path != str(Path(normalized_root_path).expanduser().resolve(strict=False)):
                return None
            if cached.status in {"queued", "running"} and not active:
                return self._mark_retry_required(cached)
            return cached
        record = self._load(normalized_root_path, normalized_job_id)
        if record is None:
            return None
        if record.status in {"queued", "running"} and not active:
            return self._mark_retry_required(record)
        with self._lock:
            self._records[normalized_job_id] = record
        return record

    def _base_dir(self, root_path: str) -> Path:
        return Path(root_path).expanduser().resolve(strict=False) / ".trainer" / "indexes"

    def _record_path(self, root_path: str, job_id: str) -> Path:
        return self._base_dir(root_path) / f"{job_id}.json"

    def _inventory_path(self, root_path: str, job_id: str) -> Path:
        return self._base_dir(root_path) / f"{job_id}.inventory.json"

    def _store(self, record: ProjectAdoptionJobRecord) -> None:
        with self._lock:
            self._records[record.job_id] = record
        _atomic_write_json(self._record_path(record.root_path, record.job_id), record.to_payload())

    def _load(self, root_path: str, job_id: str) -> ProjectAdoptionJobRecord | None:
        payload = _read_json(self._record_path(root_path, job_id))
        if not isinstance(payload, dict):
            return None
        return self._record_from_payload(payload)

    def _record_from_payload(self, payload: dict[str, Any]) -> ProjectAdoptionJobRecord:
        return ProjectAdoptionJobRecord(
            job_id=str(payload.get("job_id") or "").strip(),
            workspace_id=str(payload.get("workspace_id") or "").strip(),
            discovery_id=str(payload.get("discovery_id") or "").strip(),
            project_path=str(payload.get("project_path") or "").strip(),
            project_name=str(payload.get("project_name") or "").strip(),
            root_id=(str(payload.get("root_id") or "").strip() or None),
            root_path=str(payload.get("root_path") or "").strip(),
            context_id=(str(payload.get("context_id") or "").strip() or None),
            status=payload.get("status") if payload.get("status") in {"queued", "running", "completed", "interrupted", "retry_required"} else "retry_required",
            progress=float(payload.get("progress") or 0.0),
            progress_message=str(payload.get("progress_message") or "").strip(),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            updated_at=str(payload.get("updated_at") or utc_now_iso()),
            started_at=(str(payload.get("started_at") or "").strip() or None),
            completed_at=(str(payload.get("completed_at") or "").strip() or None),
            inventory_path=(str(payload.get("inventory_path") or "").strip() or None),
            inventory=payload.get("inventory") if isinstance(payload.get("inventory"), dict) else None,
            result=payload.get("result") if isinstance(payload.get("result"), dict) else None,
            retry_reason=(str(payload.get("retry_reason") or "").strip() or None),
        )

    def _persist(self, record: ProjectAdoptionJobRecord) -> None:
        with self._lock:
            self._records[record.job_id] = record
        _atomic_write_json(self._record_path(record.root_path, record.job_id), record.to_payload())

    def _mark_retry_required(self, record: ProjectAdoptionJobRecord) -> ProjectAdoptionJobRecord:
        updated = replace(
            record,
            status="retry_required",
            progress=record.progress if record.progress > 0 else 0.0,
            progress_message="Trainer restarted before the adoption job finished.",
            updated_at=utc_now_iso(),
            retry_reason="background job was not active after restart",
        )
        self._persist(updated)
        return updated

    def _run_job(
        self,
        *,
        job_id: str,
        finalize: Callable[[dict[str, Any]], dict[str, Any]] | None,
    ) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            self._active_jobs.add(job_id)
        try:
            record = self._update(
                record,
                status="running",
                progress=0.05,
                progress_message="Scanning project files.",
                started_at=record.started_at or utc_now_iso(),
            )
            inventory = self._scan_project(record.project_path)
            inventory_path = self._inventory_path(record.root_path, record.job_id)
            _atomic_write_json(inventory_path, inventory)
            inventory_complete = inventory.get("status") == "completed"
            # The project path may vanish mid-scan (renamed, deleted, or unmounted).
            # That is an interruption, not a retryable finalize failure: stop and
            # surface the interruption instead of attempting to provision a
            # project lane that no longer exists.
            if inventory.get("status") == "interrupted" and str(
                inventory.get("message") or ""
            ).strip() == "Project path is no longer available.":
                self._update(
                    record,
                    status="interrupted",
                    progress=1.0,
                    progress_message="Project path is no longer available.",
                    completed_at=utc_now_iso(),
                    inventory_path=str(inventory_path),
                    inventory=inventory,
                )
                return
            record = self._update(
                record,
                progress=0.9,
                progress_message=(
                    "Inventory recorded. Finalizing adoption." if finalize is not None else "Inventory recorded."
                ),
                inventory_path=str(inventory_path),
                inventory=inventory,
            )
            # A truncated inventory is acceptable: the scan is only an index for
            # later search, not a precondition for project adoption. Finalize
            # with the partial inventory so large projects can always be added.
            if not inventory_complete:
                record = self._update(
                    record,
                    progress=0.95,
                    progress_message="Inventory budget exhausted; adopting with a partial index."
                    if finalize is not None
                    else "Inventory budget exhausted; partial inventory recorded.",
                    retry_reason=None,
                )
            if finalize is None:
                self._update(
                    record,
                    status="completed",
                    progress=1.0,
                    progress_message=(
                        "Project adoption inventory completed."
                        if inventory_complete
                        else "Project adoption inventory completed (partial)."
                    ),
                    completed_at=utc_now_iso(),
                )
                return
            try:
                result = finalize(inventory)
            except Exception as exc:  # noqa: BLE001
                self._update(
                    record,
                    status="retry_required",
                    progress=1.0,
                    progress_message="Project adoption inventory completed, but finalization needs retry.",
                    completed_at=utc_now_iso(),
                    retry_reason=str(exc),
                )
                return
            self._update(
                record,
                status="completed",
                progress=1.0,
                progress_message="Project adoption completed.",
                completed_at=utc_now_iso(),
                result=result,
            )
        finally:
            with self._lock:
                self._active_jobs.discard(job_id)

    def _update(self, record: ProjectAdoptionJobRecord, **changes: Any) -> ProjectAdoptionJobRecord:
        updated = replace(record, updated_at=utc_now_iso(), **changes)
        self._persist(updated)
        return updated

    def _scan_project(self, project_path: str) -> dict[str, Any]:
        start = perf_counter()
        project_root = Path(project_path).expanduser().resolve(strict=False)
        budget = {
            "max_files": self.max_files,
            "max_directories": self.max_directories,
            "max_seconds": self.max_seconds,
        }
        if not project_root.is_dir():
            return {
                "status": "interrupted",
                "message": "Project path is no longer available.",
                "project_path": str(project_root),
                "scanned_at": utc_now_iso(),
                "duration_ms": int((perf_counter() - start) * 1000),
                "directories_scanned": 0,
                "files_scanned": 0,
                "bytes_scanned": 0,
                "skipped_directories": [],
                "truncated": True,
                "budget": budget,
                "files": [],
            }
        files: list[str] = []
        skipped_directories: list[str] = []
        directories_scanned = 0
        bytes_scanned = 0
        truncated = False
        stop_reason = "completed"

        for current_dir, dirnames, filenames in os.walk(project_root, topdown=True):
            directories_scanned += 1
            dirnames[:] = sorted(dirnames)
            kept_dirnames: list[str] = []
            for dirname in dirnames:
                if dirname in _SKIPPED_DIRECTORIES:
                    skipped_directories.append(Path(current_dir, dirname).relative_to(project_root).as_posix())
                    continue
                kept_dirnames.append(dirname)
            dirnames[:] = kept_dirnames

            if directories_scanned > self.max_directories or (perf_counter() - start) >= self.max_seconds:
                truncated = True
                stop_reason = "directory or time budget exhausted"
                break

            for filename in sorted(filenames):
                if len(files) >= self.max_files or (perf_counter() - start) >= self.max_seconds:
                    truncated = True
                    stop_reason = "file or time budget exhausted"
                    break
                file_path = Path(current_dir, filename)
                try:
                    bytes_scanned += file_path.stat().st_size
                except OSError:
                    pass
                files.append(file_path.relative_to(project_root).as_posix())
            if truncated:
                break

        duration_ms = int((perf_counter() - start) * 1000)
        status: ProjectAdoptionJobStatus = "completed" if not truncated else "interrupted"
        return {
            "status": status,
            "message": None if not truncated else stop_reason,
            "project_path": str(project_root),
            "scanned_at": utc_now_iso(),
            "duration_ms": duration_ms,
            "directories_scanned": directories_scanned,
            "files_scanned": len(files),
            "bytes_scanned": bytes_scanned,
            "skipped_directories": skipped_directories,
            "truncated": truncated,
            "budget": budget,
            "files": files,
        }
