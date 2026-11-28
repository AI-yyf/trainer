from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal
from uuid import uuid4

from ..core.models import (
    ResourceRecord,
    SandboxArchiveAuditEntry,
    SandboxArchiveAuditFinding,
    SandboxArchiveAuditResult,
    SandboxCommandEntry,
    SandboxCommandRequest,
    SandboxPatchRequest,
    SandboxSkillEgressDecision,
    SandboxSkillManifestAuditResult,
    SandboxSkillManifestFinding,
    SandboxSkillRunResult,
    SandboxSkillRuntimePolicy,
    SandboxSkillRuntimePreflightResult,
)
from ..core.process_env import child_process_environment

if TYPE_CHECKING:
    pass

from .constants import (
    ARCHIVE_AUDIT_ENTRY_PREVIEW_LIMIT,
    ARCHIVE_AUDIT_MAX_ENTRIES,
    ARCHIVE_AUDIT_MAX_TOTAL_UNCOMPRESSED_BYTES,
    ARCHIVE_AUDIT_POLICY,
    SKILL_EGRESS_ENFORCEMENT_MISSING_REASON,
    SKILL_EGRESS_NODE_GUARD_MODE,
    SKILL_EGRESS_OS_CONTAINER_MODE,
    SKILL_EGRESS_PYTHON_GUARD_MODE,
    SKILL_MANIFEST_NAMES,
    SKILL_MANIFEST_POLICY,
    SKILL_RUN_GATE_POLICY,
    SKILL_RUNTIME_FORBIDDEN_COMMAND_PATTERNS,
    SKILL_RUNTIME_MAX_TIMEOUT_MS,
    SKILL_RUNTIME_POLICY,
    LinkedResourceChange,
    LinkedResourceSnapshot,
    _contains_pattern,
    _SkillManifestContract,
)

logger = logging.getLogger(__name__)


class PatchAndSkillRunMixin:
    if TYPE_CHECKING:
        _append_unique: Any
        _archive_format: Any
        _audit_archive_entry: Any
        _command_history: Any
        _copy_file: Any
        _current_platform: Any
        _dedupe_archive_findings: Any
        _dedupe_skill_findings: Any
        _dedupe_strings: Any
        _default_archive_destination: Any
        _ensure_directory: Any
        _ensure_workspace_scaffold: Any
        _event_ledger: Any
        _execute_skill_run_in_os_container: Any
        _find_path_by_inode: Any
        _fs_path: Any
        _is_scaffold_relative_path: Any
        _iterdir_paths: Any
        _log_workspace_boundary_denial: Any
        _move_path: Any
        _operation_authority: Any
        _patch_required_permission_level: Any
        _path_exists: Any
        _path_is_dir: Any
        _path_is_file: Any
        _prepare_skill_process_invocation: Any
        _relative_path: Any
        _remove_tree: Any
        _replace_node_guard_placeholders: Any
        _resolve_within_root: Any
        _resource_operation_path: Any
        _restore_authority_permission: Any
        _runtime_command_audited_paths: Any
        _runtime_command_script_findings: Any
        _scan_skill_text: Any
        _skill_egress_decision: Any
        _skill_finding: Any
        _skill_runtime_command_argv: Any
        _skill_runtime_env_name_is_allowed: Any
        _skill_runtime_environment: Any
        _skill_runtime_inline_execution_reason: Any
        _skill_runtime_network_host_is_blocked: Any
        _skill_runtime_output_paths: Any
        _skill_script_paths: Any
        _snapshot_linked_resource: Any
        _subprocess_output_text: Any
        _tar_archive_entries: Any
        _truncate_output: Any
        _unlink_path: Any
        _validate_runtime_output_path: Any
        _windows_short_path: Any
        _write_node_egress_guard: Any
        _write_python_egress_guard: Any
        _write_text: Any
        _zip_archive_entries: Any
        ensure_operation_root: Any
        ensure_workspace_root: Any

    def apply_patch(self, workspace_id: str, request: SandboxPatchRequest) -> dict[str, object]:

        root = self.ensure_operation_root(workspace_id).resolve(strict=False)
        items = [
            item
            for item in request.items
            if any(
                str(getattr(item, field, "") or "").strip()
                for field in ("op", "path", "source", "new_path", "target", "content")
            )
        ]
        if not items:
            raise ValueError("At least one patch item is required.")

        authority, previous_level = self._operation_authority(
            workspace_id,
            self._patch_required_permission_level(items),
            explicit_destructive_policy=bool(
                getattr(request, "explicit_destructive_policy", False)
            ),
        )
        checkpoint = None
        backup_root = root / ".trainer" / "patch-backups" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        planned_changes: list[dict[str, str]] = []
        applied_changes: list[dict[str, str]] = []
        patch_lines: list[str] = []
        before_paths: list[str] = []
        after_paths: list[str] = []
        touched_paths: set[str] = set()

        def remember_path(path_text: str) -> None:
            normalized = str(path_text or "").strip()
            if not normalized:
                raise ValueError("Patch item must reference a workspace path.")
            if normalized in touched_paths:
                raise ValueError(f"Patch item targets the same path more than once: {normalized}")
            touched_paths.add(normalized)

        def relpath(path: Path) -> str:
            return path.relative_to(root).as_posix()

        try:
            for item in items:
                op = str(item.op or "").strip().lower()
                if op == "write":
                    target = self._resolve_within_root(root, item.path, allow_missing=bool(item.create))
                    if self._path_exists(target) and self._path_is_dir(target):
                        raise IsADirectoryError(f"Cannot write directory content: {target}")
                    if not authority.check_permission("write", target):
                        raise PermissionError(f"Write permission denied for sandbox path: {item.path}")
                    relative = relpath(target)
                    remember_path(relative)
                    backup_path = ""
                    if self._path_exists(target):
                        backup_path = str(backup_root / relative)
                        self._ensure_directory(Path(backup_path).parent)
                        self._copy_file(target, Path(backup_path))
                    patch_lines.append(
                        f"write {relative} {'[update]' if backup_path else '[create]'}"
                    )
                    planned_changes.append(
                        {
                            "op": "write",
                            "path": relative,
                            "backup_path": backup_path,
                            "mode": "update" if backup_path else "create",
                            "content_length": str(len(item.content)),
                            "encoding": item.encoding or "utf-8",
                        }
                    )
                    before_paths.append(relative)
                    after_paths.append(relative)
                    continue

                if op == "delete":
                    target = self._resolve_within_root(root, item.path)
                    if not authority.check_permission("delete", target):
                        raise PermissionError(f"Delete permission denied for sandbox path: {item.path}")
                    relative = relpath(target)
                    remember_path(relative)
                    planned_changes.append(
                        {
                            "op": "delete",
                            "path": relative,
                            "trashed_path": "",
                        }
                    )
                    patch_lines.append(f"trash {relative}")
                    before_paths.append(relative)
                    after_paths.append(relative)
                    continue

                if op == "rename":
                    source = self._resolve_within_root(root, item.path)
                    target = self._resolve_within_root(root, item.new_path, allow_missing=True)
                    if source == target:
                        raise ValueError("Patch rename requires distinct source and target paths.")
                    if self._path_exists(target):
                        raise FileExistsError(f"Patch rename target already exists: {item.new_path}")
                    if not authority.check_permission("rename", source):
                        raise PermissionError(f"Rename permission denied for sandbox path: {item.path}")
                    source_relative = relpath(source)
                    target_relative = relpath(target)
                    remember_path(source_relative)
                    remember_path(target_relative)
                    patch_lines.append(f"rename {source_relative} -> {target_relative}")
                    planned_changes.append(
                        {
                            "op": "rename",
                            "source": source_relative,
                            "target": target_relative,
                        }
                    )
                    before_paths.append(source_relative)
                    after_paths.append(target_relative)
                    continue

                raise ValueError(f"Unsupported patch operation: {item.op}")

            checkpoint = authority.create_checkpoint(
                f"Before applying sandbox patch for {workspace_id}",
                metadata={
                    "workspace_id": workspace_id,
                    "sandbox_root": str(root),
                    "label": request.label,
                    "note": request.note,
                    "patch": list(patch_lines),
                },
            )

            for change in planned_changes:
                op = change["op"]
                if op == "write":
                    target = root / change["path"]
                    content_item = next(
                        item for item in items if relpath(self._resolve_within_root(root, item.path, allow_missing=bool(item.create))) == change["path"] and str(item.op).strip().lower() == "write"
                    )
                    self._ensure_directory(target.parent)
                    self._write_text(target, content_item.content, encoding=content_item.encoding or "utf-8")
                    applied_changes.append(change)
                    continue

                if op == "delete":
                    target = self._resolve_within_root(root, change["path"])
                    trashed_path = authority.trash_path(target)
                    change["trashed_path"] = trashed_path
                    applied_changes.append(change)
                    after_paths[before_paths.index(change["path"])] = Path(trashed_path).relative_to(root).as_posix()
                    patch_lines[before_paths.index(change["path"])] = (
                        f"trash {change['path']} -> {Path(trashed_path).relative_to(root).as_posix()}"
                    )
                    continue

                if op == "rename":
                    source = self._resolve_within_root(root, change["source"])
                    target = self._resolve_within_root(root, change["target"], allow_missing=True)
                    self._ensure_directory(target.parent)
                    source.rename(target)
                    applied_changes.append(change)
                    continue

                raise ValueError(f"Unsupported patch operation: {op}")
        except Exception as exc:
            for change in reversed(applied_changes):
                try:
                    if change["op"] == "write":
                        target = root / change["path"]
                        backup_path = change.get("backup_path", "")
                        if backup_path:
                            backup = Path(backup_path)
                            if self._path_exists(target):
                                if self._path_is_dir(target):
                                    self._remove_tree(target, ignore_errors=True)
                                else:
                                    self._unlink_path(target)
                            self._ensure_directory(target.parent)
                            self._copy_file(backup, target)
                        else:
                            if self._path_exists(target):
                                if self._path_is_dir(target):
                                    self._remove_tree(target, ignore_errors=True)
                                else:
                                    self._unlink_path(target)
                        continue

                    if change["op"] == "delete":
                        trashed_path = change.get("trashed_path", "")
                        original = self._resolve_within_root(root, change["path"])
                        if trashed_path:
                            trashed = Path(trashed_path)
                            if self._path_exists(trashed):
                                self._ensure_directory(original.parent)
                                self._move_path(trashed, original)
                        continue

                    if change["op"] == "rename":
                        source = self._resolve_within_root(root, change["source"])
                        target = self._resolve_within_root(root, change["target"], allow_missing=True)
                        if self._path_exists(target):
                            self._ensure_directory(source.parent)
                            target.rename(source)
                except Exception as exc:
                    logger.warning("Rollback rename failed in sandbox patch: %s", exc)
                    continue

            if self._event_ledger is not None:
                self._event_ledger.record_event(
                    "sandbox_patch_failed",
                    actor="trainer",
                    scope="sandbox",
                    project_id=workspace_id,
                    payload_ref={
                        "workspace_id": workspace_id,
                        "label": request.label,
                        "note": request.note,
                        "checkpoint_id": checkpoint.checkpoint_id if checkpoint else "",
                        "patch": list(patch_lines),
                        "planned_change_count": len(planned_changes),
                        "applied_change_count": len(applied_changes),
                        "error": str(exc),
                    },
                    before_state_ref={
                        "workspace_id": workspace_id,
                        "paths": list(before_paths),
                    },
                    after_state_ref={
                        "workspace_id": workspace_id,
                        "paths": list(after_paths),
                        "rolled_back": True,
                    },
                    reversibility="compensatable",
                    audit_note=f"Sandbox patch failed: {request.label or workspace_id}",
                )
            raise
        finally:
            if self._path_exists(backup_root):
                self._remove_tree(backup_root, ignore_errors=True)
            self._restore_authority_permission(authority, previous_level)

        if checkpoint is None:
            raise RuntimeError("Sandbox patch checkpoint was not created.")

        diff_summary = "; ".join(patch_lines)
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "sandbox_patch_applied",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "workspace_id": workspace_id,
                    "label": request.label,
                    "note": request.note,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "item_count": len(applied_changes),
                    "patch": list(patch_lines),
                    "diff_summary": diff_summary,
                },
                before_state_ref={
                    "workspace_id": workspace_id,
                    "paths": list(before_paths),
                },
                after_state_ref={
                    "workspace_id": workspace_id,
                    "paths": list(after_paths),
                    "patch": list(patch_lines),
                    "diff_summary": diff_summary,
                },
                reversibility="compensatable",
                audit_note=f"Sandbox patch applied: {request.label or workspace_id}",
            )

        return {
            "ok": True,
            "workspace_id": workspace_id,
            "checkpoint_id": checkpoint.checkpoint_id,
            "item_count": len(applied_changes),
            "patch": list(patch_lines),
            "diff_summary": diff_summary,
            "changes": applied_changes,
            "authority_summary": authority.summary_model().model_dump(mode="json"),
        }

    def run_command(self, workspace_id: str, request: SandboxCommandRequest) -> SandboxCommandEntry:
        root = self.ensure_operation_root(workspace_id)
        raw_cwd = request.cwd or str(root)
        try:
            cwd = self._resolve_within_root(root, raw_cwd)
        except ValueError:
            self._log_workspace_boundary_denial(
                workspace_id,
                operation="command",
                raw_path=raw_cwd,
                reason="Command cwd is outside the active workspace root.",
                details={"command": request.command},
            )
            raise ValueError("Sandbox path must stay inside the active workspace root.") from None
        command_id = f"cmd-{uuid4().hex[:10]}"
        started_at = datetime.now(UTC).isoformat()
        timeout_ms = int(request.timeout_ms or (request.timeout_seconds * 1000))
        timeout_seconds = max(1, min(timeout_ms, 120_000)) / 1000
        if _contains_pattern(request.command, SKILL_RUNTIME_FORBIDDEN_COMMAND_PATTERNS):
            entry = SandboxCommandEntry(
                id=command_id,
                command=request.command,
                cwd=str(cwd),
                status="forbidden",
                exit_code=None,
                stdout="",
                stderr="Command rejected: forbidden pattern detected.",
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(),
                truncated=False,
            )
        else:
            try:
                argv = shlex.split(request.command, posix=os.name != "nt")
                if not argv:
                    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="No command provided.")
                else:
                    completed = subprocess.run(
                        argv,
                        shell=False,
                        cwd=str(cwd),
                        env=child_process_environment(),
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds,
                    )
                stdout = self._truncate_output(completed.stdout)
                stderr = self._truncate_output(completed.stderr)
                entry = SandboxCommandEntry(
                    id=command_id,
                    command=request.command,
                    cwd=str(cwd),
                    status="success" if completed.returncode == 0 else "error",
                    exit_code=completed.returncode,
                    stdout=stdout["text"],
                    stderr=stderr["text"],
                    started_at=started_at,
                    finished_at=datetime.now(UTC).isoformat(),
                    truncated=stdout["truncated"] or stderr["truncated"],
                )
            except subprocess.TimeoutExpired as exc:
                stdout = self._truncate_output(self._subprocess_output_text(exc.stdout))
                stderr = self._truncate_output(self._subprocess_output_text(exc.stderr))
                entry = SandboxCommandEntry(
                    id=command_id,
                    command=request.command,
                    cwd=str(cwd),
                    status="timeout",
                    exit_code=None,
                    stdout=stdout["text"],
                    stderr=stderr["text"],
                    started_at=started_at,
                    finished_at=datetime.now(UTC).isoformat(),
                    truncated=True,
                )
        self._command_history.setdefault(workspace_id, []).insert(0, entry)
        self._command_history[workspace_id] = self._command_history[workspace_id][:24]
        # §13.21 Record sandbox command executed event
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "sandbox_command_executed",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "command_id": entry.id,
                    "command": entry.command,
                    "status": entry.status,
                    "exit_code": entry.exit_code,
                },
                after_state_ref={"command_id": entry.id, "status": entry.status},
                reversibility="irreversible",
                audit_note=f"Sandbox command executed: '{entry.command}' ({entry.status})",
            )
        return entry

    def audit_skill_manifest(
        self,
        workspace_id: str,
        path: str,
        *,
        include_scripts: bool = True,
    ) -> SandboxSkillManifestAuditResult:
        root = self.ensure_operation_root(workspace_id)
        try:
            target = self._resolve_within_root(root, path)
        except ValueError as exc:
            raise ValueError("Sandbox path must stay inside the active workspace root.") from exc
        manifest_path = self._skill_manifest_path(target)
        manifest_text = self._read_text_limited(manifest_path)
        parsed_manifest = self._parse_manifest(manifest_path, manifest_text)
        manifest_contract = self._skill_manifest_contract(parsed_manifest, manifest_text, manifest_path)
        findings = self._scan_skill_text(
            manifest_text,
            source_path=str(manifest_path),
        )
        findings.extend(
            self._skill_contract_findings(
                requested_permissions=manifest_contract["requested_permissions"],
                network_allowlist=manifest_contract["network_allowlist"],
                execution_entrypoints=manifest_contract["execution_entrypoints"],
                source_path=str(manifest_path),
            )
        )

        audited_paths = [str(manifest_path)]
        if include_scripts:
            for script_path in self._skill_script_paths(
                root,
                target=target,
                manifest_path=manifest_path,
                execution_entrypoints=manifest_contract["execution_entrypoints"],
            ):
                if str(script_path) in audited_paths:
                    continue
                script_text = self._read_text_limited(script_path)
                audited_paths.append(str(script_path))
                findings.extend(
                    self._scan_skill_text(
                        script_text,
                        source_path=str(script_path),
                    )
                )

        deduped_findings = self._dedupe_skill_findings(findings)
        blocked = any(finding.severity == "blocker" for finding in deduped_findings)
        return SandboxSkillManifestAuditResult(
            workspace_id=workspace_id,
            path=str(target),
            manifest_path=str(manifest_path),
            skill_name=manifest_contract["skill_name"],
            status="blocked" if blocked else "allowed",
            allowed=not blocked,
            policy=SKILL_MANIFEST_POLICY,
            findings=deduped_findings,
            requested_permissions=manifest_contract["requested_permissions"],
            network_allowlist=manifest_contract["network_allowlist"],
            execution_entrypoints=manifest_contract["execution_entrypoints"],
            audited_paths=audited_paths,
        )

    def preflight_skill_runtime(
        self,
        workspace_id: str,
        path: str,
        *,
        runtime_policy: SandboxSkillRuntimePolicy,
        current_platform: Literal["windows", "macos", "linux"] | None = None,
        include_manifest_scripts: bool = True,
    ) -> SandboxSkillRuntimePreflightResult:
        root = self.ensure_operation_root(workspace_id)
        try:
            target = self._resolve_within_root(root, path)
        except ValueError as exc:
            raise ValueError("Sandbox path must stay inside the active workspace root.") from exc
        manifest_audit = self.audit_skill_manifest(
            workspace_id,
            path,
            include_scripts=include_manifest_scripts,
        )
        platform_name = current_platform or self._current_platform()
        findings: list[SandboxSkillManifestFinding] = []
        if not manifest_audit.allowed:
            for finding in manifest_audit.findings:
                if finding.severity != "blocker":
                    continue
                findings.append(
                    self._skill_finding(
                        finding.category,
                        f"Skill runtime preflight cannot pass because manifest audit is blocked: {finding.reason}",
                        evidence=finding.evidence or finding.reason,
                        source_path=finding.source_path or manifest_audit.manifest_path,
                    )
                )

        findings.extend(
            self._skill_runtime_policy_findings(
                root=root,
                source_path=manifest_audit.manifest_path or str(target),
                runtime_base_path=target if self._path_is_dir(target) else target.parent,
                runtime_policy=runtime_policy,
                current_platform=platform_name,
            )
        )
        normalized_output_paths = self._skill_runtime_output_paths(root, runtime_policy.output_paths)
        runtime_base_path = target if self._path_is_dir(target) else target.parent
        runtime_audited_paths = [
            str(item)
            for item in self._runtime_command_audited_paths(root, runtime_base_path, runtime_policy)
        ]
        audited_paths = self._dedupe_strings([*manifest_audit.audited_paths, *runtime_audited_paths])
        deduped_findings = self._dedupe_skill_findings(findings)
        blocked = any(finding.severity == "blocker" for finding in deduped_findings)
        return SandboxSkillRuntimePreflightResult(
            workspace_id=workspace_id,
            path=str(target),
            manifest_path=manifest_audit.manifest_path,
            skill_name=manifest_audit.skill_name,
            status="blocked" if blocked else "allowed",
            allowed=not blocked,
            policy=SKILL_RUNTIME_POLICY,
            manifest_policy=manifest_audit.policy,
            current_platform=platform_name,
            runtime_platform=runtime_policy.platform,
            command_templates=list(runtime_policy.command_templates),
            network_allowlist=list(runtime_policy.network_allowlist),
            env_whitelist=list(runtime_policy.env_whitelist),
            output_paths=list(runtime_policy.output_paths),
            normalized_output_paths=normalized_output_paths,
            timeout_ms=runtime_policy.timeout_ms,
            max_timeout_ms=SKILL_RUNTIME_MAX_TIMEOUT_MS,
            manifest_audit=manifest_audit,
            findings=deduped_findings,
            audited_paths=audited_paths,
        )

    def prepare_skill_run(
        self,
        workspace_id: str,
        path: str,
        *,
        runtime_policy: SandboxSkillRuntimePolicy,
        current_platform: Literal["windows", "macos", "linux"] | None = None,
        include_manifest_scripts: bool = True,
        dry_run: bool = True,
        requested_by: str = "trainer",
        reason: str = "",
    ) -> SandboxSkillRunResult:
        root = self.ensure_operation_root(workspace_id)
        preflight = self.preflight_skill_runtime(
            workspace_id,
            path,
            runtime_policy=runtime_policy,
            current_platform=current_platform,
            include_manifest_scripts=include_manifest_scripts,
        )
        egress_decision = self._skill_egress_decision(root, preflight, dry_run=dry_run)
        run_digest = sha1(
            json.dumps(
                {
                    "workspace_id": workspace_id,
                    "path": preflight.path,
                    "manifest_path": preflight.manifest_path,
                    "policy": SKILL_RUN_GATE_POLICY,
                    "preflight_allowed": preflight.allowed,
                    "runtime_policy": runtime_policy.model_dump(mode="json"),
                    "dry_run": bool(dry_run),
                    "requested_by": requested_by.strip(),
                    "reason": reason.strip(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        if not preflight.allowed:
            return SandboxSkillRunResult(
                run_id=f"skill-run-{run_digest}",
                workspace_id=workspace_id,
                path=preflight.path,
                manifest_path=preflight.manifest_path,
                skill_name=preflight.skill_name,
                status="blocked",
                allowed=False,
                dry_run=True,
                execution_status="blocked_by_preflight",
                execution_performed=False,
                execution_reason="Skill run request is blocked because runtime preflight did not pass.",
                policy=SKILL_RUN_GATE_POLICY,
                preflight_policy=preflight.policy,
                preflight=preflight,
                egress_decision=egress_decision,
                command_templates=list(preflight.command_templates),
                normalized_output_paths=list(preflight.normalized_output_paths),
                derived_artifact_paths=[],
                impact_scope=["resource_sandbox"],
                operation_log=[
                    "preflight_recomputed",
                    "blocked_by_runtime_preflight",
                    *egress_decision.operation_log,
                    "no_command_executed",
                    "no_output_written",
                ],
                command_results=[],
                execution_cwd="",
                exit_code=None,
                stdout="",
                stderr="",
                truncated=False,
                blockers=list(preflight.findings),
                requested_by=requested_by.strip() or "trainer",
                reason=reason.strip(),
            )

        derived_artifact_paths = list(preflight.normalized_output_paths)
        if dry_run:
            return SandboxSkillRunResult(
                run_id=f"skill-run-{run_digest}",
                workspace_id=workspace_id,
                path=preflight.path,
                manifest_path=preflight.manifest_path,
                skill_name=preflight.skill_name,
                status="ready",
                allowed=True,
                dry_run=True,
                execution_status="dry_run_ready",
                execution_performed=False,
                execution_reason="Dry-run gate prepared the skill run without executing commands.",
                policy=SKILL_RUN_GATE_POLICY,
                preflight_policy=preflight.policy,
                preflight=preflight,
                egress_decision=egress_decision,
                command_templates=list(preflight.command_templates),
                normalized_output_paths=list(preflight.normalized_output_paths),
                derived_artifact_paths=derived_artifact_paths,
                impact_scope=["resource_sandbox", "derived_artifacts"],
                operation_log=[
                    "preflight_recomputed",
                    "preflight_allowed",
                    *egress_decision.operation_log,
                    "dry_run_ready",
                    "no_command_executed",
                    "no_output_written",
                ],
                command_results=[],
                execution_cwd="",
                exit_code=None,
                stdout="",
                stderr="",
                truncated=False,
                blockers=[],
                requested_by=requested_by.strip() or "trainer",
                reason=reason.strip(),
            )

        if not egress_decision.allowed:
            return SandboxSkillRunResult(
                run_id=f"skill-run-{run_digest}",
                workspace_id=workspace_id,
                path=preflight.path,
                manifest_path=preflight.manifest_path,
                skill_name=preflight.skill_name,
                status="blocked",
                allowed=False,
                dry_run=False,
                execution_status="executor_blocked",
                execution_performed=False,
                execution_reason=egress_decision.reason,
                policy=SKILL_RUN_GATE_POLICY,
                preflight_policy=preflight.policy,
                preflight=preflight,
                egress_decision=egress_decision,
                command_templates=list(preflight.command_templates),
                normalized_output_paths=list(preflight.normalized_output_paths),
                derived_artifact_paths=derived_artifact_paths,
                impact_scope=["resource_sandbox", "derived_artifacts", "network_egress"],
                operation_log=[
                    "preflight_recomputed",
                    "preflight_allowed",
                    *egress_decision.operation_log,
                    "executor_blocked",
                    "no_command_executed",
                    "no_output_written",
                ],
                command_results=[],
                execution_cwd="",
                exit_code=None,
                stdout="",
                stderr="",
                truncated=False,
                blockers=[
                    self._skill_finding(
                        "network_exfiltration",
                        egress_decision.reason,
                        evidence=";".join(egress_decision.requested_hosts),
                        source_path=preflight.manifest_path or preflight.path,
                    )
                ],
                requested_by=requested_by.strip() or "trainer",
                reason=reason.strip(),
            )

        try:
            execution = self._execute_skill_run(
                root=root,
                preflight=preflight,
                run_id=f"skill-run-{run_digest}",
                egress_decision=egress_decision,
            )
        except ValueError as exc:
            return SandboxSkillRunResult(
                run_id=f"skill-run-{run_digest}",
                workspace_id=workspace_id,
                path=preflight.path,
                manifest_path=preflight.manifest_path,
                skill_name=preflight.skill_name,
                status="blocked",
                allowed=False,
                dry_run=False,
                execution_status="executor_blocked",
                execution_performed=False,
                execution_reason=str(exc),
                policy=SKILL_RUN_GATE_POLICY,
                preflight_policy=preflight.policy,
                preflight=preflight,
                egress_decision=egress_decision,
                command_templates=list(preflight.command_templates),
                normalized_output_paths=list(preflight.normalized_output_paths),
                derived_artifact_paths=derived_artifact_paths,
                impact_scope=["resource_sandbox", "derived_artifacts"],
                operation_log=[
                    "preflight_recomputed",
                    "preflight_allowed",
                    *egress_decision.operation_log,
                    "executor_blocked",
                    "no_command_executed",
                    "no_output_written",
                ],
                command_results=[],
                execution_cwd="",
                exit_code=None,
                stdout="",
                stderr="",
                truncated=False,
                blockers=[
                    self._skill_finding(
                        "network_exfiltration" if "network" in str(exc).lower() or "egress" in str(exc).lower() else "supply_chain",
                        str(exc),
                        evidence=str(exc),
                        source_path=preflight.manifest_path or preflight.path,
                    )
                ],
                requested_by=requested_by.strip() or "trainer",
                reason=reason.strip(),
            )

        return SandboxSkillRunResult(
            run_id=f"skill-run-{run_digest}",
            workspace_id=workspace_id,
            path=preflight.path,
            manifest_path=preflight.manifest_path,
            skill_name=preflight.skill_name,
            status=execution["status"],
            allowed=True,
            dry_run=False,
            execution_status=execution["execution_status"],
            execution_performed=execution["execution_performed"],
            execution_reason=execution["execution_reason"],
            policy=SKILL_RUN_GATE_POLICY,
            preflight_policy=preflight.policy,
            preflight=preflight,
            egress_decision=egress_decision,
            command_templates=list(preflight.command_templates),
            normalized_output_paths=list(preflight.normalized_output_paths),
            derived_artifact_paths=derived_artifact_paths,
            impact_scope=["resource_sandbox", "derived_artifacts"],
            operation_log=[*egress_decision.operation_log, *execution["operation_log"]],
            command_results=execution["command_results"],
            execution_cwd=execution["execution_cwd"],
            exit_code=execution["exit_code"],
            stdout=execution["stdout"],
            stderr=execution["stderr"],
            truncated=execution["truncated"],
            blockers=[],
            requested_by=requested_by.strip() or "trainer",
            reason=reason.strip(),
        )

    def audit_archive(
        self,
        workspace_id: str,
        path: str,
        *,
        destination_path: str | None = None,
    ) -> SandboxArchiveAuditResult:
        root = self.ensure_operation_root(workspace_id)
        try:
            archive_path = self._resolve_within_root(root, path)
        except ValueError as exc:
            raise ValueError("Sandbox path must stay inside the active workspace root.") from exc
        if archive_path.is_dir():
            raise IsADirectoryError(f"Archive audit requires a file path: {archive_path}")
        try:
            destination = self._resolve_within_root(
                root,
                destination_path or self._default_archive_destination(archive_path),
                allow_missing=True,
            )
        except ValueError as exc:
            raise ValueError("Sandbox path must stay inside the active workspace root.") from exc
        archive_format = self._archive_format(archive_path)
        if archive_format == "unsupported":
            finding = SandboxArchiveAuditFinding(
                category="malicious_document",
                severity="blocker",
                reason="Archive format is not supported by the dry-run auditor; metadata-only handling is required.",
                evidence=archive_path.name,
                source_path=str(archive_path),
            )
            return SandboxArchiveAuditResult(
                workspace_id=workspace_id,
                path=str(archive_path),
                archive_path=str(archive_path),
                destination_path=str(destination),
                archive_format="unsupported",
                status="blocked",
                allowed=False,
                policy=ARCHIVE_AUDIT_POLICY,
                findings=[finding],
            )

        raw_entries = (
            self._zip_archive_entries(archive_path)
            if archive_format == "zip"
            else self._tar_archive_entries(archive_path)
        )
        entries: list[SandboxArchiveAuditEntry] = []
        findings: list[SandboxArchiveAuditFinding] = []
        total_uncompressed_bytes = 0
        for raw_entry in raw_entries:
            entry_size = max(raw_entry["size"], 0)
            total_uncompressed_bytes += entry_size
            entry, entry_findings = self._audit_archive_entry(
                root=root,
                destination=destination,
                archive_path=archive_path,
                name=str(raw_entry["name"]),
                entry_kind=str(raw_entry["entry_kind"]),
                uncompressed_bytes=entry_size,
                link_target=str(raw_entry.get("link_target") or ""),
            )
            if len(entries) < ARCHIVE_AUDIT_ENTRY_PREVIEW_LIMIT:
                entries.append(entry)
            findings.extend(entry_findings)

        if len(raw_entries) > ARCHIVE_AUDIT_MAX_ENTRIES:
            findings.append(
                SandboxArchiveAuditFinding(
                    category="malicious_document",
                    severity="blocker",
                    reason=(
                        f"Archive contains {len(raw_entries)} entries; the dry-run limit is "
                        f"{ARCHIVE_AUDIT_MAX_ENTRIES}."
                    ),
                    evidence=str(len(raw_entries)),
                    source_path=str(archive_path),
                )
            )
        if total_uncompressed_bytes > ARCHIVE_AUDIT_MAX_TOTAL_UNCOMPRESSED_BYTES:
            findings.append(
                SandboxArchiveAuditFinding(
                    category="malicious_document",
                    severity="blocker",
                    reason=(
                        "Archive total uncompressed size exceeds the dry-run limit "
                        f"({total_uncompressed_bytes} bytes)."
                    ),
                    evidence=str(total_uncompressed_bytes),
                    source_path=str(archive_path),
                )
            )

        deduped_findings = self._dedupe_archive_findings(findings)
        blocked = any(finding.severity == "blocker" for finding in deduped_findings)
        return SandboxArchiveAuditResult(
            workspace_id=workspace_id,
            path=str(archive_path),
            archive_path=str(archive_path),
            destination_path=str(destination),
            archive_format=archive_format,
            status="blocked" if blocked else "allowed",
            allowed=not blocked,
            policy=ARCHIVE_AUDIT_POLICY,
            entry_count=len(raw_entries),
            total_uncompressed_bytes=total_uncompressed_bytes,
            max_entries=ARCHIVE_AUDIT_MAX_ENTRIES,
            max_total_uncompressed_bytes=ARCHIVE_AUDIT_MAX_TOTAL_UNCOMPRESSED_BYTES,
            findings=deduped_findings,
            entries=entries,
        )

    def capture_resource_snapshots(
        self,
        workspace_id: str,
        resources: Iterable[ResourceRecord],
    ) -> dict[str, LinkedResourceSnapshot]:
        root = self.ensure_operation_root(workspace_id)
        snapshots: dict[str, LinkedResourceSnapshot] = {}
        for resource in resources:
            resource_path = self._resource_operation_path(resource, root=root)
            if resource_path is None:
                continue
            snapshots[resource.id] = self._snapshot_linked_resource(
                root,
                resource_id=resource.id,
                path=str(resource_path),
            )
        return snapshots

    def detect_resource_changes(
        self,
        workspace_id: str,
        resources: Iterable[ResourceRecord],
        snapshots: dict[str, LinkedResourceSnapshot],
    ) -> list[LinkedResourceChange]:
        root = self.ensure_operation_root(workspace_id)
        changes: list[LinkedResourceChange] = []
        for resource in resources:
            before = snapshots.get(resource.id)
            if before is None:
                continue
            current_resource_path = self._resource_operation_path(resource, root=root)
            current_path = str(current_resource_path or before.path or "").strip()
            after = self._snapshot_linked_resource(root, resource_id=resource.id, path=current_path)
            relocated_path: str | None = None
            if before.exists and not after.exists and before.inode is not None:
                relocated_path = self._find_path_by_inode(
                    root,
                    inode=before.inode,
                    node_kind=before.node_kind,
                )
                if relocated_path:
                    after = self._snapshot_linked_resource(
                        root,
                        resource_id=resource.id,
                        path=relocated_path,
                    )

            if not after.exists:
                if before.exists:
                    changes.append(
                        LinkedResourceChange(
                            resource_id=resource.id,
                            previous_path=before.path,
                            current_path=None,
                            deleted=True,
                        )
                    )
                continue

            if before.path != after.path or before.signature != after.signature:
                changes.append(
                    LinkedResourceChange(
                        resource_id=resource.id,
                        previous_path=before.path,
                        current_path=after.path,
                        deleted=False,
                    )
                )
        return changes

    def clear_workspace(self, workspace_id: str) -> None:
        from ..workspace.authority import PermissionLevel

        root = self.ensure_workspace_root(workspace_id)
        authority, previous_level = self._operation_authority(workspace_id, PermissionLevel.DESTRUCTIVE)
        before_children = [
            str(child.relative_to(root))
            for child in sorted(self._iterdir_paths(root), key=lambda item: str(item).lower())
            if child.name != "trash"
        ]
        trashed_paths: list[str] = []
        patch_lines: list[str] = []

        def trash_non_scaffold(candidate: Path) -> None:
            relative = self._relative_path(root, candidate)
            if relative == ".trainer" and self._path_is_dir(candidate):
                return
            if self._is_scaffold_relative_path(relative) and self._path_is_dir(candidate):
                for nested in sorted(self._iterdir_paths(candidate), key=lambda item: str(item).lower()):
                    trash_non_scaffold(nested)
                return
            trashed_path = authority.trash_path(candidate)
            trashed_paths.append(trashed_path)
            patch_lines.append(f"trash {Path(candidate).relative_to(root)} -> {Path(trashed_path).name}")

        try:
            checkpoint = authority.create_trash_checkpoint(
                root,
                description=f"Before clearing sandbox workspace {workspace_id}",
                metadata={"workspace_id": workspace_id, "sandbox_root": str(root)},
            )
            for child in sorted(self._iterdir_paths(root), key=lambda item: str(item).lower()):
                # Keep the current trash root in place; trashing it would recurse into the same boundary.
                if child.name == "trash":
                    continue
                trash_non_scaffold(child)
        finally:
            self._restore_authority_permission(authority, previous_level)

        self._ensure_directory(root)
        self._ensure_workspace_scaffold(root)
        self._command_history.pop(workspace_id, None)
        # §13.21 Record sandbox workspace cleared event
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "sandbox_workspace_cleared",
                actor="trainer",
                scope="sandbox",
                project_id=workspace_id,
                payload_ref={
                    "workspace_id": workspace_id,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "trashed_count": len(trashed_paths),
                    "trashed_paths": list(trashed_paths),
                    "patch": list(patch_lines),
                    "diff_summary": "; ".join(patch_lines),
                },
                before_state_ref={
                    "workspace_id": workspace_id,
                    "root_children": before_children,
                    "root_child_count": len(before_children),
                },
                after_state_ref={
                    "workspace_id": workspace_id,
                    "cleared": True,
                    "trashed_count": len(trashed_paths),
                    "trashed_paths": list(trashed_paths),
                    "patch": list(patch_lines),
                    "diff_summary": "; ".join(patch_lines),
                    "remaining_children": [
                        str(child.relative_to(root))
                        for child in sorted(self._iterdir_paths(root), key=lambda item: str(item).lower())
                        if child.name != "trash"
                    ],
                },
                reversibility="irreversible",
                audit_note=f"Sandbox workspace cleared: '{workspace_id}'",
            )

    def _skill_manifest_path(self, target: Path) -> Path:
        if self._path_is_file(target):
            return target
        for name in SKILL_MANIFEST_NAMES:
            candidate = target / name
            if self._path_exists(candidate) and self._path_is_file(candidate):
                return candidate
        raise FileNotFoundError(f"Skill manifest was not found under: {target}")

    def _read_text_limited(self, path: Path, *, limit: int = 96_000) -> str:
        with open(self._fs_path(path), "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)

    def _parse_manifest(self, path: Path, text: str) -> dict[str, Any] | None:
        if path.suffix.lower() == ".json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return None

    def _skill_manifest_contract(
        self,
        parsed_manifest: dict[str, Any] | None,
        manifest_text: str,
        manifest_path: Path,
    ) -> _SkillManifestContract:
        skill_name = manifest_path.parent.name or manifest_path.stem
        requested_permissions: list[str] = []
        network_allowlist: list[str] = []
        execution_entrypoints: list[str] = []

        if parsed_manifest is not None:
            skill_name = str(
                parsed_manifest.get("name")
                or parsed_manifest.get("displayName")
                or parsed_manifest.get("id")
                or skill_name
            ).strip() or skill_name
            for key_path, value in self._walk_manifest_scalars(parsed_manifest):
                lowered_key = ".".join(key_path).lower()
                key_words = self._manifest_key_path_words(key_path)
                normalized_value = str(value).strip()
                if not normalized_value:
                    continue
                if key_words.intersection({"permission", "permissions", "capability", "capabilities", "scope", "access", "tool", "tools"}):
                    requested_permissions.append(f"{lowered_key}:{normalized_value}")
                if key_words.intersection({"allowlist", "allowed", "domain", "domains", "host", "hosts", "origin", "origins", "url", "urls"}):
                    if key_words.intersection({"network", "egress", "url", "urls", "host", "hosts", "domain", "domains", "origin", "origins"}):
                        network_allowlist.append(normalized_value)
                if key_words.intersection(
                    {
                        "script",
                        "scripts",
                        "command",
                        "commands",
                        "entry",
                        "entrypoint",
                        "entrypoints",
                        "main",
                        "bin",
                        "run",
                        "runner",
                    }
                ):
                    execution_entrypoints.append(f"{lowered_key}:{normalized_value}")

        if parsed_manifest is None:
            for line in manifest_text.splitlines():
                lowered = line.lower()
                stripped = line.strip()
                if not stripped:
                    continue
                if any(token in lowered for token in ("permission", "capability", "scope", "access")):
                    requested_permissions.append(stripped[:220])
                if any(token in lowered for token in ("allowlist", "allowed host", "allowed domain", "egress")):
                    network_allowlist.append(stripped[:220])
                if any(token in lowered for token in ("postinstall", "install:", "entrypoint", "command", "script")):
                    execution_entrypoints.append(stripped[:220])

        return {
            "skill_name": skill_name[:120],
            "requested_permissions": self._append_unique([], requested_permissions)[:24],
            "network_allowlist": self._append_unique([], network_allowlist)[:24],
            "execution_entrypoints": self._append_unique([], execution_entrypoints)[:24],
        }

    def _manifest_key_path_words(self, key_path: tuple[str, ...]) -> set[str]:
        words: set[str] = set()
        for raw_segment in key_path:
            if not raw_segment:
                continue
            expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(raw_segment))
            for token in re.split(r"[^A-Za-z0-9]+", expanded):
                normalized = token.strip().lower()
                if normalized:
                    words.add(normalized)
        return words

    def _walk_manifest_scalars(
        self,
        value: object,
        *,
        key_path: tuple[str, ...] = (),
    ) -> Iterable[tuple[tuple[str, ...], object]]:
        if isinstance(value, dict):
            for key, child in value.items():
                yield from self._walk_manifest_scalars(child, key_path=(*key_path, str(key)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from self._walk_manifest_scalars(child, key_path=(*key_path, str(index)))
        elif value is not None:
            yield key_path, value

    def _skill_contract_findings(
        self,
        *,
        requested_permissions: list[str],
        network_allowlist: list[str],
        execution_entrypoints: list[str],
        source_path: str,
    ) -> list[SandboxSkillManifestFinding]:
        findings: list[SandboxSkillManifestFinding] = []
        permissions_text = "\n".join(requested_permissions)
        network_text = "\n".join(network_allowlist)
        entrypoint_text = "\n".join(execution_entrypoints)
        if _contains_pattern(permissions_text, [r"\b(secret|credential|token|api[_-]?key|env|environment)\b"]):
            findings.append(
                self._skill_finding(
                    "credential_access",
                    "Skill manifest requests access to secrets, tokens, or environment credentials.",
                    evidence=permissions_text,
                    source_path=source_path,
                )
            )
        if _contains_pattern(permissions_text, [r"\b(network|internet|http|fetch|egress)\b"]) and not network_allowlist:
            findings.append(
                self._skill_finding(
                    "network_exfiltration",
                    "Skill manifest requests network access without an explicit egress allowlist.",
                    evidence=permissions_text,
                    source_path=source_path,
                )
            )
        if _contains_pattern(network_text, [r"(^|[\s,:\[])(\*|all|0\.0\.0\.0|any)([\s,\]:]|$)"]):
            findings.append(
                self._skill_finding(
                    "network_exfiltration",
                    "Skill manifest declares unrestricted network egress.",
                    evidence=network_text,
                    source_path=source_path,
                )
            )
        if _contains_pattern(
            entrypoint_text,
            [
                r"\b(preinstall|postinstall|install|npm install|pip install|bash|powershell|cmd\.exe|sh -c)\b",
                r"\b(node|python|python3|tsx|ts-node|deno|bun|ruby|perl|pwsh)\b.{0,80}\.(?:js|mjs|cjs|ts|tsx|py|rb|pl|ps1)\b",
            ],
        ):
            findings.append(
                self._skill_finding(
                    "supply_chain",
                    "Skill manifest declares executable entrypoints before isolated skill execution policy exists.",
                    evidence=entrypoint_text,
                    source_path=source_path,
                )
            )
        if _contains_pattern(permissions_text + "\n" + entrypoint_text, [r"(\.\./|\.\.\\|~[/\\]|/etc/|/var/|c:\\|%userprofile%)"]):
            findings.append(
                self._skill_finding(
                    "path_escape",
                    "Skill manifest references paths outside the managed resource sandbox.",
                    evidence=f"{permissions_text}\n{entrypoint_text}",
                    source_path=source_path,
                )
            )
        return findings

    def _skill_runtime_policy_findings(
        self,
        *,
        root: Path,
        source_path: str,
        runtime_base_path: Path,
        runtime_policy: SandboxSkillRuntimePolicy,
        current_platform: Literal["windows", "macos", "linux"],
    ) -> list[SandboxSkillManifestFinding]:
        findings: list[SandboxSkillManifestFinding] = []
        if runtime_policy.platform != "cross_platform" and runtime_policy.platform != current_platform:
            findings.append(
                self._skill_finding(
                    "supply_chain",
                    "Skill runtime policy does not support the current platform.",
                    evidence=f"{runtime_policy.platform} on {current_platform}",
                    source_path=source_path,
                )
            )
        if not runtime_policy.command_templates:
            findings.append(
                self._skill_finding(
                    "supply_chain",
                    "Skill runtime policy must declare at least one non-shell command template before execution.",
                    evidence="missing command_templates",
                    source_path=source_path,
                )
            )
        for command in runtime_policy.command_templates:
            command_text = str(command or "").strip()
            if not command_text:
                findings.append(
                    self._skill_finding(
                        "supply_chain",
                        "Skill runtime policy contains an empty command template.",
                        evidence=str(command),
                        source_path=source_path,
                    )
                )
                continue
            if _contains_pattern(command_text, SKILL_RUNTIME_FORBIDDEN_COMMAND_PATTERNS):
                findings.append(
                    self._skill_finding(
                        "supply_chain",
                        "Skill runtime command template uses shell, install, network, destructive, or dynamic execution patterns.",
                        evidence=command_text,
                        source_path=source_path,
                    )
                )
            inline_execution_reason = self._skill_runtime_inline_execution_reason(command_text)
            if inline_execution_reason:
                findings.append(
                    self._skill_finding(
                        "supply_chain",
                        inline_execution_reason,
                        evidence=command_text,
                        source_path=source_path,
                    )
                )
            if not _contains_pattern(command_text, [r"\{\{\s*(input|output|resource|sandbox)[\w.-]*\s*\}\}"]):
                findings.append(
                    self._skill_finding(
                        "supply_chain",
                        "Skill runtime command template must be declarative and parameterized with sandbox placeholders.",
                        evidence=command_text,
                        source_path=source_path,
                    )
                )

        findings.extend(
            self._runtime_command_script_findings(
                root=root,
                base_path=runtime_base_path,
                runtime_policy=runtime_policy,
                source_path=source_path,
            )
        )

        network_allowlist = [str(item or "").strip() for item in runtime_policy.network_allowlist if str(item or "").strip()]
        for host in network_allowlist:
            if self._skill_runtime_network_host_is_blocked(host):
                findings.append(
                    self._skill_finding(
                        "network_exfiltration",
                        "Skill runtime network egress must use explicit documentation domains; wildcard or local/private egress is blocked.",
                        evidence=host,
                        source_path=source_path,
                    )
                )

        if not runtime_policy.output_paths:
            findings.append(
                self._skill_finding(
                    "path_escape",
                    "Skill runtime policy must declare output paths under the managed resource sandbox.",
                    evidence="missing output_paths",
                    source_path=source_path,
                )
            )
        for output_path in runtime_policy.output_paths:
            candidate_output_path = Path(str(output_path or ""))
            try:
                resolved = self._resolve_within_root(root, str(candidate_output_path), allow_missing=True)
            except (FileNotFoundError, ValueError) as exc:
                findings.append(
                    self._skill_finding(
                        "path_escape",
                        "Skill runtime output path must stay inside the managed resource sandbox.",
                        evidence=f"{output_path}: {exc}",
                        source_path=source_path,
                    )
                )
                continue
            if resolved == root:
                findings.append(
                    self._skill_finding(
                        "path_escape",
                        "Skill runtime output path cannot target the sandbox root directly.",
                        evidence=str(output_path),
                        source_path=source_path,
                    )
                )
            try:
                self._validate_runtime_output_path(root, candidate_output_path)
            except ValueError as exc:
                findings.append(
                    self._skill_finding(
                        "path_escape",
                        "Skill runtime output path must not cross symlink, junction, or reparse boundaries.",
                        evidence=f"{output_path}: {exc}",
                        source_path=source_path,
                    )
                )

        if runtime_policy.timeout_ms is None:
            findings.append(
                self._skill_finding(
                    "supply_chain",
                    "Skill runtime policy must declare a timeout before execution.",
                    evidence="missing timeout_ms",
                    source_path=source_path,
                )
            )
        elif runtime_policy.timeout_ms <= 0 or runtime_policy.timeout_ms > SKILL_RUNTIME_MAX_TIMEOUT_MS:
            findings.append(
                self._skill_finding(
                    "supply_chain",
                    f"Skill runtime timeout must be between 1 and {SKILL_RUNTIME_MAX_TIMEOUT_MS} ms.",
                    evidence=str(runtime_policy.timeout_ms),
                    source_path=source_path,
                )
            )

        for env_name in runtime_policy.env_whitelist:
            normalized = str(env_name or "").strip()
            if not normalized:
                continue
            if not self._skill_runtime_env_name_is_allowed(normalized):
                findings.append(
                    self._skill_finding(
                        "credential_access",
                        "Skill runtime env whitelist may only include benign runtime variables; credential-like variables are blocked.",
                        evidence=normalized,
                        source_path=source_path,
                    )
                )
        return findings

    def _execute_skill_run(
        self,
        *,
        root: Path,
        preflight: SandboxSkillRuntimePreflightResult,
        run_id: str,
        egress_decision: SandboxSkillEgressDecision,
    ) -> dict[str, Any]:
        if egress_decision.enforcement_mode == SKILL_EGRESS_OS_CONTAINER_MODE:
            return self._execute_skill_run_in_os_container(
                root=root,
                preflight=preflight,
                run_id=run_id,
                egress_decision=egress_decision,
            )
        output_paths = [Path(item) for item in preflight.normalized_output_paths]
        if not output_paths:
            raise ValueError("Skill isolated executor requires at least one normalized sandbox output path.")
        if preflight.network_allowlist and not egress_decision.allowed:
            raise ValueError(SKILL_EGRESS_ENFORCEMENT_MISSING_REASON)
        for output_path in output_paths:
            self._validate_runtime_output_path(root, output_path)

        output_path = output_paths[0]
        self._ensure_directory(output_path.parent)
        self._validate_runtime_output_path(root, output_path)
        input_path = Path(preflight.path)
        cwd = input_path if self._path_is_dir(input_path) else input_path.parent
        cwd = self._resolve_within_root(root, str(cwd))
        execution_input_path = self._fs_path(input_path)
        execution_output_path = self._fs_path(output_path)
        execution_root = self._fs_path(root)
        execution_cwd = self._fs_path(cwd)
        node_input_path = str(input_path.resolve(strict=False))
        node_output_path = str(output_path.resolve(strict=False))
        node_root_path = str(root.resolve(strict=False))
        node_cwd_path = str(cwd.resolve(strict=False))
        placeholder_values = {
            "resource_path": execution_input_path,
            "input_path": execution_input_path,
            "output_path": execution_output_path,
            "output": execution_output_path,
            "sandbox_root": execution_root,
            "sandbox": execution_root,
            "cwd": execution_cwd,
        }
        guard_site_dir: Path | None = None
        node_guard_file: Path | None = None
        environment = self._skill_runtime_environment(preflight.env_whitelist)
        if egress_decision.enforcement_mode == SKILL_EGRESS_PYTHON_GUARD_MODE:
            guard_site_dir = self._write_python_egress_guard(root, egress_decision.allowed_hosts)
            guard_pythonpath = self._windows_short_path(guard_site_dir) or self._fs_path(guard_site_dir)
            existing_pythonpath = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = (
                guard_pythonpath
                if not existing_pythonpath
                else f"{guard_pythonpath}{os.pathsep}{existing_pythonpath}"
            )
            environment["TRAINER_EGRESS_ALLOWED_HOSTS"] = json.dumps(
                egress_decision.allowed_hosts,
                ensure_ascii=True,
            )
            environment["TRAINER_EGRESS_GUARD_MODE"] = SKILL_EGRESS_PYTHON_GUARD_MODE
        elif egress_decision.enforcement_mode == SKILL_EGRESS_NODE_GUARD_MODE:
            node_guard_file = self._write_node_egress_guard(root, egress_decision.allowed_hosts)
            environment["TRAINER_EGRESS_ALLOWED_HOSTS"] = json.dumps(
                egress_decision.allowed_hosts,
                ensure_ascii=True,
            )
            environment["TRAINER_EGRESS_GUARD_MODE"] = SKILL_EGRESS_NODE_GUARD_MODE
        command_results: list[SandboxCommandEntry] = []
        operation_log = [
            "preflight_recomputed",
            "preflight_allowed",
            "isolated_executor_started",
        ]
        if egress_decision.enforcement_mode == SKILL_EGRESS_PYTHON_GUARD_MODE:
            operation_log.append("python_socket_guard_enabled")
        elif egress_decision.enforcement_mode == SKILL_EGRESS_NODE_GUARD_MODE:
            operation_log.append("node_socket_guard_enabled")
        combined_stdout: list[str] = []
        combined_stderr: list[str] = []
        truncated = False
        exit_code: int | None = 0
        started_any = False

        try:
            for index, template in enumerate(preflight.command_templates, start=1):
                argv = self._skill_runtime_command_argv(template, placeholder_values)
                if egress_decision.enforcement_mode == SKILL_EGRESS_NODE_GUARD_MODE:
                    argv = self._replace_node_guard_placeholders(
                        argv,
                        {
                            execution_input_path: node_input_path,
                            execution_output_path: node_output_path,
                            execution_root: node_root_path,
                            execution_cwd: node_cwd_path,
                        },
                    )
                process_argv, process_cwd, invocation_markers = self._prepare_skill_process_invocation(
                    root=root,
                    cwd=cwd,
                    argv=argv,
                    environment=environment,
                    node_guard_file=node_guard_file,
                )
                started_any = True
                started_at = datetime.now(UTC).isoformat()
                operation_log.extend(invocation_markers)
                try:
                    completed = subprocess.run(
                        process_argv,
                        shell=False,
                        cwd=process_cwd,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=max(1, int(preflight.timeout_ms or 0)) / 1000,
                    )
                except subprocess.TimeoutExpired as exc:
                    stdout = self._truncate_output(self._subprocess_output_text(exc.stdout))
                    stderr = self._truncate_output(self._subprocess_output_text(exc.stderr))
                    entry = SandboxCommandEntry(
                        id=f"{run_id}-cmd-{index}",
                        command=" ".join(argv),
                        cwd=str(cwd),
                        status="timeout",
                        exit_code=None,
                        stdout=str(stdout["text"]),
                        stderr=str(stderr["text"]),
                        started_at=started_at,
                        finished_at=datetime.now(UTC).isoformat(),
                        truncated=True,
                    )
                    command_results.append(entry)
                    operation_log.extend(
                        [
                            f"command_{index}_started",
                            f"command_{index}_timeout",
                            "isolated_executor_timeout",
                        ]
                    )
                    combined_stdout.append(entry.stdout)
                    combined_stderr.append(entry.stderr)
                    truncated = True
                    return {
                        "status": "failed",
                        "execution_status": "execution_timeout",
                        "execution_performed": True,
                        "execution_reason": "Skill isolated executor timed out before completion.",
                        "operation_log": operation_log,
                        "command_results": command_results,
                        "execution_cwd": str(cwd),
                        "exit_code": None,
                        "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                        "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                        "truncated": truncated,
                    }

                stdout = self._truncate_output(completed.stdout)
                stderr = self._truncate_output(completed.stderr)
                entry = SandboxCommandEntry(
                    id=f"{run_id}-cmd-{index}",
                    command=" ".join(argv),
                    cwd=str(cwd),
                    status="success" if completed.returncode == 0 else "error",
                    exit_code=completed.returncode,
                    stdout=str(stdout["text"]),
                    stderr=str(stderr["text"]),
                    started_at=started_at,
                    finished_at=datetime.now(UTC).isoformat(),
                    truncated=bool(stdout["truncated"] or stderr["truncated"]),
                )
                command_results.append(entry)
                operation_log.extend(
                    [
                        f"command_{index}_started",
                        f"command_{index}_{entry.status}",
                    ]
                )
                combined_stdout.append(entry.stdout)
                combined_stderr.append(entry.stderr)
                truncated = truncated or entry.truncated
                exit_code = completed.returncode
                if completed.returncode != 0:
                    operation_log.append("isolated_executor_failed")
                    return {
                        "status": "failed",
                        "execution_status": "execution_failed",
                        "execution_performed": True,
                        "execution_reason": "Skill isolated executor finished with a non-zero exit code.",
                        "operation_log": operation_log,
                        "command_results": command_results,
                        "execution_cwd": str(cwd),
                        "exit_code": exit_code,
                        "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                        "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                        "truncated": truncated,
                    }

            if not started_any:
                raise ValueError("Skill isolated executor did not receive any runnable command template.")

            try:
                for path in output_paths:
                    self._validate_runtime_output_path(root, path, require_exists=False)
            except ValueError as exc:
                operation_log.extend(["isolated_executor_finished", "runtime_output_escape_blocked"])
                return {
                    "status": "failed",
                    "execution_status": "execution_output_escape",
                    "execution_performed": True,
                    "execution_reason": str(exc),
                    "operation_log": operation_log,
                    "command_results": command_results,
                    "execution_cwd": str(cwd),
                    "exit_code": exit_code,
                    "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                    "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                    "truncated": truncated,
                }

            output_exists = any(self._path_exists(path) for path in output_paths)
            if not output_exists:
                operation_log.extend(["isolated_executor_finished", "expected_output_missing"])
                return {
                    "status": "failed",
                    "execution_status": "execution_output_missing",
                    "execution_performed": True,
                    "execution_reason": "Skill isolated executor finished but did not produce the declared sandbox output.",
                    "operation_log": operation_log,
                    "command_results": command_results,
                    "execution_cwd": str(cwd),
                    "exit_code": exit_code,
                    "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                    "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                    "truncated": truncated,
                }

            operation_log.extend(["isolated_executor_finished", "sandbox_output_written", "skill_run_executed"])
            return {
                "status": "executed",
                "execution_status": "executed",
                "execution_performed": True,
                "execution_reason": "Skill isolated executor completed without shell access and wrote declared sandbox output.",
                "operation_log": operation_log,
                "command_results": command_results,
                "execution_cwd": str(cwd),
                "exit_code": exit_code,
                "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                "truncated": truncated,
            }
        finally:
            if guard_site_dir is not None:
                self._remove_tree(guard_site_dir, ignore_errors=True)
            if node_guard_file is not None:
                self._unlink_path(node_guard_file)
