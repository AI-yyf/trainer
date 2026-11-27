from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from ..core.models import (
    SandboxCommandEntry,
    SandboxSkillEgressDecision,
    SandboxSkillManifestFinding,
    SandboxSkillRuntimePolicy,
    SandboxSkillRuntimePreflightResult,
)
from ..core.process_env import SIDECAR_SECRET_ENV_VARS, child_process_environment

if TYPE_CHECKING:
    pass

from .constants import (
    SKILL_EGRESS_ENFORCEMENT_POLICY,
    SKILL_EGRESS_NODE_GUARD_LIMITATIONS,
    SKILL_EGRESS_NODE_GUARD_MODE,
    SKILL_EGRESS_OS_CONTAINER_LIMITATIONS,
    SKILL_EGRESS_OS_CONTAINER_MODE,
    SKILL_EGRESS_OS_CONTAINER_NODE_IMAGE,
    SKILL_EGRESS_OS_CONTAINER_RUBY_IMAGE,
    SKILL_EGRESS_PYTHON_GUARD_LIMITATIONS,
    SKILL_EGRESS_PYTHON_GUARD_MODE,
    SKILL_EGRESS_REASON_DRY_RUN_DEFERRED,
    SKILL_EGRESS_REASON_GENERAL_MISSING,
    SKILL_EGRESS_REASON_NON_PYTHON,
    SKILL_EGRESS_REASON_NOT_EVALUATED,
    SKILL_EGRESS_REASON_OS_CONTAINER_IMAGE_UNTRUSTED,
    SKILL_EGRESS_REASON_OS_CONTAINER_REQUIRED,
    SKILL_EGRESS_REASON_OS_CONTAINER_UNAVAILABLE,
    SKILL_EGRESS_REASON_UNAUDITED,
    SKILL_EGRESS_REASON_UNSUPPORTED_NODE_GUARD,
    SKILL_EGRESS_UNAUDITED_REASON,
    SKILL_RUNTIME_BASELINE_ENV_NAMES,
    SKILL_RUNTIME_CHILD_PROCESS_ESCAPE_PATTERNS,
    SKILL_RUNTIME_FORBIDDEN_COMMAND_PATTERNS,
    SKILL_RUNTIME_NETWORK_INTENT_PATTERNS,
    SKILL_RUNTIME_PLACEHOLDER_PATTERN,
    SKILL_RUNTIME_SAFE_ENV_NAMES,
    SKILL_RUNTIME_SECRET_ENV_PATTERN,
    SKILL_RUNTIME_UNSUPPORTED_NODE_SOCKET_PATTERNS,
    SKILL_RUNTIME_UNSUPPORTED_PYTHON_SOCKET_PATTERNS,
    SKILL_RUNTIME_UNSUPPORTED_RUBY_SOCKET_PATTERNS,
    SKILL_SCRIPT_SUFFIXES,
    SkillFindingCategory,
    _contains_pattern,
)


class EgressAndContainerExecMixin:
    if TYPE_CHECKING:
        _append_unique: Any
        _compose_non_python_block_reason: Any
        _compose_os_container_required_reason: Any
        _container_env_flags: Any
        _container_path: Any
        _container_volume_mount_spec: Any
        _dedupe_strings: Any
        _evidence_excerpt: Any
        _fs_path: Any
        _iter_paths: Any
        _normalize_os_container_block_reason_code: Any
        _os_container_block_reason: Any
        _os_container_execution_plan: Any
        _os_container_plan_for_request: Any
        _path_exists: Any
        _path_is_dir: Any
        _path_is_file: Any
        _probe_os_container_executor: Any
        _read_text_limited: Any
        _resolve_within_root: Any
        _select_egress_block_reason_code: Any
        _subprocess_output_text: Any
        _truncate_output: Any
        _unlink_path: Any
        _windows_short_path: Any
        _write_text: Any

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
                        env=child_process_environment(),
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
            if normalized in SIDECAR_SECRET_ENV_VARS:
                # Even an explicit whitelist entry never hands a skill process
                # the sidecar's own token.
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
