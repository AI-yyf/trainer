from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Mapping

from ..core.models import (
    LearningPlan,
    ResourceRecord,
    SandboxBatchRenameRequest,
    SandboxCommandEntry,
    SandboxDeleteRequest,
    SandboxMkdirRequest,
    SandboxPatchOperation,
    SandboxPatchRequest,
    SandboxPreview,
    SandboxPreviewRequest,
    SandboxRenameRequest,
    SandboxRestoreRequest,
    SandboxState,
    SandboxWriteRequest,
    TrainingCardCandidateSnapshot,
    WorkspaceAuthoritySummary,
)
from ..resources.canonical import strip_front_matter
from ..resources.canonical_store import managed_workspace_root
from ..resources.preview import (
    PreviewService,
    _convert_archive_to_markdown,
    _convert_eml_to_markdown,
    _convert_epub_to_markdown,
    _convert_odf_to_markdown,
    _convert_openxml_to_markdown,
    _convert_rtf_to_markdown,
    _openxml_presentation_preview,
    get_structured_preview_data,
    get_structured_preview_markdown,
)

if TYPE_CHECKING:
    from ..core.event_ledger import EventLedgerService
    from ..workspace.authority import PermissionLevel, WorkspaceAuthority

from .constants import (
    TRAINER_SANDBOX_MANAGED_ROOTS,
)
from .container_probe_and_audit_mixin import ContainerProbeAndAuditMixin
from .egress_and_container_exec_mixin import EgressAndContainerExecMixin
from .patch_and_skill_run_mixin import PatchAndSkillRunMixin

logger = logging.getLogger(__name__)


class SandboxService(
    PatchAndSkillRunMixin,
    EgressAndContainerExecMixin,
    ContainerProbeAndAuditMixin,
):
    _STRUCTURED_PREVIEW_READ_LIMIT = 256_000

    def __init__(
        self,
        data_root: Path,
        event_ledger: EventLedgerService | None = None,
        workspace_path_resolver: Any | None = None,
        workspace_sandbox_root_resolver: Callable[..., str | None] | None = None,
        workspace_authority_resolver: Callable[[str], "WorkspaceAuthority | None"] | None = None,
        library_root_resolver: Callable[[str], Path | None] | None = None,
    ) -> None:
        self.data_root = data_root
        self.sandboxes_root = self.data_root / "sandboxes"
        self._ensure_directory(self.sandboxes_root)
        self._command_history: dict[str, list[SandboxCommandEntry]] = {}
        self._workspace_authorities: dict[str, "WorkspaceAuthority"] = {}
        self._event_ledger = event_ledger
        self._workspace_path_resolver = workspace_path_resolver
        self._workspace_sandbox_root_resolver = workspace_sandbox_root_resolver
        self._workspace_authority_resolver = workspace_authority_resolver
        self._library_root_resolver = library_root_resolver
        self._preview_service = PreviewService()

    def set_workspace_path_resolver(self, resolver: Any | None) -> None:
        self._workspace_path_resolver = resolver

    def set_workspace_sandbox_root_resolver(
        self,
        resolver: Callable[..., str | None] | None,
    ) -> None:
        self._workspace_sandbox_root_resolver = resolver

    def set_workspace_authority_resolver(
        self,
        resolver: Callable[[str], "WorkspaceAuthority | None"] | None,
    ) -> None:
        self._workspace_authority_resolver = resolver

    def set_library_root_resolver(
        self,
        resolver: Callable[[str], Path | None] | None,
    ) -> None:
        self._library_root_resolver = resolver

    def _resolved_library_root(self, workspace_id: str) -> Path | None:
        if self._library_root_resolver is None:
            return None
        resolved = self._library_root_resolver(workspace_id)
        if resolved is None:
            return None
        return Path(resolved).expanduser().resolve(strict=False)

    def _resolve_canonical_markdown_file(
        self,
        workspace_id: str,
        canonical_markdown_path: str | None,
    ) -> Path | None:
        markdown = str(canonical_markdown_path or "").strip()
        if not markdown:
            return None
        path = Path(markdown)
        if path.is_absolute():
            return path if self._path_is_file(path) else None
        candidates: list[Path] = []
        library_root = self._resolved_library_root(workspace_id)
        if library_root is not None:
            candidates.append(library_root / path)
        # Same lookup order as the resource service: a cold start keeps the canonical
        # copy under the data root, and older records may still point into the
        # workspace folder (read only).
        managed_root = managed_workspace_root(self.data_root, workspace_id)
        if managed_root != library_root:
            candidates.append(managed_root / path)
        workspace_root = self._resolved_workspace_path(workspace_id)
        if workspace_root is not None and workspace_root not in {library_root, managed_root}:
            candidates.append(workspace_root / path)
        for candidate in candidates:
            if self._path_is_file(candidate):
                return candidate
        return None

    def _canonical_sandbox_markdown(
        self,
        workspace_id: str,
        resource: ResourceRecord,
        source_path: Path | None,
    ) -> Path | None:
        if resource.source_items or resource.kind == "image":
            return None
        if source_path is not None and source_path.suffix.lower() in {".md", ".markdown"}:
            return None
        return self._resolve_canonical_markdown_file(
            workspace_id,
            resource.canonical_markdown_path,
        )

    def _sync_canonical_markdown_with_assets(
        self,
        target_path: Path,
        markdown_path: Path,
    ) -> None:
        markdown_text = strip_front_matter(
            self._read_text(markdown_path, encoding="utf-8", errors="replace")
        )
        self._ensure_directory(target_path.parent)
        self._write_text(target_path, markdown_text, encoding="utf-8")
        assets_dir = markdown_path.parent / "assets" / markdown_path.stem
        if not self._path_is_dir(assets_dir):
            return
        target_assets_dir = target_path.parent / "assets" / markdown_path.stem
        if self._path_exists(target_assets_dir):
            self._remove_tree(target_assets_dir, ignore_errors=True)
        self._ensure_directory(target_assets_dir)
        for asset in self._iterdir_paths(assets_dir):
            if self._path_is_file(asset):
                self._copy_file(asset, target_assets_dir / asset.name)

    def _resolved_workspace_path(self, workspace_id: str) -> Path | None:
        if self._workspace_path_resolver is None:
            return None
        try:
            resolved = self._workspace_path_resolver(workspace_id)
        except TypeError:
            resolved = self._workspace_path_resolver(workspace_id=workspace_id)
        normalized = str(resolved or "").strip()
        if not normalized:
            return None
        candidate = Path(normalized).expanduser()
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
        return None

    def _resolved_workspace_sandbox_root(self, workspace_id: str) -> Path | None:
        if self._workspace_sandbox_root_resolver is None:
            return None
        try:
            resolved = self._workspace_sandbox_root_resolver(workspace_id)
        except TypeError:
            resolved = self._workspace_sandbox_root_resolver(workspace_id=workspace_id)
        normalized = str(resolved or "").strip()
        if not normalized:
            return None
        try:
            return self.validate_workspace_sandbox_root(workspace_id, normalized)
        except ValueError:
            # A persisted override may predate the workspace-root boundary rule.
            # Ignore it so all operations stay within the managed default root.
            return None

    @staticmethod
    def _contains_path(root: Path, candidate: Path) -> bool:
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return True

    def validate_workspace_sandbox_root(self, workspace_id: str, root_path: str | Path) -> Path:
        candidate = Path(root_path).expanduser().resolve(strict=False)
        # A persisted override that exists but is not a directory (a stale file
        # path restored from a moved snapshot, for example) must fail closed so
        # callers fall back to the managed default root instead of crashing on
        # a makedirs/exist_ok step that only tolerates existing directories.
        if candidate.exists() and not candidate.is_dir():
            raise ValueError("Sandbox root must be a directory path.")
        active_workspace_root = self._resolved_workspace_path(workspace_id)
        if active_workspace_root is None:
            return candidate
        workspace = Path(active_workspace_root).expanduser().resolve(strict=False)
        # Fail closed both ways: sandbox must stay outside the opened project,
        # and must never wrap it. Nested sandbox roots would let elevated sandbox
        # delete/write paths mutate user business files under coach-only authority.
        if self._contains_path(candidate, workspace) or self._contains_path(workspace, candidate):
            raise ValueError(
                "Sandbox root cannot be the active VS Code workspace root, contain it, or live inside it."
            )
        return candidate

    def ensure_workspace_root(self, workspace_id: str) -> Path:
        root = self._resolved_workspace_sandbox_root(workspace_id) or (
            self.sandboxes_root / self._safe_workspace_slug(workspace_id)
        )
        root = Path(root).expanduser().resolve(strict=False)
        self._ensure_directory(root)
        self._ensure_workspace_scaffold(root)
        return root

    def suggest_workspace_project_root(
        self,
        workspace_id: str,
        *,
        workspace_name: str | None = None,
        workspace_path: str | None = None,
    ) -> Path:
        base_root = self.data_root / "projects"
        self._ensure_directory(base_root)
        label = (
            (Path(str(workspace_path or "").strip()).name if str(workspace_path or "").strip() else "")
            or str(workspace_name or "").strip()
            or workspace_id
        )
        safe_label = self._safe_name(label)
        candidate = base_root / safe_label
        if not candidate.exists():
            return candidate
        suffix = 2
        while True:
            numbered = base_root / f"{safe_label}-{suffix}"
            if not numbered.exists():
                return numbered
            suffix += 1

    def ensure_operation_root(self, workspace_id: str) -> Path:
        return self.ensure_workspace_root(workspace_id)

    def _active_workspace_root_path(
        self,
        workspace_id: str,
        workspace_root_path: str | None = None,
    ) -> str:
        explicit = str(workspace_root_path or "").strip()
        if explicit:
            return explicit
        resolved = self._resolved_workspace_path(workspace_id)
        if resolved is not None:
            return str(resolved)
        # Never present the managed sandbox as the opened project root.
        return ""

    def _sandbox_authority(self, workspace_id: str) -> "WorkspaceAuthority":
        from ..workspace.authority import PermissionLevel, WorkspaceAuthority

        root = self.ensure_operation_root(workspace_id)
        authority = self._workspace_authorities.get(workspace_id)
        if authority is None:
            authority = WorkspaceAuthority(root_path=str(root), initial_permission=PermissionLevel.INSPECT)
            # Trainer-managed sandbox is a local carrier, not the opened project.
            authority.set_workspace_context(workspace_trusted=True)
            self._workspace_authorities[workspace_id] = authority
            return authority
        if authority.active_workspace_root != str(root):
            authority.set_active_workspace(str(root))
            authority.set_workspace_context(workspace_trusted=True)
        return authority

    def _resolved_project_identity(self, workspace_id: str) -> "WorkspaceAuthority | None":
        """Return host project authority even when the root is remote/rootless."""
        if self._workspace_authority_resolver is None:
            return None
        return self._workspace_authority_resolver(workspace_id)

    def _resolved_workspace_authority(self, workspace_id: str) -> "WorkspaceAuthority | None":
        authority = self._resolved_project_identity(workspace_id)
        if authority is None or not authority.active_workspace_root:
            return None
        return authority

    def _workspace_authority(self, workspace_id: str) -> "WorkspaceAuthority":
        return self._resolved_workspace_authority(workspace_id) or self._sandbox_authority(workspace_id)

    def _operation_authority(
        self,
        workspace_id: str,
        minimum_level: "PermissionLevel",
        *,
        explicit_destructive_policy: bool = False,
    ) -> tuple["WorkspaceAuthority", "PermissionLevel | None"]:
        """Return the effective authority without silently granting permission.

        Callers must check the returned authority before mutating.  Permission
        elevation belongs to an explicit host/user authorization flow; sandbox
        mutations must never manufacture it as an implementation detail.

        Trainer's library/sandbox is a local carrier root. Remote or untrusted
        learner-project context must not block those writes. Project/source
        mutations stay fail-closed at their own call sites.
        ``explicit_destructive_policy`` is unused here; the sandbox authority is
        Trainer-owned and already trusted.
        """
        _ = explicit_destructive_policy
        authority = self._sandbox_authority(workspace_id)
        previous_level = authority.permission_level
        if int(previous_level) < int(minimum_level):
            authority.set_permission_level(minimum_level)
            return authority, previous_level
        return authority, None

    @staticmethod
    def _restore_authority_permission(
        authority: "WorkspaceAuthority",
        previous_level: "PermissionLevel | None",
    ) -> None:
        if previous_level is not None:
            authority.set_permission_level(previous_level)

    @staticmethod
    def _patch_required_permission_level(operations: Iterable[object]) -> "PermissionLevel":
        from ..workspace.authority import PermissionLevel

        highest = PermissionLevel.APPLY
        for op in operations:
            operation = str(getattr(op, "op", "") or "").strip().lower()
            if operation == "delete":
                return PermissionLevel.DESTRUCTIVE
            if operation == "rename":
                highest = max(highest, PermissionLevel.REORGANIZE)
            elif operation == "write":
                highest = max(highest, PermissionLevel.APPLY)
        return highest

    def _log_workspace_boundary_denial(
        self,
        workspace_id: str,
        *,
        operation: str,
        raw_path: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        authority = self._workspace_authority(workspace_id)
        authority.log_operation(
            operation,
            str(raw_path or ""),
            "denied",
            details={
                "reason": reason,
                "activeWorkspaceRoot": authority.active_workspace_root,
                **dict(details or {}),
            },
        )

    def _normalized_authority_summary(
        self,
        workspace_id: str,
        authority_summary: WorkspaceAuthoritySummary | dict[str, object] | None = None,
        *,
        active_workspace_root: str | None = None,
    ) -> dict[str, object]:
        authority = self._workspace_authority(workspace_id)
        if isinstance(authority_summary, WorkspaceAuthoritySummary):
            summary = authority_summary.model_dump(mode="json")
        elif authority_summary is None:
            summary = authority.summary_model().model_dump(mode="json")
        else:
            summary = dict(authority_summary)
        sandbox_root = str(self.ensure_workspace_root(workspace_id))
        resolved_active_workspace_root = (
            str(active_workspace_root or "").strip() or self._active_workspace_root_path(workspace_id)
        )
        summary["authority_scope"] = "trainer_sandbox"
        project = self._resolved_project_identity(workspace_id)
        if project is not None:
            summary["remote_name"] = project.remote_name
            summary["is_remote_workspace"] = project.is_remote_workspace
        summary["resource_write_allowed"] = True
        summary["resource_write_evidence"] = {
            "operation": "write",
            "scope": "trainer_sandbox",
            "target_root": sandbox_root,
            "allowed": True,
            "reason": "Trainer artifact writes are confined to the managed sandbox root.",
        }
        summary["has_workspace_root"] = bool(resolved_active_workspace_root or sandbox_root)
        summary["active_workspace_root"] = resolved_active_workspace_root
        # `root_uri` is the carrier used by sandbox artifacts; the project
        # boundary remains explicit in `active_workspace_root`.
        summary["root_uri"] = sandbox_root
        summary["trash_root"] = str(summary.get("trash_root") or "").strip() or str(
            self._trash_root_path(self.ensure_operation_root(workspace_id))
        )
        if summary["root_uri"] != resolved_active_workspace_root:
            root_detail = str(summary.get("root_detail") or "").strip()
            root_uri_detail = f"root_uri: {summary['root_uri']}"
            if root_uri_detail not in root_detail:
                summary["root_detail"] = (
                    f"{root_detail} | {root_uri_detail}" if root_detail else root_uri_detail
                )
        return summary

    def authority_summary(self, workspace_id: str) -> dict[str, object]:
        return self._normalized_authority_summary(workspace_id)

    def sync_resource(
        self,
        workspace_id: str,
        resource: ResourceRecord,
        *,
        force: bool = False,
    ) -> ResourceRecord:
        root = self.ensure_workspace_root(workspace_id)
        source_path = self._local_path(resource.source)
        canonical_markdown = self._canonical_sandbox_markdown(
            workspace_id,
            resource,
            source_path,
        )
        relative_target = self._resource_relative_path(resource)
        if canonical_markdown is not None and not relative_target.lower().endswith(".md"):
            relative_target = str(PurePosixPath(relative_target).with_suffix(".md"))
        if resource.sandbox_path:
            try:
                target_path = self._resolve_within_root(root, resource.sandbox_path, allow_missing=True)
            except ValueError:
                target_path = self._materialize_target(root, relative_target)
            if canonical_markdown is not None and target_path.suffix.lower() != ".md":
                stale_target = target_path
                target_path = target_path.with_suffix(".md")
                if self._path_exists(stale_target) and self._path_is_file(stale_target):
                    self._unlink_path(stale_target)
            preserve_existing = not force and self._path_exists(target_path)
        else:
            target_path = self._materialize_target(root, relative_target)
            preserve_existing = False
        synced = False

        if canonical_markdown is not None:
            if not preserve_existing:
                self._sync_canonical_markdown_with_assets(target_path, canonical_markdown)
                synced = True
        elif resource.kind == "url":
            if not preserve_existing:
                body = self._url_resource_body(resource)
                self._write_text(target_path, body, encoding="utf-8")
                synced = True
        elif source_path is not None and self._path_exists(source_path):
            if self._path_is_dir(source_path):
                if not preserve_existing:
                    if self._path_exists(target_path):
                        if self._path_is_dir(target_path):
                            self._remove_tree(target_path)
                        else:
                            self._unlink_path(target_path)
                    self._copy_tree(source_path, target_path)
                    synced = True
            else:
                if not preserve_existing:
                    if self._path_exists(target_path) and self._path_is_dir(target_path):
                        self._remove_tree(target_path, ignore_errors=True)
                    self._ensure_directory(target_path.parent)
                    self._copy_file(source_path, target_path)
                    synced = True

        if synced or resource.sandbox_path or self._path_exists(target_path):
            synced_at = datetime.now(UTC).isoformat() if synced else (
                resource.sandbox_synced_at or datetime.now(UTC).isoformat()
            )
            result = resource.model_copy(
                update={
                    "sandbox_path": str(target_path),
                    "sandbox_origin": resource.source,
                    "sandbox_synced_at": synced_at,
                    "sandbox_dirty": False if synced else resource.sandbox_dirty,
                }
            )
            # §13.21 Record sandbox resource synced event
            if synced and self._event_ledger is not None:
                self._event_ledger.record_event(
                    "sandbox_resource_synced",
                    actor="trainer",
                    scope="sandbox",
                    project_id=workspace_id,
                    payload_ref={
                        "resource_id": resource.id,
                        "sandbox_path": str(target_path),
                        "kind": resource.kind,
                    },
                    after_state_ref={"resource_id": resource.id, "synced": True},
                    reversibility="reversible",
                    audit_note=f"Sandbox resource synced: '{resource.name}' -> '{target_path}'",
            )
            return result
        return resource

    def persist_plan_snapshot(
        self,
        workspace_id: str,
        plan: LearningPlan,
        *,
        reason: str = "updated",
        overlay: dict[str, str] | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> SandboxPreview:
        return self.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path="plan/current-plan.md",
                content=self._render_plan_markdown(
                    plan,
                    reason=reason,
                    overlay=overlay,
                    leftover_runtime=leftover_runtime,
                    leftover_task_title=leftover_task_title,
                ),
                create=True,
            ),
        )

    def persist_training_card(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        *,
        mark_current: bool = True,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> dict[str, SandboxPreview]:
        card_id = self._safe_name(card.card_id or card.title or "training-card")
        family = self._training_card_directory(card)
        content = self._render_training_card_markdown(
            card,
            leftover_plan=leftover_plan,
            leftover_runtime=leftover_runtime,
            leftover_task_title=leftover_task_title,
        )
        previews = {
            "family": self.write(
                workspace_id,
                SandboxWriteRequest(
                    workspace_id=workspace_id,
                    path=f"cards/{family}/{card_id}.md",
                    content=content,
                    create=True,
                ),
            )
        }
        if mark_current:
            previews["current"] = self.write(
                workspace_id,
                SandboxWriteRequest(
                    workspace_id=workspace_id,
                    path="cards/current/active.md",
                    content=content,
                    create=True,
                ),
            )
        return previews

    def persist_training_evaluation_note(
        self,
        workspace_id: str,
        *,
        card: TrainingCardCandidateSnapshot | None,
        passed: bool,
        summary: str,
        next_step: str,
        focus_area: str,
        failed_checks: list[str] | None = None,
        missing_requirements: list[str] | None = None,
        evidence_source: str = "ide_current_file",
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> SandboxPreview:
        card_id = self._safe_name(
            (card.card_id if card is not None else "")
            or focus_area
            or "training-handoff"
        )
        return self.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path=f"notes/training-handoffs/{card_id}.md",
                content=self._render_training_evaluation_note_markdown(
                    card=card,
                    passed=passed,
                    summary=summary,
                    next_step=next_step,
                    focus_area=focus_area,
                    failed_checks=failed_checks or [],
                    missing_requirements=missing_requirements or [],
                    evidence_source=evidence_source,
                    leftover_plan=leftover_plan,
                    leftover_runtime=leftover_runtime,
                    leftover_task_title=leftover_task_title,
                ),
                create=True,
            ),
        )

    def remove_resource(
        self,
        workspace_id: str,
        resource: ResourceRecord,
        *,
        linked_resources: Iterable[ResourceRecord] | None = None,
    ) -> dict[str, object]:
        root = self.ensure_operation_root(workspace_id).resolve(strict=False)
        items: list[SandboxPatchOperation] = []
        tracked_paths: dict[str, str] = {}
        seen_relatives: set[str] = set()
        shared_relatives: set[str] = set()

        for linked_resource in linked_resources or []:
            if linked_resource.id == resource.id:
                continue
            for candidate_path in (
                linked_resource.sandbox_path,
                linked_resource.extracted_artifact_path,
            ):
                if not str(candidate_path or "").strip():
                    continue
                try:
                    resolved_candidate = self._resolve_within_root(root, str(candidate_path))
                except ValueError:
                    continue
                if self._path_exists(resolved_candidate):
                    shared_relatives.add(resolved_candidate.relative_to(root).as_posix())

        def add_trash_candidate(raw_path: str | None) -> None:
            normalized_path = str(raw_path or "").strip()
            if not normalized_path:
                return
            try:
                resolved = self._resolve_within_root(root, normalized_path)
            except ValueError:
                return
            if not self._path_exists(resolved):
                return
            relative = resolved.relative_to(root).as_posix()
            if not relative or relative in seen_relatives:
                return
            if relative in shared_relatives:
                return
            seen_relatives.add(relative)
            tracked_paths[relative] = normalized_path
            items.append(SandboxPatchOperation(op="delete", path=relative))

        add_trash_candidate(resource.sandbox_path)
        add_trash_candidate(resource.extracted_artifact_path)

        if not items:
            return {
                "primary_trashed_path": None,
                "trashed_paths": {},
                "patch": [],
                "diff_summary": "",
                "checkpoint_id": "",
                "authority_summary": self.authority_summary(workspace_id),
            }

        patch_result = self.apply_patch(
            workspace_id,
            SandboxPatchRequest(
                workspace_id=workspace_id,
                label=f"Remove resource artifacts for {resource.id}",
                note=f"Trash sandbox-linked resource artifacts for {resource.id}",
                items=items,
            ),
        )

        raw_changes = patch_result.get("changes", [])
        changes = raw_changes if isinstance(raw_changes, list) else []
        raw_patch = patch_result.get("patch", [])
        patch = list(raw_patch) if isinstance(raw_patch, list) else []
        trashed_paths: dict[str, str] = {}
        for change in changes:
            if not isinstance(change, dict) or change.get("op") != "delete":
                continue
            relative = str(change.get("path") or "").strip()
            trashed_path = str(change.get("trashed_path") or "").strip()
            original_path = tracked_paths.get(relative)
            if original_path and trashed_path:
                trashed_paths[original_path] = trashed_path

        primary_trashed_path = trashed_paths.get(str(resource.sandbox_path or "").strip())
        if primary_trashed_path is None and trashed_paths:
            primary_trashed_path = next(iter(trashed_paths.values()))

        ledger_entry_id = ""
        if self._event_ledger is not None:
            entry = self._event_ledger.record_event(
                "sandbox_resource_removed",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "resource_id": resource.id,
                    "sandbox_path": resource.sandbox_path,
                    "extracted_artifact_path": resource.extracted_artifact_path,
                    "trashed_paths": dict(trashed_paths),
                    "patch": patch,
                    "diff_summary": str(patch_result.get("diff_summary") or ""),
                    "checkpoint_id": str(patch_result.get("checkpoint_id") or ""),
                },
                before_state_ref={
                    "resource_id": resource.id,
                    "sandbox_path": resource.sandbox_path,
                    "extracted_artifact_path": resource.extracted_artifact_path,
                },
                after_state_ref={
                    "resource_id": resource.id,
                    "sandbox_path": None,
                    "extracted_artifact_path": None,
                    "trashed_paths": dict(trashed_paths),
                },
                reversibility="compensatable",
                audit_note=f"Sandbox resource removed with managed artifacts: '{resource.id}'",
            )
            ledger_entry_id = entry.event_id

        return {
            "primary_trashed_path": primary_trashed_path,
            "trashed_paths": trashed_paths,
            "patch": patch,
            "diff_summary": str(patch_result.get("diff_summary") or ""),
            "checkpoint_id": str(patch_result.get("checkpoint_id") or ""),
            "ledger_entry_id": ledger_entry_id,
            "authority_summary": patch_result.get("authority_summary") or self.authority_summary(workspace_id),
        }

    def can_restore_resource_artifacts(
        self,
        workspace_id: str,
        trashed_paths: Mapping[str, str] | Iterable[str],
    ) -> bool:
        try:
            self._plan_resource_artifact_restores(
                self.ensure_operation_root(workspace_id),
                trashed_paths,
            )
        except (OSError, PermissionError, RuntimeError, ValueError):
            return False
        return True

    def restore_resource_artifacts(
        self,
        workspace_id: str,
        trashed_paths: Mapping[str, str] | Iterable[str],
    ) -> dict[str, object]:
        """Restore every archived artifact for one resource as a single compensatable unit."""
        from ..workspace.authority import PermissionLevel

        root = self.ensure_operation_root(workspace_id)
        planned_moves = self._plan_resource_artifact_restores(root, trashed_paths)
        if not planned_moves:
            return {
                "checkpoint_id": "",
                "restored_paths": [],
                "restore_handle": [],
                "authority_summary": self.authority_summary(workspace_id),
            }

        authority, previous_level = self._operation_authority(workspace_id, PermissionLevel.DESTRUCTIVE)
        checkpoint = None
        try:
            for source, _ in planned_moves:
                if not authority.check_permission("restore", source):
                    raise PermissionError(f"Restore permission denied for sandbox path: {source}")

            checkpoint = authority.create_checkpoint(
                f"Before restoring resource artifacts for {workspace_id}",
                metadata={
                    "workspace_id": workspace_id,
                    "sandbox_root": str(root),
                    "artifact_count": len(planned_moves),
                },
            )
            try:
                for source, destination in planned_moves:
                    self._ensure_directory(destination.parent)
                    self._move_path(source, destination)
                    authority.log_operation(
                        "restore",
                        str(source),
                        "allowed",
                        details={
                            "restored_path": str(destination),
                            "source_trashed_path": str(source),
                        },
                    )
            except Exception as exc:
                rollback_errors = self._compensate_resource_artifact_restores(planned_moves)
                if self._event_ledger is not None:
                    self._event_ledger.record_event(
                        "sandbox_resource_artifact_restore_failed",
                        actor="trainer",
                        scope="sandbox",
                        project_id=workspace_id,
                        payload_ref={
                            "checkpoint_id": checkpoint.checkpoint_id,
                            "artifact_count": len(planned_moves),
                            "rollback_complete": not rollback_errors,
                            "rollback_errors": rollback_errors,
                        },
                        after_state_ref={"rolled_back": not rollback_errors},
                        reversibility="compensatable",
                        audit_note="Sandbox resource artifact restore failed",
                    )
                if rollback_errors:
                    raise RuntimeError(
                        "Resource artifact restore failed and automatic compensation was incomplete."
                    ) from exc
                raise
        finally:
            self._restore_authority_permission(authority, previous_level)

        restored_paths = [str(destination) for _, destination in planned_moves]
        restore_handle = [
            {"trash_path": str(source), "restored_path": str(destination)}
            for source, destination in planned_moves
        ]
        if self._event_ledger is not None and checkpoint is not None:
            self._event_ledger.record_event(
                "sandbox_resource_artifacts_restored",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "artifact_count": len(restored_paths),
                    "restored_paths": restored_paths,
                },
                after_state_ref={"restored_paths": restored_paths},
                reversibility="reversible",
                audit_note=f"Restored {len(restored_paths)} sandbox resource artifact(s)",
            )
        return {
            "checkpoint_id": checkpoint.checkpoint_id if checkpoint is not None else "",
            "restored_paths": restored_paths,
            "restore_handle": restore_handle,
            "authority_summary": self.authority_summary(workspace_id),
        }

    def compensate_resource_artifact_restore(
        self,
        workspace_id: str,
        restore_handle: Iterable[Mapping[str, object]],
    ) -> dict[str, object]:
        """Return a completed resource restore to its original Trash paths."""
        from ..workspace.authority import PermissionLevel

        root = self.ensure_operation_root(workspace_id)
        planned_moves = self._plan_resource_artifact_return_to_trash(root, restore_handle)
        if not planned_moves:
            return {
                "checkpoint_id": "",
                "trashed_paths": [],
                "authority_summary": self.authority_summary(workspace_id),
            }

        authority, previous_level = self._operation_authority(workspace_id, PermissionLevel.DESTRUCTIVE)
        checkpoint = None
        try:
            for source, _ in planned_moves:
                if not authority.check_permission("delete", source):
                    raise PermissionError(f"Delete permission denied for sandbox path: {source}")

            checkpoint = authority.create_checkpoint(
                f"Compensate resource artifact restore for {workspace_id}",
                metadata={
                    "workspace_id": workspace_id,
                    "sandbox_root": str(root),
                    "artifact_count": len(planned_moves),
                },
            )
            try:
                for source, destination in planned_moves:
                    self._ensure_directory(destination.parent)
                    self._move_path(source, destination)
                    authority.log_operation(
                        "delete",
                        str(source),
                        "allowed",
                        details={
                            "trashed_path": str(destination),
                            "compensation": "resource_restore_activation_failed",
                        },
                    )
            except Exception as exc:
                rollback_errors = self._compensate_resource_artifact_restores(planned_moves)
                if rollback_errors:
                    raise RuntimeError(
                        "Resource artifact activation compensation was incomplete."
                    ) from exc
                raise
        finally:
            self._restore_authority_permission(authority, previous_level)

        trashed_paths = [str(destination) for _, destination in planned_moves]
        if self._event_ledger is not None and checkpoint is not None:
            self._event_ledger.record_event(
                "sandbox_resource_artifact_restore_compensated",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "artifact_count": len(trashed_paths),
                    "trashed_paths": trashed_paths,
                },
                after_state_ref={"trashed_paths": trashed_paths},
                reversibility="compensatable",
                audit_note="Returned resource artifacts to Trash after activation failure",
            )
        return {
            "checkpoint_id": checkpoint.checkpoint_id if checkpoint is not None else "",
            "trashed_paths": trashed_paths,
            "authority_summary": self.authority_summary(workspace_id),
        }

    def _plan_resource_artifact_restores(
        self,
        root: Path,
        trashed_paths: Mapping[str, str] | Iterable[str],
    ) -> list[tuple[Path, Path]]:
        if isinstance(trashed_paths, Mapping):
            raw_pairs = list(trashed_paths.items())
        elif isinstance(trashed_paths, (str, bytes)):
            raise ValueError("Resource artifact restore paths must be a mapping or iterable of paths.")
        else:
            raw_pairs = [("", path) for path in trashed_paths]

        trash_root = self._trash_root_path(root).resolve(strict=False)
        planned_moves: list[tuple[Path, Path]] = []
        for raw_destination, raw_source in raw_pairs:
            source_value = str(raw_source or "").strip()
            if not source_value:
                raise ValueError("Resource artifact Trash path is required.")
            source = self._resolve_within_root(root, source_value)
            try:
                relative_to_trash = source.relative_to(trash_root)
            except ValueError:
                raise ValueError("Resource artifact must be restored from the managed Trash.") from None
            if len(relative_to_trash.parts) < 2:
                raise ValueError("Resource artifact Trash path has no recoverable destination.")

            destination_value = str(raw_destination or "").strip()
            if destination_value:
                destination = self._resolve_within_root(root, destination_value, allow_missing=True)
            else:
                destination = self._resolve_within_root(
                    root,
                    str(Path(*relative_to_trash.parts[1:])),
                    allow_missing=True,
                )
            if destination == root:
                raise ValueError("Resource artifact restore destination cannot be the sandbox root.")
            try:
                destination.relative_to(trash_root)
            except ValueError:
                pass
            else:
                raise ValueError("Resource artifact restore destination cannot remain in Trash.")
            if self._path_exists(destination):
                raise FileExistsError(f"Restore destination already exists: {destination}")
            planned_moves.append((source, destination))

        self._validate_resource_artifact_moves(planned_moves)
        return planned_moves

    def _plan_resource_artifact_return_to_trash(
        self,
        root: Path,
        restore_handle: Iterable[Mapping[str, object]],
    ) -> list[tuple[Path, Path]]:
        if isinstance(restore_handle, (str, bytes, Mapping)):
            raise ValueError("Resource artifact restore handle must be an iterable of path mappings.")

        trash_root = self._trash_root_path(root).resolve(strict=False)
        planned_moves: list[tuple[Path, Path]] = []
        for item in restore_handle:
            if not isinstance(item, Mapping):
                raise ValueError("Resource artifact restore handle contains an invalid entry.")
            restored_value = str(item.get("restored_path") or "").strip()
            trash_value = str(item.get("trash_path") or "").strip()
            if not restored_value or not trash_value:
                raise ValueError("Resource artifact restore handle contains an incomplete path.")

            source = self._resolve_within_root(root, restored_value)
            destination = self._resolve_within_root(root, trash_value, allow_missing=True)
            if source == root:
                raise ValueError("Resource artifact compensation source cannot be the sandbox root.")
            try:
                source.relative_to(trash_root)
            except ValueError:
                pass
            else:
                raise ValueError("Resource artifact compensation source cannot remain in Trash.")
            try:
                destination.relative_to(trash_root)
            except ValueError:
                raise ValueError("Resource artifact compensation must return to managed Trash.") from None
            if self._path_exists(destination):
                raise FileExistsError(f"Trash destination already exists: {destination}")
            planned_moves.append((source, destination))

        self._validate_resource_artifact_moves(planned_moves)
        return planned_moves

    @staticmethod
    def _validate_resource_artifact_moves(planned_moves: list[tuple[Path, Path]]) -> None:
        for index, (source, destination) in enumerate(planned_moves):
            for other_source, other_destination in planned_moves[index + 1 :]:
                if source == other_source or destination == other_destination:
                    raise ValueError("Resource artifact restore paths must be unique.")
                if (
                    source.is_relative_to(other_source)
                    or other_source.is_relative_to(source)
                    or destination.is_relative_to(other_destination)
                    or other_destination.is_relative_to(destination)
                ):
                    raise ValueError("Resource artifact restore paths cannot overlap.")

    def _compensate_resource_artifact_restores(
        self,
        planned_moves: Iterable[tuple[Path, Path]],
    ) -> list[str]:
        rollback_errors: list[str] = []
        for source, destination in reversed(list(planned_moves)):
            source_exists = self._path_exists(source)
            destination_exists = self._path_exists(destination)
            if source_exists and not destination_exists:
                continue
            if destination_exists and not source_exists:
                try:
                    self._ensure_directory(source.parent)
                    self._move_path(destination, source)
                except Exception as exc:
                    logger.warning("Sandbox trash restore rollback failed (%s -> %s): %s", destination, source, exc)
                    rollback_errors.append(str(exc) or "Unable to restore artifact to Trash.")
                continue
            rollback_errors.append("Resource artifact restore rollback reached an ambiguous path state.")
        return rollback_errors

    def list_state(
        self,
        workspace_id: str,
        resources: Iterable[ResourceRecord],
        *,
        selected_path: str | None = None,
        preview_path: str | None = None,
        workspace_root_path: str | None = None,
        authority_summary: WorkspaceAuthoritySummary | dict[str, object] | None = None,
    ) -> SandboxState:
        sandbox_root = self.ensure_workspace_root(workspace_id)
        active_workspace_root = self._active_workspace_root_path(workspace_id, workspace_root_path)
        resource_index = self._resource_index(resources, root=sandbox_root)
        nodes = self._walk_nodes(sandbox_root, resource_index)
        preview = (
            self.preview(workspace_id, SandboxPreviewRequest(workspace_id=workspace_id, path=preview_path))
            if preview_path
            else None
        )
        total_files = sum(1 for node in nodes if node.node_kind == "file")
        total_directories = sum(1 for node in nodes if node.node_kind == "directory")
        total_size_bytes = sum(int(getattr(node, "size_bytes", 0) or 0) for node in nodes)
        last_updated_at = max(
            (str(getattr(node, "updated_at", "") or "") for node in nodes if getattr(node, "updated_at", "")),
            default="",
        )
        command_history = self._command_history.get(workspace_id, [])
        resolved_authority_summary = self._normalized_authority_summary(
            workspace_id,
            authority_summary,
            active_workspace_root=active_workspace_root,
        )
        return SandboxState(
            workspace_id=workspace_id,
            root_path=str(sandbox_root),
            sandbox_root_path=str(sandbox_root),
            workspace_root_path=active_workspace_root,
            active_workspace_root=active_workspace_root,
            trash_root_path=str(self._trash_root_path(sandbox_root)),
            managed_roots=list(TRAINER_SANDBOX_MANAGED_ROOTS),
            ready=True,
            linked_resource_count=sum(1 for resource in resources if resource.sandbox_path),
            total_files=total_files,
            total_directories=total_directories,
            total_size_bytes=total_size_bytes,
            last_updated_at=last_updated_at,
            nodes=nodes,
            selected_path=selected_path,
            preview=preview,
            recent_commands=command_history[:12],
            latest_command=command_history[0] if command_history else None,
            notes=self._build_notes(resources, sandbox_root, total_files),
            capability_summary=self._build_capability_summary(
                sandbox_root,
                workspace_id=workspace_id,
            ),
            authority=resolved_authority_summary,
        )

    def preview(self, workspace_id: str, request: SandboxPreviewRequest) -> SandboxPreview:
        from ..workspace.authority import OperationType

        root = self.ensure_operation_root(workspace_id)
        try:
            target = self._resolve_within_root(root, request.path)
        except ValueError as exc:
            raise ValueError("Sandbox path must stay inside the active workspace root.") from exc
        authority = self._workspace_authority(workspace_id)
        authority.check_permission(OperationType.PREVIEW, target)
        relative = self._relative_path(root, target)
        if self._path_is_dir(target):
            child_paths = self._iterdir_paths(target)
            child_names = sorted(item.name for item in child_paths)[:24]
            body = "\n".join(child_names)
            return SandboxPreview(
                path=str(target),
                relative_path=relative,
                title=target.name or relative or workspace_id,
                node_kind="directory",
                file_kind="directory",
                rendered_from="directory",
                content=body,
                excerpt=body[:400],
                is_binary=False,
                is_editable=False,
                metadata={
                    "child_count": len(child_paths),
                    "children_preview": child_names,
                },
            )

        suffix = target.suffix.lower()
        file_kind = self._file_kind_for_path(target)
        editable = file_kind in {"text", "markdown", "code", "html", "document", "table", "notebook"}
        binary = file_kind in {"image", "binary", "archive"}
        preview_artifact_path: str | None = None
        structured_data: dict[str, object] | None = None
        preview_tier: Literal["rich", "converted", "metadata"] = "rich"
        preview_kind = "text"
        body: str = ""
        target_stat = self._path_stat(target)
        structured_preview_limit = (
            self._STRUCTURED_PREVIEW_READ_LIMIT
            if suffix in {".csv", ".tsv", ".ipynb", ".xlsx", ".ods"}
            else None
        )
        if suffix == ".pdf":
            body = self._extract_pdf_text(target)
            preview_artifact_path = self._write_preview_artifact(
                workspace_id,
                source_path=target,
                rendered_from="extracted-text",
                body=body,
            )
            rendered_from = "extracted-text"
            preview_tier = "converted"
            preview_kind = "document"
        elif suffix in {".docx", ".pptx"}:
            body = _convert_openxml_to_markdown(str(target)) or ""
            if not body:
                if suffix == ".docx":
                    body = self._extract_zip_xml_text(target, "word/document.xml")
                else:
                    converted_body, _structured = _openxml_presentation_preview(str(target))
                    body = converted_body or ""
            preview_artifact_path = self._write_preview_artifact(
                workspace_id,
                source_path=target,
                rendered_from="extracted-text",
                body=body,
            )
            rendered_from = "extracted-text"
            preview_tier = "converted"
            preview_kind = "document"
        elif suffix in {".odt", ".odp", ".rtf"}:
            body = (
                _convert_odf_to_markdown(str(target))
                if suffix != ".rtf"
                else _convert_rtf_to_markdown(str(target))
            ) or self._read_text_limited(target, limit=self._STRUCTURED_PREVIEW_READ_LIMIT) or ""
            preview_artifact_path = self._write_preview_artifact(
                workspace_id,
                source_path=target,
                rendered_from="converted-text",
                body=body or "",
            )
            rendered_from = "converted-text"
            preview_tier = "converted"
            preview_kind = "document"
        elif suffix == ".epub":
            body = _convert_epub_to_markdown(str(target)) or self._read_text_limited(target, limit=self._STRUCTURED_PREVIEW_READ_LIMIT) or ""
            preview_artifact_path = self._write_preview_artifact(
                workspace_id,
                source_path=target,
                rendered_from="converted-text",
                body=body,
            )
            rendered_from = "converted-text"
            preview_tier = "converted"
            preview_kind = "document"
        elif suffix == ".eml":
            body = _convert_eml_to_markdown(str(target)) or self._read_text_limited(target, limit=self._STRUCTURED_PREVIEW_READ_LIMIT) or ""
            preview_artifact_path = self._write_preview_artifact(
                workspace_id,
                source_path=target,
                rendered_from="converted-text",
                body=body,
            )
            rendered_from = "converted-text"
            preview_tier = "converted"
            preview_kind = "document"
        elif suffix == ".ods":
            body = get_structured_preview_markdown(str(target)) or _convert_odf_to_markdown(str(target)) or ""
            rendered_from = "converted-table"
            preview_tier = "converted"
            preview_kind = "table"
        elif suffix == ".xlsx":
            body = get_structured_preview_markdown(str(target)) or ""
            rendered_from = "converted-table"
            preview_tier = "converted"
            preview_kind = "table"
        elif file_kind == "archive":
            body = _convert_archive_to_markdown(str(target)) or ""
            rendered_from = "converted-archive" if body.strip() else "archive-meta"
            preview_tier = "converted" if body.strip() else "metadata"
            preview_kind = "archive"
            structured_data = self._archive_preview_data(target)
        elif binary:
            body = f"Binary file: {target.name}\nSize: {target_stat.st_size} bytes"
            rendered_from = "binary-meta"
            preview_tier = "metadata"
            preview_kind = "image" if file_kind == "image" else "text"
        else:
            if structured_preview_limit is not None:
                body = self._read_text_limited(target, limit=structured_preview_limit)
            else:
                body = self._read_text(target, encoding="utf-8", errors="replace")
            rendered_from = "raw"
            if suffix in {".csv", ".tsv"}:
                preview_kind = "table"
            elif suffix == ".ipynb":
                preview_kind = "notebook"
            elif suffix in {".html", ".htm"}:
                preview_kind = "markup"
        if suffix in {".csv", ".tsv", ".pdf", ".docx", ".docm", ".epub", ".eml", ".ipynb", ".xlsx", ".ods", ".pptx", ".pptm", ".html", ".htm"}:
            structured_data = get_structured_preview_data(str(target), body)
        if preview_artifact_path is None and file_kind == "archive" and body.strip():
            preview_artifact_path = self._write_preview_artifact(
                workspace_id,
                source_path=target,
                rendered_from=rendered_from,
                body=body,
            )
        if preview_artifact_path is None and suffix in {".csv", ".tsv", ".pdf", ".docx", ".docm", ".epub", ".eml", ".ipynb", ".xlsx", ".ods", ".pptx", ".pptm", ".html", ".htm"}:
            artifact_body = get_structured_preview_markdown(str(target), body) or body
            if artifact_body.strip():
                preview_artifact_path = self._write_preview_artifact(
                    workspace_id,
                    source_path=target,
                    rendered_from="structured-preview",
                    body=artifact_body,
                )
        html: str | None = None
        if file_kind not in {"image", "audio", "video"}:
            try:
                preview_result = self._preview_service.get_preview(str(target))
                if preview_result.html:
                    html = preview_result.html
            except Exception as exc:
                logger.debug("Sandbox HTML preview rendering failed for %s: %s", target, exc)
                html = None
        excerpt = body[:1200]
        return SandboxPreview(
            path=str(target),
            relative_path=relative,
            title=target.name,
            node_kind="file",
            file_kind=file_kind,
            preview_tier=preview_tier,
            preview_kind=preview_kind,
            language_hint=self._language_hint(target) or "",
            rendered_from=rendered_from,
            content=body,
            html=html,
            excerpt=excerpt,
            is_binary=binary,
            is_editable=editable and not binary and suffix != ".pdf",
            structured_data=structured_data,
            metadata={
                "size_bytes": target_stat.st_size,
                "updated_at": datetime.fromtimestamp(target_stat.st_mtime, tz=UTC).isoformat(),
                "preview_artifact_path": preview_artifact_path,
                "content_truncated": bool(structured_preview_limit is not None and target_stat.st_size > structured_preview_limit),
            },
        )

    def mkdir(
        self,
        workspace_id: str,
        request: SandboxMkdirRequest,
        *,
        resources: Iterable[ResourceRecord] | None = None,
        workspace_root_path: str | None = None,
        authority_summary: WorkspaceAuthoritySummary | dict[str, object] | None = None,
    ) -> SandboxState:
        from ..workspace.authority import PermissionLevel

        requested_path = str(request.path or "").strip().replace("\\", "/")
        if not requested_path or requested_path in {".", "/"}:
            raise ValueError("Sandbox folder path is required.")

        root = self.ensure_operation_root(workspace_id)
        try:
            target = self._resolve_within_root(root, requested_path, allow_missing=True)
        except ValueError:
            self._log_workspace_boundary_denial(
                workspace_id,
                operation="mkdir",
                raw_path=request.path,
                reason="Path is outside the active workspace root.",
            )
            raise ValueError("Sandbox path must stay inside the active workspace root.") from None
        if target == root:
            raise ValueError("Sandbox folder path cannot target the sandbox root directly.")
        authority, previous_level = self._operation_authority(
            workspace_id,
            PermissionLevel.REORGANIZE,
            explicit_destructive_policy=bool(
                getattr(request, "explicit_destructive_policy", False)
            ),
        )
        try:
            if not authority.check_permission("mkdir", target):
                raise PermissionError(f"Mkdir permission denied for sandbox path: {request.path}")
            target.mkdir(parents=True, exist_ok=True)
        finally:
            self._restore_authority_permission(authority, previous_level)
        resolved_authority_summary = authority_summary or authority.summary_model()
        return self.list_state(
            workspace_id,
            list(resources or []),
            selected_path=str(target),
            preview_path=str(target),
            workspace_root_path=workspace_root_path or authority.active_workspace_root or str(root),
            authority_summary=resolved_authority_summary,
        )

    def write(self, workspace_id: str, request: SandboxWriteRequest) -> SandboxPreview:
        from ..workspace.authority import PermissionLevel

        root = self.ensure_operation_root(workspace_id)
        try:
            target = self._resolve_relative_destination_within_root(
                root,
                request.path,
                allow_missing=bool(getattr(request, "create", False)),
            )
        except ValueError:
            self._log_workspace_boundary_denial(
                workspace_id,
                operation="write",
                raw_path=request.path,
                reason="Path is outside the active workspace root.",
            )
            raise ValueError("Sandbox path must stay inside the active workspace root.") from None
        authority, previous_level = self._operation_authority(
            workspace_id,
            PermissionLevel.APPLY,
            explicit_destructive_policy=bool(
                getattr(request, "explicit_destructive_policy", False)
            ),
        )
        try:
            if not authority.check_permission("write", target):
                raise PermissionError(f"Write permission denied for sandbox path: {request.path}")
            if self._path_exists(target) and self._path_is_dir(target):
                raise IsADirectoryError(f"Cannot write directory content: {target}")
            self._ensure_directory(target.parent)
            self._write_text(target, request.content, encoding="utf-8")
        finally:
            self._restore_authority_permission(authority, previous_level)
        # §13.21 Record sandbox file written event
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "sandbox_file_written",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "path": request.path,
                    "content_length": len(request.content),
                },
                after_state_ref={"path": request.path, "written": True},
                reversibility="reversible",
                audit_note=f"Sandbox file written: '{request.path}'",
            )
        return self.preview(
            workspace_id,
            SandboxPreviewRequest(workspace_id=workspace_id, path=str(target)),
        )

    def delete(
        self,
        workspace_id: str,
        request: SandboxDeleteRequest,
        *,
        resources: Iterable[ResourceRecord] | None = None,
        workspace_root_path: str | None = None,
        authority_summary: WorkspaceAuthoritySummary | dict[str, object] | None = None,
    ) -> SandboxState:
        from ..workspace.authority import PermissionLevel

        root = self.ensure_operation_root(workspace_id)
        try:
            target = self._resolve_within_root(root, request.path)
        except ValueError:
            self._log_workspace_boundary_denial(
                workspace_id,
                operation="delete",
                raw_path=request.path,
                reason="Path is outside the active workspace root.",
            )
            raise ValueError("Sandbox path must stay inside the active workspace root.") from None
        if target == root:
            raise ValueError("Cannot delete sandbox root.")
        authority, previous_level = self._operation_authority(
            workspace_id,
            PermissionLevel.DESTRUCTIVE,
            explicit_destructive_policy=bool(
                getattr(request, "explicit_destructive_policy", False)
            ),
        )
        try:
            if not authority.check_permission("delete", target):
                raise PermissionError(f"Delete permission denied for sandbox path: {request.path}")
            checkpoint = authority.create_trash_checkpoint(
                target,
                description=f"Before deleting sandbox path {request.path}",
                metadata={"workspace_id": workspace_id, "sandbox_root": str(root)},
            )
            trashed_path = authority.trash_path(target)
        finally:
            self._restore_authority_permission(authority, previous_level)
        # §13.21 Record sandbox file deleted event
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "sandbox_file_deleted",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={"path": request.path, "trashed_path": trashed_path},
                before_state_ref={"path": request.path, "existed": True},
                after_state_ref={
                    "path": request.path,
                    "existed": False,
                    "trashed_path": trashed_path,
                    "checkpoint_id": checkpoint.checkpoint_id,
                },
                reversibility="compensatable",
                audit_note=f"Sandbox file deleted: '{request.path}'",
            )
        authority_summary = authority.summary_model()
        return self.list_state(
            workspace_id,
            list(resources or []),
            selected_path=None,
            workspace_root_path=workspace_root_path or authority.active_workspace_root or str(root),
            authority_summary=authority_summary,
        )

    def restore(
        self,
        workspace_id: str,
        request: SandboxRestoreRequest,
        *,
        resources: Iterable[ResourceRecord] | None = None,
        workspace_root_path: str | None = None,
        authority_summary: WorkspaceAuthoritySummary | dict[str, object] | None = None,
    ) -> SandboxState:
        from ..workspace.authority import PermissionLevel

        root = self.ensure_operation_root(workspace_id)
        try:
            target = self._resolve_within_root(root, request.path)
            restore_path = request.restore_path
            restore_destination = (
                self._resolve_relative_destination_within_root(
                    root,
                    restore_path,
                    allow_missing=True,
                )
                if restore_path is not None and restore_path.strip()
                else None
            )
        except ValueError:
            self._log_workspace_boundary_denial(
                workspace_id,
                operation="restore",
                raw_path=request.path,
                reason="Path is outside the active workspace root.",
                details={"restorePath": request.restore_path},
            )
            raise ValueError("Sandbox path must stay inside the active workspace root.") from None
        if target == root:
            raise ValueError("Cannot restore the sandbox root.")

        authority, previous_level = self._operation_authority(
            workspace_id,
            PermissionLevel.DESTRUCTIVE,
            explicit_destructive_policy=bool(
                getattr(request, "explicit_destructive_policy", False)
            ),
        )
        try:
            checkpoint = authority.create_checkpoint(
                f"Before restoring sandbox path {request.path}",
                metadata={
                    "workspace_id": workspace_id,
                    "sandbox_root": str(root),
                    "restore_path": request.restore_path or "",
                },
            )
            restored_path = authority.restore_from_trash(
                target,
                str(restore_destination) if restore_destination is not None else None,
            )
        finally:
            self._restore_authority_permission(authority, previous_level)
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "sandbox_file_restored",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "path": request.path,
                    "restore_path": request.restore_path or None,
                    "restored_path": restored_path,
                },
                before_state_ref={"path": request.path, "existed": True},
                after_state_ref={
                    "path": restored_path,
                    "existed": True,
                    "restored_path": restored_path,
                    "checkpoint_id": checkpoint.checkpoint_id,
                },
                reversibility="reversible",
                audit_note=f"Sandbox file restored: '{request.path}' -> '{restored_path}'",
            )
        resolved_authority_summary = authority_summary or authority.summary_model()
        selected_path = Path(restored_path).relative_to(root).as_posix()
        return self.list_state(
            workspace_id,
            list(resources or []),
            selected_path=selected_path,
            workspace_root_path=workspace_root_path or authority.active_workspace_root or str(root),
            authority_summary=resolved_authority_summary,
        )

    def rename(self, workspace_id: str, request: SandboxRenameRequest) -> SandboxPreview:
        from ..workspace.authority import PermissionLevel

        root = self.ensure_operation_root(workspace_id)
        try:
            source = self._resolve_within_root(root, request.path)
            target = self._resolve_relative_destination_within_root(
                root,
                request.new_path,
                allow_missing=True,
            )
        except ValueError:
            self._log_workspace_boundary_denial(
                workspace_id,
                operation="rename",
                raw_path=request.path,
                reason="Path is outside the active workspace root.",
                details={"newPath": request.new_path},
            )
            raise ValueError("Sandbox path must stay inside the active workspace root.") from None
        authority, previous_level = self._operation_authority(
            workspace_id,
            PermissionLevel.REORGANIZE,
            explicit_destructive_policy=bool(
                getattr(request, "explicit_destructive_policy", False)
            ),
        )
        try:
            if not authority.check_permission("rename", source):
                raise PermissionError(f"Rename permission denied for sandbox path: {request.path}")
            self._ensure_directory(target.parent)
            source.rename(target)
        finally:
            self._restore_authority_permission(authority, previous_level)
        # §13.21 Record sandbox file renamed event
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "sandbox_file_renamed",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={"old_path": request.path, "new_path": request.new_path},
                before_state_ref={"path": request.path},
                after_state_ref={"path": request.new_path},
                reversibility="reversible",
                audit_note=f"Sandbox file renamed: '{request.path}' -> '{request.new_path}'",
            )
        return self.preview(
            workspace_id,
            SandboxPreviewRequest(workspace_id=workspace_id, path=str(target)),
        )

    def batch_rename(self, workspace_id: str, request: SandboxBatchRenameRequest) -> dict[str, object]:
        from ..workspace.authority import PermissionLevel

        root = Path(self.ensure_operation_root(workspace_id)).expanduser().resolve(strict=False)
        items = [item for item in request.items if str(item.path or "").strip() and str(item.new_path or "").strip()]
        if not items:
            raise ValueError("At least one rename item is required.")

        authority, previous_level = self._operation_authority(
            workspace_id,
            PermissionLevel.REORGANIZE,
            explicit_destructive_policy=bool(
                getattr(request, "explicit_destructive_policy", False)
            ),
        )
        planned_moves: list[tuple[Path, Path, str, str]] = []
        seen_targets: set[str] = set()
        before_paths: list[str] = []
        after_paths: list[str] = []
        patch_lines: list[str] = []
        try:
            for item in items:
                try:
                    source = self._resolve_within_root(root, item.path)
                    target = self._resolve_within_root(root, item.new_path, allow_missing=True)
                except ValueError:
                    self._log_workspace_boundary_denial(
                        workspace_id,
                        operation="rename",
                        raw_path=item.path,
                        reason="Path is outside the active workspace root.",
                        details={"newPath": item.new_path},
                    )
                    raise ValueError("Sandbox path must stay inside the active workspace root.") from None
                if not authority.check_permission("rename", source):
                    raise PermissionError(f"Rename permission denied for sandbox path: {item.path}")
                if source == target:
                    raise ValueError("Sandbox batch rename requires distinct source and target paths.")
                before_path = source.resolve(strict=False).relative_to(root).as_posix()
                after_path = target.resolve(strict=False).relative_to(root).as_posix()
                if after_path in seen_targets:
                    raise ValueError("Sandbox batch rename target paths must be unique.")
                if self._path_exists(target):
                    raise FileExistsError(f"Sandbox batch rename target already exists: {item.new_path}")
                seen_targets.add(after_path)
                before_paths.append(before_path)
                after_paths.append(after_path)
                planned_moves.append((source, target, before_path, after_path))

            batch_checkpoint = authority.create_checkpoint(
                f"Before batch reorganizing sandbox workspace {workspace_id}",
                metadata={
                    "workspace_id": workspace_id,
                    "sandbox_root": str(root),
                    "operation": "batch_rename",
                    "item_count": len(planned_moves),
                },
            )

            changes: list[dict[str, str]] = []
            completed_moves: list[tuple[Path, Path]] = []
            try:
                for source, target, before_path, after_path in planned_moves:
                    self._ensure_directory(target.parent)
                    source.rename(target)
                    completed_moves.append((source, target))
                    changes.append({"from": before_path, "to": after_path})
                    patch_lines.append(f"rename {before_path} -> {after_path}")
            except Exception:
                for source, target in reversed(completed_moves):
                    try:
                        if self._path_exists(target):
                            target.rename(source)
                    except Exception as exc:
                        logger.warning("Sandbox batch rename rollback failed (%s -> %s): %s", target, source, exc)
                        continue
                raise
        finally:
            self._restore_authority_permission(authority, previous_level)

        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "sandbox_files_reorganized",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "checkpoint_id": batch_checkpoint.checkpoint_id,
                    "item_count": len(changes),
                    "changes": list(changes),
                    "patch": list(patch_lines),
                    "diff_summary": "; ".join(patch_lines),
                },
                before_state_ref={
                    "workspace_id": workspace_id,
                    "paths": list(before_paths),
                },
                after_state_ref={
                    "workspace_id": workspace_id,
                    "paths": list(after_paths),
                    "patch": list(patch_lines),
                    "diff_summary": "; ".join(patch_lines),
                },
                reversibility="compensatable",
                audit_note=f"Sandbox batch rename: {len(changes)} item(s) reorganized",
            )

        return {
            "ok": True,
            "workspace_id": workspace_id,
            "checkpoint_id": batch_checkpoint.checkpoint_id,
            "item_count": len(changes),
            "changes": changes,
            "patch": patch_lines,
            "diff_summary": "; ".join(patch_lines),
            "before_paths": before_paths,
            "after_paths": after_paths,
            "authority_summary": authority.summary_model().model_dump(mode="json"),
        }
