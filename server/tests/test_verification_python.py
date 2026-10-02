from __future__ import annotations

import sys
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from app.core.models import EvaluateCurrentFileRequest, TaskSpec
from app.evaluator.check_cache import CheckResultCache
from app.evaluator.models import CheckCommand, CheckResult, CheckStatus
from app.evaluator.service import EvaluationPipeline, EvaluatorService, SubprocessCommandRunner


@pytest.mark.real_tools
def test_selected_python_is_used_by_all_verifiers_after_sandbox_copy(tmp_path):
    # The explicit interpreter must survive the API -> pipeline -> sandbox adapters.
    service = EvaluatorService(pipeline=EvaluationPipeline(runner=SubprocessCommandRunner()))
    code = 'def test_mutability() -> None:\n    pair = ([1, 2], 3)\n    pair[0].append(4)\n    assert pair[0] == [1, 2, 4]\n'
    request = EvaluateCurrentFileRequest(file_path=str(tmp_path / 'sample.py'), language_id='python',
        content=code, verification_python=sys.executable, evaluation_source='training',
        acceptance_criteria=['Implement test_mutability'], expected_symbols=['test_mutability'])
    with patch.object(sys, 'frozen', True, create=True):
        report = service.evaluate_current_file(request)
    assert report.dynamic_checks[0].status == 'passed', report.model_dump()
    assert '1 passed' in report.dynamic_checks[0].detail
    assert all(check.status == 'passed' for check in report.static_checks), report.model_dump()
    assert not (tmp_path / 'sample.py').exists()


@pytest.mark.real_tools
def test_missing_pytest_module_is_skipped_and_cli_error_is_not_hidden_by_warning():
    command = CheckCommand(name='pytest', argv=[sys.executable, '-m', 'pytest'], cwd='.')
    completed = CompletedProcess(command.argv, 1, stdout='', stderr=f'{sys.executable}: No module named pytest\n')
    with patch('app.evaluator.service.subprocess.run', return_value=completed):
        result = SubprocessCommandRunner().run(command)
    assert result.status == CheckStatus.SKIPPED
    completed.stderr = 'launcher: error: unrecognized arguments: -m pytest\nwarning: deprecated API\n'
    with patch('app.evaluator.service.subprocess.run', return_value=completed):
        result = SubprocessCommandRunner().run(command)
    assert result.status == CheckStatus.FAILED
    assert result.summary == 'launcher: error: unrecognized arguments: -m pytest'


def test_verifier_cache_does_not_cross_python_environments(tmp_path):
    target = tmp_path / 'sample.py'
    target.write_text('def test_example():\n    assert True\n')
    cache = CheckResultCache()
    first = CheckCommand(name='pytest', argv=['/env-a/python', '-m', 'pytest', str(target)], cwd=str(tmp_path))
    second = CheckCommand(name='pytest', argv=['/env-b/python', '-m', 'pytest', str(target)], cwd=str(tmp_path))
    assert cache.key(first, str(tmp_path)) != cache.key(second, str(tmp_path))


@pytest.mark.real_tools
def test_generic_file_has_no_invented_requirement_and_requires_a_real_test(tmp_path):
    service = EvaluatorService(pipeline=EvaluationPipeline(runner=SubprocessCommandRunner()))
    request = EvaluateCurrentFileRequest(file_path=str(tmp_path / 'sample.py'), language_id='python',
        content='def test_example() -> None:\n    assert True\n', verification_python=sys.executable)
    report = service.evaluate_current_file(request)
    assert report.passed, report.model_dump()
    assert report.semantic_checks[0].status == 'skipped'
    request.content = 'value = 1\n'
    report = service.evaluate_current_file(request)
    assert not report.passed
    assert report.dynamic_checks[0].status == 'skipped'
    assert 'no dynamic verifier' in report.summary


@pytest.mark.real_tools
def test_training_requirements_do_not_inherit_an_unrelated_task(tmp_path):
    service = EvaluatorService(pipeline=EvaluationPipeline(runner=SubprocessCommandRunner()))
    request = EvaluateCurrentFileRequest(file_path=str(tmp_path / 'sample.py'), language_id='python',
        content='def test_example() -> None:\n    assert True\n', verification_python=sys.executable,
        evaluation_source='training', acceptance_criteria=['Implement test_example'], expected_symbols=['test_example'])
    unrelated = TaskSpec(id='old-task', title='Old task', natural_language_goal='Implement unrelated_operation')
    report = service.evaluate_current_file(request, unrelated)
    assert report.passed, report.model_dump()
    assert report.semantic_checks[0].status == 'skipped'
    assert report.semantic_checks[1].status == 'passed'
    assert 'ruff, pyright, pytest' in report.summary
    assert 'Training acceptance signals matched' in report.summary
    assert 'No task requirements' not in report.summary
    assert 'reflection' in report.next_step
    assert 'blocker' not in report.next_step


@pytest.mark.real_tools
def test_missing_interpreter_is_a_bounded_check_error(tmp_path):
    command = CheckCommand(name='pytest', argv=[str(tmp_path / 'missing-python'), '-m', 'pytest'], cwd=str(tmp_path))
    result = SubprocessCommandRunner().run(command)
    assert result.status == CheckStatus.ERROR
    assert 'Could not start pytest' in result.summary


def test_failure_report_preserves_the_actionable_diagnostic():
    check = CheckResult(name='ruff', status=CheckStatus.FAILED, summary='Found 1 error.',
        stdout='S102 Use of exec detected\nFound 1 error.')
    report = EvaluatorService()._to_api_check(check)
    assert 'S102 Use of exec detected' in report.detail


@pytest.mark.real_tools
def test_runtime_acceptance_requires_real_tests_and_return_prose_is_not_code(tmp_path):
    service = EvaluatorService(pipeline=EvaluationPipeline(runner=SubprocessCommandRunner()))
    request = EvaluateCurrentFileRequest(
        file_path=str(tmp_path / 'sample.py'), language_id='python',
        content='def test_boundary() -> None:\n    value = 1\n    assert value == 1\n',
        verification_python=sys.executable, evaluation_source='training',
        acceptance_criteria=['Implement `test_boundary`', 'Run without `SyntaxError` or `RuntimeError`'],
        expected_symbols=['test_boundary'],
        learner_deliverables=['One short reflection', 'One verification output'],
    )
    report = service.evaluate_current_file(request)
    assert report.passed, report.model_dump()
    assert report.semantic_checks[-1].status == 'passed'
    request.content = 'def test_boundary() -> None:\n    value = 1\n    assert value == 99\n'
    report = service.evaluate_current_file(request)
    assert not report.passed
    assert report.dynamic_checks[0].status == 'failed'
    assert report.semantic_checks[-1].status == 'failed'
    request.content = 'def boundary_helper() -> None:\n    return None\n'
    report = service.evaluate_current_file(request)
    assert not report.passed
    assert report.dynamic_checks[0].status == 'skipped'
    assert 'Verification is still required' in report.summary


@pytest.mark.real_tools
def test_python_card_acceptance_distinguishes_file_and_implicit_assignment_protocol(tmp_path):
    service = EvaluatorService(pipeline=EvaluationPipeline(runner=SubprocessCommandRunner()))
    code = (
        'def replace_second_item(container, replacement):\n    container[1] = replacement\n\n\n'
        'def test_nested_mutability() -> None:\n    value = ([1, 2], 3)\n'
        '    try:\n        replace_second_item(value, 9)\n    except TypeError:\n        pass\n'
        '    else:\n        raise AssertionError("Tuple assignment should fail")\n'
    )
    request = EvaluateCurrentFileRequest(
        file_path=str(tmp_path / 'list_pairs.py'), language_id='python', content=code,
        verification_python=sys.executable, evaluation_source='training',
        acceptance_criteria=[
            '定义 `replace_second_item` 触发的失败类型为 `TypeError`（来自 tuple 的 `__setitem__`）',
            '在 `.tmp-native-training/list_pairs.py` 中跑通整段脚本而不触发 `AssertionError`',
        ],
        expected_symbols=['replace_second_item', 'test_nested_mutability', 'TypeError'],
    )
    report = service.evaluate_current_file(request)
    assert report.passed, report.model_dump()
    request.expected_symbols.append('__setitem__')
    report = service.evaluate_current_file(request)
    assert not report.passed, 'An explicitly required method still needs its implementation'
