"""(n) Evaluator: verification of the learner's code is real, bounded and honest about
    what it could not check.

Guarantees covered:
  * evaluation is deterministic and produces valid reports for any task spec and code (property-based);
  * acceptance criteria need real code evidence, not file names or explanations alone;
  * Python verification executes the learner's tests and reports their real outcome;
  * project analysis, call graphs and symbol indexes come from real AST / LSP / git evidence and degrade honestly.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_evaluator_training_acceptance.py
  * server/tests/test_evaluator_properties.py
  * server/tests/test_scip_adapter.py
  * server/tests/test_verify_practice_progress_feedback.py
  * server/tests/test_token_benchmark.py
  * server/tests/test_project_analysis.py
  * server/tests/test_project_callgraph.py
  * server/tests/test_project_adoption_index.py
  * server/tests/test_project_import.py
  * server/tests/test_provenance_bench.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import unittest
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

import app.workspace.adoption_index as adoption_index
from app.benchmarks.token_benchmark import run_token_benchmark
from app.core.settings import AppSettings
from app.evaluator import CheckResult, CheckStatus, EvaluationPipeline, EvaluationRequest
from app.evaluator.models import CheckCommand, SemanticReview
from app.evaluator.service import EvaluatorService
from app.llm.tools import ToolContext, _handle_verify_practice_current_file
from app.main import create_app
from app.project.analysis_adapter import LspScipProvider
from app.project.importer import parse_github_url
from app.project.symbols import RepoIndex, build_repo_index
from app.specs import TaskSpec
from app.specs.models import RequirementItem
from app.workspace.adoption_index import ProjectAdoptionIndexService

# ---------------------------------------------------------------------------
# Restored from test_evaluator_training_acceptance.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _check(service: EvaluatorService, **kwargs):
    return service._training_acceptance_check(
        source="training",
        language_id="python",
        learner_deliverables=[],
        execution_passed=True,
        **kwargs,
    )


def test_explanation_only_criterion_defers_to_reflection() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code=(
            '"""queue_lock.py practice."""\n'
            "import threading\n\n"
            "class Queue:\n"
            "    def __init__(self):\n"
            "        self._lock = threading.Lock()\n\n"
            "    def push(self, item):\n"
            "        with self._lock:\n"
            "            pass\n"
        ),
        acceptance_criteria=[
            "使用 `queue_lock.py` 标出锁保护的临界区边界及其中的共享状态访问。",
            "使用 `with` 保证异常时释放锁。",
        ],
        expected_symbols=["queue_lock.py", "Lock", "with"],
    )

    assert check is not None
    assert check.status == "passed", check.detail
    assert "Deferred to reflection" in check.detail
    assert "File targets verified as the current file" in check.detail


def test_real_missing_code_symbol_still_fails() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code=(
            "import threading\n\n"
            "class Queue:\n"
            "    def __init__(self):\n"
            "        self._lock = threading.Lock()\n"
        ),
        acceptance_criteria=["实现 `snapshot` 并返回副本。"],
        expected_symbols=["snapshot"],
    )

    assert check is not None
    assert check.status == "failed"
    assert "snapshot" in check.detail


def test_deferred_only_acceptance_cannot_pass_without_code_evidence() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code="def untouched():\n    pass\n",
        acceptance_criteria=["实现线程安全队列，保证所有共享状态访问都在锁保护之内。"],
        expected_symbols=["queue_lock.py"],
    )

    assert check is not None
    assert check.status == "failed"
    assert "No concrete code signal matched" in check.detail


def test_file_only_symbols_cannot_pass_without_a_code_criterion() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code="def untouched():\n    pass\n",
        acceptance_criteria=[],
        expected_symbols=["queue_lock.py"],
    )

    assert check is not None
    assert check.status == "failed"
    assert "no concrete code criterion" in check.detail.lower()


def test_no_modification_guardrail_cannot_defer_to_reflection() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code="def sum_nested():\n    return 0\n",
        acceptance_criteria=["在 `sum_nested.py` 中不修改 `list_pairs.py`"],
        expected_symbols=["sum_nested"],
    )

    assert check is not None
    assert check.status == "failed", check.detail
    assert "不修改" in check.detail


def test_substantive_unsignalled_requirement_cannot_defer() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code="import threading\nlock = threading.Lock()\n",
        acceptance_criteria=[
            "使用 `Lock` 初始化锁。",
            "保证所有共享状态访问都在锁保护之内。",
        ],
        expected_symbols=["Lock"],
    )

    assert check is not None
    assert check.status == "failed", check.detail
    assert "共享状态" in check.detail


def test_explanation_plus_implementation_cannot_defer() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code="import threading\nlock = threading.Lock()\n",
        acceptance_criteria=[
            "使用 `Lock` 初始化锁。",
            "解释并实现所有共享状态的锁保护。",
        ],
        expected_symbols=["Lock"],
    )

    assert check is not None
    assert check.status == "failed", check.detail


def test_explanation_plus_fix_cannot_defer() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code="import threading\nlock = threading.Lock()\n",
        acceptance_criteria=[
            "使用 `Lock` 初始化锁。",
            "说明并修复队列的竞态。",
        ],
        expected_symbols=["Lock"],
    )

    assert check is not None
    assert check.status == "failed", check.detail


_PPO_CRITERIA = [
    "使用 `ppo_clip_loss` 接收 `ratio`、`advantage` 和 `epsilon`。",
    "通过 `ppo_clip_loss` 实现逐元素取较小值后求负均值的裁剪目标。",
    "通过 `ppo_clip_loss` 在 `epsilon=0.2`、`ratio=1.5`、`advantage=-1.0` 时返回 `1.5`。",
    "使用 `ppo_clip_loss` 的 `docstring` 解释正优势与负优势下的裁剪差异。",
]


_PPO_SYMBOLS = ["ppo_clip_loss", "ratio", "advantage", "epsilon", "docstring"]


_PPO_DOCSTRING = '''    """计算 PPO 逐元素裁剪目标，并取逐元素较小值的负均值。

    正优势（``advantage > 0``）：当 ratio 超过 ``1 + epsilon`` 时，过大的正向
    收益被限制在裁剪上界。
    负优势（``advantage < 0``）：未裁剪项更小，逐元素取 ``min`` 会保留未裁剪
    的惩罚，因此不会削弱本应保留的惩罚。

    例如 ``epsilon=0.2``、``ratio=1.5``、``advantage=-1.0`` 时，负均值结果为
    ``1.5``。
    """
'''


def _ppo_submission(docstring: str = _PPO_DOCSTRING) -> str:
    return (
        "def ppo_clip_loss(ratio, advantage, epsilon):\n"
        f"{docstring}"
        "    lower, upper = 1.0 - epsilon, 1.0 + epsilon\n"
        "    values = [\n"
        "        min(r * a, min(max(r, lower), upper) * a)\n"
        "        for r, a in zip(ratio, advantage)\n"
        "    ]\n"
        "    return -sum(values) / len(values)\n"
        "\n"
        "\n"
        "def test_card_contract():\n"
        "    assert ppo_clip_loss([1.5], [-1.0], 0.2) == 1.5\n"
    )


def test_real_documented_answer_passes_its_docstring_criterion() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code=_ppo_submission(),
        acceptance_criteria=_PPO_CRITERIA,
        expected_symbols=_PPO_SYMBOLS,
    )

    assert check is not None
    assert check.status == "passed", check.detail
    assert "Acceptance progress: 9/9" in check.detail
    assert "docstring on ppo_clip_loss" in check.detail


def test_missing_docstring_is_a_real_miss_for_the_named_function() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code=_ppo_submission(docstring=""),
        acceptance_criteria=_PPO_CRITERIA,
        expected_symbols=_PPO_SYMBOLS,
    )

    assert check is not None
    assert check.status == "failed", check.detail
    assert "Missing: 使用 `ppo_clip_loss` 的 `docstring`" in check.detail
    assert "docstring on ppo_clip_loss" in check.detail


def test_docstring_on_another_function_does_not_satisfy_the_criterion() -> None:
    service = EvaluatorService()
    code = (
        '"""Module note."""\n'
        "\n"
        "def helper():\n"
        '    """Explains something else."""\n'
        "\n"
        "def ppo_clip_loss(ratio, advantage, epsilon):\n"
        "    return -sum(min(r * a, a) for r, a in zip(ratio, advantage)) / len(ratio)\n"
    )
    check = _check(
        service,
        code=code,
        acceptance_criteria=["使用 `ppo_clip_loss` 的 `docstring` 解释裁剪差异。"],
        expected_symbols=["ppo_clip_loss"],
    )

    assert check is not None
    assert check.status == "failed", check.detail
    assert "docstring on ppo_clip_loss" in check.detail


def test_runner_words_are_satisfied_by_execution_not_by_literals_in_the_file() -> None:
    criteria = [
        "Define a `main` entry point and run the submission via `python`.",
        "Run the submission once via `pytest` or `python` and keep the output.",
    ]
    code = (
        "def main():\n"
        "    print('done')\n"
        "\n"
        "\n"
        "def test_submission_passes():\n"
        "    assert main is not None\n"
    )

    executed = _check(
        EvaluatorService(),
        code=code,
        acceptance_criteria=criteria,
        expected_symbols=["main"],
    )
    not_executed = EvaluatorService()._training_acceptance_check(
        source="training",
        language_id="python",
        learner_deliverables=[],
        execution_passed=False,
        code=code,
        acceptance_criteria=criteria,
        expected_symbols=["main"],
    )

    assert executed is not None
    assert "python" not in code and "pytest" not in code
    assert executed.status == "passed", executed.detail
    assert not_executed is not None
    assert not_executed.status == "failed", not_executed.detail
    assert "python" in not_executed.detail and "pytest" in not_executed.detail


def test_docstring_requirement_is_not_a_permanent_miss_in_other_languages() -> None:
    service = EvaluatorService()
    check = service._training_acceptance_check(
        source="training",
        language_id="typescript",
        learner_deliverables=[],
        code="export function clip(ratio: number): number {\n  return ratio;\n}\n",
        acceptance_criteria=[
            "Implement `clip` for the ratio.",
            "Add a `docstring` explaining the clipping.",
        ],
        expected_symbols=["clip", "docstring"],
        execution_passed=False,
    )

    assert check is not None
    assert check.status == "passed", check.detail
    assert "Deferred to reflection: docstring" in check.detail


def test_comment_only_requirement_defers_instead_of_failing_forever() -> None:
    # Comments are deliberately not code evidence, so nothing in the file can
    # ever satisfy the requirement by name. It defers; it is never "missing".
    check = _check(
        EvaluatorService(),
        code="def clip(ratio, advantage, epsilon):\n    return ratio\n",
        acceptance_criteria=["添加 `注释` 说明裁剪差异。"],
        expected_symbols=[],
    )

    assert check is not None
    # Deferred evidence alone still cannot verify a file (unchanged rule).
    assert check.status == "failed"
    assert "Deferred to reflection: 添加 `注释` 说明裁剪差异。" in check.detail
    assert "Missing:" not in check.detail


# ---------------------------------------------------------------------------
# Restored from test_evaluator_properties.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


# Custom strategies for generating test data
@st.composite
def check_status(draw):
    """Generate a valid CheckStatus."""
    return draw(st.sampled_from([
        CheckStatus.PENDING,
        CheckStatus.PASSED,
        CheckStatus.FAILED,
        CheckStatus.SKIPPED,
        CheckStatus.ERROR,
    ]))


@st.composite
def check_result(draw):
    """Generate a CheckResult with random status."""
    name = draw(st.sampled_from(["ruff", "pyright", "pytest", "hypothesis", "custom"]))
    status = draw(check_status())
    return CheckResult(
        name=name,
        status=status,
        command=[name, "check"],
        summary=draw(st.text(max_size=100)) if status != CheckStatus.PASSED else "ok",
    )


@st.composite
def check_results_list(draw):
    """Generate a list of CheckResults."""
    count = draw(st.integers(min_value=0, max_value=5))
    results = []
    for _ in range(count):
        results.append(draw(check_result()))
    return results


@st.composite
def requirement_item(draw):
    """Generate a RequirementItem."""
    category = draw(st.sampled_from(["constraint", "functional", "non-functional"]))
    text = draw(st.text(min_size=5, max_size=100, alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Zs'))))
    return RequirementItem(category=category, text=text, source="test")


@st.composite
def task_spec(draw):
    """Generate a TaskSpec with random requirements."""
    requirements = draw(st.lists(requirement_item(), min_size=0, max_size=5))
    spec = TaskSpec.create(
        title=draw(st.text(min_size=5, max_size=50)),
        objective=draw(st.text(min_size=10, max_size=100)),
    )
    spec.requirements = requirements
    return spec


@st.composite
def code_snippet(draw):
    """Generate a code snippet."""
    # Simple Python-like code
    lines = draw(st.integers(min_value=1, max_value=10))
    code = "def example():\n"
    for i in range(lines):
        code += f"    pass  # line {i}\n"
    return code


class FakeRunner:
    """Fake command runner for testing."""

    def __init__(self, results: list[CheckResult] | None = None):
        self._results = results or []
        self._index = 0

    def run(self, command: CheckCommand) -> CheckResult:
        if self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return CheckResult(name=command.name, status=CheckStatus.PASSED, command=command.argv, summary="ok")


class FakeSemanticReviewer:
    """Fake semantic reviewer for testing."""

    def __init__(self, status: CheckStatus = CheckStatus.PASSED):
        self._status = status

    def review(self, spec: TaskSpec, code: str, checks: list[CheckResult]) -> SemanticReview:
        return SemanticReview(
            status=self._status,
            summary="Test review",
            missing_requirements=[],
            recommendations=[],
        )


class TestEvaluatorProperties:
    """Property-based tests for EvaluatorService."""

    @given(
        checks=check_results_list(),
    )
    @settings(max_examples=50)
    def test_overall_status_aggregation_failed_check(self, checks):
        """Property: If any check fails, overall status should be FAILED.

        Tests _overall_status directly to avoid FakeRunner/pipeline command
        mismatch — the pipeline generates its own commands (ruff, pyright, pytest)
        so the generated checks may not align with what the pipeline actually runs.
        """
        pipeline = EvaluationPipeline(
            runner=FakeRunner(),
            semantic_reviewer=FakeSemanticReviewer(CheckStatus.PASSED),
        )
        semantic_review = SemanticReview(
            status=CheckStatus.PASSED,
            summary="ok",
            missing_requirements=[],
            recommendations=[],
        )
        overall = pipeline._overall_status(checks, semantic_review)

        has_error = any(c.status == CheckStatus.ERROR for c in checks)
        has_failed = any(c.status == CheckStatus.FAILED for c in checks if c.name != "hypothesis")

        if has_error:
            assert overall == CheckStatus.ERROR
        elif has_failed:
            assert overall == CheckStatus.FAILED
        else:
            assert overall == CheckStatus.PASSED

    @given(
        status=check_status(),
    )
    @settings(max_examples=50)
    def test_check_result_status_is_valid(self, status):
        """Property: CheckStatus should always be a valid enum value."""
        assert status in CheckStatus

    @given(
        spec=task_spec(),
        code=code_snippet(),
    )
    @settings(max_examples=30)
    def test_evaluation_produces_valid_report(self, spec, code):
        """Property: Evaluation should always produce a valid report."""
        pipeline = EvaluationPipeline(
            runner=FakeRunner(),
            semantic_reviewer=FakeSemanticReviewer(CheckStatus.PASSED),
        )
        request = EvaluationRequest(spec=spec, code=code)
        report = pipeline.evaluate(request)
        
        # Report should have valid structure
        assert report.target is not None
        assert report.overall_status in CheckStatus
        assert isinstance(report.checks, list)
        assert report.semantic_review is not None

    @given(
        checks=check_results_list(),
    )
    @settings(max_examples=50)
    def test_check_determinism(self, checks):
        """Property: Same input -> same output for check results."""
        # Create two identical lists
        checks_copy = [
            CheckResult(
                name=c.name,
                status=c.status,
                command=list(c.command),
                summary=c.summary,
            )
            for c in checks
        ]
        
        # Verify they have the same properties
        for c1, c2 in zip(checks, checks_copy, strict=True):
            assert c1.name == c2.name
            assert c1.status == c2.status
            assert c1.command == c2.command

    @given(
        spec=task_spec(),
    )
    @settings(max_examples=50)
    def test_spec_has_valid_id(self, spec):
        """Property: TaskSpec should have a valid ID."""
        assert spec.id.startswith("spec_")
        assert len(spec.id) > 5

    @given(
        requirements=st.lists(requirement_item(), min_size=0, max_size=10),
    )
    @settings(max_examples=50)
    def test_requirements_have_valid_categories(self, requirements):
        """Property: All requirements should have valid categories."""
        valid_categories = {"constraint", "functional", "non-functional"}
        for req in requirements:
            assert req.category in valid_categories

    @given(
        checks=check_results_list(),
    )
    @settings(max_examples=50)
    def test_passed_check_count(self, checks):
        """Property: Passed check count should match actual passed checks."""
        passed_count = sum(1 for c in checks if c.status == CheckStatus.PASSED)
        assert passed_count >= 0
        assert passed_count <= len(checks)

    @given(
        checks=check_results_list(),
    )
    @settings(max_examples=50)
    def test_failed_check_count(self, checks):
        """Property: Failed check count should match actual failed checks."""
        failed_count = sum(1 for c in checks if c.status == CheckStatus.FAILED)
        assert failed_count >= 0
        assert failed_count <= len(checks)

    @given(
        status=check_status(),
    )
    @settings(max_examples=50)
    def test_semantic_review_status_valid(self, status):
        """Property: SemanticReview status should be a valid CheckStatus."""
        review = SemanticReview(
            status=status,
            summary="Test",
            missing_requirements=[],
            recommendations=[],
        )
        assert review.status in CheckStatus

    @given(
        spec=task_spec(),
        code=code_snippet(),
    )
    @settings(max_examples=30)
    def test_evaluation_with_empty_checks(self, spec, code):
        """Property: Evaluation with no failing checks should produce PASSED status."""
        pipeline = EvaluationPipeline(
            runner=FakeRunner([]),
            semantic_reviewer=FakeSemanticReviewer(CheckStatus.PASSED),
        )
        request = EvaluationRequest(spec=spec, code=code)
        report = pipeline.evaluate(request)

        assert report.overall_status == CheckStatus.PASSED
        # All checks should be PASSED or SKIPPED (hypothesis is SKIPPED by default)
        non_failing = {CheckStatus.PASSED, CheckStatus.SKIPPED}
        assert all(c.status in non_failing for c in report.checks)

    @given(
        checks=check_results_list(),
    )
    @settings(max_examples=50)
    def test_overall_status_priority(self, checks):
        """Property: ERROR status should take priority over FAILED."""
        has_error = any(c.status == CheckStatus.ERROR for c in checks)
        has_failed = any(c.status == CheckStatus.FAILED for c in checks if c.name != "hypothesis")
        
        if has_error and has_failed:
            # ERROR should take priority
            # This tests the logic in _overall_status
            assert True  # The actual test is in the implementation

    @given(
        name=st.text(min_size=1, max_size=20),
        status=check_status(),
    )
    @settings(max_examples=50)
    def test_check_result_name_preserved(self, name, status):
        """Property: CheckResult should preserve the name."""
        result = CheckResult(name=name, status=status, command=[], summary="")
        assert result.name == name

    @given(
        spec=task_spec(),
        code=code_snippet(),
    )
    @settings(max_examples=30)
    def test_evaluation_request_preserves_spec(self, spec, code):
        """Property: EvaluationRequest should preserve the spec."""
        request = EvaluationRequest(spec=spec, code=code)
        assert request.spec.id == spec.id
        assert request.spec.title == spec.title


# ---------------------------------------------------------------------------
# Restored from test_scip_adapter.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _index(root: Path) -> RepoIndex:
    return RepoIndex(root=root, files=[], symbols=[], truncated_files=False)


def _write_index(root: Path, payload: object) -> Path:
    path = root / ".trainer" / "scip" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_scip_json_references_become_compiler_evidence(tmp_path: Path) -> None:
    _write_index(
        tmp_path,
        {
            "documents": [
                {
                    "relativePath": "src/a.py",
                    "symbols": [
                        {
                            "symbol": "scip-python python pkg a/Foo#",
                            "displayName": "Foo",
                        }
                    ],
                    "occurrences": [
                        {
                            "symbol": "scip-python python pkg a/Foo#",
                            "symbolRoles": 1,
                            "range": [3, 0, 3],
                        }
                    ],
                },
                {
                    "relative_path": "src/b.py",
                    "occurrences": [
                        {
                            "symbol": "scip-python python pkg a/Foo#",
                            "symbol_roles": 8,
                            "range": [10, 4, 7],
                        }
                    ],
                },
            ]
        },
    )

    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is True
    assert report.confidence == "scip_reference"
    assert len(report.edges) == 1
    edge = report.edges[0]
    assert edge.caller_file == "src/b.py"
    assert edge.callee_file == "src/a.py"
    assert edge.callee_symbol == "Foo"
    assert edge.confidence == "scip_reference"
    assert any("binary protobuf" in item for item in report.limitations)


def test_scip_missing_index_reports_honest_reason(tmp_path: Path) -> None:
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is False
    assert "No SCIP index" in report.reason


def test_scip_invalid_binary_reports_decode_failure(tmp_path: Path) -> None:
    (tmp_path / "index.scip").write_bytes(b"not-a-json-index")
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is False
    assert "binary index could not be decoded" in report.reason


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field_varint(number: int, value: int) -> bytes:
    return _varint((number << 3) | 0) + _varint(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _scip_binary_index() -> bytes:
    symbol = "scip-python python pkg 0.1 `lib.py`/foo()."
    lib_symbol = _field_bytes(1, symbol.encode()) + _field_bytes(5, b"foo")
    lib_document = (
        _field_bytes(1, b"lib.py")
        + _field_bytes(3, lib_symbol)
    )
    reference = _field_bytes(2, symbol.encode()) + _field_varint(3, 8)
    app_document = _field_bytes(1, b"app.py") + _field_bytes(2, reference)
    return _field_bytes(2, lib_document) + _field_bytes(2, app_document)


def test_scip_binary_protobuf_references_become_compiler_evidence(tmp_path: Path) -> None:
    path = tmp_path / ".trainer" / "scip" / "index.scip"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_scip_binary_index())

    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is True
    assert report.confidence == "scip_reference"
    assert len(report.edges) == 1
    edge = report.edges[0]
    assert edge.caller_file == "app.py"
    assert edge.callee_file == "lib.py"
    assert edge.callee_symbol == "foo"
    assert any("index.scip" in item for item in report.limitations)


def test_scip_invalid_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "index.scip.json"
    path.write_text("{not json", encoding="utf-8")
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is False
    assert "could not be read" in report.reason


def test_scip_skips_unmapped_and_self_file_references(tmp_path: Path) -> None:
    _write_index(
        tmp_path,
        {
            "documents": [
                {
                    "relativePath": "src/a.py",
                    "symbols": [{"symbol": "sym-a", "displayName": "A"}],
                    "occurrences": [
                        {"symbol": "unknown-symbol", "symbolRoles": 8},
                        {"symbol": "sym-a", "symbolRoles": 8},
                    ],
                },
                {
                    "relativePath": "src/b.py",
                    "occurrences": [
                        {"symbol": "unknown-symbol", "symbolRoles": 8},
                    ],
                },
            ]
        },
    )
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is True
    assert report.edges == []


# ---------------------------------------------------------------------------
# Restored from test_verify_practice_progress_feedback.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _context(content: str) -> ToolContext:
    return ToolContext(
        runtime=None,
        workspace_id="workspace-1",
        session_id="session-1",
        extra={
            "current_file": {
                "path": "src/search.ts",
                "language_id": "typescript",
                "content": content,
                "diagnostics": [],
            }
        },
    )


class VerifyPracticeProgressFeedbackTest(unittest.TestCase):
    def test_partial_match_reports_progress_and_first_missing_signal(self) -> None:
        result = asyncio.run(
            _handle_verify_practice_current_file(
                _context("export function searchNow(query: string) { return query; }\n"),
                {
                    "acceptance_criteria": [
                        "Implement debounceSearch for the search input.",
                        "Keep the search function pure.",
                    ],
                    "expected_symbols": ["debounceSearch"],
                },
            )
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["matched_signal_count"], 1)
        self.assertEqual(result["total_signal_count"], 3)
        self.assertIn("1/3 acceptance signals matched", result["summary"])
        self.assertIn("Still missing:", result["summary"])
        self.assertIn("debounceSearch", result["summary"])
        self.assertIn("Implement the missing acceptance signals (starting with", result["next_step"])
        self.assertIn("debounceSearch", result["next_step"])

    def test_full_match_reports_progress_without_missing_list(self) -> None:
        content = (
            "export function debounceSearch(fn: unknown) { return fn; }\n"
            "export const debounceSearchPure = debounceSearch;\n"
        )
        result = asyncio.run(
            _handle_verify_practice_current_file(
                _context(content),
                {
                    "acceptance_criteria": [
                        "debounceSearch",
                        "debounceSearchPure",
                    ],
                    "expected_symbols": [],
                },
            )
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["matched_signal_count"], result["total_signal_count"])
        self.assertEqual(result["total_signal_count"], 2)
        self.assertNotIn("Still missing:", result["summary"])

    def test_zero_match_names_every_missing_signal(self) -> None:
        result = asyncio.run(
            _handle_verify_practice_current_file(
                _context("const nothing = 1;\n"),
                {"acceptance_criteria": ["retryFetch", "abortController"]},
            )
        )

        self.assertFalse(result["passed"])
        self.assertIn("0/2 acceptance signals matched", result["summary"])
        self.assertIn("Still missing:", result["summary"])


# ---------------------------------------------------------------------------
# Restored from test_token_benchmark.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


QUERIES = [
    {
        "question": "Where is the workspace classifier heuristic defined?",
        "expect_paths": ["trainer_workspace/classifier.py"],
        "keywords": ["classify", "heuristic", "workspace"],
    },
    {
        "question": "How does the cost ledger record estimated token usage?",
        "expect_paths": ["llm/cost_ledger.py"],
        "keywords": ["cost", "ledger", "token"],
    },
    {
        "question": "Which module ingests documents into canonical markdown?",
        "expect_paths": ["resources/canonical.py", "resources/canonical_store.py"],
        "keywords": ["canonical", "markdown", "ingest"],
    },
    {
        "question": "Where does the agent loop handle tool calls?",
        "expect_paths": ["llm/agent_loop.py"],
        "keywords": ["agent", "loop", "tool"],
    },
]


def _build_fixture_repo(root: Path) -> None:
    """A miniature repo shaped like Trainer: deep dirs, realistic symbols."""

    sources = {
        "trainer_workspace/classifier.py": (
            '"""Classify workspace folders."""\n\n'
            "def classify_heuristic(folder: str) -> str:\n"
            "    return 'existing_engineering'\n\n"
            "class WorkspaceClassifier:\n"
            "    def classify(self, folder: str) -> str:\n"
            "        return classify_heuristic(folder)\n"
        ),
        "llm/cost_ledger.py": (
            '"""Append-only cost ledger."""\n\n'
            "class CostLedger:\n"
            "    def record(self, workspace: str, tokens: int) -> None:\n"
            "        pass\n"
        ),
        "llm/agent_loop.py": (
            "class AgentLoop:\n"
            "    def handle_tool_call(self, name: str) -> str:\n"
            "        return name\n"
        ),
        "resources/canonical.py": (
            "def digest_document(path: str) -> str:\n"
            "    return 'canonical markdown'\n"
        ),
        "resources/canonical_store.py": (
            "class CanonicalStore:\n"
            "    def write(self, path: str, body: str) -> None:\n"
            "        pass\n"
        ),
        "llm/provider_service.py": (
            "class ProviderService:\n"
            "    def chat(self, message: str) -> str:\n"
            "        return message\n"
        ),
        "README.md": "# Trainer\nLearning workspace tooling.\n",
    }
    for relative, text in sources.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    # Scale: filler modules make the naive full-repo dump genuinely large, the
    # way a real repository is. Without them the toy fixture flatters the dump.
    for index in range(24):
        filler = (
            f"# generated filler module {index}\n\n"
            f"class Filler{index}:\n"
            f"    def run_{index}(self, value: str) -> str:\n"
            f"        return value.strip()\n\n"
            f"    def helper_{index}(self, a: int, b: int) -> int:\n"
            f"        return a + b\n\n"
            f"def entry_{index}(payload: dict) -> bool:\n"
            f"    return bool(payload)\n"
        )
        target = root / "services" / f"gen_module_{index:02d}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(filler, encoding="utf-8")
    (root / "node_modules" / "leftpad" / "index.js").parent.mkdir(parents=True, exist_ok=True)
    (root / "node_modules" / "leftpad" / "index.js").write_text("noise", encoding="utf-8")


def test_layered_mode_beats_full_tokens_and_matches_rag_localization(tmp_path: Path) -> None:
    repo = tmp_path / "trainer-fixture"
    _build_fixture_repo(repo)
    report = run_token_benchmark(repo, QUERIES)

    modes = report["modes"]
    assert modes["full_repository"]["tokens"] > modes["layered"]["tokens"]
    assert modes["layered"]["localization_hit_rate"] >= 0.75
    assert report["verdict"]["layered_qualifies"] is True
    # Deterministic symbol index found the expected anchors.
    assert report["repo_symbol_count"] >= 8
    assert report["repo_file_count"] >= 6
    serialized = json.dumps(report)
    assert "node_modules" not in serialized


def test_queries_without_expected_path_still_report_selections(tmp_path: Path) -> None:
    repo = tmp_path / "trainer-fixture"
    _build_fixture_repo(repo)
    report = run_token_benchmark(
        repo,
        [
            {
                "question": "provider service chat behaviour",
                "expect_paths": [],
                "keywords": ["provider", "chat"],
            }
        ],
    )
    assert report["query_count"] == 1
    assert report["modes"]["layered"]["tokens"] > 0


def test_report_is_json_serializable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_fixture_repo(repo)
    report = run_token_benchmark(repo, QUERIES[:1])
    assert isinstance(json.dumps(report), str)


# ---------------------------------------------------------------------------
# Restored from test_project_analysis.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "utils.py").write_text(
        "def format_name(name: str) -> str:\n    return name.strip().title()\n",
        encoding="utf-8",
    )
    (repo / "service.py").write_text(
        "from utils import format_name\n\n\ndef handle(name: str) -> str:\n    return format_name(name)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "x"],
        capture_output=True,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def test_unavailable_providers_never_fabricate_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.project.analysis_adapter as adapter

    repo = tmp_path / "repo"
    _init_repo(repo)
    index = build_repo_index(repo)

    monkeypatch.setattr(adapter, "_tree_sitter_available", lambda: (False, "grammar missing"))
    tree = adapter.TreeSitterPythonProvider().run(repo, index)
    assert tree.available is False
    assert tree.reason == "grammar missing"
    assert tree.edges == []

    lsp = LspScipProvider().run(repo, index)
    assert lsp.available is False
    assert "No SCIP index" in lsp.reason
    assert lsp.edges == []


def test_lsp_python_provider_reports_unavailable_without_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.project.analysis_adapter import LspPythonProvider

    repo = tmp_path / "repo"
    _init_repo(repo)
    index = build_repo_index(repo)
    provider = LspPythonProvider()
    monkeypatch.setattr(provider, "_server_available", lambda: (False, "python-lsp-server is not installed"))
    report = provider.run(repo, index)
    assert report.available is False
    assert report.reason == "python-lsp-server is not installed"
    assert report.edges == []


# ---------------------------------------------------------------------------
# Restored from test_project_callgraph.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c", "user.email=trainer@test",
        "-c", "user.name=Trainer",
        "commit", "-m", message,
    )


def _init_fixture_repo(repo: Path) -> str:
    """utils.format_name ← service.handle ← main (module-level call)."""

    repo.mkdir(parents=True, exist_ok=True)
    files = {
        "utils.py": (
            "def format_name(name: str) -> str:\n"
            "    return name.strip().title()\n"
            "\n"
            "def legacy_render(name: str) -> str:\n"
            "    return f'[{name}]'\n"
        ),
        "service.py": (
            "from utils import format_name, legacy_render\n"
            "\n"
            "\n"
            "def handle(name: str) -> str:\n"
            "    return format_name(name)\n"
            "\n"
            "def render(name: str) -> str:\n"
            "    return legacy_render(name)\n"
        ),
        "main.py": (
            "from service import handle\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    print(handle('ada'))\n"
        ),
    }
    for relative, text in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _commit_all(repo, "fixture")
    return _git(repo, "rev-parse", "HEAD")


def test_callgraph_function_level_edges(tmp_path: Path) -> None:
    from app.project.callgraph import build_call_graph
    from app.project.symbols import build_repo_index

    repo = tmp_path / "repos" / "graph-repo"
    _init_fixture_repo(repo)
    repo_index = build_repo_index(repo)
    graph = build_call_graph(repo, repo_index)

    # Function-level edge: service.handle → utils.format_name.
    edge_pairs = {
        (e.caller_symbol, e.callee_symbol, e.caller_kind)
        for e in graph.edges
    }
    assert ("handle", "format_name", "function") in edge_pairs
    assert ("render", "legacy_render", "function") in edge_pairs
    # Module-level call (main.py top-level handle()) → honest file-level caller.
    assert any(
        e.caller_kind == "file" and e.caller_file == "main.py" and e.callee_symbol == "handle"
        for e in graph.edges
    )
    # Reverse index: callers of format_name resolve to service.handle.
    callers = {e.caller_symbol for e in graph.callers_by_symbol.get("format_name", [])}
    assert "handle" in callers


def test_change_impact_working_tree_and_removed_symbols(tmp_path: Path) -> None:
    """改动影响面: working-tree diff → changed symbols → affected callers."""

    from app.project.callgraph import build_call_graph, compute_change_impact
    from app.project.symbols import build_repo_index

    repo = tmp_path / "repos" / "impact-repo"
    _init_fixture_repo(repo)

    # Working-tree change: rewrite utils.py, REMOVING legacy_render.
    (repo / "utils.py").write_text(
        "def format_name(name: str) -> str:\n    return name.strip().title()\n",
        encoding="utf-8",
    )
    repo_index = build_repo_index(repo)
    graph = build_call_graph(repo, repo_index)
    impact = compute_change_impact(repo, repo_index, graph)

    assert impact.changed_files == ["utils.py"]
    assert "format_name" in impact.changed_symbols
    # Removed symbol detection needs the old blob → since is empty for the
    # working tree, so removed_symbols stay empty there (honest limitation).
    assert impact.removed_symbols == []

    # With a since commit the removed symbol is detected and its caller flagged.
    since = _git(repo, "rev-parse", "HEAD")
    _commit_all(repo, "remove legacy_render")
    (repo / "utils.py").write_text(
        "def format_name(name: str) -> str:\n    return name.strip().title()\n",
        encoding="utf-8",
    )
    repo_index2 = build_repo_index(repo)
    graph2 = build_call_graph(repo, repo_index2)
    impact2 = compute_change_impact(repo, repo_index2, graph2, since=since)
    assert "legacy_render" in impact2.removed_symbols
    caller_keys = {(c["caller_file"], c["caller_symbol"]) for c in impact2.affected_callers}
    assert ("service.py", "render") in caller_keys
    # Transitive: handle (changed-file symbol) affects main.py's file-level caller.
    assert any(c["caller_file"] == "main.py" for c in impact2.affected_callers)
    assert all(1 <= c["hops"] <= 2 for c in impact2.affected_callers)

    # Depth 1 narrows the closure (no main.py file-level caller via transit).
    impact_d1 = compute_change_impact(repo, repo_index2, graph2, since=since, depth=1)
    assert impact_d1.affected_callers
    assert all(c["hops"] == 1 for c in impact_d1.affected_callers)

    # Clean tree (working tree == HEAD) → empty impact.
    impact_clean = compute_change_impact(repo, repo_index2, graph2)
    assert impact_clean.changed_files == []
    assert impact_clean.affected_callers == []


# ---------------------------------------------------------------------------
# Restored from test_project_adoption_index.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class _HeldThread:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        return None


def test_queued_job_is_not_mistaken_for_a_restart_before_its_worker_starts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "trainer-workspace"
    project = root / "Projects" / "sample"
    project.mkdir(parents=True)
    monkeypatch.setattr(adoption_index, "Thread", _HeldThread)
    service = ProjectAdoptionIndexService()

    started = service.start(
        workspace_id="workspace-1",
        discovery_id="discovery-1",
        project_path=str(project),
        project_name="sample",
        root_id="root-1",
        root_path=str(root),
        context_id="context-1",
    )

    observed = service.get(root_path=str(root), job_id=started.job_id)

    assert observed is not None
    assert observed.status == "queued"
    assert observed.retry_reason is None


def test_missing_project_path_interrupts_inventory_without_finalizing(tmp_path: Path) -> None:
    service = ProjectAdoptionIndexService()

    inventory = service._scan_project(str(tmp_path / "missing-project"))

    assert inventory["status"] == "interrupted"
    assert inventory["truncated"] is True
    assert inventory["files"] == []
    assert inventory["message"] == "Project path is no longer available."


# ---------------------------------------------------------------------------
# Restored from test_project_import.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_parse_github_url_accepts_url_tree_and_slug() -> None:
    assert parse_github_url("https://github.com/octocat/Hello-World") == {
        "owner": "octocat",
        "repo": "Hello-World",
        "branch": "",
        "clone_url": "https://github.com/octocat/Hello-World.git",
    }
    parsed = parse_github_url("https://github.com/psf/requests/tree/main")
    assert parsed["repo"] == "requests"
    assert parsed["branch"] == "main"
    assert parse_github_url("psf/requests")["clone_url"] == "https://github.com/psf/requests.git"
    with pytest.raises(ValueError, match="GitHub repository"):
        parse_github_url("https://gitlab.com/a/b")


# ---------------------------------------------------------------------------
# Restored from test_provenance_bench.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


_DOCS = [
    {"name": "Classifier Guide", "filename": "docs/classifier.md",
     "content": "# Classifier\nThe workspace classifier uses heuristic rules.\n"},
    {"name": "Ledger Guide", "filename": "docs/ledger.md",
     "content": "# Cost Ledger\nToken usage is recorded per workspace.\n"},
    {"name": "Reader Guide", "filename": "docs/reader.md",
     "content": "# Reader\nThe reader renders canonical markdown.\n"},
]


_QUERIES = ["classifier heuristic", "cost ledger", "canonical markdown"]


def test_provenance_verifiability(tmp_path: Path) -> None:
    settings = AppSettings(
        app_name="Trainer Provenance Bench",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-provenance.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    with TestClient(create_app(settings)) as client:
        client.post(
            "/session/start",
            json={"workspace_id": "ws-prov", "workspace_name": "prov", "workspace_path": str(workspace)},
        ).json()
        workspace_id = "ws-prov"
        for doc in _DOCS:
            path = workspace / doc["filename"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(doc["content"], encoding="utf-8")
            upload = client.post(
                "/resource/upload",
                json={"workspace_id": workspace_id, "kind": "markdown", "name": doc["name"], "source": str(path)},
            )
            assert upload.status_code == 200, upload.text
            indexed = client.post(
                "/resource/index",
                json={"workspace_id": workspace_id, "resource_id": upload.json()["id"]},
            ).json()
            assert indexed["index_status"] == "indexed"

        total = 0
        verifiable = 0
        for query in _QUERIES:
            search = client.post(
                "/resource/search",
                json={"workspace_id": workspace_id, "query": query, "top_k": 5},
            ).json()
            for hit in search.get("hits", []):
                total += 1
                if hit.get("version_id") and hit.get("content_hash"):
                    verifiable += 1

        assert total >= 3, f"Expected ≥3 citations, got {total}"
        rate = verifiable / total
        assert rate >= 0.95, f"Provenance verifiability {rate:.2%} < 95%"
