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
