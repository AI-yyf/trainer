from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import zipfile
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, Iterable, Literal
from uuid import uuid4

from ..core.models import (
    LearningPlan,
    ResourceRecord,
    SandboxArchiveAuditEntry,
    SandboxArchiveAuditFinding,
    SandboxCapabilityStatus,
    SandboxCapabilitySummary,
    SandboxNetworkExecutionFacts,
    SandboxNode,
    SandboxOsContainerExecutionPlan,
    SandboxOsContainerExecutorProbe,
    SandboxPlatformInfo,
    SandboxSkillRuntimePreflightResult,
    TrainingCardCandidateSnapshot,
)
from ..core.process_env import child_process_environment
from ..memory.workspace_recovery import (
    leftover_formal_plan_is_live_for_fill,
    live_plan_snapshot_persist_chrome,
    live_training_card_title,
)

if TYPE_CHECKING:
    pass

from .constants import (
    ARCHIVE_AUDIT_EXECUTABLE_SUFFIXES,
    ARCHIVE_AUDIT_POLICY,
    ARCHIVE_AUDIT_RECURSIVE_SUFFIXES,
    ARCHIVE_AUDIT_SUPPORTED_SUFFIXES,
    SKILL_EGRESS_NON_PYTHON_REASON,
    SKILL_EGRESS_OS_CONTAINER_DAEMON_UNREACHABLE_REASON,
    SKILL_EGRESS_OS_CONTAINER_EXECUTOR_NOT_IMPLEMENTED_REASON,
    SKILL_EGRESS_OS_CONTAINER_IMAGE_MISSING_REASON,
    SKILL_EGRESS_OS_CONTAINER_IMAGE_TRUST_POLICY,
    SKILL_EGRESS_OS_CONTAINER_IMAGE_UNTRUSTED_REASON,
    SKILL_EGRESS_OS_CONTAINER_NODE_IMAGE,
    SKILL_EGRESS_OS_CONTAINER_NODE_TRUSTED_REPO_DIGESTS,
    SKILL_EGRESS_OS_CONTAINER_PROBE_FAILED_REASON,
    SKILL_EGRESS_OS_CONTAINER_REQUIRED_REASON,
    SKILL_EGRESS_OS_CONTAINER_RUBY_IMAGE,
    SKILL_EGRESS_OS_CONTAINER_RUNTIME_MISSING_REASON,
    SKILL_EGRESS_OS_CONTAINER_TRUSTED_REPO_DIGESTS,
    SKILL_EGRESS_OS_CONTAINER_UNAVAILABLE_REASON,
    SKILL_EGRESS_REASON_GENERAL_MISSING,
    SKILL_EGRESS_REASON_NON_PYTHON,
    SKILL_EGRESS_REASON_OS_CONTAINER_DAEMON_UNREACHABLE,
    SKILL_EGRESS_REASON_OS_CONTAINER_EXECUTOR_NOT_IMPLEMENTED,
    SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_MISSING,
    SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_UNTRUSTED,
    SKILL_EGRESS_REASON_OS_CONTAINER_PROBE_FAILED,
    SKILL_EGRESS_REASON_OS_CONTAINER_REQUIRED,
    SKILL_EGRESS_REASON_OS_CONTAINER_RUNTIME_MISSING,
    SKILL_EGRESS_REASON_OS_CONTAINER_UNAVAILABLE,
    SKILL_EGRESS_REASON_UNAUDITED,
    SKILL_EGRESS_REASON_UNSUPPORTED_NODE_GUARD,
    SKILL_EGRESS_UNAUDITED_REASON,
    SKILL_MANIFEST_POLICY,
    SKILL_RUNTIME_POLICY,
    TRAINER_SANDBOX_MANAGED_ROOTS,
    TRAINER_SANDBOX_SCAFFOLD_PATH_SET,
    TRAINER_SANDBOX_SCAFFOLD_PATHS,
    LinkedResourceSnapshot,
    _ArchiveEntryMetadata,
    _TruncatedOutput,
)

logger = logging.getLogger(__name__)


class ContainerProbeAndAuditMixin:
    if TYPE_CHECKING:
        _current_platform: Any
        _resolved_project_identity: Any
        data_root: Any

    def _os_container_plan_for_request(
        self,
        plan: SandboxOsContainerExecutionPlan,
        *,
        probe: SandboxOsContainerExecutorProbe,
        supported_by_executor: bool,
        block_reason_code: str,
        selected_entry_runtime: Literal["none", "ruby", "node"] = "none",
    ) -> SandboxOsContainerExecutionPlan:
        plan = self._os_container_plan_with_entry_runtime(
            plan,
            probe=probe,
            selected_entry_runtime=selected_entry_runtime,
        )
        if supported_by_executor or probe.availability != "available":
            return plan
        reason_code = block_reason_code or SKILL_EGRESS_REASON_NON_PYTHON
        if reason_code == SKILL_EGRESS_REASON_UNAUDITED:
            reason = SKILL_EGRESS_UNAUDITED_REASON
        elif reason_code == SKILL_EGRESS_REASON_UNSUPPORTED_NODE_GUARD:
            reason = (
                "The verified os/container executor does not accept this Node.js entry shape; only audited argv-only "
                "Ruby .rb or Node.js .js/.mjs/.cjs entry scripts can enter the current container lanes."
            )
        elif selected_entry_runtime in {"ruby", "node"} and selected_entry_runtime not in probe.supported_entry_runtimes:
            requested_lane = self._os_container_entry_runtime_label(selected_entry_runtime)
            supported_lanes = self._os_container_supported_entries_label(probe.supported_entry_runtimes)
            reason = (
                f"A verified os/container executor exists on this host, but the audited {requested_lane} entry still "
                f"cannot run because the current trusted container lanes are limited to: {supported_lanes}."
            )
        else:
            reason = (
                "A verified os/container executor exists, but this request still cannot enter it because only "
                "audited argv-only Ruby or Node.js entry scripts are currently supported."
            )
        return plan.model_copy(
            update={
                "status": "planned_blocked",
                "executor_mode": "none",
                "selected_entry_runtime": selected_entry_runtime,
                "reason_code": reason_code,
                "reason": reason,
            }
        )

    def _select_egress_block_reason_code(
        self,
        python_block_reason_code: str,
        node_block_reason_code: str,
        ruby_block_reason_code: str,
    ) -> str:
        block_reason_code = python_block_reason_code or node_block_reason_code or ruby_block_reason_code
        if block_reason_code in {"", SKILL_EGRESS_REASON_NON_PYTHON} and node_block_reason_code:
            block_reason_code = node_block_reason_code
        if block_reason_code in {"", SKILL_EGRESS_REASON_NON_PYTHON} and ruby_block_reason_code:
            block_reason_code = ruby_block_reason_code
        return block_reason_code

    def _evidence_excerpt(self, value: str, *, limit: int = 240) -> str:
        compact = " ".join(str(value or "").split())
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip() + "..."

    def _normalize_os_container_block_reason_code(
        self,
        block_reason_code: str,
        probe: SandboxOsContainerExecutorProbe,
    ) -> str:
        if block_reason_code not in {
            "",
            SKILL_EGRESS_REASON_GENERAL_MISSING,
            SKILL_EGRESS_REASON_OS_CONTAINER_REQUIRED,
            SKILL_EGRESS_REASON_OS_CONTAINER_UNAVAILABLE,
        }:
            return block_reason_code
        if probe.reason_code:
            return probe.reason_code
        return SKILL_EGRESS_REASON_OS_CONTAINER_UNAVAILABLE

    def _compose_non_python_block_reason(
        self,
        probe: SandboxOsContainerExecutorProbe,
    ) -> str:
        return (
            f"{SKILL_EGRESS_NON_PYTHON_REASON} {self._os_container_probe_suffix(probe)}"
            if self._os_container_probe_suffix(probe)
            else SKILL_EGRESS_NON_PYTHON_REASON
        )

    def _compose_os_container_required_reason(
        self,
        probe: SandboxOsContainerExecutorProbe,
    ) -> str:
        suffix = self._os_container_probe_suffix(probe)
        if not suffix:
            return SKILL_EGRESS_OS_CONTAINER_REQUIRED_REASON
        return f"{SKILL_EGRESS_OS_CONTAINER_REQUIRED_REASON} {suffix}"

    def _os_container_probe_suffix(self, probe: SandboxOsContainerExecutorProbe) -> str:
        detail = (probe.reason or "").strip()
        if not detail:
            return ""
        return f"Host probe detail: {detail}"

    def _os_container_block_reason(
        self,
        reason_code: str,
        probe: SandboxOsContainerExecutorProbe,
    ) -> str:
        if reason_code == SKILL_EGRESS_REASON_OS_CONTAINER_RUNTIME_MISSING:
            return probe.reason or SKILL_EGRESS_OS_CONTAINER_RUNTIME_MISSING_REASON
        if reason_code == SKILL_EGRESS_REASON_OS_CONTAINER_DAEMON_UNREACHABLE:
            return probe.reason or SKILL_EGRESS_OS_CONTAINER_DAEMON_UNREACHABLE_REASON
        if reason_code == SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_MISSING:
            return probe.reason or SKILL_EGRESS_OS_CONTAINER_IMAGE_MISSING_REASON
        if reason_code == SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_UNTRUSTED:
            return probe.reason or SKILL_EGRESS_OS_CONTAINER_IMAGE_UNTRUSTED_REASON
        if reason_code == SKILL_EGRESS_REASON_OS_CONTAINER_EXECUTOR_NOT_IMPLEMENTED:
            return probe.reason or SKILL_EGRESS_OS_CONTAINER_EXECUTOR_NOT_IMPLEMENTED_REASON
        if reason_code == SKILL_EGRESS_REASON_OS_CONTAINER_PROBE_FAILED:
            return probe.reason or SKILL_EGRESS_OS_CONTAINER_PROBE_FAILED_REASON
        return probe.reason or SKILL_EGRESS_OS_CONTAINER_UNAVAILABLE_REASON

    def _os_container_lane_status(
        self,
        probe: SandboxOsContainerExecutorProbe,
    ) -> Literal["guarded_allowlist_only", "blocked", "blocked_by_preflight", "missing", "enforced"]:
        if probe.availability == "available":
            return "enforced"
        if probe.availability in {
            "unavailable_daemon_unreachable",
            "unavailable_image_missing",
            "unavailable_image_untrusted",
            "probe_failed",
        }:
            return "blocked"
        return "missing"

    def _os_container_lane_current_enforcement(
        self,
        probe: SandboxOsContainerExecutorProbe,
    ) -> Literal["python_socket_guard", "node_socket_guard", "runtime_preflight", "os_container_egress", "missing"]:
        if probe.availability == "available":
            return "os_container_egress"
        return "missing"

    def _os_container_lane_next_requirement(
        self,
        probe: SandboxOsContainerExecutorProbe,
    ) -> Literal["none", "audited_sandbox_python_script", "subprocess_free_audited_entrypoint", "os_or_container_egress_enforcement"]:
        if probe.availability == "available":
            return "none"
        return "os_or_container_egress_enforcement"

    def _os_container_entry_image(self, entry_runtime: str) -> str:
        if entry_runtime == "node":
            return SKILL_EGRESS_OS_CONTAINER_NODE_IMAGE
        if entry_runtime == "ruby":
            return SKILL_EGRESS_OS_CONTAINER_RUBY_IMAGE
        return ""

    def _os_container_entry_runtime_label(self, entry_runtime: str) -> str:
        if entry_runtime == "node":
            return "Node.js"
        if entry_runtime == "ruby":
            return "Ruby"
        return "OS/container"

    def _os_container_supported_entries_label(self, supported_entry_runtimes: Iterable[str]) -> str:
        labels = [
            self._os_container_entry_runtime_label(item)
            for item in supported_entry_runtimes
            if str(item or "").strip() in {"ruby", "node"}
        ]
        if not labels:
            return "none"
        return ", ".join(labels)

    def _os_container_runtime_command_preview(
        self,
        *,
        runtime: str,
        mount_root_path: str,
        container_root_path: str,
        container_workdir: str,
        container_image: str,
    ) -> list[str]:
        if runtime not in {"docker", "podman"} or not container_image:
            return []
        return [
            runtime,
            "run",
            "--rm",
            "--network",
            "bridge",
            "--workdir",
            container_workdir,
            "--volume",
            f"{mount_root_path}:{container_root_path}:rw",
            container_image,
        ]

    def _os_container_plan_with_entry_runtime(
        self,
        plan: SandboxOsContainerExecutionPlan,
        *,
        probe: SandboxOsContainerExecutorProbe,
        selected_entry_runtime: Literal["none", "ruby", "node"],
    ) -> SandboxOsContainerExecutionPlan:
        if selected_entry_runtime == "none":
            return plan.model_copy(update={"selected_entry_runtime": "none"})
        container_image = self._os_container_entry_image(selected_entry_runtime) or plan.container_image
        container_image_repo_digest = ""
        image_trust_status = plan.image_trust_status
        if selected_entry_runtime == probe.selected_entry_runtime:
            container_image = probe.image_reference or container_image
            container_image_repo_digest = probe.selected_image_repo_digest
            image_trust_status = probe.image_trust_status or image_trust_status
        elif selected_entry_runtime in probe.supported_entry_runtimes:
            image_trust_status = "trusted"
        runtime_command = self._os_container_runtime_command_preview(
            runtime=plan.runtime,
            mount_root_path=plan.mount_root_path,
            container_root_path=plan.container_root_path,
            container_workdir=plan.container_workdir,
            container_image=container_image,
        )
        return plan.model_copy(
            update={
                "selected_entry_runtime": selected_entry_runtime,
                "container_image": container_image,
                "container_image_repo_digest": container_image_repo_digest,
                "image_trust_status": image_trust_status,
                "runtime_command": runtime_command,
            }
        )

    def _os_container_execution_plan(
        self,
        *,
        root: Path,
        preflight: SandboxSkillRuntimePreflightResult,
        probe: SandboxOsContainerExecutorProbe,
    ) -> SandboxOsContainerExecutionPlan:
        container_root_path = "/trainer-sandbox"
        input_path = Path(preflight.path)
        cwd = input_path if self._path_is_dir(input_path) else input_path.parent
        cwd = self._resolve_within_root(root, str(cwd))
        container_workdir = self._container_path(root, cwd, container_root_path)
        container_input_path = self._container_path(root, input_path, container_root_path)
        container_output_paths = [
            self._container_path(root, Path(item), container_root_path)
            for item in preflight.normalized_output_paths
        ]
        runtime = probe.selected_runtime if probe.selected_runtime in {"docker", "podman"} else "none"
        executor_mode: Literal["none", "os_container_egress"] = (
            "os_container_egress" if probe.availability == "available" else "none"
        )
        plan_status: Literal["planned_blocked", "planned_probe_ready", "planned_ready"] = "planned_blocked"
        if probe.availability == "available":
            plan_status = "planned_ready"
        elif probe.availability == "unavailable_executor_not_implemented":
            plan_status = "planned_probe_ready"
        container_image = probe.image_reference or self._os_container_entry_image(probe.selected_entry_runtime)
        runtime_command = self._os_container_runtime_command_preview(
            runtime=runtime,
            mount_root_path=self._fs_path(root),
            container_root_path=container_root_path,
            container_workdir=container_workdir,
            container_image=container_image,
        )
        return SandboxOsContainerExecutionPlan(
            status=plan_status,
            runtime=runtime,
            executor_mode=executor_mode,
            selected_entry_runtime=probe.selected_entry_runtime,
            container_root_path=container_root_path,
            container_workdir=container_workdir,
            container_input_path=container_input_path,
            container_output_paths=container_output_paths,
            mount_root_path=self._fs_path(root),
            mount_root_read_only=False,
            network_allowlist=self._dedupe_strings(preflight.network_allowlist),
            runtime_command=runtime_command,
            container_image=container_image,
            container_image_repo_digest=probe.selected_image_repo_digest,
            image_trust_policy=probe.image_trust_policy or SKILL_EGRESS_OS_CONTAINER_IMAGE_TRUST_POLICY,
            image_trust_status=probe.image_trust_status,
            reason_code=probe.reason_code or SKILL_EGRESS_REASON_OS_CONTAINER_UNAVAILABLE,
            reason=probe.reason or SKILL_EGRESS_OS_CONTAINER_UNAVAILABLE_REASON,
        )

    def _probe_os_container_executor(self) -> SandboxOsContainerExecutorProbe:
        checked_at = datetime.now(UTC).isoformat()
        runtimes = (
            ("docker", ["docker", "version", "--format", "{{.Server.Version}}"]),
            ("podman", ["podman", "version", "--format", "{{.Server.Version}}"]),
        )
        missing_runtime_names: list[str] = []
        daemon_failures: list[str] = []
        probe_failures: list[str] = []
        last_probe_exit_code: int | None = None
        for runtime_name, command in runtimes:
            runtime_path = shutil.which(runtime_name)
            if not runtime_path:
                missing_runtime_names.append(runtime_name)
                continue
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    shell=False,
                    env=child_process_environment(),
                )
                last_probe_exit_code = completed.returncode
            except (OSError, subprocess.SubprocessError) as exc:
                probe_failures.append(f"{runtime_name}: {exc}")
                return SandboxOsContainerExecutorProbe(
                    availability="probe_failed",
                    selected_runtime=runtime_name,
                    selected_executor_mode="none",
                    selected_entry_runtime="none",
                    supported_entry_runtimes=[],
                    reason_code=SKILL_EGRESS_REASON_OS_CONTAINER_PROBE_FAILED,
                    reason=(
                        f"{SKILL_EGRESS_OS_CONTAINER_PROBE_FAILED_REASON} Runtime '{runtime_name}' probe raised: {exc}."
                    ),
                    checked_at=checked_at,
                    runtime_path=runtime_path,
                    probe_command=list(command),
                    probe_stdout_excerpt="",
                    probe_stderr_excerpt=self._evidence_excerpt(str(exc), limit=180),
                )
            stdout_excerpt = self._evidence_excerpt(completed.stdout or "", limit=180)
            stderr_excerpt = self._evidence_excerpt(completed.stderr or "", limit=180)
            if completed.returncode == 0:
                ruby_probe = self._probe_os_container_ruby_image(runtime_name)
                node_probe = self._probe_os_container_node_image(runtime_name)
                supported_entry_runtimes: list[str] = []
                if ruby_probe is not None and bool(ruby_probe["available"]) and str(ruby_probe["trust_status"]) == "trusted":
                    supported_entry_runtimes.append("ruby")
                if node_probe is not None and bool(node_probe["available"]) and str(node_probe["trust_status"]) == "trusted":
                    supported_entry_runtimes.append("node")
                selected_entry_runtime: Literal["none", "ruby", "node"] = (
                    "ruby"
                    if "ruby" in supported_entry_runtimes
                    else "node"
                    if "node" in supported_entry_runtimes
                    else "none"
                )
                selected_probe = (
                    ruby_probe
                    if selected_entry_runtime == "ruby"
                    else node_probe
                    if selected_entry_runtime == "node"
                    else None
                )
                if supported_entry_runtimes and selected_probe is not None:
                    selected_image = self._os_container_entry_image(selected_entry_runtime)
                    selected_label = self._os_container_entry_runtime_label(selected_entry_runtime)
                    return SandboxOsContainerExecutorProbe(
                        availability="available",
                        selected_runtime=runtime_name,
                        selected_executor_mode="os_container_egress",
                        selected_entry_runtime=selected_entry_runtime,
                        supported_entry_runtimes=supported_entry_runtimes,
                        reason_code="",
                        reason=(
                            f"Trainer verified runtime '{runtime_name}', trusted repo digest '{selected_probe['selected_repo_digest']}', "
                            f"and local image '{selected_image}' for the audited {selected_label} os/container executor."
                        ),
                        checked_at=checked_at,
                        runtime_path=runtime_path,
                        probe_command=selected_probe["command"],
                        probe_exit_code=selected_probe["exit_code"],
                        probe_stdout_excerpt=selected_probe["stdout_excerpt"],
                        probe_stderr_excerpt=selected_probe["stderr_excerpt"],
                        image_reference=selected_image,
                        image_repo_digests=list(selected_probe["repo_digests"]),
                        selected_image_repo_digest=str(selected_probe["selected_repo_digest"]),
                        image_trust_policy=SKILL_EGRESS_OS_CONTAINER_IMAGE_TRUST_POLICY,
                        image_trust_status=str(selected_probe["trust_status"]),
                    )
                for entry_runtime, image_probe, image_reference, trusted_repo_digests in (
                    ("ruby", ruby_probe, SKILL_EGRESS_OS_CONTAINER_RUBY_IMAGE, SKILL_EGRESS_OS_CONTAINER_TRUSTED_REPO_DIGESTS),
                    ("node", node_probe, SKILL_EGRESS_OS_CONTAINER_NODE_IMAGE, SKILL_EGRESS_OS_CONTAINER_NODE_TRUSTED_REPO_DIGESTS),
                ):
                    if image_probe is None:
                        continue
                    image_available = bool(image_probe["available"])
                    trust_status = str(image_probe["trust_status"])
                    if image_available and trust_status != "trusted":
                        return SandboxOsContainerExecutorProbe(
                            availability="unavailable_image_untrusted",
                            selected_runtime=runtime_name,
                            selected_executor_mode="none",
                            selected_entry_runtime=entry_runtime,
                            supported_entry_runtimes=supported_entry_runtimes,
                            reason_code=SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_UNTRUSTED,
                            reason=(
                                f"{SKILL_EGRESS_OS_CONTAINER_IMAGE_UNTRUSTED_REASON} Checked runtime '{runtime_name}', image "
                                f"'{image_reference}', trust policy '{SKILL_EGRESS_OS_CONTAINER_IMAGE_TRUST_POLICY}', "
                                f"and repo digests {image_probe['repo_digests'] or ['<none>']}. "
                                f"Expected one of {list(trusted_repo_digests) or ['<configure trusted repo digests>']}."
                            ),
                            checked_at=checked_at,
                            runtime_path=runtime_path,
                            probe_command=image_probe["command"],
                            probe_exit_code=image_probe["exit_code"],
                            probe_stdout_excerpt=image_probe["stdout_excerpt"],
                            probe_stderr_excerpt=image_probe["stderr_excerpt"],
                            image_reference=image_reference,
                            image_repo_digests=list(image_probe["repo_digests"]),
                            selected_image_repo_digest=str(image_probe["selected_repo_digest"]),
                            image_trust_policy=SKILL_EGRESS_OS_CONTAINER_IMAGE_TRUST_POLICY,
                            image_trust_status=trust_status,
                        )
                for entry_runtime, image_probe, image_reference in (
                    ("ruby", ruby_probe, SKILL_EGRESS_OS_CONTAINER_RUBY_IMAGE),
                    ("node", node_probe, SKILL_EGRESS_OS_CONTAINER_NODE_IMAGE),
                ):
                    if image_probe is None:
                        continue
                    return SandboxOsContainerExecutorProbe(
                        availability="unavailable_image_missing",
                        selected_runtime=runtime_name,
                        selected_executor_mode="none",
                        selected_entry_runtime=entry_runtime,
                        supported_entry_runtimes=supported_entry_runtimes,
                        reason_code=SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_MISSING,
                        reason=(
                            f"{SKILL_EGRESS_OS_CONTAINER_IMAGE_MISSING_REASON} Checked runtime '{runtime_name}' "
                            f"and image '{image_reference}'. Probe detail: {image_probe['detail']}."
                        ),
                        checked_at=checked_at,
                        runtime_path=runtime_path,
                        probe_command=image_probe["command"],
                        probe_exit_code=image_probe["exit_code"],
                        probe_stdout_excerpt=image_probe["stdout_excerpt"],
                        probe_stderr_excerpt=image_probe["stderr_excerpt"],
                        image_reference=image_reference,
                        image_repo_digests=list(image_probe["repo_digests"]),
                        selected_image_repo_digest=str(image_probe["selected_repo_digest"]),
                        image_trust_policy=SKILL_EGRESS_OS_CONTAINER_IMAGE_TRUST_POLICY,
                        image_trust_status=str(image_probe["trust_status"]),
                    )
                return SandboxOsContainerExecutorProbe(
                    availability="unavailable_executor_not_implemented",
                    selected_runtime=runtime_name,
                    selected_executor_mode="none",
                    selected_entry_runtime="none",
                    supported_entry_runtimes=supported_entry_runtimes,
                    reason_code=SKILL_EGRESS_REASON_OS_CONTAINER_EXECUTOR_NOT_IMPLEMENTED,
                    reason=(
                        f"{SKILL_EGRESS_OS_CONTAINER_EXECUTOR_NOT_IMPLEMENTED_REASON} "
                        f"Detected reachable runtime '{runtime_name}' at '{runtime_path}'."
                    ),
                    checked_at=checked_at,
                    runtime_path=runtime_path,
                    probe_command=list(command),
                    probe_exit_code=completed.returncode,
                    probe_stdout_excerpt=stdout_excerpt,
                    probe_stderr_excerpt=stderr_excerpt,
                )
            daemon_failures.append(
                f"{runtime_name} exit={completed.returncode}"
                + (f" stderr={stderr_excerpt}" if stderr_excerpt else "")
            )
        if daemon_failures:
            detail = "; ".join(daemon_failures)
            runtime_label = "docker" if shutil.which("docker") else "podman" if shutil.which("podman") else "none"
            runtime_path = shutil.which(runtime_label) if runtime_label != "none" else ""
            probe_command = (
                ["docker", "version", "--format", "{{.Server.Version}}"]
                if runtime_label == "docker"
                else ["podman", "version", "--format", "{{.Server.Version}}"]
                if runtime_label == "podman"
                else []
            )
            return SandboxOsContainerExecutorProbe(
                availability="unavailable_daemon_unreachable",
                selected_runtime=runtime_label,
                selected_executor_mode="none",
                selected_entry_runtime="none",
                supported_entry_runtimes=[],
                reason_code=SKILL_EGRESS_REASON_OS_CONTAINER_DAEMON_UNREACHABLE,
                reason=f"{SKILL_EGRESS_OS_CONTAINER_DAEMON_UNREACHABLE_REASON} Probe detail: {detail}.",
                checked_at=checked_at,
                runtime_path=runtime_path or "",
                probe_command=probe_command,
                probe_exit_code=last_probe_exit_code,
                probe_stdout_excerpt="",
                probe_stderr_excerpt=self._evidence_excerpt(detail, limit=180),
            )
        if probe_failures:
            detail = "; ".join(probe_failures)
            return SandboxOsContainerExecutorProbe(
                availability="probe_failed",
                selected_runtime="none",
                selected_executor_mode="none",
                selected_entry_runtime="none",
                supported_entry_runtimes=[],
                reason_code=SKILL_EGRESS_REASON_OS_CONTAINER_PROBE_FAILED,
                reason=f"{SKILL_EGRESS_OS_CONTAINER_PROBE_FAILED_REASON} Probe detail: {detail}.",
                checked_at=checked_at,
                runtime_path="",
                probe_command=[],
                probe_stdout_excerpt="",
                probe_stderr_excerpt=self._evidence_excerpt(detail, limit=180),
            )
        return SandboxOsContainerExecutorProbe(
            availability="unavailable_runtime_missing",
            selected_runtime="none",
            selected_executor_mode="none",
            selected_entry_runtime="none",
            supported_entry_runtimes=[],
            reason_code=SKILL_EGRESS_REASON_OS_CONTAINER_RUNTIME_MISSING,
            reason=(
                f"{SKILL_EGRESS_OS_CONTAINER_RUNTIME_MISSING_REASON} "
                f"Checked runtimes: {', '.join(runtime for runtime, _ in runtimes)}."
            ),
            checked_at=checked_at,
            runtime_path="",
            probe_command=[],
            probe_stdout_excerpt="",
            probe_stderr_excerpt="",
        )

    def _probe_os_container_ruby_image(self, runtime_name: str) -> dict[str, Any] | None:
        return self._probe_os_container_image(
            runtime_name,
            image_reference=SKILL_EGRESS_OS_CONTAINER_RUBY_IMAGE,
            trusted_repo_digests=SKILL_EGRESS_OS_CONTAINER_TRUSTED_REPO_DIGESTS,
        )

    def _probe_os_container_node_image(self, runtime_name: str) -> dict[str, Any] | None:
        return self._probe_os_container_image(
            runtime_name,
            image_reference=SKILL_EGRESS_OS_CONTAINER_NODE_IMAGE,
            trusted_repo_digests=SKILL_EGRESS_OS_CONTAINER_NODE_TRUSTED_REPO_DIGESTS,
        )

    def _probe_os_container_image(
        self,
        runtime_name: str,
        *,
        image_reference: str,
        trusted_repo_digests: tuple[str, ...],
    ) -> dict[str, Any] | None:
        command = [
            runtime_name,
            "image",
            "inspect",
            "--format",
            "{{json .RepoDigests}}",
            image_reference,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
                env=child_process_environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "available": False,
                "command": command,
                "exit_code": None,
                "stdout_excerpt": "",
                "stderr_excerpt": self._evidence_excerpt(str(exc), limit=180),
                "detail": str(exc),
                "repo_digests": [],
                "selected_repo_digest": "",
                "trust_status": "unknown",
            }
        repo_digests: list[str] = []
        if completed.returncode == 0:
            try:
                parsed = json.loads((completed.stdout or "").strip() or "[]")
                if isinstance(parsed, list):
                    repo_digests = [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                repo_digests = []
        selected_repo_digest = repo_digests[0] if repo_digests else ""
        if completed.returncode != 0:
            trust_status = "unknown"
        elif not repo_digests:
            trust_status = "missing_repo_digest"
        elif trusted_repo_digests and selected_repo_digest not in trusted_repo_digests:
            trust_status = "allowlist_mismatch"
        elif trusted_repo_digests:
            trust_status = "trusted"
        else:
            trust_status = "allowlist_mismatch"
        return {
            "available": completed.returncode == 0,
            "command": command,
            "exit_code": completed.returncode,
            "stdout_excerpt": self._evidence_excerpt(completed.stdout or "", limit=180),
            "stderr_excerpt": self._evidence_excerpt(completed.stderr or "", limit=180),
            "detail": (completed.stderr or completed.stdout or f"exit={completed.returncode}").strip(),
            "repo_digests": repo_digests,
            "selected_repo_digest": selected_repo_digest,
            "trust_status": trust_status,
        }

    def _append_unique(self, existing: list[str], additions: Iterable[str]) -> list[str]:
        values = list(existing)
        seen = {item for item in values}
        for addition in additions:
            normalized = str(addition).strip()
            if not normalized or normalized in seen:
                continue
            values.append(normalized)
            seen.add(normalized)
        return values

    def _walk_nodes(
        self,
        root: Path,
        resource_index: dict[str, ResourceRecord],
    ) -> list[SandboxNode]:
        nodes: list[SandboxNode] = []
        for path in sorted(self._iter_paths(root), key=lambda item: (self._path_is_file(item), str(item).lower())):
            if path == root:
                continue
            relative = self._relative_path(root, path)
            resource = resource_index.get(str(path))
            stat = self._path_stat(path)
            is_directory = self._path_is_dir(path)
            child_count = len(self._iterdir_paths(path)) if is_directory else 0
            is_file = self._path_is_file(path)
            nodes.append(
                SandboxNode(
                    path=str(path),
                    relative_path=relative,
                    name=path.name,
                    node_kind="directory" if is_directory else "file",
                    file_kind=self._file_kind_for_path(path),
                    resource_id=resource.id if resource else None,
                    source_uri=resource.source if resource else None,
                    size_bytes=0 if is_directory else stat.st_size,
                    updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    children_count=child_count,
                    is_editable=is_file and self._file_kind_for_path(path) in {"text", "markdown", "code", "html", "document"},
                )
            )
        return nodes

    def _resource_index(
        self,
        resources: Iterable[ResourceRecord],
        *,
        root: Path,
    ) -> dict[str, ResourceRecord]:
        root_resolved = root.resolve(strict=False)
        index: dict[str, ResourceRecord] = {}
        for resource in resources:
            for candidate in (
                self._resource_operation_path(resource, root=root),
                Path(resource.sandbox_path).resolve(strict=False) if resource.sandbox_path else None,
            ):
                if candidate is None:
                    continue
                resolved = candidate.resolve(strict=False)
                try:
                    resolved.relative_to(root_resolved)
                except ValueError:
                    continue
                index[str(resolved)] = resource
        return index

    def _resource_operation_path(self, resource: ResourceRecord, *, root: Path) -> Path | None:
        local_source = self._local_path(resource.source)
        if local_source is not None:
            resolved_source = local_source.expanduser().resolve(strict=False)
            try:
                resolved_source.relative_to(root.resolve(strict=False))
            except ValueError:
                pass
            else:
                return resolved_source
        sandbox_path = str(resource.sandbox_path or "").strip()
        if sandbox_path:
            return Path(sandbox_path).resolve(strict=False)
        return None

    def _resource_relative_path(self, resource: ResourceRecord) -> str:
        collection_path = self._validated_collection_path(resource.collection_path)
        trusted_collection_root = self._trusted_collection_root(resource)
        if resource.source_items:
            source_path = self._local_path(resource.source)
            if source_path is not None:
                folder_name = source_path.name or self._safe_name(resource.name or resource.id)
                return (
                    f"sources/folders/{self._resource_source_fingerprint(resource)}/"
                    f"{self._safe_name(resource.id)}/{folder_name}"
                )
        if collection_path and trusted_collection_root is not None:
            collection_key = sha1(collection_path.encode("utf-8")).hexdigest()[:12]
            file_name = PurePosixPath(collection_path).name
            return (
                f"sources/collections/{self._resource_source_fingerprint(resource)}/"
                f"{collection_key}/{self._safe_name(resource.id)}/{file_name}"
            )
        sandbox_path = resource.sandbox_path
        if sandbox_path:
            return Path(sandbox_path).name
        if resource.kind == "url":
            safe_name = self._safe_name(resource.name or resource.id)
            suffix = self._default_suffix(resource)
            return f"sources/web/{self._safe_name(resource.id)}/{safe_name}{suffix}"
        source_path = self._local_path(resource.source)
        if source_path is not None:
            return f"sources/inbox/{self._safe_name(resource.id)}/{source_path.name or resource.name}"
        safe_name = self._safe_name(resource.name or resource.id)
        suffix = self._default_suffix(resource)
        return f"sources/inbox/{self._safe_name(resource.id)}/{safe_name}{suffix}"

    def _resource_source_fingerprint(self, resource: ResourceRecord) -> str:
        collection_root = self._trusted_collection_root(resource)
        source = str(collection_root or resource.canonical_source or resource.source or resource.id).strip()
        return sha1(source.encode("utf-8")).hexdigest()[:12]

    def _trusted_collection_root(self, resource: ResourceRecord) -> Path | None:
        """Return an explicit collection root only when it proves the supplied display path."""
        collection_path = self._validated_collection_path(resource.collection_path)
        collection_root_value = str(resource.collection_root or "").strip()
        if not collection_path or not collection_root_value:
            return None

        collection_root_path = self._local_path(collection_root_value)
        source_path = next(
            (
                local_path
                for candidate in (resource.canonical_source, resource.source)
                if candidate
                if (local_path := self._local_path(candidate)) is not None
            ),
            None,
        )
        if collection_root_path is None or source_path is None:
            return None

        try:
            resolved_root = collection_root_path.resolve(strict=True)
            resolved_source = source_path.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if not self._path_is_dir(resolved_root):
            return None

        try:
            relative_source = resolved_source.relative_to(resolved_root)
        except ValueError:
            return None

        expected_path = PurePosixPath(collection_root_path.name, *relative_source.parts).as_posix()
        if not self._collection_paths_match(collection_path, expected_path):
            return None
        return resolved_root

    @staticmethod
    def _collection_paths_match(value: str, expected: str) -> bool:
        return value == expected

    @staticmethod
    def _validated_collection_path(value: str | None) -> str | None:
        if value is None:
            return None

        candidate = value.strip()
        if not candidate:
            raise ValueError("collection_path must be a non-empty POSIX relative file path.")
        if "\\" in candidate or "\x00" in candidate:
            raise ValueError("collection_path must use safe POSIX path separators.")
        if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate) or "://" in candidate:
            raise ValueError("collection_path must be relative to its resource collection.")

        parts = candidate.split("/")
        if any(not part or part in {".", ".."} for part in parts):
            raise ValueError("collection_path must not contain empty, current, or parent segments.")

        normalized = PurePosixPath(*parts).as_posix()
        if normalized in {"", "."} or PurePosixPath(normalized).is_absolute():
            raise ValueError("collection_path must be a non-empty POSIX relative file path.")
        return normalized

    def _materialize_target(self, root: Path, relative_target: str) -> Path:
        target = self._resolve_within_root(root, relative_target, allow_missing=True)
        self._ensure_directory(target.parent)
        return target

    def _ensure_workspace_scaffold(self, root: Path) -> None:
        for relative_path in TRAINER_SANDBOX_SCAFFOLD_PATHS:
            self._ensure_directory(root / Path(relative_path))

    def _is_scaffold_relative_path(self, relative_path: str) -> bool:
        normalized = str(relative_path or "").strip().replace("\\", "/").strip("/")
        return normalized in TRAINER_SANDBOX_SCAFFOLD_PATH_SET

    def _fs_path(self, path: Path) -> str:
        value = str(path)
        if os.name != "nt" or not value:
            return value
        if value.startswith("\\\\?\\"):
            return value
        if value.startswith("\\\\"):
            return "\\\\?\\UNC\\" + value.lstrip("\\")
        if path.is_absolute():
            return f"\\\\?\\{value}"
        return value

    def _fs_posix_path(self, path: Path) -> str:
        return PurePosixPath(path.as_posix()).as_posix()

    def _container_volume_mount_spec(self, root: Path, container_root_path: str) -> str:
        host_root = str(root.resolve(strict=False))
        if os.name == "nt":
            if host_root.startswith("\\\\?\\UNC\\"):
                host_root = "\\\\" + host_root[len("\\\\?\\UNC\\") :]
            elif host_root.startswith("\\\\?\\"):
                host_root = host_root[len("\\\\?\\") :]
            drive, rest = os.path.splitdrive(host_root)
            drive_prefix = drive[:1].lower()
            normalized_rest = rest.replace("\\", "/")
            if normalized_rest.startswith("/"):
                normalized_rest = normalized_rest[1:]
            host_root = f"/{drive_prefix}/{normalized_rest}" if drive_prefix else host_root.replace("\\", "/")
        return f"{host_root}:{container_root_path}:rw"

    def _container_env_flags(self, environment: dict[str, str]) -> list[str]:
        flags: list[str] = []
        for key, value in sorted(environment.items()):
            if key in {"TRAINER_EGRESS_ALLOWED_HOSTS", "TRAINER_EGRESS_GUARD_MODE", "RUBYOPT"}:
                continue
            flags.extend(["--env", f"{key}={value}"])
        return flags

    def _container_path(self, root: Path, path: Path, container_root_path: str) -> str:
        root_resolved = root.resolve(strict=False)
        candidate = path if path.is_absolute() else root_resolved / path
        relative = candidate.resolve(strict=False).relative_to(root_resolved)
        relative_posix = PurePosixPath(*relative.parts).as_posix()
        if not relative_posix or relative_posix == ".":
            return container_root_path
        return f"{container_root_path}/{relative_posix}"

    def _ensure_directory(self, path: Path) -> None:
        os.makedirs(self._fs_path(path), exist_ok=True)

    def _path_exists(self, path: Path) -> bool:
        return os.path.exists(self._fs_path(path))

    def _path_is_dir(self, path: Path) -> bool:
        return os.path.isdir(self._fs_path(path))

    def _path_is_file(self, path: Path) -> bool:
        return os.path.isfile(self._fs_path(path))

    def _path_stat(self, path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        return os.stat(self._fs_path(path), follow_symlinks=follow_symlinks)

    def _read_text(self, path: Path, *, encoding: str = "utf-8", errors: str = "strict") -> str:
        with open(self._fs_path(path), "r", encoding=encoding, errors=errors) as handle:
            return handle.read()

    def _write_text(self, path: Path, content: str, *, encoding: str = "utf-8") -> None:
        with open(self._fs_path(path), "w", encoding=encoding) as handle:
            handle.write(content)

    def _iterdir_paths(self, path: Path) -> list[Path]:
        return [path / child for child in os.listdir(self._fs_path(path))]

    def _windows_short_path(self, path: Path) -> str | None:
        if os.name != "nt":
            return None
        candidate = self._fs_path(path)
        buffer = ctypes.create_unicode_buffer(4096)
        result = ctypes.windll.kernel32.GetShortPathNameW(candidate, buffer, len(buffer))
        if result <= 0:
            return None
        return buffer.value or None

    def _copy_tree(self, source: Path, target: Path) -> None:
        try:
            shutil.copytree(self._fs_path(source), self._fs_path(target))
        except shutil.Error as exc:
            raise ValueError(f"Failed to copy resource folder into sandbox: {exc}") from exc
        except OSError as exc:
            raise ValueError(f"Failed to copy resource folder into sandbox: {exc}") from exc

    def _copy_file(self, source: Path, target: Path) -> None:
        try:
            shutil.copy2(self._fs_path(source), self._fs_path(target))
        except OSError as exc:
            raise ValueError(f"Failed to copy resource file into sandbox: {exc}") from exc

    def _remove_tree(self, path: Path, *, ignore_errors: bool = False) -> None:
        shutil.rmtree(self._fs_path(path), ignore_errors=ignore_errors)

    def _unlink_path(self, path: Path) -> None:
        try:
            os.unlink(self._fs_path(path))
        except FileNotFoundError:
            return

    def _move_path(self, source: Path, target: Path) -> None:
        shutil.move(self._fs_path(source), self._fs_path(target))

    def _trash_root_path(self, root: Path) -> Path:
        trash_root = root / "trash"
        self._ensure_directory(trash_root)
        return trash_root

    def _preview_artifact_root(self, workspace_id: str) -> Path:
        root = self.data_root / "previews" / self._safe_workspace_slug(workspace_id)
        self._ensure_directory(root)
        return root

    def _write_preview_artifact(
        self,
        workspace_id: str,
        *,
        source_path: Path,
        rendered_from: str,
        body: str,
    ) -> str:
        if not body.strip():
            return ""
        artifact_root = self._preview_artifact_root(workspace_id)
        artifact_name = self._preview_artifact_name(source_path, rendered_from=rendered_from)
        artifact_path = artifact_root / artifact_name
        self._ensure_directory(artifact_path.parent)
        self._write_text(artifact_path, body, encoding="utf-8")
        return str(artifact_path)

    def _preview_artifact_name(self, source_path: Path, *, rendered_from: str) -> str:
        stem = source_path.stem or source_path.name or "preview"
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "preview"
        suffix = source_path.suffix.lower().lstrip(".") or "file"
        return f"{safe_stem}-{rendered_from}-{suffix}.md"

    def _move_to_trash(self, root: Path, target: Path) -> str | None:
        trash_root = self._trash_root_path(root)
        trash_root_resolved = trash_root.resolve(strict=False)
        try:
            target.resolve(strict=False).relative_to(trash_root_resolved)
        except ValueError:
            pass
        else:
            if self._path_is_dir(target):
                self._remove_tree(target, ignore_errors=True)
            else:
                self._unlink_path(target)
            return None

        relative = self._relative_path(root, target)
        bucket = trash_root / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        destination = bucket / Path(relative)
        self._ensure_directory(destination.parent)
        self._move_path(target, destination)
        return str(destination)

    def _url_resource_body(self, resource: ResourceRecord) -> str:
        lines = [f"# {resource.name}", "", f"Source: {resource.source}"]
        if resource.summary:
            lines.extend(["", resource.summary])
        if resource.knowledge_fragments:
            lines.append("")
            lines.append("## Fragments")
            for fragment in resource.knowledge_fragments[:6]:
                snippet = str(fragment.get("snippet") or "").strip()
                if snippet:
                    lines.append(f"- {snippet}")
        return "\n".join(lines).strip() + "\n"

    def _snapshot_linked_resource(
        self,
        root: Path,
        *,
        resource_id: str,
        path: str,
    ) -> LinkedResourceSnapshot:
        resolved = self._resolve_within_root(root, path, allow_missing=True)
        if not resolved.exists():
            return LinkedResourceSnapshot(
                resource_id=resource_id,
                path=str(resolved),
                exists=False,
                node_kind="missing",
                inode=None,
                signature="missing",
            )
        stat = resolved.stat()
        node_kind = "directory" if resolved.is_dir() else "file"
        return LinkedResourceSnapshot(
            resource_id=resource_id,
            path=str(resolved),
            exists=True,
            node_kind=node_kind,
            inode=getattr(stat, "st_ino", None),
            signature=self._path_signature(resolved),
        )

    def _path_signature(self, path: Path) -> str:
        if not self._path_exists(path):
            return "missing"
        stat = self._path_stat(path)
        if self._path_is_file(path):
            return f"file:{stat.st_size}:{stat.st_mtime_ns}"

        digest = sha1()
        for candidate in sorted(self._iter_paths(path), key=lambda item: str(item).lower()):
            candidate_stat = self._path_stat(candidate)
            relative = "." if candidate == path else candidate.relative_to(path).as_posix()
            is_directory = self._path_is_dir(candidate)
            kind = "d" if is_directory else "f"
            size = 0 if is_directory else candidate_stat.st_size
            digest.update(f"{kind}:{relative}:{size}:{candidate_stat.st_mtime_ns}\n".encode("utf-8"))
        return f"dir:{digest.hexdigest()}"

    def _iter_paths(self, root: Path) -> Iterable[Path]:
        if not self._path_exists(root):
            return
        stack = [root]
        while stack:
            current = stack.pop()
            yield current
            if not self._path_is_dir(current):
                continue
            children = sorted(self._iterdir_paths(current), key=lambda item: str(item).lower(), reverse=True)
            stack.extend(children)

    def _find_path_by_inode(
        self,
        root: Path,
        *,
        inode: int,
        node_kind: str,
    ) -> str | None:
        expected_is_dir = node_kind == "directory"
        for candidate in self._iter_paths(root):
            if self._path_is_dir(candidate) != expected_is_dir:
                continue
            try:
                candidate_stat = self._path_stat(candidate)
            except FileNotFoundError:
                continue
            if getattr(candidate_stat, "st_ino", None) == inode:
                return str(candidate)
        return None

    def _resolve_relative_destination_within_root(
        self,
        root: Path,
        value: str,
        *,
        allow_missing: bool = False,
    ) -> Path:
        raw_value = str(value or "").strip()
        windows_path = PureWindowsPath(raw_value)
        if (
            Path(raw_value).is_absolute()
            or PurePosixPath(raw_value).is_absolute()
            or bool(windows_path.drive)
            or bool(windows_path.root)
            or any(part == ".." for part in re.split(r"[\\\\/]+", raw_value))
        ):
            raise ValueError("Sandbox destination must be a relative path inside the sandbox root.")
        return self._resolve_within_root(root, raw_value, allow_missing=allow_missing)

    def _resolve_within_root(
        self,
        root: Path,
        value: str,
        *,
        allow_missing: bool = False,
    ) -> Path:
        raw_value = str(value or "").strip()
        candidate = Path(raw_value)
        host_absolute = candidate.is_absolute()
        cross_system_absolute = PurePosixPath(raw_value).is_absolute() or PureWindowsPath(raw_value).is_absolute()
        if cross_system_absolute and not host_absolute:
            raise ValueError("Sandbox path must stay inside the sandbox root.")
        if not host_absolute:
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            raise ValueError("Sandbox path must stay inside the sandbox root.") from None
        if resolved == root_resolved:
            return resolved
        if not allow_missing and not self._path_exists(resolved):
            raise FileNotFoundError(f"Sandbox path does not exist: {resolved}")
        return resolved

    def _default_archive_destination(self, archive_path: Path) -> str:
        name = archive_path.name
        lowered = name.lower()
        for suffix in sorted(ARCHIVE_AUDIT_SUPPORTED_SUFFIXES, key=len, reverse=True):
            if lowered.endswith(suffix):
                stem = name[:-len(suffix)] or archive_path.stem or archive_path.name
                return f"{stem}-extracted"
        return f"{archive_path.stem or archive_path.name}-extracted"

    def _archive_format(self, archive_path: Path) -> Literal["zip", "tar", "unsupported"]:
        name = archive_path.name.lower()
        if name.endswith(".zip") and zipfile.is_zipfile(archive_path):
            return "zip"
        if any(name.endswith(suffix) for suffix in ARCHIVE_AUDIT_SUPPORTED_SUFFIXES if suffix != ".zip"):
            if tarfile.is_tarfile(archive_path):
                return "tar"
        return "unsupported"

    def _zip_archive_entries(self, archive_path: Path) -> list[_ArchiveEntryMetadata]:
        entries: list[_ArchiveEntryMetadata] = []
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                mode = (info.external_attr >> 16) & 0o777777
                entry_kind = "directory" if info.is_dir() else "file"
                if mode and stat.S_IFMT(mode) == stat.S_IFLNK:
                    entry_kind = "symlink"
                entries.append(
                    {
                        "name": info.filename,
                        "entry_kind": entry_kind,
                        "size": int(info.file_size or 0),
                        "link_target": "",
                    }
                )
        return entries

    def _tar_archive_entries(self, archive_path: Path) -> list[_ArchiveEntryMetadata]:
        entries: list[_ArchiveEntryMetadata] = []
        with tarfile.open(archive_path) as archive:
            for info in archive.getmembers():
                entry_kind = "other"
                if info.isdir():
                    entry_kind = "directory"
                elif info.issym():
                    entry_kind = "symlink"
                elif info.islnk():
                    entry_kind = "hardlink"
                elif info.isfile():
                    entry_kind = "file"
                entries.append(
                    {
                        "name": info.name,
                        "entry_kind": entry_kind,
                        "size": int(info.size or 0),
                        "link_target": getattr(info, "linkname", "") or "",
                    }
                )
        return entries

    def _audit_archive_entry(
        self,
        *,
        root: Path,
        destination: Path,
        archive_path: Path,
        name: str,
        entry_kind: str,
        uncompressed_bytes: int,
        link_target: str = "",
    ) -> tuple[SandboxArchiveAuditEntry, list[SandboxArchiveAuditFinding]]:
        findings: list[SandboxArchiveAuditFinding] = []
        normalized_path, path_reasons = self._normalize_archive_entry_path(name)
        for reason in path_reasons:
            findings.append(
                SandboxArchiveAuditFinding(
                    category="path_escape",
                    severity="blocker",
                    reason=reason,
                    evidence=name,
                    source_path=str(archive_path),
                )
            )
        target_path = ""
        if normalized_path:
            target = (destination / normalized_path).resolve(strict=False)
            target_path = str(target)
            for boundary, reason in (
                (root.resolve(strict=False), "Archive entry would write outside the sandbox root."),
                (
                    destination.resolve(strict=False),
                    "Archive entry would escape the dry-run extraction destination.",
                ),
            ):
                try:
                    target.relative_to(boundary)
                except ValueError:
                    findings.append(
                        SandboxArchiveAuditFinding(
                            category="path_escape",
                            severity="blocker",
                            reason=reason,
                            evidence=name,
                            source_path=str(archive_path),
                        )
                    )

        if entry_kind in {"symlink", "hardlink"}:
            findings.append(
                SandboxArchiveAuditFinding(
                    category="path_escape",
                    severity="blocker",
                    reason=(
                        "Archive link entries are blocked because symlink, hardlink, or junction-like "
                        "payloads can redirect extraction outside the sandbox."
                    ),
                    evidence=f"{name} -> {link_target}".strip(),
                    source_path=str(archive_path),
                )
            )
        if normalized_path and Path(normalized_path).suffix.lower() in ARCHIVE_AUDIT_EXECUTABLE_SUFFIXES:
            findings.append(
                SandboxArchiveAuditFinding(
                    category="malicious_document",
                    severity="blocker",
                    reason="Archive contains executable or script-like payloads; Trainer keeps them out of teaching material.",
                    evidence=normalized_path,
                    source_path=str(archive_path),
                )
            )
        if normalized_path and entry_kind == "file" and self._is_archive_payload_name(normalized_path):
            findings.append(
                SandboxArchiveAuditFinding(
                    category="malicious_document",
                    severity="blocker",
                    reason=(
                        "Archive contains nested or recursive archive payloads, including unsupported archive types; "
                        "Trainer does not recurse into archive-inside-archive content."
                    ),
                    evidence=normalized_path,
                    source_path=str(archive_path),
                )
            )
        if entry_kind == "other":
            findings.append(
                SandboxArchiveAuditFinding(
                    category="malicious_document",
                    severity="blocker",
                    reason="Archive contains a special file entry that is not safe for cross-platform extraction.",
                    evidence=name,
                    source_path=str(archive_path),
                )
            )

        reasons = [finding.reason for finding in findings if finding.severity == "blocker"]
        return (
            SandboxArchiveAuditEntry(
                name=name,
                normalized_path=normalized_path,
                target_path=target_path,
                entry_kind=entry_kind if entry_kind in {"file", "directory", "symlink", "hardlink", "other"} else "other",
                uncompressed_bytes=uncompressed_bytes,
                blocked=bool(reasons),
                reasons=self._dedupe_strings(reasons),
            ),
            findings,
        )

    def _normalize_archive_entry_path(self, value: str) -> tuple[str, list[str]]:
        raw = str(value or "")
        reasons: list[str] = []
        if not raw.strip():
            return "", ["Archive entry name is empty."]
        if "\x00" in raw:
            reasons.append("Archive entry name contains a NUL byte.")
        if raw.startswith(("/", "\\")) or raw.startswith("//") or raw.startswith("\\\\"):
            reasons.append("Archive entry uses an absolute or UNC path.")
        if re.match(r"^[A-Za-z]:", raw):
            reasons.append("Archive entry uses a Windows drive-qualified path.")
        normalized = raw.replace("\\", "/")
        parts: list[str] = []
        for part in normalized.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                reasons.append("Archive entry uses parent traversal (`..`).")
                continue
            if re.match(r"^[A-Za-z]:", part):
                reasons.append("Archive entry path segment contains a Windows drive prefix.")
                continue
            parts.append(part)
        normalized_path = "/".join(parts)
        if not normalized_path and not reasons:
            normalized_path = "."
        return normalized_path, self._dedupe_strings(reasons)

    def _is_archive_payload_name(self, value: str) -> bool:
        lowered = str(value or "").strip().lower()
        return any(lowered.endswith(suffix) for suffix in ARCHIVE_AUDIT_RECURSIVE_SUFFIXES)

    def _dedupe_archive_findings(
        self,
        findings: Iterable[SandboxArchiveAuditFinding],
    ) -> list[SandboxArchiveAuditFinding]:
        deduped: list[SandboxArchiveAuditFinding] = []
        seen: set[tuple[str, str, str, str]] = set()
        for finding in findings:
            key = (
                finding.category,
                finding.severity,
                finding.reason.strip(),
                finding.evidence.strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(finding)
        return deduped

    def _dedupe_strings(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _relative_path(self, root: Path, value: Path) -> str:
        try:
            return value.relative_to(root).as_posix()
        except ValueError:
            return value.name

    def _local_path(self, value: str) -> Path | None:
        if value.startswith(("http://", "https://")):
            return None
        return Path(value).expanduser()

    def _safe_workspace_slug(self, workspace_id: str) -> str:
        cleaned = "".join(character if character.isalnum() else "-" for character in workspace_id.lower())
        return cleaned.strip("-") or "workspace"

    def _safe_name(self, value: str) -> str:
        cleaned = "".join(character if character.isalnum() or character in {"-", "_", "."} else "-" for character in value)
        return cleaned.strip("-") or "resource"

    def _default_suffix(self, resource: ResourceRecord) -> str:
        if resource.kind == "markdown":
            return ".md"
        if resource.kind == "code":
            return ".txt"
        if resource.kind == "pdf":
            return ".pdf"
        if resource.kind == "image":
            return ".png"
        if resource.kind == "url":
            return ".md"
        return ".txt"

    def _file_kind_for_path(self, path: Path) -> str:
        if path.is_dir():
            return "directory"
        lowered_name = path.name.lower()
        if any(lowered_name.endswith(suffix) for suffix in ARCHIVE_AUDIT_SUPPORTED_SUFFIXES):
            return "archive"
        suffix = path.suffix.lower()
        if suffix in {".md", ".markdown"}:
            return "markdown"
        if suffix in {".csv", ".tsv"}:
            return "text"
        if suffix == ".ipynb":
            return "notebook"
        if suffix in {".xlsx", ".ods"}:
            return "table"
        if suffix in {".epub", ".eml"}:
            return "document"
        if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".toml", ".css", ".scss", ".vue", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".php", ".rb", ".sh", ".zsh", ".bash", ".ps1", ".sql"}:
            return "code"
        if suffix in {".html", ".htm"}:
            return "html"
        if suffix == ".pdf":
            return "pdf"
        if suffix in {".docx", ".pptx", ".odt", ".odp", ".rtf"}:
            return "document"
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            return "image"
        if suffix in {".txt", ".rst"}:
            return "text"
        return "binary"

    def _archive_preview_data(self, path: Path) -> dict[str, object]:
        lowered_name = path.name.lower()
        if lowered_name.endswith(".zip") and zipfile.is_zipfile(path):
            entries = self._zip_archive_entries(path)
            archive_format = "zip"
        elif any(lowered_name.endswith(suffix) for suffix in ARCHIVE_AUDIT_SUPPORTED_SUFFIXES if suffix != ".zip") and tarfile.is_tarfile(path):
            entries = self._tar_archive_entries(path)
            archive_format = "tar"
        else:
            return {
                "kind": "archive",
                "format": "unknown",
                "entryCount": 0,
                "previewEntries": [],
                "truncated": False,
            }

        preview_entries = [
            {
                "path": str(entry.get("name") or ""),
                "kind": str(entry.get("entry_kind") or "file"),
                "sizeBytes": int(entry.get("size") or 0),
                "linkTarget": str(entry.get("link_target") or ""),
            }
            for entry in entries[:24]
        ]
        return {
            "kind": "archive",
            "format": archive_format,
            "entryCount": len(entries),
            "previewEntries": preview_entries,
            "truncated": len(entries) > len(preview_entries),
        }

    def _language_hint(self, path: Path) -> str | None:
        suffix = path.suffix.lower()
        return {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".js": "javascript",
            ".jsx": "javascriptreact",
            ".json": "json",
            ".md": "markdown",
            ".html": "html",
            ".css": "css",
            ".sql": "sql",
            ".sh": "shell",
        }.get(suffix)

    def _extract_pdf_text(self, path: Path) -> str:
        try:
            import fitz  # type: ignore
        except Exception as exc:
            logger.debug("PyMuPDF unavailable for PDF preview of %s: %s", path.name, exc)
            return f"PDF preview requires PyMuPDF. File: {path.name}"
        with fitz.open(path) as document:  # type: ignore[attr-defined]
            pages = [str(page.get_text()) for page in document]
        return "\n\n".join(page for page in pages if page).strip()

    def _extract_zip_xml_text(self, path: Path, inner_path: str) -> str:
        import re
        import zipfile

        with zipfile.ZipFile(path) as archive:
            raw = archive.read(inner_path).decode("utf-8", errors="replace")
        text = re.sub(r"<[^>]+>", " ", raw)
        return " ".join(text.split())

    def _extract_pptx_xml_text(self, path: Path) -> str:
        import re
        import zipfile

        paragraphs: list[str] = []
        with zipfile.ZipFile(path) as archive:
            for inner_path in sorted(
                name for name in archive.namelist() if name.startswith("ppt/slides/") and name.endswith(".xml")
            ):
                raw = archive.read(inner_path).decode("utf-8", errors="replace")
                text = re.sub(r"<[^>]+>", " ", raw)
                paragraph = " ".join(text.split())
                if paragraph:
                    paragraphs.append(paragraph)
        return "\n\n".join(paragraphs)

    @staticmethod
    def _subprocess_output_text(value: str | bytes | None) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value or ""

    def _truncate_output(self, value: str, *, limit: int = 24_000) -> _TruncatedOutput:
        if len(value) <= limit:
            return {"text": value, "truncated": False}
        return {"text": value[:limit] + "\n... output truncated ...", "truncated": True}

    def _render_plan_markdown(
        self,
        plan: LearningPlan,
        *,
        reason: str,
        overlay: dict[str, str] | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> str:
        chrome = overlay if isinstance(overlay, dict) else {}
        active_stage = next(
            (
                stage
                for stage in plan.stages
                if stage.id == plan.current_stage_id or stage.status == "active"
            ),
            plan.stages[0] if plan.stages else None,
        )
        if not chrome:
            chrome = live_plan_snapshot_persist_chrome(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                stage_title=str(getattr(active_stage, "title", "") or "") if active_stage is not None else "",
                task_title=leftover_task_title,
            )
        live_title = str(chrome.get("plan_title") or "").strip()
        live_stage_title = str(chrome.get("stage_title") or "").strip()
        live_step = str(chrome.get("current_step") or "").strip()
        live_why = str(chrome.get("why_now") or "").strip()
        live_next = str(chrome.get("next_after_current") or "").strip()
        live_summary = str(chrome.get("summary") or "").strip()
        show_stages = str(chrome.get("show_stages") or "").strip() == "1"
        live_plan_id = str(chrome.get("plan_id") or "").strip()
        if chrome:
            heading = live_title or "Trainer Plan"
            current_step = live_step
            why_now = live_why
            next_after_current = live_next
            stage_title = live_stage_title
            summary = live_summary
            plan_id = live_plan_id
        else:
            heading = plan.title or "Trainer Plan"
            current_step = plan.current_step
            why_now = plan.why_now
            next_after_current = plan.next_after_current
            stage_title = active_stage.title if active_stage is not None else ""
            summary = plan.summary
            show_stages = True
            plan_id = plan.id or plan.plan_id or "plan"
        lines = [
            f"# {heading}",
            "",
        ]
        if plan_id:
            lines.append(f"- Plan ID: {plan_id}")
        lines.extend(
            [
                f"- Persisted reason: {reason}",
                f"- Cadence: {plan.weekly_cadence or plan.cadence or 'not-set'}",
                f"- Frozen: {'yes' if plan.frozen else 'no'}",
                f"- Updated at: {plan.updated_at or plan.created_at or datetime.now(UTC).isoformat()}",
            ]
        )
        if summary:
            lines.extend(["", "## Summary", summary])
        if active_stage is not None and stage_title:
            live_goal = (
                active_stage.goal
                if not chrome or stage_title == active_stage.title
                else ""
            )
            lines.extend(
                [
                    "",
                    "## Current stage",
                    f"- Title: {stage_title}",
                    *([f"- Goal: {live_goal}"] if live_goal else []),
                    f"- Status: {active_stage.status}",
                ]
            )
        leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        recovered_step = str(leftover_runtime.get("current_step") or "").strip()
        leftover_live = leftover_formal_plan_is_live_for_fill(
            plan=plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )
        if leftover_runtime and not recovered_step:
            verify_method: list[str] = []
            blocked_reason = ""
        elif leftover_runtime and not leftover_live:
            verify_raw = leftover_runtime.get("verify_method") or []
            verify_method = (
                [str(item).strip() for item in verify_raw if str(item).strip()]
                if isinstance(verify_raw, list)
                else []
            )
            blocked_reason = str(leftover_runtime.get("blocked_reason") or "").strip()
        elif not leftover_runtime and str(chrome.get("show_stages") or "").strip() != "1":
            verify_method = []
            blocked_reason = ""
        else:
            verify_method = [str(item).strip() for item in (plan.verify_method or []) if str(item).strip()]
            blocked_reason = str(plan.blocked_reason or "").strip()
        if current_step:
            lines.extend(["", "## Current step", current_step])
        if why_now:
            lines.extend(["", "## Why now", why_now])
        if verify_method:
            lines.extend(["", "## Verify", *self._markdown_bullets(verify_method)])
        if blocked_reason:
            lines.extend(["", "## Blocked by", blocked_reason])
        if next_after_current:
            lines.extend(["", "## Next after current", next_after_current])
        if show_stages and plan.stages:
            lines.append("")
            lines.append("## Stages")
            for index, stage in enumerate(plan.stages, start=1):
                lines.append(f"### {index}. {stage.title} [{stage.status}]")
                lines.append(f"- Goal: {stage.goal}")
                if stage.outcomes:
                    lines.extend(self._markdown_bullets(stage.outcomes, prefix="  - "))
                else:
                    lines.append("  - No outcomes captured yet.")
                if stage.resources:
                    lines.append("- Resources:")
                    lines.extend(self._markdown_bullets(stage.resources, prefix="  - "))
                lines.append("")
            while lines and lines[-1] == "":
                lines.pop()
        return "\n".join(lines) + "\n"

    def _render_training_card_markdown(
        self,
        card: TrainingCardCandidateSnapshot,
        *,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> str:
        deliverables = [item for item in card.learner_deliverables if item]
        if card.deliverable and card.deliverable not in deliverables:
            deliverables.insert(0, card.deliverable)
        verification_steps = [item for item in card.verification_steps if item]
        for item in (card.validation_method, card.verification_method):
            cleaned = str(item or "").strip()
            if cleaned and cleaned not in verification_steps:
                verification_steps.append(cleaned)
        leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        live_title = live_training_card_title(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=leftover_task_title,
            card_title=card.title or "",
        )
        lines = [
            f"# {live_title or 'Training Card'}",
            "",
            f"- Card ID: {card.card_id or 'card'}",
            f"- Type: {card.card_type}",
            f"- Status: {card.status}",
            f"- Scenario Pack: {card.scenario_pack or 'general'}",
            f"- Focus area: {card.focus_area or card.target_skill or 'training'}",
            f"- Trust: {card.trust_state or 'unknown'}",
            f"- Updated at: {card.updated_at or card.created_at or datetime.now(UTC).isoformat()}",
        ]
        if card.why_now:
            lines.extend(["", "## Why now", card.why_now])
        if card.target_skill:
            lines.extend(["", "## Target skill", card.target_skill])
        if card.problem_statement or card.question:
            lines.extend(["", "## Problem", card.problem_statement or card.question])
        if deliverables:
            lines.extend(["", "## Learner deliverable", *self._markdown_bullets(deliverables)])
        if verification_steps:
            lines.extend(["", "## Verification", *self._markdown_bullets(verification_steps)])
        if card.return_with:
            lines.extend(["", "## Return with", card.return_with])
        if card.stuck_recovery:
            lines.extend(["", "## Fallback", card.stuck_recovery])
        if card.next_after_completion:
            lines.extend(["", "## Next after completion", card.next_after_completion])
        evidence_lines: list[str] = []
        if card.resource_id:
            evidence_lines.append(f"Resource ID: {card.resource_id}")
        if card.files_to_touch:
            evidence_lines.extend(f"File: {item}" for item in card.files_to_touch if item)
        if card.source_chain:
            evidence_lines.append(f"Source chain: {' -> '.join(item for item in card.source_chain if item)}")
        if evidence_lines:
            lines.extend(["", "## Evidence anchors", *self._markdown_bullets(evidence_lines)])
        return "\n".join(lines) + "\n"

    def _render_training_evaluation_note_markdown(
        self,
        *,
        card: TrainingCardCandidateSnapshot | None,
        passed: bool,
        summary: str,
        next_step: str,
        focus_area: str,
        failed_checks: list[str],
        missing_requirements: list[str],
        evidence_source: str,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> str:
        leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        raw_title = (card.title if card is not None else "") or focus_area
        live_title = live_training_card_title(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=leftover_task_title,
            card_title=raw_title,
        )
        title = live_title or "Training handoff"
        lines = [
            f"# {title}",
            "",
            f"- Card ID: {(card.card_id if card is not None else '') or 'unknown'}",
            f"- Status: {'verified' if passed else 'needs_revision'}",
            f"- Scenario Pack: {(card.scenario_pack if card is not None else '') or 'general'}",
            f"- Evidence source: {evidence_source or 'ide_current_file'}",
            f"- Focus area: {focus_area or (card.focus_area if card is not None else '') or 'training'}",
            f"- Updated at: {datetime.now(UTC).isoformat()}",
        ]
        if summary:
            lines.extend(["", "## Summary", summary])
        if next_step:
            lines.extend(["", "## Next step", next_step])
        if failed_checks:
            lines.extend(["", "## Failed checks", *self._markdown_bullets(failed_checks)])
        if missing_requirements:
            lines.extend(["", "## Missing requirements", *self._markdown_bullets(missing_requirements)])
        if card is not None and card.return_with:
            lines.extend(["", "## Return with", card.return_with])
        if card is not None and card.next_after_completion:
            lines.extend(["", "## Next after completion", card.next_after_completion])
        return "\n".join(lines) + "\n"

    def _training_card_directory(self, card: TrainingCardCandidateSnapshot) -> str:
        if card.card_type == "flash":
            return "flash"
        if card.status in {"reviewed", "fed_back", "archived"}:
            return "review"
        if card.card_type == "transfer" or str(card.scenario_pack or "").strip():
            return "scenario"
        return "practice"

    @staticmethod
    def _markdown_bullets(values: Iterable[str], *, prefix: str = "- ") -> list[str]:
        return [f"{prefix}{str(value).strip()}" for value in values if str(value).strip()]

    def _build_notes(self, resources: Iterable[ResourceRecord], root: Path, total_files: int) -> list[str]:
        linked = sum(1 for resource in resources if resource.sandbox_path)
        notes = [
            f"Sandbox root: {root}",
            f"Trainer layout: {' / '.join(TRAINER_SANDBOX_MANAGED_ROOTS)}",
            f"Linked resources: {linked}",
            f"Managed files: {total_files}",
            "Imported materials default to sources/inbox, sources/web, or sources/folders; derived work stays in the Trainer workspace.",
        ]
        return notes

    def _resolve_capability_workspace_trust_state(self, workspace_id: str) -> str:
        """Fail-closed trust label for capability summary.

        Only host-attested project authority can paint trusted. Missing
        attestation → unknown. Untrusted and remote must never paint trusted.
        """
        project = self._resolved_project_identity(workspace_id)
        if project is None:
            return "unknown"
        if not project.is_workspace_trusted:
            return "untrusted"
        if project.is_remote_workspace:
            return "remote"
        if not project.active_workspace_root:
            return "unknown"
        return "trusted"

    def _build_capability_summary(
        self,
        root: Path,
        *,
        workspace_id: str = "",
    ) -> SandboxCapabilitySummary:
        current_platform = self._current_platform()
        os_container_probe = self._probe_os_container_executor()
        path_separator = "\\" if current_platform == "windows" else "/"
        shell_family: Literal["powershell", "posix"] = "powershell" if current_platform == "windows" else "posix"
        case_sensitivity: Literal["case-sensitive", "case-insensitive"] = (
            "case-insensitive" if current_platform in {"windows", "macos"} else "case-sensitive"
        )
        platform_info = SandboxPlatformInfo(
            os=current_platform,
            architecture=platform.machine().lower(),
            shell_family=shell_family,
            path_separator=path_separator,
            case_sensitivity=case_sensitivity,
            default_encoding="utf-8",
            workspace_trust_state=self._resolve_capability_workspace_trust_state(workspace_id),
        )

        return SandboxCapabilitySummary(
            platform=platform_info,
            permission_state="coach_only",
            path_guard_status=SandboxCapabilityStatus(
                status="available",
                summary="Sandbox path resolution is enforced server-side and escapes are blocked before file operations.",
                policy="trainer.resource_sandbox.path_guard.v1",
            ),
            archive_audit_status=SandboxCapabilityStatus(
                status="available",
                summary=(
                    "Archive dry-run audit blocks zip-slip, tar-slip, symlink/junction pivots, "
                    "nested archive payloads, and unsafe payload patterns."
                ),
                policy=ARCHIVE_AUDIT_POLICY,
            ),
            skill_manifest_status=SandboxCapabilityStatus(
                status="available",
                summary="Skill manifest audit blocks prompt injection, supply-chain, credential, and path-escape risks before runtime.",
                policy=SKILL_MANIFEST_POLICY,
            ),
            skill_runtime_status=SandboxCapabilityStatus(
                status="available",
                summary="Runtime preflight validates declared platform, command templates, env whitelist, output paths, and timeout.",
                policy=SKILL_RUNTIME_POLICY,
            ),
            network_execution_status=SandboxCapabilityStatus(
                status="degraded",
                summary=(
                    "Narrow Python and Node.js socket guards can run audited entry scripts with an explicit allowlist; "
                    "broader OS/container egress enforcement still depends on host runtime availability, locally trusted audited images, and verified container execution."
                ),
                reason_code=os_container_probe.reason_code or "network_egress_enforcement_missing",
                reasons=[
                    "Only audited sandbox Python and Node.js scripts can enter per-run guarded egress.",
                    "Runtime preflight still blocks unaudited and child-process escape lanes before execution.",
                    os_container_probe.reason or "OS/container-level per-run egress isolation is still unavailable, so general network execution remains degraded.",
                ],
                policy="trainer.resource_sandbox.skill_isolated_executor.v1",
                network_facts=SandboxNetworkExecutionFacts(
                    audited_python={
                        "status": "guarded_allowlist_only",
                        "current_enforcement": "python_socket_guard",
                        "next_requirement": "os_or_container_egress_enforcement",
                        "reason_code": "",
                        "reason": "Audited Python entry scripts can use the narrow per-run Python socket guard.",
                        "required_executor": "python_socket_guard",
                    },
                    unaudited_python={
                        "status": "blocked",
                        "current_enforcement": "runtime_preflight",
                        "next_requirement": "audited_sandbox_python_script",
                        "reason_code": SKILL_EGRESS_REASON_UNAUDITED,
                        "reason": SKILL_EGRESS_UNAUDITED_REASON,
                        "required_executor": "python_socket_guard",
                    },
                    non_python={
                        "status": "guarded_allowlist_only",
                        "current_enforcement": "node_socket_guard",
                        "next_requirement": "os_or_container_egress_enforcement",
                        "reason_code": "",
                        "reason": (
                            "Audited Node.js entry scripts can use the narrow per-run Node socket guard; "
                            "broader non-Python network execution still requires verified OS/container lanes."
                        ),
                        "required_executor": "node_socket_guard",
                    },
                    child_process={
                        "status": "blocked_by_preflight",
                        "current_enforcement": "runtime_preflight",
                        "next_requirement": "subprocess_free_audited_entrypoint",
                        "reason_code": "network_egress_child_process_escape_blocked",
                        "reason": (
                            "Child-process and fan-out escape paths are blocked during runtime preflight before any "
                            "network execution right is evaluated."
                        ),
                        "required_executor": "none",
                    },
                    os_container={
                        "status": self._os_container_lane_status(os_container_probe),
                        "current_enforcement": self._os_container_lane_current_enforcement(os_container_probe),
                        "next_requirement": self._os_container_lane_next_requirement(os_container_probe),
                        "reason_code": os_container_probe.reason_code or SKILL_EGRESS_REASON_OS_CONTAINER_UNAVAILABLE,
                        "reason": os_container_probe.reason or SKILL_EGRESS_OS_CONTAINER_UNAVAILABLE_REASON,
                        "required_executor": "os_container_egress",
                    },
                    os_container_probe=os_container_probe,
                ),
            ),
            output_boundary_status=SandboxCapabilityStatus(
                status="available",
                summary="Skill output writes are restricted to declared sandbox paths and reject symlink/junction/reparse boundary escapes.",
                policy="trainer.resource_sandbox.skill_isolated_executor.v1",
            ),
            cross_system_degradation=[
                (
                    "Skill network execution stays degraded across windows/macos/linux outside the audited Python or Node.js guard paths because "
                    f"{(os_container_probe.reason or SKILL_EGRESS_OS_CONTAINER_UNAVAILABLE_REASON).rstrip('.') .lower()}."
                ),
                f"Sandbox root and platform path semantics are normalized for {current_platform}; the current root is {root}.",
            ],
        )
