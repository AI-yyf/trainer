from __future__ import annotations

import ast
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, Protocol

from ..core.models import (
    EvaluateCurrentFileRequest,
    EvaluateSnippetRequest,
    EvaluationCheck,
    EvaluationReport,
)
from ..core.models import TaskSpec as ApiTaskSpec
from ..memory.workspace_recovery import live_training_card_title
from ..specs.models import RequirementItem, TaskSpec
from .check_cache import CHECK_RESULT_CACHE
from .models import CheckCommand, CheckResult, CheckStatus, EvaluationRequest, SemanticReview
from .models import EvaluationReport as LaneEvaluationReport
from .verifiers import VerifierPack, verifier_pack_for


def _prefers_chinese(language: str | None) -> bool:
    return bool((language or "").strip().lower().startswith("zh"))


def _localized_text(english: str, chinese: str, language: str | None) -> str:
    """Learner-facing summary/next-step template pick.

    Same convention as ``training.card_generator._localized_text``: zh requests
    get the zh catalog entry, every other (or unknown) locale falls back to the
    English template. The evidence semantics of each sentence stay identical in
    both languages.
    """
    return chinese if _prefers_chinese(language) else english


class CommandRunner(Protocol):
    def run(self, command: CheckCommand) -> CheckResult: ...


class HypothesisHook(Protocol):
    def run(self, request: EvaluationRequest) -> CheckResult: ...


class SemanticReviewer(Protocol):
    def review(self, spec: TaskSpec, code: str, checks: list[CheckResult]) -> SemanticReview: ...


def _normalize_process_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class SubprocessCommandRunner:
    def run(self, command: CheckCommand) -> CheckResult:
        executable = self._resolve_executable(command.argv[0])
        if executable is None:
            return CheckResult(
                name=command.name,
                status=CheckStatus.SKIPPED,
                command=command.argv,
                summary=f"{command.argv[0]} is not installed.",
            )
        argv = [executable, *command.argv[1:]]
        try:
            completed = subprocess.run(
                argv,
                cwd=command.cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _normalize_process_output(getattr(exc, "stdout", None))
            stderr = _normalize_process_output(getattr(exc, "stderr", None))
            return CheckResult(
                name=command.name,
                status=CheckStatus.ERROR,
                command=argv,
                stdout=stdout,
                stderr=stderr,
                summary=f"{command.name} timed out after 60 seconds.",
            )
        except OSError as exc:
            return CheckResult(
                name=command.name,
                status=CheckStatus.ERROR,
                command=argv,
                summary=f"Could not start {command.name}: {exc.strerror or type(exc).__name__}.",
            )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        combined = f"{stdout}\n{stderr}".lower()
        missing_module = (
            command.argv[1:3] == ["-m", command.name]
            and re.search(rf": No module named ['\"]?{re.escape(command.name)}['\"]?\s*$", stderr.strip())
        )
        if missing_module or "uv trampoline failed" in combined or "failed to canonicalize script path" in combined:
            status = CheckStatus.SKIPPED
        elif command.name == "pytest" and _pytest_collected_no_tests(
            completed.returncode,
            stdout,
            stderr,
        ):
            status = CheckStatus.SKIPPED
        else:
            status = CheckStatus.PASSED if completed.returncode == 0 else CheckStatus.FAILED
        summary = (
            stdout.strip().splitlines()[-1]
            if stdout.strip()
            else stderr.strip().splitlines()[-1]
            if stderr.strip()
            else ""
        )
        if completed.returncode != 0:
            errors = [line.strip() for line in stderr.splitlines()
                      if "error:" in line.lower() or ": No module named " in line]
            if errors:
                summary = errors[-1]
        return CheckResult(
            name=command.name,
            status=status,
            command=argv,
            stdout=stdout,
            stderr=stderr,
            exit_code=completed.returncode,
            summary=summary,
        )
    def _resolve_executable(self, executable: str) -> str | None:
        candidate = str(executable or "").strip().strip("\"'")
        if not candidate:
            return None

        candidate_path = Path(candidate)
        if candidate_path.is_absolute():
            # Lexical normalization only: Path.resolve() would follow symlinks,
            # which on POSIX rewrites `.venv/bin/python` (a symlink to the base
            # interpreter) into e.g. `/usr/bin/python3`. The spawned verifier
            # then loses venv membership ("No module named pytest"). abspath
            # keeps the invoked path so the OS-level venv detection applies.
            return os.path.abspath(candidate)

        resolved = shutil.which(candidate)
        if resolved is not None:
            return str(Path(resolved).resolve(strict=False))

        sibling = self._resolve_sibling_console_script(candidate)
        if sibling is not None:
            return str(sibling)

        return None

    def _resolve_sibling_console_script(self, candidate: str) -> Path | None:
        # Keep the invoked interpreter path un-resolved: on POSIX the venv
        # python is a symlink, and resolving it would point the sibling search
        # at the base interpreter's directory (e.g. /usr/bin) instead of the
        # venv bin directory that actually hosts the console scripts.
        scripts_dir = Path(sys.executable).absolute().parent
        sibling_candidates = [scripts_dir / candidate]
        if os.name == "nt" and not Path(candidate).suffix:
            sibling_candidates.append(scripts_dir / f"{candidate}.exe")

        for path in sibling_candidates:
            if path.is_file():
                return path.resolve(strict=False)
        return None


class DefaultHypothesisHook:
    def run(self, request: EvaluationRequest) -> CheckResult:
        del request
        return CheckResult(
            name="hypothesis",
            status=CheckStatus.SKIPPED,
            summary="No Hypothesis hook is configured yet; core API can inject one later.",
        )


class DefaultSemanticReviewer:
    def review(self, spec: TaskSpec, code: str, checks: list[CheckResult]) -> SemanticReview:
        if not spec.requirements:
            return SemanticReview(
                status=CheckStatus.SKIPPED,
                summary="No task requirements were supplied; only the executable checks were evaluated.",
            )
        missing: list[str] = []
        recommendations: list[str] = []
        code_lower = code.lower()
        for requirement in spec.requirements:
            signal = self._keyword_signal(requirement)
            if signal and signal not in code_lower:
                missing.append(requirement.text)
        failed_tools = [
            check.name
            for check in checks
            if check.status in {CheckStatus.FAILED, CheckStatus.ERROR}
        ]
        if failed_tools:
            recommendations.append(f"Resolve failing checks first: {', '.join(failed_tools)}.")
        if missing:
            recommendations.append(
                "Implement the requirement gaps before asking for the full answer."
            )
        status = CheckStatus.PASSED if not missing and not failed_tools else CheckStatus.FAILED
        summary = (
            "Implementation satisfies the available signals."
            if status is CheckStatus.PASSED
            else "Implementation still misses requirement signals."
        )
        return SemanticReview(
            status=status,
            summary=summary,
            missing_requirements=missing,
            recommendations=recommendations,
        )

    def _keyword_signal(self, requirement: RequirementItem) -> str:
        for token in requirement.text.lower().split():
            cleaned = token.strip(".,:;()[]{}'\"")
            if len(cleaned) >= 4:
                return cleaned
        return ""


def default_command_runner() -> CommandRunner:
    """The runner an EvaluationPipeline uses when none is injected.

    Indirection rather than calling ``SubprocessCommandRunner()`` inline: the
    suite replaces *this* to stop spawning real linters for every test, while
    the runner class itself stays directly constructible and directly tested.
    Swapping the class would have silently changed what
    ``tests/test_evaluator.py`` exercises.
    """
    return SubprocessCommandRunner()


_PROJECT_COPY_IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".turbo",
}
_PROJECT_COPY_MAX_FILES = 2000
_PROJECT_COPY_MAX_BYTES = 50 * 1024 * 1024


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _copy_project_to_sandbox(project_root: Path, sandbox: Path) -> bool:
    """Copy a bounded, symlink-free project tree for project-test verification.

    The learner project itself is never written to. The copy exists so a
    training card's `pytest` check can discover the project's own tests while
    the edited file comes from the in-memory editor buffer.
    """
    if not project_root.is_dir():
        return False
    total_files = 0
    total_bytes = 0
    for current, dirs, files in os.walk(project_root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if name not in _PROJECT_COPY_IGNORED_DIRS
            and not (current_path / name).is_symlink()
        ]
        for name in files:
            source = current_path / name
            if source.is_symlink():
                continue
            try:
                file_stat = source.stat()
            except OSError:
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                continue
            total_bytes += file_stat.st_size
            total_files += 1
            if total_files > _PROJECT_COPY_MAX_FILES or total_bytes > _PROJECT_COPY_MAX_BYTES:
                return False
    for current, dirs, files in os.walk(project_root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if name not in _PROJECT_COPY_IGNORED_DIRS
            and not (current_path / name).is_symlink()
        ]
        for name in files:
            source = current_path / name
            if source.is_symlink():
                continue
            try:
                file_stat = source.stat()
            except OSError:
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                continue
            destination = sandbox / source.relative_to(project_root)
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            except OSError:
                return False
    return True


class EvaluationPipeline:
    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        hypothesis_hook: HypothesisHook | None = None,
        semantic_reviewer: SemanticReviewer | None = None,
        verifier_pack: VerifierPack | None = None,
    ) -> None:
        self._runner = runner or default_command_runner()
        self._hypothesis_hook = hypothesis_hook or DefaultHypothesisHook()
        self._semantic_reviewer = semantic_reviewer or DefaultSemanticReviewer()
        # Subject-scoped deterministic check plan (§2.2 verifier registry).
        # Missing/unknown families resolve to the "code" pack, i.e. the exact
        # pre-registry chain; packs never add trust sources, only commands.
        self._verifier_pack = verifier_pack or verifier_pack_for(None)

    def plan_commands(self, request: EvaluationRequest) -> list[CheckCommand]:
        # Delegates to the pack's planner (PythonToolchainPlanner for "code",
        # moved verbatim so behavior is identical). Subclasses/tests may still
        # override this method; the sandbox-cwd fail-closed guard lives inside
        # the planner and propagates.
        return list(self._verifier_pack.command_planner.plan(request))

    def evaluate(self, request: EvaluationRequest) -> LaneEvaluationReport:
        # Always own a TemporaryDirectory as tool cwd — ignore any caller workspace
        # that might point at the learner project.
        temp_dir = tempfile.TemporaryDirectory()
        target_path_value = request.target_path
        target = target_path_value or "<snippet>"
        code = request.code or ""

        try:
            sandbox = temp_dir.name
            reported_target = target
            project_copy = False
            if target_path_value is not None:
                # Fail-close: never rewrite the learner project. Copy in-memory
                # content (or the on-disk bytes) into the sandbox and run tools there.
                if not code:
                    code = Path(target_path_value).read_text(encoding="utf-8")
                original_abs = str(Path(target_path_value).resolve())
                original_target = Path(original_abs)
                project_root_value = request.project_root
                project_root = (
                    Path(project_root_value).resolve()
                    if project_root_value
                    else None
                )
                if (
                    project_root is not None
                    and project_root.is_dir()
                    and _path_is_within(original_target, project_root)
                    and _copy_project_to_sandbox(project_root, Path(sandbox))
                ):
                    # Run the project's own tests against the learner's edited
                    # file inside the bounded sandbox copy. The real project is
                    # never written to.
                    relative_target = original_target.relative_to(project_root)
                    sandbox_file = Path(sandbox) / relative_target
                    sandbox_file.parent.mkdir(parents=True, exist_ok=True)
                    sandbox_file.write_text(code, encoding="utf-8")
                    sandbox_target = str(sandbox_file)
                    request = EvaluationRequest(
                        spec=request.spec,
                        target_path=sandbox_target,
                        code=code,
                        workspace=sandbox,
                        pytest_args=[sandbox],
                        hypothesis_target=request.hypothesis_target,
                        verification_python=request.verification_python,
                    )
                    target = sandbox_target
                    reported_target = original_abs
                    project_copy = True
                if not project_copy:
                    sandbox_name = Path(target_path_value).name or "trainer_current_file.py"
                    sandbox_file = Path(sandbox) / sandbox_name
                    sandbox_file.write_text(code, encoding="utf-8")
                    sandbox_target = str(sandbox_file)
                    request = EvaluationRequest(
                        spec=request.spec,
                        target_path=sandbox_target,
                        code=code,
                        workspace=sandbox,
                        pytest_args=request.pytest_args or [sandbox_target],
                        hypothesis_target=request.hypothesis_target,
                        verification_python=request.verification_python,
                    )
                    target = sandbox_target
                    reported_target = original_abs
            elif request.code is not None:
                # Snippet-only: materialize under TemporaryDirectory, never under the project.
                temp_path = Path(sandbox) / "trainer_snippet.py"
                temp_path.write_text(request.code, encoding="utf-8")
                request = EvaluationRequest(
                    spec=request.spec,
                    target_path=str(temp_path),
                    code=request.code,
                    workspace=sandbox,
                    pytest_args=request.pytest_args,
                    hypothesis_target=request.hypothesis_target,
                    verification_python=request.verification_python,
                )
                target = str(temp_path)
                reported_target = target
            else:
                request = EvaluationRequest(
                    spec=request.spec,
                    target_path=request.target_path,
                    code=code,
                    workspace=sandbox,
                    pytest_args=request.pytest_args,
                    hypothesis_target=request.hypothesis_target,
                    verification_python=request.verification_python,
                )

            # ruff, pyright and pytest are independent processes over the same
            # sandbox. Running them one after another made a single "verify this
            # file" turn cost the *sum* of three cold starts, and pyright alone
            # is 2-4s of Node startup before it looks at a line of code. They do
            # not share state, so overlap them: the turn is now bounded by the
            # slowest tool instead of the sum. Order is preserved by mapping
            # over the plan rather than collecting from the pool.
            planned = self.plan_commands(request)
            # A script may write temporary files. Run it after the independent
            # analysis/test processes, and never reuse a cached execution result.
            commands = [command for command in planned if command.name != "python-script"]
            sandbox = request.workspace or ""
            # Re-verifying an unchanged file must not re-pay three process
            # cold starts, so results are cached by content rather than by the
            # throwaway sandbox path. All-or-nothing: a half-cached report would
            # mix a stale verdict with a fresh one for the same file, which is
            # worse than either being wrong on its own.
            cached_results = [
                CHECK_RESULT_CACHE.get(command, sandbox, self._runner) for command in commands
            ]
            if all(result is not None for result in cached_results):
                checks = [result for result in cached_results if result is not None]
            else:
                # ruff, pyright and pytest are independent processes over the
                # same sandbox. One after another made a single "verify this
                # file" turn cost the *sum* of three cold starts, and pyright
                # alone is 2-4s of Node startup before it reads a line. They
                # share no state, so overlap them: the turn is bounded by the
                # slowest tool instead of the sum. Order is preserved by
                # mapping over the plan rather than collecting from the pool.
                if len(commands) > 1:
                    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
                        checks = list(pool.map(self._runner.run, commands))
                else:
                    checks = [self._runner.run(command) for command in commands]
                for command, result in zip(commands, checks, strict=False):
                    CHECK_RESULT_CACHE.put(command, sandbox, result, self._runner)
            checks.extend(
                self._runner.run(command) for command in planned if command.name == "python-script"
            )
            checks.append(self._hypothesis_hook.run(request))
            semantic_review = self._semantic_reviewer.review(request.spec, code, checks)
            overall_status = self._overall_status(checks, semantic_review)
            return LaneEvaluationReport(
                target=reported_target,
                overall_status=overall_status,
                checks=checks,
                semantic_review=semantic_review,
                missing_requirements=list(semantic_review.missing_requirements),
                recommendations=list(semantic_review.recommendations),
                reflection={
                    "summary": semantic_review.summary,
                    "missing_requirements": list(semantic_review.missing_requirements),
                    "failed_checks": [
                        check.name for check in checks if check.status == CheckStatus.FAILED
                    ],
                },
            )
        finally:
            temp_dir.cleanup()

    def _overall_status(
        self, checks: list[CheckResult], semantic_review: SemanticReview
    ) -> CheckStatus:
        if semantic_review.status in {CheckStatus.FAILED, CheckStatus.ERROR}:
            return CheckStatus.FAILED
        if any(check.status == CheckStatus.ERROR for check in checks):
            return CheckStatus.ERROR
        if any(
            check.status == CheckStatus.FAILED for check in checks if check.name != "hypothesis"
        ):
            return CheckStatus.FAILED
        return CheckStatus.PASSED


class EvaluatorService:
    def __init__(self, pipeline: EvaluationPipeline | None = None) -> None:
        self.pipeline = pipeline or EvaluationPipeline()

    def evaluate_current_file(
        self,
        request: EvaluateCurrentFileRequest,
        spec: ApiTaskSpec | None = None,
        *,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
        response_language: str | None = None,
        project_root: str | None = None,
    ) -> EvaluationReport:
        if spec is not None and request.task_spec_id != spec.id:
            spec = None
        use_training_acceptance_only = _uses_training_acceptance_only(
            source=request.evaluation_source,
            spec=spec,
            acceptance_criteria=request.acceptance_criteria,
            learner_deliverables=request.learner_deliverables,
            expected_symbols=request.expected_symbols,
        )
        report = self.pipeline.evaluate(
            EvaluationRequest(
                spec=_convert_spec(
                    None if use_training_acceptance_only else spec,
                    request.task_spec_id,
                ),
                target_path=request.file_path,
                code=request.content,
                project_root=project_root,
                verification_python=request.verification_python,
                # cwd sandbox is owned by EvaluationPipeline.evaluate (TemporaryDirectory);
                # never pass the learner project parent (avoids .pytest_cache / pyc writes).
            )
        )
        training_acceptance_check = self._training_acceptance_check(
            source=request.evaluation_source,
            code=request.content,
            language_id=request.language_id,
            acceptance_criteria=request.acceptance_criteria,
            learner_deliverables=request.learner_deliverables,
            expected_symbols=request.expected_symbols,
            execution_passed=report.overall_status == CheckStatus.PASSED and any(
                check.name in {"pytest", "hypothesis", "python-script"} and check.status == CheckStatus.PASSED
                for check in report.checks
            ),
            script_stdout=next((
                check.stdout for check in report.checks
                if check.name == "python-script" and check.status == CheckStatus.PASSED
            ), None),
        )
        context_notes = self._evaluation_context_notes(
            source=request.evaluation_source,
            file_path=request.file_path,
            language_id=request.language_id,
            training_card_title=request.training_card_title,
            leftover_plan=leftover_plan,
            leftover_runtime=leftover_runtime,
            leftover_task_title=leftover_task_title,
        )
        return self._to_api_report(
            request.task_spec_id,
            report,
            context_notes=context_notes,
            vscode_diagnostics=request.diagnostics,
            training_acceptance_check=training_acceptance_check,
            requires_dynamic_verification=(
                _requires_code_evidence(request.language_id)
            ),
            response_language=response_language,
        )

    def evaluate_snippet(
        self,
        request: EvaluateSnippetRequest,
        spec: ApiTaskSpec | None = None,
        *,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
        response_language: str | None = None,
    ) -> EvaluationReport:
        if spec is not None and request.task_spec_id != spec.id:
            spec = None
        use_training_acceptance_only = _uses_training_acceptance_only(
            source=request.evaluation_source,
            spec=spec,
            acceptance_criteria=request.acceptance_criteria,
            learner_deliverables=request.learner_deliverables,
            expected_symbols=request.expected_symbols,
        )
        report = self.pipeline.evaluate(
            EvaluationRequest(
                spec=_convert_spec(
                    None if use_training_acceptance_only else spec,
                    request.task_spec_id,
                ),
                code=request.content,
                verification_python=request.verification_python,
            )
        )
        training_acceptance_check = self._training_acceptance_check(
            source=request.evaluation_source,
            code=request.content,
            language_id=request.language_id,
            acceptance_criteria=request.acceptance_criteria,
            learner_deliverables=request.learner_deliverables,
            expected_symbols=request.expected_symbols,
            execution_passed=report.overall_status == CheckStatus.PASSED and any(
                check.name in {"pytest", "hypothesis", "python-script"} and check.status == CheckStatus.PASSED
                for check in report.checks
            ),
            script_stdout=next((
                check.stdout for check in report.checks
                if check.name == "python-script" and check.status == CheckStatus.PASSED
            ), None),
        )
        context_notes = self._evaluation_context_notes(
            source=request.evaluation_source,
            file_path=None,
            language_id=request.language_id,
            training_card_title=request.training_card_title,
            leftover_plan=leftover_plan,
            leftover_runtime=leftover_runtime,
            leftover_task_title=leftover_task_title,
        )
        return self._to_api_report(
            request.task_spec_id,
            report,
            context_notes=context_notes,
            vscode_diagnostics=request.diagnostics,
            training_acceptance_check=training_acceptance_check,
            requires_dynamic_verification=(
                _requires_code_evidence(request.language_id)
            ),
            response_language=response_language,
        )

    def _to_api_report(
        self,
        task_spec_id: str | None,
        report: LaneEvaluationReport,
        *,
        context_notes: list[str] | None = None,
        vscode_diagnostics: list[str] | None = None,
        training_acceptance_check: EvaluationCheck | None = None,
        requires_dynamic_verification: bool = False,
        response_language: str | None = None,
    ) -> EvaluationReport:
        diagnostics = [item.strip() for item in (vscode_diagnostics or []) if item and item.strip()]
        has_error_diagnostics = any(item.lower().startswith("[error]") for item in diagnostics)
        static_checks = [
            self._to_api_check(check)
            for check in report.checks
            if check.name in {"ruff", "pyright"}
        ]
        if diagnostics:
            static_checks.append(
                EvaluationCheck(
                    id="vscode-diagnostics",
                    label="VS Code diagnostics",
                    status="failed" if has_error_diagnostics else "warning",
                    detail="\n".join(diagnostics[:8]),
                )
            )
        dynamic_checks = [
            self._to_api_check(check)
            for check in report.checks
            if check.name in {"pytest", "hypothesis", "python-script"}
        ]
        semantic_detail_lines = [
            *(context_notes or []),
            f"VS Code diagnostics attached: {len(diagnostics)}." if diagnostics else "",
            report.semantic_review.summary.strip(),
            *[item.strip() for item in report.missing_requirements if item and item.strip()],
        ]
        semantic_detail = "\n".join(item for item in semantic_detail_lines if item)
        failed_tool_labels = [
            check.name
            for check in report.checks
            if check.status in {CheckStatus.FAILED, CheckStatus.ERROR}
        ]
        has_dynamic_verification = any(
            check.name in {"pytest", "hypothesis", "python-script"} and check.status == CheckStatus.PASSED
            for check in report.checks
        )
        verification_required = requires_dynamic_verification and not has_dynamic_verification
        if has_error_diagnostics:
            failed_tool_labels.append("vscode-diagnostics")
        training_acceptance_blocks = (
            training_acceptance_check is not None and training_acceptance_check.status != "passed"
        )
        passed = (
            report.overall_status == CheckStatus.PASSED
            and not has_error_diagnostics
            and not training_acceptance_blocks
            and not verification_required
        )
        if passed:
            passed_tools = [check.name for check in report.checks if check.status == CheckStatus.PASSED]
            summary = (
                _localized_text(
                    f"Executable checks passed: {', '.join(passed_tools)}.",
                    f"可执行检查通过：{'、'.join(passed_tools)}。",
                    response_language,
                )
                if passed_tools
                else _localized_text(
                    "The implementation passed the current evaluation loop.",
                    "实现通过了当前评估循环。",
                    response_language,
                )
            )
            if training_acceptance_check is not None:
                summary += _localized_text(
                    " Training acceptance signals matched.",
                    " 训练验收信号已匹配。",
                    response_language,
                )
            if report.semantic_review.status == CheckStatus.PASSED and report.semantic_review.summary:
                summary += f" {report.semantic_review.summary}"
        elif failed_tool_labels:
            summary = _localized_text(
                f"Evaluation failed on: {', '.join(failed_tool_labels)}.",
                f"评估未通过项：{'、'.join(failed_tool_labels)}。",
                response_language,
            )
        elif training_acceptance_blocks:
            acceptance_progress = _acceptance_progress_from_detail(
                training_acceptance_check.detail if training_acceptance_check else ""
            )
            if acceptance_progress is not None:
                matched_count, total_count, missing_preview = acceptance_progress
                summary = _localized_text(
                    f"Training acceptance: {matched_count}/{total_count} acceptance signals matched.",
                    f"训练验收：{matched_count}/{total_count} 个验收信号已匹配。",
                    response_language,
                )
                if missing_preview:
                    summary = _localized_text(
                        f"{summary} Still missing: {missing_preview}.",
                        f"{summary} 仍缺少：{missing_preview}。",
                        response_language,
                    )
                if verification_required:
                    summary += _localized_text(
                        " Verification is still required because no dynamic verifier actually ran.",
                        " 仍需验证：尚无动态验证器实际运行。",
                        response_language,
                    )
            else:
                summary = _localized_text(
                    "Training practice verification needs current-file evidence for the card acceptance signals.",
                    "训练练习验证需要当前文件证据来核对该卡片的验收信号。",
                    response_language,
                )
        elif verification_required:
            summary = _localized_text(
                "Verification is still required because no dynamic verifier actually ran.",
                "仍需验证：尚无动态验证器实际运行。",
                response_language,
            )
        elif report.missing_requirements:
            summary = _localized_text(
                "Evaluation found requirement gaps that still need to be implemented.",
                "评估发现仍有需求缺口需要实现。",
                response_language,
            )
        else:
            summary = report.semantic_review.summary or _localized_text(
                "Evaluation found a blocking issue.",
                "评估发现一个阻塞问题。",
                response_language,
            )
        if passed:
            next_step = _localized_text(
                "Record a reflection on the verified result, then bring it back to Coach.",
                "记录一条针对已验证结果的反思，然后带回 Coach。",
                response_language,
            )
        elif report.recommendations:
            next_step = report.recommendations[0]
        elif has_error_diagnostics:
            next_step = _localized_text(
                "Fix the VS Code diagnostics attached to the current file, then re-run evaluation.",
                "先修复当前文件附带的 VS Code 诊断问题，再重新运行评估。",
                response_language,
            )
        elif (
            training_acceptance_check is not None
            and "No training acceptance criteria" in training_acceptance_check.detail
        ):
            next_step = _localized_text(
                "Provide concrete acceptance criteria or expected symbols for this practice card, then re-run verification.",
                "为这张练习卡提供具体的验收标准或期望符号，然后重新运行验证。",
                response_language,
            )
        elif verification_required:
            next_step = _localized_text(
                "Run at least one dynamic verifier, then re-run verification.",
                "先运行至少一个动态验证器，再重新运行验证。",
                response_language,
            )
        elif training_acceptance_blocks:
            acceptance_progress = _acceptance_progress_from_detail(
                training_acceptance_check.detail if training_acceptance_check else ""
            )
            if acceptance_progress is not None and acceptance_progress[2]:
                first_missing = acceptance_progress[2].split(";")[0].strip()
                next_step = _localized_text(
                    "Implement the missing practice acceptance signals in the current file "
                    f'(starting with "{first_missing}"), then re-run verification.',
                    f"在当前文件中实现缺失的练习验收信号（从“{first_missing}”开始），然后重新运行验证。",
                    response_language,
                )
            else:
                next_step = _localized_text(
                    "Implement the missing practice acceptance signals in the current file, then re-run verification.",
                    "在当前文件中实现缺失的练习验收信号，然后重新运行验证。",
                    response_language,
                )
        elif failed_tool_labels:
            next_step = _localized_text(
                "Fix failed checks first, then re-run evaluation.",
                "先修复未通过的检查，再重新运行评估。",
                response_language,
            )
        elif report.missing_requirements:
            next_step = _localized_text(
                "Implement the missing requirement signals, then re-run evaluation.",
                "先实现缺失的需求信号，再重新运行评估。",
                response_language,
            )
        else:
            next_step = _localized_text(
                "Tighten the implementation around the first blocker, then re-run evaluation.",
                "围绕第一个阻塞点收紧实现，再重新运行评估。",
                response_language,
            )
        semantic_checks = [
            EvaluationCheck(
                id="semantic-review",
                label="semantic-review",
                status="skipped" if report.semantic_review.status == CheckStatus.SKIPPED
                else "passed" if report.semantic_review.status == CheckStatus.PASSED else "failed",
                detail=semantic_detail or report.semantic_review.summary,
            )
        ]
        if training_acceptance_check is not None:
            semantic_checks.append(training_acceptance_check)
        return EvaluationReport(
            task_spec_id=task_spec_id,
            summary=summary,
            static_checks=static_checks,
            dynamic_checks=dynamic_checks,
            semantic_checks=semantic_checks,
            next_step=next_step,
            reflection=report.reflection.get("summary"),
            passed=passed,
        )

    def _evaluation_context_notes(
        self,
        *,
        source: str | None,
        file_path: str | None,
        language_id: str | None,
        training_card_title: str | None,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> list[str]:
        notes: list[str] = []
        if source == "training":
            notes.append("Source: training practice verification.")
        elif source:
            notes.append(f"Source: {source}.")
        leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        live_title = live_training_card_title(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=leftover_task_title,
            card_title=str(training_card_title or "").strip(),
        )
        if live_title:
            notes.append(f"Training card: {live_title}.")
        if file_path:
            language_suffix = f" ({language_id})" if language_id else ""
            notes.append(f"Current file: {file_path}{language_suffix}.")
        elif language_id:
            notes.append(f"Language: {language_id}.")
        return notes

    def _training_acceptance_check(
        self,
        *,
        source: str | None,
        code: str,
        language_id: str | None,
        acceptance_criteria: list[str],
        learner_deliverables: list[str],
        expected_symbols: list[str],
        execution_passed: bool = False,
        script_stdout: str | None = None,
    ) -> EvaluationCheck | None:
        if source != "training":
            return None

        # Explanations, screenshots and reflections are collected by the return
        # flow. They must not become impossible source-code presence checks.
        criteria = _dedupe_non_empty(acceptance_criteria or learner_deliverables)
        all_symbols = _dedupe_non_empty(expected_symbols)
        if not criteria and not all_symbols:
            # No card contract was supplied at all: keep the historical warning,
            # not a hard failure, so generic current-file inspection still works.
            return EvaluationCheck(
                id="training-acceptance",
                label="training-acceptance",
                status="warning",
                detail=(
                    "No training acceptance criteria were supplied with this current-file "
                    "verification, so Trainer cannot mark the practice card as passed."
                ),
            )
        file_references = [item for item in all_symbols if _looks_like_file_reference(item)]
        symbols = [item for item in all_symbols if item not in file_references]
        if not criteria and not symbols:
            # A contract existed, but only as file targets: a file verification
            # cannot pass on the target file alone.
            return EvaluationCheck(
                id="training-acceptance",
                label="training-acceptance",
                status="failed",
                detail=(
                    "This card has no concrete code criterion or code symbol; a file "
                    "verification cannot pass on the target file alone. Use reflection "
                    "or manual verification for an explanation-only card."
                ),
            )

        requires_code_evidence = _requires_code_evidence(language_id)
        evidence = _code_evidence_text(code, language_id) if requires_code_evidence else code
        literal_evidence = (
            _code_evidence_text(code, language_id, mask_strings=False)
            if requires_code_evidence
            else code
        )
        implicit_protocols: set[str] = set()
        python_expressions: set[str] = set()
        if str(language_id or "").lower() in _PYTHON_LANGUAGE_IDS:
            try:
                syntax = ast.parse(code)
            except SyntaxError:
                syntax = None
            if syntax is not None:
                python_expressions = {
                    ast.dump(node, include_attributes=False)
                    for node in ast.walk(syntax)
                    if isinstance(node, _PYTHON_EVIDENCE_EXPRESSIONS)
                    and not isinstance(getattr(node, "ctx", None), ast.Store)
                }
            if syntax is not None and any(
                isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
                for node in ast.walk(syntax)
            ):
                implicit_protocols.add("__setitem__")
        criteria_results = [
            _criterion_result(
                item,
                evidence,
                requires_code_evidence=requires_code_evidence,
                expected_symbols=symbols,
                execution_passed=execution_passed,
                implicit_protocols=implicit_protocols,
                python_expressions=python_expressions,
                script_stdout=script_stdout,
                raw_code=literal_evidence,
                defer_without_signals=(
                    _criterion_is_explanation_only(item)
                    and not _criterion_requires_explicit_evidence(item)
                ),
            )
            for item in criteria
        ]
        symbol_results = [
            _expected_symbol_result(
                item,
                evidence,
                requires_code_evidence=requires_code_evidence,
                python_expressions=python_expressions,
                raw_code=literal_evidence,
            )
            for item in symbols
        ]
        # A criterion such as "verify the result via `queue_lock.py`" names a
        # file target, not a missing code symbol. When that target is the
        # current verified file, the criterion is satisfied. Implementation
        # verbs stay strict so an untouched file cannot pass that way.
        verified_file_references = {item.lower() for item in file_references}
        for result in criteria_results:
            if result["status"] != "missing" or result["matched_signals"]:
                continue
            criterion_text = str(result["text"])
            criterion_files = _criterion_file_references(criterion_text)
            if (
                criterion_files
                and _FILE_VERIFICATION_VERB.search(criterion_text)
                and all(item.lower() in verified_file_references for item in criterion_files)
            ):
                result["status"] = "matched"
                result["matched_signals"] = ["current file target"]
                result["missing_signals"] = []
        deferred_results = [item for item in criteria_results if item["status"] == "deferred"]
        missing_results = [
            item
            for item in [*criteria_results, *symbol_results]
            if item["status"] not in {"matched", "deferred"}
        ]
        total_signals = len(criteria_results) + len(symbol_results)
        matched_signals = total_signals - len(missing_results) - len(deferred_results)
        no_concrete_code_evidence = total_signals > 0 and matched_signals == 0
        detail_lines = [
            f"Acceptance progress: {matched_signals}/{total_signals} acceptance signals matched.",
            f"Acceptance criteria supplied: {len(criteria)}.",
            f"Expected symbols supplied: {len(symbols)}.",
            *[
                f"Matched: {item['text']} ({', '.join(item['matched_signals'])})"
                for item in [*criteria_results, *symbol_results]
                if item["status"] == "matched"
            ],
            *[
                f"Missing: {item['text']} ({', '.join(item['missing_signals'])})"
                for item in missing_results
            ],
            *[
                f"Deferred to reflection: {item['text']}"
                for item in deferred_results
            ],
            *(
                [f"File targets verified as the current file: {', '.join(file_references)}"]
                if file_references else []
            ),
            *(
                ["No concrete code signal matched; deferred explanation alone cannot verify a file."]
                if no_concrete_code_evidence else []
            ),
        ]

        return EvaluationCheck(
            id="training-acceptance",
            label="training-acceptance",
            status="passed" if not missing_results and not no_concrete_code_evidence else "failed",
            detail="\n".join(detail_lines),
        )

    def _to_api_check(self, check: CheckResult) -> EvaluationCheck:
        status_map: dict[
            CheckStatus,
            Literal["passed", "failed", "warning", "skipped"],
        ] = {
            CheckStatus.PASSED: "passed",
            CheckStatus.FAILED: "failed",
            CheckStatus.SKIPPED: "skipped",
            CheckStatus.ERROR: "warning",
            CheckStatus.PENDING: "warning",
        }
        detail = check.summary or check.stderr or check.stdout or "No output."
        if check.name == "python-script" and check.status == CheckStatus.PASSED:
            detail = "Script exited successfully.\n" + (check.stdout.strip() or "No stdout.")
        if check.status in {CheckStatus.FAILED, CheckStatus.ERROR}:
            output = (check.stderr or check.stdout).strip()
            if output and output != detail:
                detail = f"{detail}\n{output[-1000:]}"
        return EvaluationCheck(
            id=check.name, label=check.name, status=status_map[check.status], detail=detail[:1200]
        )


def _convert_spec(
    spec: ApiTaskSpec | None,
    task_spec_id: str | None,
) -> TaskSpec:
    if spec is None:
        generated = TaskSpec.create(
            title="Trainer task", objective="Validate the current implementation against the task."
        )
        generated.id = task_spec_id or generated.id
        # A missing task is not an implicit keyword requirement on the code.
        # The executable checks still run, but cannot establish task completion.
        return generated
    generated = TaskSpec.create(title=spec.title, objective=spec.natural_language_goal)
    generated.id = spec.id
    generated.inputs = list(spec.inputs)
    generated.outputs = list(spec.outputs)
    generated.constraints = list(spec.constraints)
    generated.edge_cases = list(spec.edge_cases)
    generated.failure_conditions = list(spec.failure_conditions)
    generated.requirements = [
        RequirementItem(category="constraint", text=text, source="task_spec")
        for text in spec.constraints
    ] or [
        RequirementItem(category="constraint", text=spec.natural_language_goal, source="task_spec")
    ]
    return generated


def _pytest_collected_no_tests(return_code: int, stdout: str, stderr: str) -> bool:
    if return_code != 5:
        return False
    output = f"{stdout}\n{stderr}".lower()
    return bool(re.search(r"\bno tests (?:ran|collected)\b|\bcollected 0 items\b", output))


def _uses_training_acceptance_only(
    *,
    source: str | None,
    spec: ApiTaskSpec | None,
    acceptance_criteria: list[str],
    learner_deliverables: list[str],
    expected_symbols: list[str],
) -> bool:
    return (
        source == "training"
        and spec is None
        and bool(
            _dedupe_non_empty([*acceptance_criteria, *learner_deliverables])
            or _dedupe_non_empty(expected_symbols)
        )
    )


_TRAINING_SIGNAL_STOPWORDS = {
    "add",
    "and",
    "card",
    "code",
    "current",
    "ensure",
    "file",
    "for",
    "from",
    "implementation",
    "implement",
    "practice",
    "should",
    "that",
    "the",
    "this",
    "trainer",
    "using",
    "verify",
    "with",
    "使用",
    "当前",
    "文件",
    "代码",
    "实现",
    "应该",
    "需要",
}


_NON_CODE_LANGUAGE_IDS = {
    "markdown",
    "md",
    "plaintext",
    "plain-text",
    "text",
    "rst",
    "latex",
    "writing",
    "prose",
}

_PYTHON_LANGUAGE_IDS = {"python", "py", "python3"}
_SLASH_COMMENT_LANGUAGE_IDS = {
    "c",
    "cpp",
    "csharp",
    "cs",
    "css",
    "dart",
    "go",
    "java",
    "javascript",
    "js",
    "jsx",
    "kotlin",
    "php",
    "rust",
    "scala",
    "swift",
    "ts",
    "tsx",
    "typescript",
    "vue",
}
_IDENTIFIER_PATTERN = r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*"
_CODE_SYMBOL_PATTERN = re.compile(rf"{_IDENTIFIER_PATTERN}(?:\s*\.\s*{_IDENTIFIER_PATTERN})*")


def _dedupe_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _acceptance_progress_from_detail(detail: str) -> tuple[int, int, str] | None:
    """Parse "Matched:/Missing:" breakdown lines of a training-acceptance check.

    Returns ``(matched, total, missing_preview)`` where ``missing_preview``
    joins up to three missing signal texts, or ``None`` when the detail does
    not carry an acceptance progress breakdown.
    """
    matched = 0
    missing_texts: list[str] = []
    for raw_line in str(detail or "").splitlines():
        line = raw_line.strip()
        if line.startswith("Matched:"):
            matched += 1
        elif line.startswith("Missing:"):
            text = line[len("Missing:"):].strip()
            text = text.split(" (", 1)[0].strip()
            if text:
                missing_texts.append(text)
    if matched == 0 and not missing_texts:
        return None
    total = matched + len(missing_texts)
    preview = "; ".join(missing_texts[:3])
    return matched, total, preview


def _practice_signals(text: str) -> list[str]:
    raw_tokens = re.findall(r"`[^`]+`|[A-Za-z_][A-Za-z0-9_.$-]*|[\u4e00-\u9fff]{2,}", text)
    signals: list[str] = []
    for token in raw_tokens:
        normalized = token.strip("`._-$").lower()
        if len(normalized) < 3 or normalized in _TRAINING_SIGNAL_STOPWORDS:
            continue
        if normalized not in signals:
            signals.append(normalized)
    return signals[:8]


def _requires_code_evidence(language_id: str | None) -> bool:
    return str(language_id or "").strip().lower() not in _NON_CODE_LANGUAGE_IDS


def _code_evidence_text(
    source: str,
    language_id: str | None,
    *,
    mask_strings: bool = True,
) -> str:
    characters = list(source)
    language = str(language_id or "").strip().lower()
    uses_hash_comments = language not in _SLASH_COMMENT_LANGUAGE_IDS
    uses_slash_comments = language not in _PYTHON_LANGUAGE_IDS
    index = 0

    def mask(start: int, end: int) -> None:
        for position in range(start, end):
            if characters[position] != "\n":
                characters[position] = " "

    while index < len(source):
        if uses_hash_comments and source[index] == "#":
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            mask(index, end)
            index = end
            continue
        if uses_slash_comments and source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            mask(index, end)
            index = end
            continue
        if uses_slash_comments and source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            end = len(source) if closing == -1 else closing + 2
            mask(index, end)
            index = end
            continue

        quote = source[index]
        if quote not in {"'", '"', "`"}:
            index += 1
            continue

        delimiter = (
            quote * 3 if quote in {"'", '"'} and source.startswith(quote * 3, index) else quote
        )
        start = index
        index += len(delimiter)
        while index < len(source):
            if len(delimiter) == 1 and source[index] == "\\":
                index += 2
                continue
            if source.startswith(delimiter, index):
                index += len(delimiter)
                break
            index += 1
        if mask_strings:
            mask(start, min(index, len(source)))

    return "".join(characters)



_PYTHON_EVIDENCE_EXPRESSIONS = (
    ast.Name, ast.Attribute, ast.Subscript, ast.Call, ast.Dict, ast.List, ast.Tuple, ast.Set,
)


def _criterion_output_numbers(criterion: str) -> list[str]:
    """Recognize an explicit numeric stdout requirement; never scan input literals."""
    match = re.search(
        r"(?:\bprint\s+|跑出\s*|输出(?:分别)?(?:为|是|中包含)?\s*|outputs?\s+(?:is\s+|are\s+)?)"
        r"(?P<numbers>-?\d+(?:\.\d+)?(?:\s*[、,，]\s*-?\d+(?:\.\d+)?)*)",
        criterion, re.IGNORECASE,
    )
    return re.split(r"\s*[、,，]\s*", match.group("numbers")) if match else []


def _python_expression_key(value: str) -> str | None:
    """Compare expressions as syntax, never by prose, comments, or string contents."""
    try:
        expression = ast.parse(value.strip().strip("`").strip(), mode="eval").body
    except (SyntaxError, ValueError):
        return None
    if not isinstance(expression, _PYTHON_EVIDENCE_EXPRESSIONS):
        return None
    return ast.dump(expression, include_attributes=False)


def _normalize_code_symbol(value: str) -> str | None:
    normalized = value.strip().strip("`").strip()
    normalized = re.sub(r"\(\s*\)$", "", normalized)
    if not normalized or _CODE_SYMBOL_PATTERN.fullmatch(normalized) is None:
        return None
    return re.sub(r"\s*\.\s*", ".", normalized)


def _matches_string_literal(symbol: str, code: str | None) -> bool:
    """Match an explicit returned string value without trusting comments.

    ``_code_evidence_text`` masks string literals so prose can never satisfy a
    symbol check. Some practice cards legitimately require an exact returned
    string (``"ask_clarification"`` / ``"answer"``). Match those only when the
    identifier appears as a quoted string in the original source.
    """

    if not code:
        return False
    normalized = _normalize_code_symbol(symbol)
    if normalized is None:
        return False
    return bool(
        re.search(
            rf"(['\"]){re.escape(normalized)}\1",
            code,
        )
    )


def _matches_code_symbol(symbol: str, evidence: str) -> bool:
    normalized = _normalize_code_symbol(symbol)
    if normalized is None:
        return False
    pattern = re.escape(normalized).replace(r"\.", r"\s*\.\s*")
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_\u4e00-\u9fff]){pattern}(?![A-Za-z0-9_\u4e00-\u9fff])",
            evidence,
            flags=re.IGNORECASE,
        )
    )


def _criterion_code_signals(criterion: str, expected_symbols: list[str]) -> list[str]:
    signals: list[str] = []
    # File references provide location, not a required function named after
    # the file stem. Mask the complete reference before scanning identifiers.
    criterion = re.sub(r"`(?:python(?:3(?:\.\d+)?)?|py|pytest)\s+[^`]*`", " ", criterion)
    criterion = re.sub(
        r"[A-Za-z0-9_./\\-]+\.(?:py|pyi|js|jsx|ts|tsx|json|md|txt|rs|go|java|cpp|c|cs)\b",
        " ", criterion, flags=re.IGNORECASE,
    )

    def add(value: str) -> None:
        normalized = _normalize_code_symbol(value) or (
            value.strip() if _python_expression_key(value) is not None else None
        )
        if normalized and normalized not in signals:
            signals.append(normalized)

    for literal in re.findall(r"`([^`]+)`", criterion):
        add(literal)
    for symbol in expected_symbols:
        normalized = _normalize_code_symbol(symbol)
        if normalized and _matches_code_symbol(normalized, criterion):
            add(normalized)
    for token in re.findall(_IDENTIFIER_PATTERN, criterion):
        if "_" in token or (
            token[0].islower() and any(character.isupper() for character in token[1:])
        ):
            add(token)
    return signals


def _criterion_is_explanation_only(criterion: str) -> bool:
    """Only explicit explanation prompts may defer to reflection.

    A substantive code requirement without a code signal is a real gap, not a
    reflection item; deferring it would let an untouched file pass.
    """
    if re.search(
        r"实现|修复|补充|添加|编写|创建|优化|更新|完善|"
        r"\bimplement\b|\bfix\b|\badd\b|\bmodify\b|\brefactor\b|"
        r"\bcreate\b|\bupdate\b|\boptimize\b|\bimprove\b|\bwrite\b|\bbuild\b",
        criterion,
        flags=re.IGNORECASE,
    ):
        # An implementation/fix clause must not hide behind an explanation verb.
        return False
    return bool(
        re.search(
            r"解释|说明|为什么|描述|标出|指出|列出|总结|回答|对比|"
            r"记录.*(?:证据|输出)|调试控制台|测试输出|"
            r"\bexplain\b|\bwhy\b|\bdescribe\b|\bidentify\b|\bmark\b|"
            r"\blist\b|\bsummarize\b|\bcompare\b|"
            r"\bdebug console\b|\btest output\b",
            criterion,
            flags=re.IGNORECASE,
        )
    )


def _criterion_requires_explicit_evidence(criterion: str) -> bool:
    """Guardrail claims ("do not modify X") cannot be deferred to reflection."""
    return bool(
        re.search(
            r"不修改|不要修改|未修改|保持不变|不得修改|不要改动|不改动|保留|"
            r"without\s+(?:modifying|changing)|do\s+not\s+(?:modify|change)|"
            r"must\s+not\s+(?:modify|change)|unchanged",
            criterion,
            flags=re.IGNORECASE,
        )
    )


def _criterion_result(
    criterion: str,
    evidence: str,
    *,
    requires_code_evidence: bool,
    expected_symbols: list[str],
    execution_passed: bool = False,
    implicit_protocols: set[str] | None = None,
    python_expressions: set[str] | None = None,
    script_stdout: str | None = None,
    raw_code: str | None = None,
    defer_without_signals: bool = False,
) -> dict[str, list[str] | str]:
    if requires_code_evidence:
        output_numbers = _criterion_output_numbers(criterion)
        signals = _criterion_code_signals(criterion, expected_symbols)
        expects_no_exception = re.search(
            r"\b(?:without|no|not\s+raise)\b|不抛|不触发|无|没有|不得", criterion, re.IGNORECASE,
        )
        execution_signals = (
            [signal for signal in signals if signal.endswith(("Error", "Exception"))]
            if expects_no_exception else []
        )
        code_signals = [signal for signal in signals if signal not in execution_signals]
        if output_numbers:
            signals.append("actual script output")
        if not signals:
            return {
                "text": criterion,
                "status": "deferred" if defer_without_signals else "missing",
                "matched_signals": [],
                "missing_signals": (
                    [] if defer_without_signals
                    else ["a verifiable code symbol or explicit acceptance test"]
                ),
            }
        describes_protocol = bool(re.search(r"\b(?:from|via)\b|来自|对应", criterion, re.IGNORECASE))
        matched_signals = [
            signal for signal in code_signals
            if _matches_code_symbol(signal, evidence)
            or _matches_string_literal(signal, raw_code)
            or _python_expression_key(signal) in (python_expressions or set()) or (
                describes_protocol and signal not in expected_symbols
                and signal in (implicit_protocols or set())
            )
        ]
        if execution_passed:
            matched_signals.extend(execution_signals)
            if output_numbers and script_stdout is not None:
                actual = [line.strip() for line in script_stdout.splitlines() if line.strip()]
                # Require exact numeric lines in order, not matching text inside
                # debug prose or merely present print calls in unexecuted code.
                if any(actual[index:index + len(output_numbers)] == output_numbers
                       for index in range(len(actual) - len(output_numbers) + 1)):
                    matched_signals.append("actual script output")
        return {
            "text": criterion,
            "status": "matched" if len(matched_signals) == len(signals) else "missing",
            "matched_signals": matched_signals,
            "missing_signals": [signal for signal in signals if signal not in matched_signals],
        }

    signals = _practice_signals(criterion)
    evidence_lower = evidence.lower()
    if not signals:
        criterion_lower = criterion.strip().lower()
        matched = bool(criterion_lower and criterion_lower in evidence_lower)
        return {
            "text": criterion,
            "status": "matched" if matched else "missing",
            "matched_signals": [criterion.strip()] if matched else [],
            "missing_signals": [] if matched else [criterion.strip()],
        }
    matched_signals = [signal for signal in signals if signal in evidence_lower]
    return {
        "text": criterion,
        "status": "matched" if len(matched_signals) == len(signals) else "missing",
        "matched_signals": matched_signals,
        "missing_signals": [signal for signal in signals if signal not in matched_signals],
    }


def _looks_like_file_reference(value: str) -> bool:
    text = value.strip().strip("`")
    if not text:
        return False
    if "/" in text or "\\" in text:
        return True
    return bool(
        re.search(
            r"\.(?:py|pyi|js|jsx|ts|tsx|json|md|txt|rs|go|java|cpp|c|cs|sh|html|css)$",
            text,
            flags=re.IGNORECASE,
        )
    )


_FILE_VERIFICATION_VERB = re.compile(
    r"验证|检查|核对|打开|运行|确认|verify|check|confirm|open|run",
    re.IGNORECASE,
)
_FILE_REFERENCE_TOKEN = re.compile(
    r"[A-Za-z0-9_./\\-]+\.(?:py|pyi|js|jsx|ts|tsx|json|md|txt|rs|go|java|cpp|c|cs|sh|html|css)\b",
    re.IGNORECASE,
)


def _criterion_file_references(criterion: str) -> list[str]:
    """File targets named by one acceptance criterion (not code symbols)."""
    references: list[str] = []
    for literal in re.findall(r"`([^`]+)`", criterion):
        text = literal.strip().strip("`")
        if _looks_like_file_reference(text) and text not in references:
            references.append(text)
    for token in _FILE_REFERENCE_TOKEN.findall(criterion):
        if _looks_like_file_reference(token) and token not in references:
            references.append(token)
    return references


def _expected_symbol_result(
    symbol: str,
    evidence: str,
    *,
    requires_code_evidence: bool,
    python_expressions: set[str] | None = None,
    raw_code: str | None = None,
) -> dict[str, list[str] | str]:
    normalized = symbol.strip()
    # Some cards name a statement, not an identifier (`with self._lock`).
    # A statement is verified by the exact normalized code line, not by the
    # identifier-only matcher, otherwise a true option is reported missing.
    statement_match = bool(
        requires_code_evidence
        and re.search(r"\s", normalized)
        and normalized
        and normalized in (raw_code or "")
    )
    matched = (
        (
            _matches_code_symbol(normalized, evidence)
            or _matches_string_literal(normalized, raw_code)
            or statement_match
            or _python_expression_key(normalized) in (python_expressions or set())
        )
        if requires_code_evidence
        else bool(normalized and normalized.lower() in evidence.lower())
    )
    return {
        "text": symbol,
        "status": "matched" if matched else "missing",
        "matched_signals": [symbol] if matched else [],
        "missing_signals": [] if matched else [symbol],
    }
