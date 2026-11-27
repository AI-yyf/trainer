from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Literal, TypedDict

if TYPE_CHECKING:
    pass


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
