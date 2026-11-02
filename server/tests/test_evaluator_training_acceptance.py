from app.evaluator.service import EvaluatorService


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
