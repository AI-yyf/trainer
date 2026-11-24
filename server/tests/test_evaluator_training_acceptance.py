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


# --- model-authored process words ---------------------------------------------
# A real-model journey produced this card and this answer. The answer is a
# complete, documented implementation; the evaluator rejected it because the
# card (like most model-authored cards) names process requirements with
# backticks: "使用 `ppo_clip_loss` 的 `docstring` 解释 ..." and lists
# `docstring` in expected_symbols. A docstring never contains the identifier
# `docstring`, so a correct answer could not pass. Runner names (`pytest`,
# `python`) are the same defect: they belong to the command line, not the file.

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


_CLIP_IMPLEMENTATION = (
    "def ppo_clip_loss(ratio, advantage, epsilon):\n"
    "    # Positive advantage: the clipped branch caps the gain.\n"
    "    clipped = min(max(ratio, 1 - epsilon), 1 + epsilon)\n"
    "    return -sum(min(r * a, c * a) for r, a, c in zip(ratio, advantage, clipped)) / len(ratio)\n"
)


def test_comment_and_out_of_file_documentation_never_block_a_correct_answer() -> None:
    service = EvaluatorService()
    commented = _check(
        service,
        code=_CLIP_IMPLEMENTATION,
        acceptance_criteria=["为 `ppo_clip_loss` 添加 `注释` 说明裁剪差异。"],
        expected_symbols=["ppo_clip_loss"],
    )
    assert commented.status == "passed", commented.detail

    alongside_code = _check(
        service,
        code=_CLIP_IMPLEMENTATION,
        acceptance_criteria=["实现 `ppo_clip_loss`。", "Write a `README` for the module."],
        expected_symbols=["ppo_clip_loss", "comment"],
    )
    assert alongside_code.status == "passed", alongside_code.detail
    assert "Deferred to reflection: Write a `README` for the module." in alongside_code.detail
    assert "Deferred to reflection: comment" in alongside_code.detail


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


def test_type_hints_are_checked_on_the_named_definition() -> None:
    annotated = "def clip(ratio: float, advantage: float) -> float:\n    return ratio * advantage\n"
    bare = "def clip(ratio, advantage):\n    return ratio * advantage\n"
    criteria = ["为 `clip` 添加 `类型注解`。"]

    documented = _check(
        EvaluatorService(),
        code=annotated,
        acceptance_criteria=criteria,
        expected_symbols=["clip", "类型注解"],
    )
    missing = _check(
        EvaluatorService(),
        code=bare,
        acceptance_criteria=criteria,
        expected_symbols=["clip", "类型注解"],
    )

    assert documented.status == "passed", documented.detail
    assert missing.status == "failed"
    assert "type hints on clip" in missing.detail


def test_phrase_expected_symbol_is_not_a_permanent_miss() -> None:
    service = EvaluatorService()
    check = _check(
        service,
        code="def ppo_clip_loss(ratio, advantage, epsilon):\n    return ratio\n",
        acceptance_criteria=["实现 `ppo_clip_loss`。"],
        expected_symbols=["ppo_clip_loss", "main entry point"],
    )
    assert check.status == "passed", check.detail
    assert "Deferred to reflection: main entry point" in check.detail

    # A real code statement stays a required signal.
    statement = _check(
        service,
        code="class Queue:\n    pass\n",
        acceptance_criteria=["Implement the queue."],
        expected_symbols=["with self._lock"],
    )
    assert statement.status == "failed"
    assert "Missing: with self._lock" in statement.detail


def test_a_comment_naming_the_symbol_is_still_not_evidence() -> None:
    # The honesty rule behind all of this is untouched.
    check = _check(
        EvaluatorService(),
        code="# ppo_clip_loss\n",
        acceptance_criteria=["实现 `ppo_clip_loss`。"],
        expected_symbols=["ppo_clip_loss"],
    )

    assert check.status == "failed"
    assert "Missing: ppo_clip_loss (ppo_clip_loss)" in check.detail


def test_backticked_callable_signature_requires_only_the_callable() -> None:
    # The card illustrates the interface with parameter names; the answer
    # names them differently and must still pass. Only `ppo_clip_loss` is a
    # required symbol.
    check = _check(
        EvaluatorService(),
        code=(
            "def ppo_clip_loss(new_logps, old_logps, advantages, clip_eps=0.2):\n"
            "    return 0.0\n"
        ),
        acceptance_criteria=[
            "定义 `ppo_clip_loss(new_logprobs, old_logprobs, advantages, clip_eps=0.2)`，"
            "返回保留计算图的标量 loss。"
        ],
        expected_symbols=["ppo_clip_loss"],
    )

    assert check.status == "passed", check.detail


def test_callable_signature_without_the_callable_still_fails() -> None:
    check = _check(
        EvaluatorService(),
        code="def some_other_loss(new_logps, advantages):\n    return 0.0\n",
        acceptance_criteria=[
            "定义 `ppo_clip_loss(new_logprobs, old_logprobs, advantages, clip_eps=0.2)`。"
        ],
        expected_symbols=["ppo_clip_loss"],
    )

    assert check.status == "failed"
    assert "ppo_clip_loss" in check.detail
