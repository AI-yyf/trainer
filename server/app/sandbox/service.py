from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Mapping, TypedDict
from uuid import uuid4

from ..core.models import (
    LearningPlan,
    ResourceRecord,
    SandboxArchiveAuditEntry,
    SandboxArchiveAuditFinding,
    SandboxArchiveAuditResult,
    SandboxBatchRenameRequest,
    SandboxCapabilityStatus,
    SandboxCapabilitySummary,
    SandboxCommandEntry,
    SandboxCommandRequest,
    SandboxDeleteRequest,
    SandboxMkdirRequest,
    SandboxNetworkExecutionFacts,
    SandboxNode,
    SandboxOsContainerExecutionPlan,
    SandboxOsContainerExecutorProbe,
    SandboxPatchOperation,
    SandboxPatchRequest,
    SandboxPlatformInfo,
    SandboxPreview,
    SandboxPreviewRequest,
    SandboxRenameRequest,
    SandboxRestoreRequest,
    SandboxSkillEgressDecision,
    SandboxSkillManifestAuditResult,
    SandboxSkillManifestFinding,
    SandboxSkillRunResult,
    SandboxSkillRuntimePolicy,
    SandboxSkillRuntimePreflightResult,
    SandboxState,
    SandboxWriteRequest,
    TrainingCardCandidateSnapshot,
    WorkspaceAuthoritySummary,
)
from ..memory.workspace_recovery import (
    leftover_formal_plan_is_live_for_fill,
    live_plan_snapshot_persist_chrome,
    live_training_card_title,
)
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


ARCHIVE_AUDIT_POLICY = "trainer.resource_sandbox.archive_dry_run.v1"
ARCHIVE_AUDIT_MAX_ENTRIES = 2_000
ARCHIVE_AUDIT_ENTRY_PREVIEW_LIMIT = 200
ARCHIVE_AUDIT_MAX_TOTAL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
ARCHIVE_AUDIT_EXECUTABLE_SUFFIXES = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".dylib",
    ".exe",
    ".jar",
    ".msi",
    ".ps1",
    ".scr",
    ".sh",
    ".so",
    ".vbs",
}
ARCHIVE_AUDIT_SUPPORTED_SUFFIXES = {
    ".zip",
    ".tar",
    ".tgz",
    ".tar.gz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
}
ARCHIVE_AUDIT_RECURSIVE_SUFFIXES = tuple(
    sorted(
        {
            *ARCHIVE_AUDIT_SUPPORTED_SUFFIXES,
            ".7z",
            ".rar",
            ".gz",
            ".bz2",
            ".xz",
        },
        key=len,
        reverse=True,
    )
)
SKILL_MANIFEST_POLICY = "trainer.resource_sandbox.skill_manifest.v1"
SKILL_MANIFEST_NAMES = (
    "skill.json",
    "skill.toml",
    "skill.yaml",
    "skill.yml",
    "manifest.json",
    "plugin.json",
    "package.json",
    "SKILL.md",
)
SKILL_SCRIPT_SUFFIXES = {
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".py",
    ".rb",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".cmd",
}
SKILL_BLOCKING_CATEGORIES = {
    "prompt_injection",
    "credential_access",
    "network_exfiltration",
    "supply_chain",
    "path_escape",
}
SKILL_RUNTIME_POLICY = "trainer.resource_sandbox.skill_runtime.v1"
SKILL_RUN_GATE_POLICY = "trainer.resource_sandbox.skill_run_gate.v1"
SKILL_EGRESS_ENFORCEMENT_POLICY = "trainer.resource_sandbox.skill_egress_enforcement.v1"
SKILL_EGRESS_REASON_NOT_EVALUATED = ""
SKILL_EGRESS_REASON_DRY_RUN_DEFERRED = "network_egress_enforcement_missing"
SKILL_EGRESS_REASON_GENERAL_MISSING = "network_egress_enforcement_missing"
SKILL_EGRESS_REASON_NON_PYTHON = "network_egress_non_python_entrypoint"
SKILL_EGRESS_REASON_UNAUDITED = "network_egress_unaudited_command_path"
SKILL_EGRESS_REASON_UNSUPPORTED_NODE_GUARD = "network_egress_unsupported_node_entrypoint"
SKILL_EGRESS_REASON_OS_CONTAINER_REQUIRED = "network_egress_requires_os_container_executor"
SKILL_EGRESS_REASON_OS_CONTAINER_UNAVAILABLE = "network_egress_os_container_executor_unavailable"
SKILL_EGRESS_REASON_OS_CONTAINER_RUNTIME_MISSING = "network_egress_os_container_runtime_missing"
SKILL_EGRESS_REASON_OS_CONTAINER_DAEMON_UNREACHABLE = "network_egress_os_container_daemon_unreachable"
SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_MISSING = "network_egress_os_container_image_missing"
SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_UNTRUSTED = "network_egress_os_container_image_untrusted"
SKILL_EGRESS_REASON_OS_CONTAINER_EXECUTOR_NOT_IMPLEMENTED = "network_egress_os_container_executor_not_implemented"
SKILL_EGRESS_REASON_OS_CONTAINER_PROBE_FAILED = "network_egress_os_container_probe_failed"
SKILL_EGRESS_ENFORCEMENT_MISSING_REASON = (
    "Egress enforcement missing: skill isolated executor blocks network-enabled runtime policies "
    "until per-run egress enforcement exists."
)
SKILL_EGRESS_OS_CONTAINER_REQUIRED_REASON = (
    "Network execution is blocked because this runtime policy requires OS/container-level per-run egress "
    "isolation, and Trainer currently only supports narrow guarded execution for audited Python or Node.js "
    "entry scripts."
)
SKILL_EGRESS_OS_CONTAINER_UNAVAILABLE_REASON = (
    "OS/container-level per-run egress isolation is not available in the current Trainer sandbox runtime, so "
    "this network-enabled skill run cannot be executed yet."
)
SKILL_EGRESS_OS_CONTAINER_RUNTIME_MISSING_REASON = (
    "OS/container-level per-run egress isolation is unavailable because no supported container runtime "
    "(Docker or Podman) was found on the current host."
)
SKILL_EGRESS_OS_CONTAINER_DAEMON_UNREACHABLE_REASON = (
    "OS/container-level per-run egress isolation is unavailable because a supported container runtime was found, "
    "but its daemon/service is not reachable from the current Trainer host."
)
SKILL_EGRESS_OS_CONTAINER_IMAGE_MISSING_REASON = (
    "OS/container-level per-run egress isolation is unavailable because the required audited Ruby or Node.js "
    "executor image is not available locally in the detected container runtime."
)
SKILL_EGRESS_OS_CONTAINER_IMAGE_UNTRUSTED_REASON = (
    "OS/container-level per-run egress isolation is unavailable because the required audited Ruby or Node.js "
    "executor image does not match Trainer's trusted image policy."
)
SKILL_EGRESS_OS_CONTAINER_EXECUTOR_NOT_IMPLEMENTED_REASON = (
    "A supported container runtime is reachable, but Trainer has not yet wired a verified os_container_egress "
    "executor on top of it, so general network-enabled skill runs remain blocked."
)
SKILL_EGRESS_OS_CONTAINER_PROBE_FAILED_REASON = (
    "OS/container-level per-run egress isolation could not be verified because probing the host container runtime failed."
)
SKILL_EGRESS_NON_PYTHON_REASON = (
    "Network execution is blocked because only audited argv-only Python or Node.js entry scripts can use "
    "Trainer's narrow per-run guards; other non-Python command templates still require OS/container-level "
    "egress isolation."
)
SKILL_EGRESS_UNAUDITED_REASON = (
    "Network execution is blocked because the runtime command path is not an audited sandbox Python or Node.js "
    "script; per-run guarded egress only applies to preflight-audited entry scripts."
)
SKILL_EGRESS_PYTHON_GUARD_MODE = "python_socket_guard"
SKILL_EGRESS_NODE_GUARD_MODE = "node_socket_guard"
SKILL_EGRESS_PYTHON_GUARD_LIMITATIONS = [
    "Python socket guard only covers audited Python entry scripts launched directly by the isolated skill executor.",
    "The guard only enforces supported direct socket APIs inside that Python subprocess: connect, create_connection, and getaddrinfo.",
    "Low-level socket APIs such as connect_ex and sendto are not granted network execution rights and are blocked during runtime preflight.",
    "Non-Python commands, nested child processes, and OS-level cross-platform network isolation still remain blocked.",
]
SKILL_EGRESS_NODE_GUARD_LIMITATIONS = [
    "Node socket guard only covers audited Node.js entry scripts launched directly by the isolated skill executor.",
    "The guard only patches supported core networking paths inside that Node.js subprocess: dns.lookup, net.Socket.connect, http/https request, fetch, and undici fetch.",
    "Child-process creation, worker-thread fan-out, and alternate runtimes remain blocked by runtime preflight rather than granted by the guard.",
    "OS-level cross-platform network isolation still remains unavailable outside the guarded Node subprocess.",
]
SKILL_EGRESS_OS_CONTAINER_LIMITATIONS = [
    "OS/container-level per-run egress isolation only covers audited argv-only Ruby or Node.js entry scripts launched through Trainer's verified container executors.",
    "The current os/container lanes require a supported Docker or Podman runtime and preloaded local audited images; Trainer does not auto-pull images during skill execution.",
    "Generic non-Python network execution, alternate runtimes, child-process fan-out, and unaudited entrypoints still remain intentionally blocked.",
]
SKILL_EGRESS_OS_CONTAINER_RUBY_IMAGE = os.environ.get("TRAINER_OS_CONTAINER_RUBY_IMAGE", "ruby:3.3-alpine")
SKILL_EGRESS_OS_CONTAINER_NODE_IMAGE = os.environ.get("TRAINER_OS_CONTAINER_NODE_IMAGE", "node:22-alpine")
SKILL_EGRESS_OS_CONTAINER_IMAGE_TRUST_POLICY = "trainer.resource_sandbox.os_container_image_trust.v1"
SKILL_EGRESS_OS_CONTAINER_TRUSTED_REPO_DIGESTS = tuple(
    item.strip()
    for item in os.environ.get("TRAINER_OS_CONTAINER_RUBY_IMAGE_REPO_DIGESTS", "").split(",")
    if item.strip()
)
SKILL_EGRESS_OS_CONTAINER_NODE_TRUSTED_REPO_DIGESTS = tuple(
    item.strip()
    for item in os.environ.get("TRAINER_OS_CONTAINER_NODE_IMAGE_REPO_DIGESTS", "").split(",")
    if item.strip()
)
SKILL_EGRESS_OS_CONTAINER_MODE = "os_container_egress"
SKILL_RUNTIME_MAX_TIMEOUT_MS = 60_000
SKILL_RUNTIME_SAFE_ENV_NAMES = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USER",
    "USERNAME",
    "SYSTEMROOT",
    "WINDIR",
}
SKILL_RUNTIME_BASELINE_ENV_NAMES = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
}
TRAINER_SANDBOX_LAYOUT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("plan", ()),
    ("cards", ("current", "flash", "practice", "scenario", "review")),
    ("knowledge", ("remote", "debug", "function-guidance", "apis")),
    ("sources", ("inbox", "web", "folders")),
    ("notes", ()),
    ("outputs", ()),
)
TRAINER_SANDBOX_MANAGED_ROOTS = tuple(root for root, _children in TRAINER_SANDBOX_LAYOUT)
TRAINER_SANDBOX_SCAFFOLD_PATHS = tuple(
    path
    for root, children in TRAINER_SANDBOX_LAYOUT
    for path in (root, *(f"{root}/{child}" for child in children))
)
TRAINER_SANDBOX_SCAFFOLD_PATH_SET = frozenset(TRAINER_SANDBOX_SCAFFOLD_PATHS)
SKILL_RUNTIME_SECRET_ENV_PATTERN = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|credential|auth|bearer|openai|anthropic|mistral|gemini|azure|aws|gcp|github|gitlab|npm|pypi)",
    re.IGNORECASE,
)
SKILL_RUNTIME_FORBIDDEN_COMMAND_PATTERNS = (
    r"\b(?:bash|sh|zsh|powershell|pwsh|cmd(?:\.exe)?)\b\s*(?:-c|/c)",
    r"\b(?:npm|pnpm|yarn|pip|pipx|poetry|uv|cargo|go)\s+(?:install|add|get|update|upgrade|publish|run)\b",
    r"\b(?:curl|wget|invoke-webrequest|invoke-restmethod|fetch)\b",
    r"\b(?:rm\s+-rf|remove-item|del\s+/s|rmdir\s+/s|mklink|chmod|chown|sudo)\b",
    r"\b(?:eval|exec|invoke-expression|child_process|subprocess)\b",
    r"\b(?:api[_-]?key|token|secret|password|credential|openai|anthropic|gemini|secretstorage|process\.env|os\.environ)\b",
    r"[;&|`$<>]",
)
SKILL_RUNTIME_INLINE_EXECUTION_FLAGS = {"-c", "/c", "-m", "-e", "--eval"}
SKILL_RUNTIME_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")
SKILL_RUNTIME_NETWORK_INTENT_PATTERNS = (
    r"\b(?:requests|httpx|urllib(?:\.request)?|aiohttp)\s*\.",
    r"\b(?:fetch|axios)\s*\(",
    r"\b(?:socket|http\.client|https?)\b",
    r"\b(?:net::http|open-uri|uri\.open|tcpsocket|socket\.tcp|addrinfo)\b",
    r"\b(?:curl|wget|invoke-webrequest|invoke-restmethod)\b",
    r"\bhttps?://",
)
SKILL_RUNTIME_UNSUPPORTED_PYTHON_SOCKET_PATTERNS = (
    r"\bconnect_ex\s*\(",
    r"\bsendto\s*\(",
)
SKILL_RUNTIME_UNSUPPORTED_NODE_SOCKET_PATTERNS = (
    r"\bchild_process\.",
    r"\bworker_threads\b",
    r"\bcluster\b",
)
SKILL_RUNTIME_UNSUPPORTED_RUBY_SOCKET_PATTERNS = (
    r"\budpsocket\b",
    r"\bunixsocket\b",
    r"\bsocket\.(?:new|pair|socketpair)\b",
    r"\bconnect_nonblock\b",
    r"\bsendmsg\b",
    r"\brecvfrom\b",
)
SKILL_RUNTIME_CHILD_PROCESS_ESCAPE_PATTERNS = (
    r"\bos\.(?:system|popen|startfile|posix_spawn|posix_spawnp|spawn[a-z_]*|exec[a-z_]*)\b",
    r"\bsubprocess\.(?:Popen|run|call|check_call|check_output|getoutput|getstatusoutput)\b",
    r"\basyncio\.create_subprocess_(?:exec|shell)\b",
    r"\bmultiprocessing\.(?:Process|get_context|set_start_method)\b",
    r"\bProcessPoolExecutor\b",
    r"\bpty\.spawn\b",
    r"\b(?:kernel\.)?(?:system|exec|spawn|fork)\s*\(",
    r"\bprocess\.spawn\b",
    r"\bopen3\b",
    r"%x\[[^\]]+\]",
)
SkillFindingCategory = Literal[
    "prompt_injection",
    "malicious_document",
    "credential_access",
    "network_exfiltration",
    "supply_chain",
    "path_escape",
]


class _ArchiveEntryMetadata(TypedDict):
    name: str
    entry_kind: str
    size: int
    link_target: str


class _SkillManifestContract(TypedDict):
    skill_name: str
    requested_permissions: list[str]
    network_allowlist: list[str]
    execution_entrypoints: list[str]


class _TruncatedOutput(TypedDict):
    text: str
    truncated: bool


def _contains_pattern(value: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, value, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns)


@dataclass(slots=True)
class LinkedResourceSnapshot:
    resource_id: str
    path: str
    exists: bool
    node_kind: str
    inode: int | None
    signature: str


@dataclass(slots=True)
class LinkedResourceChange:
    resource_id: str
    previous_path: str
    current_path: str | None
    deleted: bool = False


class SandboxService:
    _STRUCTURED_PREVIEW_READ_LIMIT = 256_000

    def __init__(
        self,
        data_root: Path,
        event_ledger: EventLedgerService | None = None,
        workspace_path_resolver: Any | None = None,
        workspace_sandbox_root_resolver: Callable[..., str | None] | None = None,
        workspace_authority_resolver: Callable[[str], "WorkspaceAuthority | None"] | None = None,
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
        relative_target = self._resource_relative_path(resource)
        if resource.sandbox_path:
            try:
                target_path = self._resolve_within_root(root, resource.sandbox_path, allow_missing=True)
            except ValueError:
                target_path = self._materialize_target(root, relative_target)
            preserve_existing = not force and self._path_exists(target_path)
        else:
            target_path = self._materialize_target(root, relative_target)
            preserve_existing = False
        source_path = self._local_path(resource.source)
        synced = False

        if resource.kind == "url":
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
            except Exception:
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
                    except Exception:
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
                except Exception:
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

    def _execute_skill_run_in_os_container(
        self,
        *,
        root: Path,
        preflight: SandboxSkillRuntimePreflightResult,
        run_id: str,
        egress_decision: SandboxSkillEgressDecision,
    ) -> dict[str, Any]:
        output_paths = [Path(item) for item in preflight.normalized_output_paths]
        if not output_paths:
            raise ValueError("Skill os/container executor requires at least one normalized sandbox output path.")
        plan = egress_decision.container_execution_plan
        probe = egress_decision.required_executor_probe
        if plan is None or probe is None:
            raise ValueError("Skill os/container executor requires a verified container execution plan.")
        if probe.availability != "available" or plan.runtime not in {"docker", "podman"}:
            raise ValueError(self._os_container_block_reason(probe.reason_code, probe))
        if plan.image_trust_status != "trusted":
            raise ValueError(self._os_container_block_reason(SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_UNTRUSTED, probe))
        entry_runtime = plan.selected_entry_runtime
        if entry_runtime not in {"ruby", "node"}:
            raise ValueError("Skill os/container executor requires a supported selected entry runtime.")
        for output_path in output_paths:
            self._validate_runtime_output_path(root, output_path)
        input_path = Path(preflight.path)
        cwd = input_path if self._path_is_dir(input_path) else input_path.parent
        cwd = self._resolve_within_root(root, str(cwd))
        placeholder_values = {
            "resource_path": plan.container_input_path,
            "input_path": plan.container_input_path,
            "output_path": plan.container_output_paths[0],
            "output": plan.container_output_paths[0],
            "sandbox_root": plan.container_root_path,
            "sandbox": plan.container_root_path,
            "cwd": plan.container_workdir,
        }
        environment = self._skill_runtime_environment(preflight.env_whitelist)
        container_guard_file = (
            self._write_ruby_container_egress_guard(root, egress_decision.allowed_hosts)
            if entry_runtime == "ruby"
            else self._write_node_container_egress_guard(root, egress_decision.allowed_hosts)
        )
        command_results: list[SandboxCommandEntry] = []
        operation_log = [
            "preflight_recomputed",
            "preflight_allowed",
            "os_container_executor_started",
            f"os_container_{entry_runtime}_guard_enabled",
        ]
        combined_stdout: list[str] = []
        combined_stderr: list[str] = []
        truncated = False
        exit_code: int | None = 0

        try:
            for index, template in enumerate(preflight.command_templates, start=1):
                inner_argv = self._skill_runtime_command_argv(template, placeholder_values)
                process_argv = [
                    plan.runtime,
                    "run",
                    "--rm",
                    "--network",
                    "bridge",
                    "--workdir",
                    plan.container_workdir,
                    "--volume",
                    self._container_volume_mount_spec(root, plan.container_root_path),
                    "--env",
                    f"TRAINER_EGRESS_ALLOWED_HOSTS={json.dumps(egress_decision.allowed_hosts, ensure_ascii=True)}",
                    "--env",
                    "TRAINER_EGRESS_GUARD_MODE=os_container_egress",
                    *self._container_env_flags(environment),
                ]
                if entry_runtime == "ruby":
                    process_argv.extend(
                        [
                            "--env",
                            f"RUBYOPT=-r{self._container_path(root, container_guard_file, plan.container_root_path)}",
                        ]
                    )
                    process_argv.extend(
                        [
                            plan.container_image or SKILL_EGRESS_OS_CONTAINER_RUBY_IMAGE,
                            *inner_argv,
                        ]
                    )
                else:
                    process_argv.extend(
                        [
                            plan.container_image or SKILL_EGRESS_OS_CONTAINER_NODE_IMAGE,
                            "node",
                            "--require",
                            self._container_path(root, container_guard_file, plan.container_root_path),
                            *inner_argv[1:],
                        ]
                    )
                started_at = datetime.now(UTC).isoformat()
                operation_log.extend([f"os_container_command_{index}_started"])
                try:
                    completed = subprocess.run(
                        process_argv,
                        shell=False,
                        cwd=self._fs_path(root),
                        capture_output=True,
                        text=True,
                        timeout=max(1, int(preflight.timeout_ms or 0)) / 1000,
                    )
                except subprocess.TimeoutExpired as exc:
                    stdout = self._truncate_output(self._subprocess_output_text(exc.stdout))
                    stderr = self._truncate_output(self._subprocess_output_text(exc.stderr))
                    entry = SandboxCommandEntry(
                        id=f"{run_id}-cmd-{index}",
                        command=" ".join(process_argv),
                        cwd=self._fs_path(root),
                        status="timeout",
                        exit_code=None,
                        stdout=str(stdout["text"]),
                        stderr=str(stderr["text"]),
                        started_at=started_at,
                        finished_at=datetime.now(UTC).isoformat(),
                        truncated=True,
                    )
                    command_results.append(entry)
                    operation_log.extend(["os_container_executor_timeout"])
                    combined_stdout.append(entry.stdout)
                    combined_stderr.append(entry.stderr)
                    truncated = True
                    return {
                        "status": "failed",
                        "execution_status": "execution_timeout",
                        "execution_performed": True,
                        "execution_reason": "Skill os/container executor timed out before completion.",
                        "operation_log": operation_log,
                        "command_results": command_results,
                        "execution_cwd": self._fs_path(root),
                        "exit_code": None,
                        "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                        "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                        "truncated": truncated,
                    }

                stdout = self._truncate_output(completed.stdout)
                stderr = self._truncate_output(completed.stderr)
                entry = SandboxCommandEntry(
                    id=f"{run_id}-cmd-{index}",
                    command=" ".join(process_argv),
                    cwd=self._fs_path(root),
                    status="success" if completed.returncode == 0 else "error",
                    exit_code=completed.returncode,
                    stdout=str(stdout["text"]),
                    stderr=str(stderr["text"]),
                    started_at=started_at,
                    finished_at=datetime.now(UTC).isoformat(),
                    truncated=bool(stdout["truncated"] or stderr["truncated"]),
                )
                command_results.append(entry)
                operation_log.extend([f"os_container_command_{index}_{entry.status}"])
                combined_stdout.append(entry.stdout)
                combined_stderr.append(entry.stderr)
                truncated = truncated or entry.truncated
                exit_code = completed.returncode
                if completed.returncode != 0:
                    operation_log.append("os_container_executor_failed")
                    return {
                        "status": "failed",
                        "execution_status": "execution_failed",
                        "execution_performed": True,
                        "execution_reason": "Skill os/container executor finished with a non-zero exit code.",
                        "operation_log": operation_log,
                        "command_results": command_results,
                        "execution_cwd": self._fs_path(root),
                        "exit_code": exit_code,
                        "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                        "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                        "truncated": truncated,
                    }

            try:
                for path in output_paths:
                    self._validate_runtime_output_path(root, path, require_exists=False)
            except ValueError as exc:
                operation_log.extend(["os_container_executor_finished", "runtime_output_escape_blocked"])
                return {
                    "status": "failed",
                    "execution_status": "execution_output_escape",
                    "execution_performed": True,
                    "execution_reason": str(exc),
                    "operation_log": operation_log,
                    "command_results": command_results,
                    "execution_cwd": self._fs_path(root),
                    "exit_code": exit_code,
                    "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                    "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                    "truncated": truncated,
                }

            if not any(self._path_exists(path) for path in output_paths):
                operation_log.extend(["os_container_executor_finished", "expected_output_missing"])
                return {
                    "status": "failed",
                    "execution_status": "execution_output_missing",
                    "execution_performed": True,
                    "execution_reason": "Skill os/container executor finished but did not produce the declared sandbox output.",
                    "operation_log": operation_log,
                    "command_results": command_results,
                    "execution_cwd": self._fs_path(root),
                    "exit_code": exit_code,
                    "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                    "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                    "truncated": truncated,
                }

            operation_log.extend(["os_container_executor_finished", "sandbox_output_written", "skill_run_executed"])
            return {
                "status": "executed",
                "execution_status": "executed",
                "execution_performed": True,
                "execution_reason": "Skill os/container executor completed and wrote declared sandbox output.",
                "operation_log": operation_log,
                "command_results": command_results,
                "execution_cwd": self._fs_path(root),
                "exit_code": exit_code,
                "stdout": "\n".join(item for item in combined_stdout if item).strip(),
                "stderr": "\n".join(item for item in combined_stderr if item).strip(),
                "truncated": truncated,
            }
        finally:
            self._unlink_path(container_guard_file)

    def _validate_runtime_output_path(
        self,
        root: Path,
        output_path: Path,
        *,
        require_exists: bool = False,
    ) -> None:
        root_resolved = root.resolve(strict=False)
        candidate = Path(output_path)
        if not candidate.is_absolute():
            candidate = root_resolved / candidate
        try:
            lexical_relative = candidate.relative_to(root_resolved)
        except ValueError:
            raise ValueError("Skill isolated executor output path escaped the resource sandbox.") from None
        lexical_current = root_resolved
        for part in lexical_relative.parts[:-1]:
            lexical_current = lexical_current / part
            if not lexical_current.exists():
                continue
            if self._path_has_reparse_boundary(lexical_current):
                raise ValueError("Skill isolated executor output path crosses a symlink or junction boundary.")
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            raise ValueError("Skill isolated executor output path escaped the resource sandbox.") from None
        if resolved == root_resolved:
            raise ValueError("Skill isolated executor output path cannot target the sandbox root.")
        if require_exists and not resolved.exists():
            raise FileNotFoundError(f"Skill isolated executor output path does not exist: {resolved}")
        for path in (resolved.parent, *resolved.parents):
            if path == root_resolved:
                return
            if not path.exists():
                continue
            if self._path_has_reparse_boundary(path):
                raise ValueError("Skill isolated executor output path crosses a symlink or junction boundary.")

    def _skill_runtime_environment(self, env_whitelist: list[str]) -> dict[str, str]:
        environment: dict[str, str] = {}
        requested_names = {str(name or "").strip().upper() for name in env_whitelist if str(name or "").strip()}
        for name in sorted({*requested_names, *SKILL_RUNTIME_BASELINE_ENV_NAMES}):
            normalized = str(name or "").strip().upper()
            if not normalized or not self._skill_runtime_env_name_is_allowed(normalized):
                raise ValueError(f"Skill isolated executor rejected runtime env name: {name}")
            value = os.environ.get(normalized)
            if value is not None:
                environment[normalized] = value
        return environment

    def _skill_runtime_command_argv(
        self,
        template: str,
        placeholders: dict[str, str],
    ) -> list[str]:
        command_text = str(template or "").strip()
        if not command_text:
            raise ValueError("Skill isolated executor requires a non-empty declarative command template.")
        if _contains_pattern(command_text, SKILL_RUNTIME_FORBIDDEN_COMMAND_PATTERNS):
            raise ValueError("Skill isolated executor rejected a forbidden runtime command template.")
        inline_execution_reason = self._skill_runtime_inline_execution_reason(command_text)
        if inline_execution_reason:
            raise ValueError(inline_execution_reason)

        def replace(match: re.Match[str]) -> str:
            key = str(match.group(1) or "").strip().lower()
            if key not in placeholders:
                raise ValueError(f"Skill isolated executor does not recognize placeholder '{key}'.")
            return placeholders[key]

        template_argv = shlex.split(command_text, posix=os.name != "nt")
        argv = [
            SKILL_RUNTIME_PLACEHOLDER_PATTERN.sub(replace, item.strip("\"'"))
            for item in template_argv
        ]
        if not argv:
            raise ValueError("Skill isolated executor rendered an empty argv.")
        executable = argv[0].lower()
        if executable in {"bash", "sh", "zsh", "powershell", "pwsh", "cmd", "cmd.exe"}:
            raise ValueError("Skill isolated executor does not allow shell entrypoints.")
        return argv

    def _skill_runtime_inline_execution_reason(self, command_text: str) -> str:
        try:
            argv = shlex.split(str(command_text or ""), posix=os.name != "nt")
        except ValueError:
            argv = re.split(r"\s+", str(command_text or "").strip())
        if not argv:
            return ""
        executable = str(argv[0] or "").strip().strip("\"'")
        if not executable:
            return ""
        executable_name = Path(executable).name.lower()
        if self._is_python_executable_name(executable_name):
            for token in argv[1:]:
                flag = str(token or "").strip()
                if not flag:
                    continue
                if flag in {"-c", "/c", "-m"}:
                    return (
                        "Skill runtime command templates must resolve to audited sandbox file scripts; "
                        "inline or module Python execution is not allowed."
                    )
                if not flag.startswith("-"):
                    break
        if executable_name in {"node", "node.exe"}:
            for token in argv[1:]:
                flag = str(token or "").strip()
                if not flag:
                    continue
                if flag in {"-e", "--eval"}:
                    return (
                        "Skill runtime command templates must resolve to audited sandbox file scripts; "
                        "inline Node.js evaluation is not allowed."
                    )
                if not flag.startswith("-"):
                    break
        return ""

    def _prepare_skill_process_invocation(
        self,
        *,
        root: Path,
        cwd: Path,
        argv: list[str],
        environment: dict[str, str],
        node_guard_file: Path | None = None,
    ) -> tuple[list[str], str | None, list[str]]:
        process_cwd = self._fs_path(cwd)
        process_argv = list(argv)
        invocation_markers: list[str] = []
        if self._is_node_executable_name(process_argv[0]):
            process_argv = self._absolutize_node_entry_script(root=root, cwd=cwd, argv=process_argv)
        if node_guard_file is not None and self._is_node_executable_name(process_argv[0]):
            process_argv = self._inject_node_guard_argv(process_argv, node_guard_file)
            invocation_markers.append("node_socket_guard_preload_enabled")
        if os.name != "nt":
            return process_argv, process_cwd, invocation_markers

        short_cwd = self._windows_short_path(cwd)
        if short_cwd:
            if short_cwd != process_cwd:
                return process_argv, short_cwd, [*invocation_markers, "windows_short_path_cwd_enabled"]
            return process_argv, short_cwd, invocation_markers

        if self._is_python_executable_name(process_argv[0]):
            wrapped = self._wrap_python_command_for_windows_long_path(
                root=root,
                cwd=cwd,
                argv=process_argv,
                environment=environment,
            )
            return wrapped, None, [*invocation_markers, "windows_python_runpath_wrapper_enabled"]
        return process_argv, process_cwd, invocation_markers

    def _wrap_python_command_for_windows_long_path(
        self,
        *,
        root: Path,
        cwd: Path,
        argv: list[str],
        environment: dict[str, str],
    ) -> list[str]:
        script_index: int | None = None
        for index, token in enumerate(argv[1:], start=1):
            cleaned = str(token or "").strip()
            if cleaned and not cleaned.startswith("-") and Path(cleaned).suffix.lower() == ".py":
                script_index = index
                break
        if script_index is None:
            return argv

        script_token = argv[script_index]
        script_candidate = Path(script_token)
        script_path = self._resolve_within_root(
            root,
            str(script_candidate if script_candidate.is_absolute() else cwd / script_candidate),
            allow_missing=False,
        )
        executable = self._resolve_python_command_executable(argv[0], environment)
        wrapper = (
            "import os, runpy, sys; "
            "os.chdir(sys.argv[1]); "
            "script = sys.argv[2]; "
            "display = sys.argv[3]; "
            "sys.argv = [display, *sys.argv[4:]]; "
            "runpy.run_path(script, run_name='__main__')"
        )
        return [
            executable,
            *argv[1:script_index],
            "-c",
            wrapper,
            self._fs_path(cwd),
            self._fs_path(script_path),
            self._fs_path(script_path),
            *argv[script_index + 1 :],
        ]

    def _resolve_python_command_executable(
        self,
        executable: str,
        environment: dict[str, str],
    ) -> str:
        candidate = str(executable or "").strip().strip("\"'")
        if candidate:
            path_candidate = Path(candidate)
            if path_candidate.is_absolute():
                return self._fs_path(path_candidate)
        resolved = shutil.which(candidate, path=environment.get("PATH")) if candidate else None
        if resolved:
            return self._fs_path(Path(resolved))
        return self._fs_path(Path(sys.executable))

    def _inject_node_guard_argv(self, argv: list[str], node_guard_file: Path) -> list[str]:
        if not argv:
            return argv
        preload_path = str(node_guard_file.resolve(strict=False))
        return [argv[0], "--require", preload_path, *argv[1:]]

    def _absolutize_node_entry_script(self, *, root: Path, cwd: Path, argv: list[str]) -> list[str]:
        if len(argv) < 2:
            return argv
        updated = list(argv)
        for index, token in enumerate(updated[1:], start=1):
            cleaned = str(token or "").strip()
            if not cleaned or cleaned.startswith("-"):
                continue
            suffix = Path(cleaned).suffix.lower()
            if suffix not in {".js", ".mjs", ".cjs"}:
                break
            script_candidate = Path(cleaned)
            script_path = self._resolve_within_root(
                root,
                str(script_candidate if script_candidate.is_absolute() else cwd / script_candidate),
                allow_missing=False,
            )
            updated[index] = str(script_path.resolve(strict=False))
            break
        return updated

    def _replace_node_guard_placeholders(
        self,
        argv: list[str],
        replacements: dict[str, str],
    ) -> list[str]:
        if not replacements:
            return argv
        normalized: list[str] = []
        for token in argv:
            replacement = replacements.get(token)
            normalized.append(replacement if replacement is not None else token)
        return normalized

    def _runtime_command_script_findings(
        self,
        *,
        root: Path,
        base_path: Path,
        runtime_policy: SandboxSkillRuntimePolicy,
        source_path: str,
    ) -> list[SandboxSkillManifestFinding]:
        findings: list[SandboxSkillManifestFinding] = []
        for script_path in self._runtime_command_audited_paths(root, base_path, runtime_policy):
            script_text = self._read_text_limited(script_path)
            if not runtime_policy.network_allowlist and _contains_pattern(script_text, SKILL_RUNTIME_NETWORK_INTENT_PATTERNS):
                findings.append(
                    self._skill_finding(
                        "network_exfiltration",
                        "Skill runtime command script contains network primitives but runtime_policy does not declare network_allowlist.",
                        evidence=script_text,
                        source_path=str(script_path),
                    )
                )
            if _contains_pattern(script_text, SKILL_RUNTIME_CHILD_PROCESS_ESCAPE_PATTERNS):
                findings.append(
                    self._skill_finding(
                        "supply_chain",
                        "Skill runtime command script attempts to launch child processes or dynamic execution, which is blocked even inside python_socket_guard.",
                        evidence=script_text,
                        source_path=str(script_path),
                    )
                )
            if runtime_policy.network_allowlist and _contains_pattern(
                script_text,
                SKILL_RUNTIME_UNSUPPORTED_PYTHON_SOCKET_PATTERNS,
            ):
                findings.append(
                    self._skill_finding(
                        "network_exfiltration",
                        "Skill runtime command script uses unsupported low-level socket APIs (connect_ex/sendto) that are not granted network execution rights by python_socket_guard.",
                        evidence=script_text,
                        source_path=str(script_path),
                    )
                )
            if runtime_policy.network_allowlist and _contains_pattern(
                script_text,
                SKILL_RUNTIME_UNSUPPORTED_NODE_SOCKET_PATTERNS,
            ):
                findings.append(
                    self._skill_finding(
                        "network_exfiltration",
                    "Skill runtime command script uses unsupported Node.js escape surfaces (child_process/worker_threads/cluster) that are not granted network execution rights by Trainer's Node.js guards.",
                        evidence=script_text,
                        source_path=str(script_path),
                    )
                )
            if runtime_policy.network_allowlist and script_path.suffix.lower() == ".rb" and _contains_pattern(
                script_text,
                SKILL_RUNTIME_UNSUPPORTED_RUBY_SOCKET_PATTERNS,
            ):
                findings.append(
                    self._skill_finding(
                        "network_exfiltration",
                        "Skill runtime Ruby command script uses unsupported low-level socket APIs that are not granted network execution rights by Trainer's Ruby os/container guard.",
                        evidence=script_text,
                        source_path=str(script_path),
                    )
                )
        return findings

    def _runtime_command_audited_paths(
        self,
        root: Path,
        base_path: Path,
        runtime_policy: SandboxSkillRuntimePolicy,
    ) -> list[Path]:
        candidates: list[Path] = []
        for command in runtime_policy.command_templates:
            if self._skill_runtime_inline_execution_reason(str(command or "").strip()):
                continue
            for token in self._runtime_command_path_tokens(command):
                try:
                    script_path = self._resolve_within_root(root, str(base_path / token), allow_missing=False)
                except (FileNotFoundError, ValueError):
                    continue
                if self._path_is_file(script_path):
                    candidates.append(script_path)
        deduped: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            marker = str(candidate.resolve(strict=False))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(candidate)
        return deduped

    def _runtime_command_path_tokens(self, command: str) -> list[str]:
        tokens: list[str]
        try:
            tokens = shlex.split(str(command or ""), posix=os.name != "nt")
        except ValueError:
            tokens = re.split(r"\s+", str(command or ""))
        script_tokens: list[str] = []
        for token in tokens:
            cleaned = SKILL_RUNTIME_PLACEHOLDER_PATTERN.sub("", token.strip("\"'"))
            if not cleaned:
                continue
            suffix = Path(cleaned).suffix.lower()
            if suffix in SKILL_SCRIPT_SUFFIXES:
                script_tokens.append(cleaned)
        return self._dedupe_strings(script_tokens)

    def _path_has_reparse_boundary(self, path: Path) -> bool:
        try:
            if path.is_symlink():
                return True
            attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        except (FileNotFoundError, OSError):
            return False
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    def _skill_runtime_network_host_is_blocked(self, value: str) -> bool:
        lowered = value.strip().lower()
        if not lowered:
            return False
        if _contains_pattern(
            lowered,
            [
                r"(^|[/:.])(\*|all|any)([/:.]|$)",
                r"0\.0\.0\.0|::|localhost|127\.0\.0\.1|169\.254\.",
                r"10\.\d{1,3}\.|172\.(1[6-9]|2\d|3[0-1])\.|192\.168\.",
                r"file://|ftp://|ssh://|scp://",
            ],
        ):
            return True
        if "*" in lowered:
            return True
        return bool(lowered.startswith(("http://", "//")))

    def _skill_runtime_env_name_is_allowed(self, value: str) -> bool:
        normalized = value.strip().upper()
        if not normalized or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", normalized):
            return False
        if SKILL_RUNTIME_SECRET_ENV_PATTERN.search(normalized):
            return False
        return normalized in SKILL_RUNTIME_SAFE_ENV_NAMES

    def _skill_runtime_output_paths(self, root: Path, output_paths: list[str]) -> list[str]:
        normalized: list[str] = []
        for output_path in output_paths:
            try:
                normalized.append(str(self._resolve_within_root(root, str(output_path or ""), allow_missing=True)))
            except (FileNotFoundError, ValueError):
                continue
        return self._append_unique([], normalized)[:24]

    def _current_platform(self) -> Literal["windows", "macos", "linux"]:
        if os.name == "nt":
            return "windows"
        system = platform.system().lower()
        if system == "darwin":
            return "macos"
        return "linux"

    def _scan_skill_text(self, text: str, *, source_path: str) -> list[SandboxSkillManifestFinding]:
        findings: list[SandboxSkillManifestFinding] = []
        if _contains_pattern(
            text,
            [
                r"\bignore (?:all )?(?:previous|prior|above|system|developer) (?:instructions|rules|prompts)\b",
                r"\bdisregard (?:all )?(?:previous|prior|above|system|developer) (?:instructions|rules|prompts)\b",
                r"\breveal (?:the )?(?:system|developer) (?:prompt|message|instructions)\b",
            ],
        ):
            findings.append(
                self._skill_finding(
                    "prompt_injection",
                    "Skill text attempts to override Trainer instructions or reveal hidden prompts.",
                    evidence=text,
                    source_path=source_path,
                )
            )
        if _contains_pattern(
            text,
            [
                r"\b(process\.env|os\.environ|secretstorage|secret storage|api[_-]?key|access[_-]?token|bearer token)\b",
                r"\b(open|cat|type|get-content).{0,80}(\.env|id_rsa|credentials|secrets)\b",
            ],
        ):
            findings.append(
                self._skill_finding(
                    "credential_access",
                    "Skill text attempts to read environment variables, local credentials, or secret storage.",
                    evidence=text,
                    source_path=source_path,
                )
            )
        if _contains_pattern(
            text,
            [
                r"\b(curl|wget|fetch|axios|requests\.(?:post|put)|invoke-webrequest|invoke-restmethod)\b.{0,160}\b(upload|post|token|secret|env|credential|exfiltrate)\b",
            ],
        ):
            findings.append(
                self._skill_finding(
                    "network_exfiltration",
                    "Skill text includes network egress before an isolated allow/deny policy is enforced.",
                    evidence=text,
                    source_path=source_path,
                )
            )
        if _contains_pattern(
            text,
            [
                r"\b(preinstall|postinstall|npm install|pip install|pnpm install|yarn install)\b",
                r"\b(child_process|subprocess|shell=True|eval\(|exec\(|invoke-expression|bash -c|powershell)\b",
                *SKILL_RUNTIME_CHILD_PROCESS_ESCAPE_PATTERNS,
                r"\b(os\.symlink|symlink\(|mklink|new-item\s+-itemtype\s+(?:symboliclink|junction)|junction)\b",
                r"\b(rm -rf|del /s|remove-item).{0,80}(\*|/|\\|\.)",
            ],
        ):
            findings.append(
                self._skill_finding(
                    "supply_chain",
                    "Skill text includes install hooks, shell execution, or destructive command patterns.",
                    evidence=text,
                    source_path=source_path,
                )
            )
        if _contains_pattern(text, [r"(\.\./|\.\.\\|~[/\\]|/etc/|/var/|c:\\|%userprofile%|/users/)"]):
            findings.append(
                self._skill_finding(
                    "path_escape",
                    "Skill text references paths outside the managed resource sandbox.",
                    evidence=text,
                    source_path=source_path,
                )
            )
        return findings

    def _skill_script_paths(
        self,
        root: Path,
        *,
        target: Path,
        manifest_path: Path,
        execution_entrypoints: list[str],
    ) -> list[Path]:
        base = target if target.is_dir() else manifest_path.parent
        candidates: list[Path] = []
        for entrypoint in execution_entrypoints:
            for token in re.findall(r"[\w./\\-]+\.(?:js|mjs|cjs|ts|tsx|py|sh|bash|zsh|ps1|bat|cmd)", entrypoint, flags=re.IGNORECASE):
                try:
                    candidate = self._resolve_within_root(root, str(base / token), allow_missing=False)
                except (FileNotFoundError, ValueError):
                    continue
                candidates.append(candidate)
        if self._path_exists(base) and self._path_is_dir(base):
            for candidate in sorted(self._iter_paths(base), key=lambda item: str(item).lower()):
                if candidate == base:
                    continue
                if self._path_is_file(candidate) and candidate.suffix.lower() in SKILL_SCRIPT_SUFFIXES:
                    candidates.append(candidate)
                if len(candidates) >= 24:
                    break
        deduped: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            marker = str(candidate.resolve(strict=False))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(candidate)
        return deduped[:24]

    def _skill_finding(
        self,
        category: str,
        reason: str,
        *,
        evidence: str,
        source_path: str,
    ) -> SandboxSkillManifestFinding:
        normalized_category: SkillFindingCategory = "supply_chain"
        if category == "prompt_injection":
            normalized_category = "prompt_injection"
        elif category == "malicious_document":
            normalized_category = "malicious_document"
        elif category == "credential_access":
            normalized_category = "credential_access"
        elif category == "network_exfiltration":
            normalized_category = "network_exfiltration"
        elif category == "path_escape":
            normalized_category = "path_escape"
        return SandboxSkillManifestFinding(
            category=normalized_category,
            severity="blocker",
            reason=reason,
            evidence=self._evidence_excerpt(evidence),
            source_path=source_path,
        )

    def _dedupe_skill_findings(
        self,
        findings: list[SandboxSkillManifestFinding],
    ) -> list[SandboxSkillManifestFinding]:
        deduped: list[SandboxSkillManifestFinding] = []
        seen: set[tuple[str, str, str]] = set()
        for finding in findings:
            marker = (finding.category, finding.reason, finding.source_path)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(finding)
        return deduped[:16]

    def _python_socket_guard_command_paths(
        self,
        root: Path,
        preflight: SandboxSkillRuntimePreflightResult,
    ) -> tuple[list[Path], str]:
        input_path = Path(preflight.path)
        runtime_base_path = input_path if self._path_is_dir(input_path) else input_path.parent
        audited = {
            str(Path(path).resolve(strict=False))
            for path in preflight.audited_paths
            if str(path or "").strip()
        }
        verified: list[Path] = []
        for command in preflight.command_templates:
            try:
                argv = self._skill_runtime_command_argv(
                    command,
                    {
                        "resource_path": str(input_path),
                        "input_path": str(input_path),
                        "output_path": str(root / "__trainer_guard_probe__"),
                        "output": str(root / "__trainer_guard_probe__"),
                        "sandbox_root": str(root),
                        "sandbox": str(root),
                        "cwd": str(runtime_base_path),
                    },
                )
            except ValueError:
                return [], SKILL_EGRESS_REASON_GENERAL_MISSING
            if len(argv) < 2 or not self._is_python_executable_name(argv[0]):
                return [], SKILL_EGRESS_REASON_NON_PYTHON
            script_path: Path | None = None
            for token in argv[1:]:
                cleaned = str(token or "").strip()
                if not cleaned or cleaned.startswith("-") or Path(cleaned).suffix.lower() != ".py":
                    continue
                try:
                    script_path = self._resolve_within_root(
                        root,
                        str(Path(cleaned) if Path(cleaned).is_absolute() else runtime_base_path / cleaned),
                        allow_missing=False,
                    )
                except (FileNotFoundError, ValueError):
                    return [], SKILL_EGRESS_REASON_UNAUDITED
                break
            if script_path is None:
                return [], SKILL_EGRESS_REASON_NON_PYTHON
            if str(script_path.resolve(strict=False)) not in audited:
                return [], SKILL_EGRESS_REASON_UNAUDITED
            verified.append(script_path)
        if len(verified) != len(preflight.command_templates):
            return [], SKILL_EGRESS_REASON_UNAUDITED
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in verified:
            marker = str(path.resolve(strict=False))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(path)
        return deduped, ""

    def _node_socket_guard_command_paths(
        self,
        root: Path,
        preflight: SandboxSkillRuntimePreflightResult,
    ) -> tuple[list[Path], str]:
        input_path = Path(preflight.path)
        runtime_base_path = input_path if self._path_is_dir(input_path) else input_path.parent
        audited = {
            str(Path(path).resolve(strict=False))
            for path in preflight.audited_paths
            if str(path or "").strip()
        }
        verified: list[Path] = []
        for command in preflight.command_templates:
            try:
                argv = self._skill_runtime_command_argv(
                    command,
                    {
                        "resource_path": str(input_path),
                        "input_path": str(input_path),
                        "output_path": str(root / "__trainer_guard_probe__"),
                        "output": str(root / "__trainer_guard_probe__"),
                        "sandbox_root": str(root),
                        "sandbox": str(root),
                        "cwd": str(runtime_base_path),
                    },
                )
            except ValueError:
                return [], SKILL_EGRESS_REASON_GENERAL_MISSING
            if len(argv) < 2 or not self._is_node_executable_name(argv[0]):
                return [], SKILL_EGRESS_REASON_NON_PYTHON
            script_path: Path | None = None
            for token in argv[1:]:
                cleaned = str(token or "").strip()
                if not cleaned or cleaned.startswith("-"):
                    continue
                suffix = Path(cleaned).suffix.lower()
                if suffix not in {".js", ".mjs", ".cjs"}:
                    continue
                try:
                    script_path = self._resolve_within_root(
                        root,
                        str(Path(cleaned) if Path(cleaned).is_absolute() else runtime_base_path / cleaned),
                        allow_missing=False,
                    )
                except (FileNotFoundError, ValueError):
                    return [], SKILL_EGRESS_REASON_UNAUDITED
                break
            if script_path is None:
                return [], SKILL_EGRESS_REASON_UNSUPPORTED_NODE_GUARD
            if str(script_path.resolve(strict=False)) not in audited:
                return [], SKILL_EGRESS_REASON_UNAUDITED
            verified.append(script_path)
        if len(verified) != len(preflight.command_templates):
            return [], SKILL_EGRESS_REASON_UNAUDITED
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in verified:
            marker = str(path.resolve(strict=False))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(path)
        return deduped, ""

    def _is_python_executable_name(self, value: str) -> bool:
        name = Path(str(value or "").strip().strip("\"'")).name.lower()
        return bool(re.fullmatch(r"python(?:3(?:\.\d+)?)?(?:\.exe)?|py(?:\.exe)?", name))

    def _is_node_executable_name(self, value: str) -> bool:
        name = Path(str(value or "").strip().strip("\"'")).name.lower()
        return name in {"node", "node.exe"}

    def _is_ruby_executable_name(self, value: str) -> bool:
        name = Path(str(value or "").strip().strip("\"'")).name.lower()
        return name in {"ruby", "ruby.exe"}

    def _ruby_os_container_command_paths(
        self,
        root: Path,
        preflight: SandboxSkillRuntimePreflightResult,
    ) -> tuple[list[Path], str]:
        input_path = Path(preflight.path)
        runtime_base_path = input_path if self._path_is_dir(input_path) else input_path.parent
        audited = {
            str(Path(path).resolve(strict=False))
            for path in preflight.audited_paths
            if str(path or "").strip()
        }
        verified: list[Path] = []
        for command in preflight.command_templates:
            try:
                argv = self._skill_runtime_command_argv(
                    command,
                    {
                        "resource_path": str(input_path),
                        "input_path": str(input_path),
                        "output_path": str(root / "__trainer_guard_probe__"),
                        "output": str(root / "__trainer_guard_probe__"),
                        "sandbox_root": str(root),
                        "sandbox": str(root),
                        "cwd": str(runtime_base_path),
                    },
                )
            except ValueError:
                return [], SKILL_EGRESS_REASON_GENERAL_MISSING
            if len(argv) < 2 or not self._is_ruby_executable_name(argv[0]):
                return [], SKILL_EGRESS_REASON_NON_PYTHON
            script_path: Path | None = None
            for token in argv[1:]:
                cleaned = str(token or "").strip()
                if not cleaned or cleaned.startswith("-") or Path(cleaned).suffix.lower() != ".rb":
                    continue
                try:
                    script_path = self._resolve_within_root(
                        root,
                        str(Path(cleaned) if Path(cleaned).is_absolute() else runtime_base_path / cleaned),
                        allow_missing=False,
                    )
                except (FileNotFoundError, ValueError):
                    return [], SKILL_EGRESS_REASON_UNAUDITED
                break
            if script_path is None:
                return [], SKILL_EGRESS_REASON_NON_PYTHON
            if str(script_path.resolve(strict=False)) not in audited:
                return [], SKILL_EGRESS_REASON_UNAUDITED
            verified.append(script_path)
        if len(verified) != len(preflight.command_templates):
            return [], SKILL_EGRESS_REASON_UNAUDITED
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in verified:
            marker = str(path.resolve(strict=False))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(path)
        return deduped, ""

    def _node_os_container_command_paths(
        self,
        root: Path,
        preflight: SandboxSkillRuntimePreflightResult,
    ) -> tuple[list[Path], str]:
        input_path = Path(preflight.path)
        runtime_base_path = input_path if self._path_is_dir(input_path) else input_path.parent
        audited = {
            str(Path(path).resolve(strict=False))
            for path in preflight.audited_paths
            if str(path or "").strip()
        }
        verified: list[Path] = []
        for command in preflight.command_templates:
            try:
                argv = self._skill_runtime_command_argv(
                    command,
                    {
                        "resource_path": str(input_path),
                        "input_path": str(input_path),
                        "output_path": str(root / "__trainer_guard_probe__"),
                        "output": str(root / "__trainer_guard_probe__"),
                        "sandbox_root": str(root),
                        "sandbox": str(root),
                        "cwd": str(runtime_base_path),
                    },
                )
            except ValueError:
                return [], SKILL_EGRESS_REASON_GENERAL_MISSING
            if len(argv) < 2 or not self._is_node_executable_name(argv[0]):
                return [], SKILL_EGRESS_REASON_NON_PYTHON
            script_path: Path | None = None
            for token in argv[1:]:
                cleaned = str(token or "").strip()
                if not cleaned or cleaned.startswith("-"):
                    continue
                suffix = Path(cleaned).suffix.lower()
                if suffix not in {".js", ".mjs", ".cjs"}:
                    continue
                try:
                    script_path = self._resolve_within_root(
                        root,
                        str(Path(cleaned) if Path(cleaned).is_absolute() else runtime_base_path / cleaned),
                        allow_missing=False,
                    )
                except (FileNotFoundError, ValueError):
                    return [], SKILL_EGRESS_REASON_UNAUDITED
                break
            if script_path is None:
                return [], SKILL_EGRESS_REASON_UNSUPPORTED_NODE_GUARD
            if str(script_path.resolve(strict=False)) not in audited:
                return [], SKILL_EGRESS_REASON_UNAUDITED
            verified.append(script_path)
        if len(verified) != len(preflight.command_templates):
            return [], SKILL_EGRESS_REASON_UNAUDITED
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in verified:
            marker = str(path.resolve(strict=False))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(path)
        return deduped, ""

    def _write_python_egress_guard(self, root: Path, allowed_hosts: list[str]) -> Path:
        guard_site_dir = self._resolve_within_root(
            root,
            f".trainer-egress-guard-{uuid4().hex}",
            allow_missing=True,
        )
        os.makedirs(self._fs_path(guard_site_dir), mode=0o700, exist_ok=False)
        allowed_literal = json.dumps(
            [str(host or "").strip().lower() for host in allowed_hosts if str(host or "").strip()],
            ensure_ascii=True,
            sort_keys=True,
        )
        self._write_text(
            guard_site_dir / "sitecustomize.py",
            f"""
import ipaddress
import socket
import os
import subprocess

_TRAINER_ALLOWED_HOSTS = set({allowed_literal})
_TRAINER_ALLOWED_IPS = set()
_TRAINER_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_TRAINER_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_TRAINER_ORIGINAL_CONNECT = socket.socket.connect


def _trainer_normalize_host(host):
    if host is None:
        return ""
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            host = host.decode("utf-8", "ignore")
    return str(host).strip().lower().strip("[]")


def _trainer_is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _trainer_block(host):
    normalized = _trainer_normalize_host(host)
    raise PermissionError("Trainer egress guard blocked host " + (normalized or "<unknown>"))


def _trainer_block_process(api):
    raise PermissionError("Trainer egress guard blocked child process creation via " + api)


def _trainer_allow(host):
    normalized = _trainer_normalize_host(host)
    if not normalized:
        _trainer_block(host)
    if normalized in _TRAINER_ALLOWED_HOSTS or normalized in _TRAINER_ALLOWED_IPS:
        return normalized
    if _trainer_is_ip(normalized):
        _trainer_block(host)
    _trainer_block(host)


def _trainer_getaddrinfo(host, port, *args, **kwargs):
    _trainer_allow(host)
    infos = _TRAINER_ORIGINAL_GETADDRINFO(host, port, *args, **kwargs)
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            _TRAINER_ALLOWED_IPS.add(_trainer_normalize_host(sockaddr[0]))
    return infos


def _trainer_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *args, **kwargs):
    _trainer_allow(address[0] if isinstance(address, tuple) and address else address)
    return _TRAINER_ORIGINAL_CREATE_CONNECTION(address, timeout, source_address, *args, **kwargs)


def _trainer_connect(self, address):
    _trainer_allow(address[0] if isinstance(address, tuple) and address else address)
    return _TRAINER_ORIGINAL_CONNECT(self, address)


socket.getaddrinfo = _trainer_getaddrinfo
socket.create_connection = _trainer_create_connection
socket.socket.connect = _trainer_connect
""".lstrip(),
        )
        return guard_site_dir

    def _write_node_egress_guard(self, root: Path, allowed_hosts: list[str]) -> Path:
        guard_file = self._resolve_within_root(
            root,
            f".trainer-node-egress-guard-{uuid4().hex}.cjs",
            allow_missing=True,
        )
        allowed_literal = json.dumps(
            [str(host or "").strip().lower() for host in allowed_hosts if str(host or "").strip()],
            ensure_ascii=True,
            sort_keys=True,
        )
        self._write_text(
            guard_file,
            f"""
const dns = require("node:dns");
const net = require("node:net");
const http = require("node:http");
const https = require("node:https");

const allowedHosts = new Set({allowed_literal});

function normalizeHost(host) {{
  if (host === undefined || host === null) {{
    return "";
  }}
  return String(host).trim().toLowerCase().replace(/^\\[/, "").replace(/\\]$/, "");
}}

function block(host) {{
  const normalized = normalizeHost(host);
  throw new Error("Trainer egress guard blocked host " + (normalized || "<unknown>"));
}}

function allow(host) {{
  const normalized = normalizeHost(host);
  if (!normalized || !allowedHosts.has(normalized)) {{
    block(host);
  }}
  return normalized;
}}

const originalLookup = dns.lookup.bind(dns);
dns.lookup = function patchedLookup(hostname, ...args) {{
  allow(hostname);
  return originalLookup(hostname, ...args);
}};

const originalConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function patchedConnect(...args) {{
  const target = args[0];
  if (typeof target === "object" && target !== null) {{
    allow(target.host || target.hostname);
  }} else if (args.length > 1) {{
    allow(args[1]);
  }}
  return originalConnect.apply(this, args);
}};

function wrapRequest(original) {{
  return function patchedRequest(...args) {{
    const target = args[0];
    if (typeof target === "string") {{
      const parsed = new URL(target);
      allow(parsed.hostname);
    }} else if (target && typeof target === "object") {{
      allow(target.hostname || target.host);
    }}
    return original.apply(this, args);
  }};
}}

http.request = wrapRequest(http.request.bind(http));
https.request = wrapRequest(https.request.bind(https));
http.get = wrapRequest(http.get.bind(http));
https.get = wrapRequest(https.get.bind(https));

if (typeof globalThis.fetch === "function") {{
  const originalFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async function patchedFetch(resource, init) {{
    const url = resource instanceof URL ? resource : new URL(String(resource));
    allow(url.hostname);
    return originalFetch(resource, init);
  }};
}}

globalThis.__TRAINER_NODE_EGRESS_GUARD__ = true;
            """.strip()
            + "\n",
        )
        return guard_file

    def _write_node_container_egress_guard(self, root: Path, allowed_hosts: list[str]) -> Path:
        return self._write_node_egress_guard(root, allowed_hosts)

    def _write_ruby_container_egress_guard(self, root: Path, allowed_hosts: list[str]) -> Path:
        guard_file = self._resolve_within_root(
            root,
            f".trainer-ruby-egress-guard-{uuid4().hex}.rb",
            allow_missing=True,
        )
        allowed_literal = json.dumps(
            [str(host or "").strip().lower() for host in allowed_hosts if str(host or "").strip()],
            ensure_ascii=True,
            sort_keys=True,
        )
        self._write_text(
            guard_file,
            f"""
require "json"
require "net/http"
require "socket"
require "uri"
require "open-uri"

TRAINER_ALLOWED_HOSTS = JSON.parse(%q({allowed_literal}))
TRAINER_ALLOWED_SET = TRAINER_ALLOWED_HOSTS.to_h {{ |host| [host, true] }}

def trainer_normalize_host(host)
  return "" if host.nil?
  host.to_s.strip.downcase.delete_prefix("[").delete_suffix("]")
end

def trainer_allow!(host)
  normalized = trainer_normalize_host(host)
  raise SecurityError, "Trainer egress guard blocked host <unknown>" if normalized.empty?
  return normalized if TRAINER_ALLOWED_SET[normalized]
  raise SecurityError, "Trainer egress guard blocked host #{{normalized}}"
end

class << TCPSocket
  alias_method :trainer_original_open, :open
  def open(host, *args, **kwargs)
    trainer_allow!(host)
    trainer_original_open(host, *args, **kwargs)
  end
end

class << Socket
  alias_method :trainer_original_tcp, :tcp
  def tcp(host, *args, **kwargs, &block)
    trainer_allow!(host)
    trainer_original_tcp(host, *args, **kwargs, &block)
  end
end

class << Addrinfo
  alias_method :trainer_original_getaddrinfo, :getaddrinfo
  def getaddrinfo(host, *args)
    trainer_allow!(host)
    trainer_original_getaddrinfo(host, *args)
  end
end

module TrainerGuardedNetHTTP
  def connect
    trainer_allow!(address)
    super
  end
end

Net::HTTP.prepend(TrainerGuardedNetHTTP)

module TrainerGuardedURIOpen
  def open(*rest, &block)
    trainer_allow!(self.host)
    super
  end
end

URI::HTTP.prepend(TrainerGuardedURIOpen)
URI::HTTPS.prepend(TrainerGuardedURIOpen)
            """.strip()
            + "\n",
        )
        return guard_file

    def _skill_egress_decision(
        self,
        root: Path,
        preflight: SandboxSkillRuntimePreflightResult,
        *,
        dry_run: bool,
    ) -> SandboxSkillEgressDecision:
        os_container_probe = self._probe_os_container_executor()
        os_container_plan = self._os_container_execution_plan(
            root=root,
            preflight=preflight,
            probe=os_container_probe,
        )
        requested_hosts = self._dedupe_strings(preflight.network_allowlist)
        if not preflight.allowed:
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="not_required",
                allowed=True,
                enforcement_available=False,
                requested_hosts=requested_hosts,
                allowed_hosts=[],
                blocked_hosts=[],
                lane="none",
                required_executor="none",
                container_execution_plan=os_container_plan,
                reason_code=SKILL_EGRESS_REASON_NOT_EVALUATED,
                reason="Runtime preflight blocked before egress enforcement was evaluated; no command ran.",
                operation_log=["egress_not_evaluated_preflight_blocked"],
            )

        if not requested_hosts:
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="not_required",
                allowed=True,
                enforcement_available=False,
                requested_hosts=[],
                allowed_hosts=[],
                blocked_hosts=[],
                lane="none",
                required_executor="none",
                container_execution_plan=os_container_plan,
                reason_code=SKILL_EGRESS_REASON_NOT_EVALUATED,
                reason="No network egress was requested by this skill runtime policy.",
                operation_log=["egress_not_required"],
            )

        python_verified_command_paths, python_block_reason_code = self._python_socket_guard_command_paths(
            root,
            preflight,
        )
        if dry_run and python_verified_command_paths:
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="dry_run_deferred",
                allowed=True,
                enforcement_available=False,
                requested_hosts=requested_hosts,
                allowed_hosts=requested_hosts,
                blocked_hosts=[],
                enforcement_mode=SKILL_EGRESS_PYTHON_GUARD_MODE,
                verified_command_paths=[str(path) for path in python_verified_command_paths],
                lane="audited_python",
                required_executor="python_socket_guard",
                required_executor_probe=os_container_probe,
                container_execution_plan=os_container_plan,
                limitations=list(SKILL_EGRESS_PYTHON_GUARD_LIMITATIONS),
                reason_code=SKILL_EGRESS_REASON_DRY_RUN_DEFERRED,
                reason=(
                    "Dry-run verified that audited Python command scripts could enter Trainer's per-run "
                    "Python socket guard, but no real network execution right was granted and no command ran."
                ),
                operation_log=["egress_declared", "egress_python_socket_guard_verified", "egress_dry_run_deferred"],
            )
        if python_verified_command_paths:
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="allowed",
                allowed=True,
                enforcement_available=True,
                requested_hosts=requested_hosts,
                allowed_hosts=requested_hosts,
                blocked_hosts=[],
                enforcement_mode=SKILL_EGRESS_PYTHON_GUARD_MODE,
                verified_command_paths=[str(path) for path in python_verified_command_paths],
                lane="audited_python",
                required_executor="python_socket_guard",
                required_executor_probe=os_container_probe,
                container_execution_plan=os_container_plan,
                limitations=list(SKILL_EGRESS_PYTHON_GUARD_LIMITATIONS),
                reason_code=SKILL_EGRESS_REASON_NOT_EVALUATED,
                reason=(
                    "Network egress is allowed only for audited Python command scripts through "
                    "Trainer's per-run Python socket guard."
                ),
                operation_log=["egress_declared", "egress_python_socket_guard_allowed"],
            )

        ruby_verified_command_paths, ruby_block_reason_code = self._ruby_os_container_command_paths(root, preflight)
        node_container_verified_command_paths, node_container_block_reason_code = self._node_os_container_command_paths(
            root,
            preflight,
        )
        node_verified_command_paths: list[Path] = []
        node_block_reason_code = ""
        ruby_executor_supported = (
            os_container_probe.availability == "available" and "ruby" in os_container_probe.supported_entry_runtimes
        )
        node_executor_supported = (
            os_container_probe.availability == "available" and "node" in os_container_probe.supported_entry_runtimes
        )
        if not node_executor_supported:
            node_verified_command_paths, node_block_reason_code = self._node_socket_guard_command_paths(root, preflight)
            if dry_run and node_verified_command_paths:
                return SandboxSkillEgressDecision(
                    policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                    status="dry_run_deferred",
                    allowed=True,
                    enforcement_available=False,
                    requested_hosts=requested_hosts,
                    allowed_hosts=requested_hosts,
                    blocked_hosts=[],
                    enforcement_mode=SKILL_EGRESS_NODE_GUARD_MODE,
                    verified_command_paths=[str(path) for path in node_verified_command_paths],
                    lane="non_python",
                    required_executor="node_socket_guard",
                    required_executor_probe=os_container_probe,
                    container_execution_plan=os_container_plan,
                    limitations=list(SKILL_EGRESS_NODE_GUARD_LIMITATIONS),
                    reason_code=SKILL_EGRESS_REASON_DRY_RUN_DEFERRED,
                    reason=(
                        "Dry-run verified that audited Node.js command scripts could enter Trainer's per-run "
                        "Node socket guard, but no real network execution right was granted and no command ran."
                    ),
                    operation_log=["egress_declared", "egress_node_socket_guard_verified", "egress_dry_run_deferred"],
                )
            if node_verified_command_paths:
                return SandboxSkillEgressDecision(
                    policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                    status="allowed",
                    allowed=True,
                    enforcement_available=True,
                    requested_hosts=requested_hosts,
                    allowed_hosts=requested_hosts,
                    blocked_hosts=[],
                    enforcement_mode=SKILL_EGRESS_NODE_GUARD_MODE,
                    verified_command_paths=[str(path) for path in node_verified_command_paths],
                    lane="non_python",
                    required_executor="node_socket_guard",
                    required_executor_probe=os_container_probe,
                    container_execution_plan=os_container_plan,
                    limitations=list(SKILL_EGRESS_NODE_GUARD_LIMITATIONS),
                    reason_code=SKILL_EGRESS_REASON_NOT_EVALUATED,
                    reason=(
                        "Network egress is allowed only for audited Node.js command scripts through "
                        "Trainer's per-run Node socket guard."
                    ),
                    operation_log=["egress_declared", "egress_node_socket_guard_allowed"],
                )
        request_scope_os_container_block_reason_code = self._select_egress_block_reason_code(
            python_block_reason_code,
            node_block_reason_code or node_container_block_reason_code,
            ruby_block_reason_code,
        )
        if ruby_verified_command_paths:
            os_container_plan = self._os_container_plan_for_request(
                os_container_plan,
                probe=os_container_probe,
                supported_by_executor=ruby_executor_supported,
                block_reason_code="" if ruby_executor_supported else SKILL_EGRESS_REASON_OS_CONTAINER_REQUIRED,
                selected_entry_runtime="ruby",
            )
        elif node_container_verified_command_paths:
            os_container_plan = self._os_container_plan_for_request(
                os_container_plan,
                probe=os_container_probe,
                supported_by_executor=node_executor_supported,
                block_reason_code="" if node_executor_supported else SKILL_EGRESS_REASON_OS_CONTAINER_REQUIRED,
                selected_entry_runtime="node",
            )
        else:
            os_container_plan = self._os_container_plan_for_request(
                os_container_plan,
                probe=os_container_probe,
                supported_by_executor=False,
                block_reason_code=request_scope_os_container_block_reason_code,
                selected_entry_runtime="none",
            )
        if dry_run and ruby_verified_command_paths and ruby_executor_supported:
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="dry_run_deferred",
                allowed=True,
                enforcement_available=False,
                requested_hosts=requested_hosts,
                allowed_hosts=requested_hosts,
                blocked_hosts=[],
                enforcement_mode=SKILL_EGRESS_OS_CONTAINER_MODE,
                verified_command_paths=[str(path) for path in ruby_verified_command_paths],
                lane="os_container",
                required_executor="os_container_egress",
                required_executor_probe=os_container_probe,
                container_execution_plan=os_container_plan.model_copy(update={"selected_entry_runtime": "ruby"}),
                limitations=list(SKILL_EGRESS_OS_CONTAINER_LIMITATIONS),
                reason_code=SKILL_EGRESS_REASON_DRY_RUN_DEFERRED,
                reason=(
                    "Dry-run verified that audited Ruby command scripts could enter Trainer's os/container "
                    "egress lane, but no real network execution right was granted and no command ran."
                ),
                operation_log=["egress_declared", "egress_os_container_ruby_verified", "egress_dry_run_deferred"],
            )
        if ruby_verified_command_paths and ruby_executor_supported:
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="allowed",
                allowed=True,
                enforcement_available=True,
                requested_hosts=requested_hosts,
                allowed_hosts=requested_hosts,
                blocked_hosts=[],
                enforcement_mode=SKILL_EGRESS_OS_CONTAINER_MODE,
                verified_command_paths=[str(path) for path in ruby_verified_command_paths],
                lane="os_container",
                required_executor="os_container_egress",
                required_executor_probe=os_container_probe,
                container_execution_plan=os_container_plan.model_copy(update={"selected_entry_runtime": "ruby"}),
                limitations=list(SKILL_EGRESS_OS_CONTAINER_LIMITATIONS),
                reason_code=SKILL_EGRESS_REASON_NOT_EVALUATED,
                reason=(
                    "Network egress is allowed only for audited Ruby command scripts through Trainer's "
                    "verified os/container executor."
                ),
                operation_log=["egress_declared", "egress_os_container_ruby_allowed"],
            )
        if dry_run and node_container_verified_command_paths and node_executor_supported:
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="dry_run_deferred",
                allowed=True,
                enforcement_available=False,
                requested_hosts=requested_hosts,
                allowed_hosts=requested_hosts,
                blocked_hosts=[],
                enforcement_mode=SKILL_EGRESS_OS_CONTAINER_MODE,
                verified_command_paths=[str(path) for path in node_container_verified_command_paths],
                lane="os_container",
                required_executor="os_container_egress",
                required_executor_probe=os_container_probe,
                container_execution_plan=os_container_plan.model_copy(update={"selected_entry_runtime": "node"}),
                limitations=list(SKILL_EGRESS_OS_CONTAINER_LIMITATIONS),
                reason_code=SKILL_EGRESS_REASON_DRY_RUN_DEFERRED,
                reason=(
                    "Dry-run verified that audited Node.js command scripts could enter Trainer's os/container "
                    "egress lane, but no real network execution right was granted and no command ran."
                ),
                operation_log=["egress_declared", "egress_os_container_node_verified", "egress_dry_run_deferred"],
            )
        if node_container_verified_command_paths and node_executor_supported:
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="allowed",
                allowed=True,
                enforcement_available=True,
                requested_hosts=requested_hosts,
                allowed_hosts=requested_hosts,
                blocked_hosts=[],
                enforcement_mode=SKILL_EGRESS_OS_CONTAINER_MODE,
                verified_command_paths=[str(path) for path in node_container_verified_command_paths],
                lane="os_container",
                required_executor="os_container_egress",
                required_executor_probe=os_container_probe,
                container_execution_plan=os_container_plan.model_copy(update={"selected_entry_runtime": "node"}),
                limitations=list(SKILL_EGRESS_OS_CONTAINER_LIMITATIONS),
                reason_code=SKILL_EGRESS_REASON_NOT_EVALUATED,
                reason=(
                    "Network egress is allowed only for audited Node.js command scripts through Trainer's "
                    "verified os/container executor."
                ),
                operation_log=["egress_declared", "egress_os_container_node_allowed"],
            )

        if dry_run and os_container_plan.status != "planned_blocked":
            return SandboxSkillEgressDecision(
                policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
                status="dry_run_deferred",
                allowed=True,
                enforcement_available=False,
                requested_hosts=requested_hosts,
                allowed_hosts=requested_hosts,
                blocked_hosts=[],
                lane="os_container",
                required_executor="os_container_egress",
                required_executor_probe=os_container_probe,
                container_execution_plan=os_container_plan,
                reason_code=SKILL_EGRESS_REASON_DRY_RUN_DEFERRED,
                reason=(
                    "Dry-run validated the declared egress allowlist structurally, but no real network "
                    "execution right was granted and no command ran."
                ),
                operation_log=["egress_declared", "egress_dry_run_deferred"],
            )

        block_reason_code = request_scope_os_container_block_reason_code

        lane: Literal["none", "audited_python", "unaudited_python", "non_python", "child_process", "os_container"] = (
            "os_container"
        )
        required_executor: Literal["none", "python_socket_guard", "node_socket_guard", "os_container_egress"] = (
            "os_container_egress"
        )
        block_reason_code = self._normalize_os_container_block_reason_code(
            block_reason_code,
            os_container_probe,
        )
        blocked_reason = self._os_container_block_reason(block_reason_code, os_container_probe)
        if block_reason_code == SKILL_EGRESS_REASON_NON_PYTHON:
            lane = "non_python"
            blocked_reason = self._compose_non_python_block_reason(os_container_probe)
        elif block_reason_code == SKILL_EGRESS_REASON_UNAUDITED:
            lane = "unaudited_python"
            required_executor = "python_socket_guard"
            blocked_reason = SKILL_EGRESS_UNAUDITED_REASON
        elif block_reason_code == SKILL_EGRESS_REASON_UNSUPPORTED_NODE_GUARD:
            lane = "non_python"
            blocked_reason = (
                "Network execution is blocked because the current Node.js request still does not match an audited "
                "argv-only .js/.mjs/.cjs file entry script."
            )
        elif block_reason_code == SKILL_EGRESS_REASON_OS_CONTAINER_REQUIRED:
            blocked_reason = self._compose_os_container_required_reason(os_container_probe)

        return SandboxSkillEgressDecision(
            policy=SKILL_EGRESS_ENFORCEMENT_POLICY,
            status="blocked_missing_enforcement",
            allowed=False,
            enforcement_available=False,
            requested_hosts=requested_hosts,
            allowed_hosts=[],
            blocked_hosts=requested_hosts,
            lane=lane,
            required_executor=required_executor,
            required_executor_probe=os_container_probe,
            container_execution_plan=os_container_plan,
            limitations=[
                *SKILL_EGRESS_PYTHON_GUARD_LIMITATIONS,
                *SKILL_EGRESS_NODE_GUARD_LIMITATIONS,
                *SKILL_EGRESS_OS_CONTAINER_LIMITATIONS,
            ],
            reason_code=block_reason_code or SKILL_EGRESS_REASON_OS_CONTAINER_UNAVAILABLE,
            reason=blocked_reason,
            operation_log=[
                "egress_declared",
                "egress_os_container_executor_required",
                "egress_blocked_missing_enforcement",
            ],
        )

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
        except Exception:
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
