from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
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
from .models import CheckCommand, CheckResult, CheckStatus, EvaluationRequest, SemanticReview
from .models import EvaluationReport as LaneEvaluationReport


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
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        combined = f"{stdout}\n{stderr}".lower()
        if "uv trampoline failed" in combined or "failed to canonicalize script path" in combined:
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
            return str(candidate_path.resolve(strict=False))

        resolved = shutil.which(candidate)
        if resolved is not None:
            return str(Path(resolved).resolve(strict=False))

        sibling = self._resolve_sibling_console_script(candidate)
        if sibling is not None:
            return str(sibling)

        return None

    def _resolve_sibling_console_script(self, candidate: str) -> Path | None:
        scripts_dir = Path(sys.executable).resolve(strict=False).parent
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


class EvaluationPipeline:
    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        hypothesis_hook: HypothesisHook | None = None,
        semantic_reviewer: SemanticReviewer | None = None,
    ) -> None:
        self._runner = runner or SubprocessCommandRunner()
        self._hypothesis_hook = hypothesis_hook or DefaultHypothesisHook()
        self._semantic_reviewer = semantic_reviewer or DefaultSemanticReviewer()

    def plan_commands(self, request: EvaluationRequest) -> list[CheckCommand]:
        # Absolute target so tools can check a project file while cwd stays sandboxed.
        target = (
            str(Path(request.target_path).resolve())
            if request.target_path
            else "."
        )
        # Fail-closed: never fall back to project parent / os.getcwd() (ruff/pytest
        # caches like .pytest_cache must not land in the learner project).
        cwd = request.workspace
        if not cwd:
            raise ValueError(
                "EvaluationRequest.workspace sandbox cwd is required; "
                "refusing project/os.getcwd() to avoid tool cache side effects."
            )
        pytest_args = list(request.pytest_args) if request.pytest_args else [target]
        if "-p" not in pytest_args:
            pytest_args = [*pytest_args, "-p", "no:cacheprovider"]
        return [
            CheckCommand(name="ruff", argv=["ruff", "check", target], cwd=cwd),
            CheckCommand(name="pyright", argv=["pyright", target], cwd=cwd),
            CheckCommand(
                name="pytest",
                argv=[sys.executable, "-m", "pytest", *pytest_args],
                cwd=cwd,
            ),
        ]

    def evaluate(self, request: EvaluationRequest) -> LaneEvaluationReport:
        # Always own a TemporaryDirectory as tool cwd — ignore any caller workspace
        # that might point at the learner project.
        temp_dir = tempfile.TemporaryDirectory()
        target = request.target_path or "<snippet>"
        code = request.code or ""

        try:
            sandbox = temp_dir.name
            reported_target = target
            if request.target_path is not None:
                # Fail-close: never rewrite the learner project. Copy in-memory
                # content (or the on-disk bytes) into the sandbox and run tools there.
                if not code:
                    code = Path(request.target_path).read_text(encoding="utf-8")
                original_abs = str(Path(request.target_path).resolve())
                sandbox_name = Path(request.target_path).name or "trainer_current_file.py"
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
                )

            checks = [self._runner.run(command) for command in self.plan_commands(request)]
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
    ) -> EvaluationReport:
        training_acceptance_check = self._training_acceptance_check(
            source=request.evaluation_source,
            code=request.content,
            language_id=request.language_id,
            acceptance_criteria=request.acceptance_criteria,
            learner_deliverables=request.learner_deliverables,
            expected_symbols=request.expected_symbols,
        )
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
                    spec,
                    request.task_spec_id,
                    include_default_requirement=not use_training_acceptance_only,
                ),
                target_path=request.file_path,
                code=request.content,
                # cwd sandbox is owned by EvaluationPipeline.evaluate (TemporaryDirectory);
                # never pass the learner project parent (avoids .pytest_cache / pyc writes).
            )
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
                request.evaluation_source == "training"
                and _requires_code_evidence(request.language_id)
            ),
        )

    def evaluate_snippet(
        self,
        request: EvaluateSnippetRequest,
        spec: ApiTaskSpec | None = None,
        *,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> EvaluationReport:
        training_acceptance_check = self._training_acceptance_check(
            source=request.evaluation_source,
            code=request.content,
            language_id=request.language_id,
            acceptance_criteria=request.acceptance_criteria,
            learner_deliverables=request.learner_deliverables,
            expected_symbols=request.expected_symbols,
        )
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
                    spec,
                    request.task_spec_id,
                    include_default_requirement=not use_training_acceptance_only,
                ),
                code=request.content,
            )
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
                request.evaluation_source == "training"
                and _requires_code_evidence(request.language_id)
            ),
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
            if check.name in {"pytest", "hypothesis"}
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
            check.name in {"pytest", "hypothesis"} and check.status == CheckStatus.PASSED
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
            summary = (
                report.semantic_review.summary
                or "The implementation passed the current evaluation loop."
            )
        elif failed_tool_labels:
            summary = f"Evaluation failed on: {', '.join(failed_tool_labels)}."
        elif training_acceptance_blocks:
            summary = "Training practice verification needs current-file evidence for the card acceptance signals."
        elif verification_required:
            summary = "Verification is still required because no dynamic verifier actually ran."
        elif report.missing_requirements:
            summary = "Evaluation found requirement gaps that still need to be implemented."
        else:
            summary = report.semantic_review.summary or "Evaluation found a blocking issue."
        if report.recommendations:
            next_step = report.recommendations[0]
        elif has_error_diagnostics:
            next_step = (
                "Fix the VS Code diagnostics attached to the current file, then re-run evaluation."
            )
        elif (
            training_acceptance_check is not None
            and "No training acceptance criteria" in training_acceptance_check.detail
        ):
            next_step = "Provide concrete acceptance criteria or expected symbols for this practice card, then re-run verification."
        elif training_acceptance_blocks:
            next_step = "Implement the missing practice acceptance signals in the current file, then re-run verification."
        elif verification_required:
            next_step = "Run at least one dynamic verifier, then re-run verification."
        elif failed_tool_labels:
            next_step = "Fix failed checks first, then re-run evaluation."
        elif report.missing_requirements:
            next_step = "Implement the missing requirement signals, then re-run evaluation."
        else:
            next_step = (
                "Tighten the implementation around the first blocker, then re-run evaluation."
            )
        semantic_checks = [
            EvaluationCheck(
                id="semantic-review",
                label="semantic-review",
                status="passed"
                if report.semantic_review.status == CheckStatus.PASSED
                else "failed",
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
    ) -> EvaluationCheck | None:
        if source != "training":
            return None

        criteria = _dedupe_non_empty([*acceptance_criteria, *learner_deliverables])
        symbols = _dedupe_non_empty(expected_symbols)
        if not criteria and not symbols:
            return EvaluationCheck(
                id="training-acceptance",
                label="training-acceptance",
                status="warning",
                detail=(
                    "No training acceptance criteria were supplied with this current-file "
                    "verification, so Trainer cannot mark the practice card as passed."
                ),
            )

        requires_code_evidence = _requires_code_evidence(language_id)
        evidence = _code_evidence_text(code, language_id) if requires_code_evidence else code
        criteria_results = [
            _criterion_result(
                item,
                evidence,
                requires_code_evidence=requires_code_evidence,
                expected_symbols=symbols,
            )
            for item in criteria
        ]
        symbol_results = [
            _expected_symbol_result(
                item,
                evidence,
                requires_code_evidence=requires_code_evidence,
            )
            for item in symbols
        ]
        missing_results = [
            item for item in [*criteria_results, *symbol_results] if item["status"] != "matched"
        ]
        detail_lines = [
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
        ]

        return EvaluationCheck(
            id="training-acceptance",
            label="training-acceptance",
            status="passed" if not missing_results else "failed",
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
        return EvaluationCheck(
            id=check.name, label=check.name, status=status_map[check.status], detail=detail[:1200]
        )


def _convert_spec(
    spec: ApiTaskSpec | None,
    task_spec_id: str | None,
    *,
    include_default_requirement: bool = True,
) -> TaskSpec:
    if spec is None:
        generated = TaskSpec.create(
            title="Trainer task", objective="Validate the current implementation against the task."
        )
        generated.id = task_spec_id or generated.id
        if include_default_requirement:
            generated.requirements = [
                RequirementItem(
                    category="constraint",
                    text="Validate the current implementation against the task.",
                    source="generated",
                )
            ]
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


def _code_evidence_text(source: str, language_id: str | None) -> str:
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
        mask(start, min(index, len(source)))

    return "".join(characters)


def _normalize_code_symbol(value: str) -> str | None:
    normalized = value.strip().strip("`").strip()
    normalized = re.sub(r"\(\s*\)$", "", normalized)
    if not normalized or _CODE_SYMBOL_PATTERN.fullmatch(normalized) is None:
        return None
    return re.sub(r"\s*\.\s*", ".", normalized)


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

    def add(value: str) -> None:
        normalized = _normalize_code_symbol(value)
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


def _criterion_result(
    criterion: str,
    evidence: str,
    *,
    requires_code_evidence: bool,
    expected_symbols: list[str],
) -> dict[str, list[str] | str]:
    if requires_code_evidence:
        signals = _criterion_code_signals(criterion, expected_symbols)
        if not signals:
            return {
                "text": criterion,
                "status": "missing",
                "matched_signals": [],
                "missing_signals": ["a verifiable code symbol or explicit acceptance test"],
            }
        matched_signals = [signal for signal in signals if _matches_code_symbol(signal, evidence)]
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


def _expected_symbol_result(
    symbol: str,
    evidence: str,
    *,
    requires_code_evidence: bool,
) -> dict[str, list[str] | str]:
    normalized = symbol.strip()
    matched = (
        _matches_code_symbol(normalized, evidence)
        if requires_code_evidence
        else bool(normalized and normalized.lower() in evidence.lower())
    )
    return {
        "text": symbol,
        "status": "matched" if matched else "missing",
        "matched_signals": [symbol] if matched else [],
        "missing_signals": [] if matched else [symbol],
    }
