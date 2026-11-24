from __future__ import annotations

from app.core.models import TrainingCardCandidateSnapshot


def test_implementation_card_without_files_downgrades_to_reading() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Confirm the project purpose",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=[],
    )

    assert card.learning_subtype == "reading"


def test_implementation_card_with_a_concrete_file_stays_implementation() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Add a boundary test",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["src/queue_lock.py"],
    )

    assert card.learning_subtype == "implementation"


def test_placeholder_file_targets_do_not_count_as_concrete_files() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Fill the implementation",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["<current failing file>"],
    )

    assert card.learning_subtype == "reading"


def test_files_to_touch_normalizes_markdown_and_keeps_concrete_target() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Check lock boundary",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["`queue_lock.py`", " src/queue_lock.py ", "`queue_lock.py`"],
    )

    assert card.files_to_touch == ["queue_lock.py", "src/queue_lock.py"]
    assert card.learning_subtype == "implementation"


def test_markdown_wrapped_placeholder_still_downgrades_to_reading() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Fill the implementation",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["`<current failing file>`"],
    )

    assert card.files_to_touch == ["<current failing file>"]
    assert card.learning_subtype == "reading"


def test_analysis_card_with_file_downgrades_to_reading() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="梳理 queue_lock.py 的加锁边界",
        learning_family="code",
        learning_subtype="function",
        files_to_touch=["queue_lock.py"],
        problem_statement="聚焦第 1-41 行，记录锁相关符号和调用点。不要先改生产代码。",
    )

    assert card.learning_subtype == "reading"


def test_implementation_card_with_change_verb_stays_implementation() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="为 Queue 增加受锁保护的快照",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["queue_lock.py"],
        problem_statement="实现 snapshot，返回副本。",
    )

    assert card.learning_subtype == "implementation"


def test_supplement_or_optimize_keeps_implementation() -> None:
    for title, statement in (
        ("检查 queue_lock.py 中的竞态并补充回归测试", "补充回归测试。"),
        ("分析 Queue 的锁设计并优化临界区", "优化临界区。"),
    ):
        card = TrainingCardCandidateSnapshot(
            card_type="practice",
            title=title,
            learning_family="code",
            learning_subtype="implementation",
            files_to_touch=["queue_lock.py"],
            problem_statement=statement,
        )
        assert card.learning_subtype == "implementation", title


def test_file_target_wrapped_in_prose_keeps_only_the_file() -> None:
    """A real-model card put a whole sentence in ``files_to_touch``.

    The entry was shown to the learner as the target file, and host
    verification refused every real artifact because its name never matched
    that "target".
    """
    for raw, expected in (
        ("ppo_clip_exercise.py（建议新建，具体路径由学习者选择）", "ppo_clip_exercise.py"),
        ("foo.py (create it)", "foo.py"),
        ("新建 foo.py", "foo.py"),
        ("src/app.py 的入口", "src/app.py"),
        ("My Project/app.py", "My Project/app.py"),
        ("C:\\work\\demo\\app.py", "C:/work/demo/app.py"),
        ("Dockerfile", "Dockerfile"),
        ("src/queue_lock.py:12", "src/queue_lock.py:12"),
    ):
        card = TrainingCardCandidateSnapshot(card_type="practice", files_to_touch=[raw])
        assert card.files_to_touch == [expected], raw


def test_prose_without_a_file_is_not_a_file_target() -> None:
    for raw in (
        "具体路径由学习者选择",
        "main entry point",
        "一个新建的文件",
        "Edit the module you prefer",
        "新建一个练习文件，验证裁剪行为。",
    ):
        card = TrainingCardCandidateSnapshot(
            card_type="practice",
            title="Implement the boundary",
            learning_family="code",
            learning_subtype="implementation",
            files_to_touch=[raw],
        )
        assert card.files_to_touch == [], raw
        assert card.learning_subtype == "reading", raw


def test_symbols_the_card_presents_as_alternatives_are_not_both_required() -> None:
    """A real-model card hinted "`torch.minimum`（或 `torch.min`）" and then
    listed both as expected symbols; a correct torch.minimum implementation
    failed on torch.min."""
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        acceptance_criteria=[
            "定义 `ppo_clip_loss`，用 `torch.minimum` 逐元素取两个代理目标的较小值。",
        ],
        api_hints=["`torch.minimum`（或双 tensor 形式的 `torch.min`）：逐元素取较小值。"],
        expected_symbols=["ppo_clip_loss", "torch.minimum", "torch.min"],
    )

    assert card.expected_symbols == ["ppo_clip_loss", "torch.minimum"]


def test_symbols_never_presented_as_alternatives_stay_required() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        acceptance_criteria=["用 `torch.min` 求最小值，再用 `torch.maximum` 取上界。"],
        api_hints=["`torch.clamp` 把 `ratio` 限制在 `[1 - epsilon, 1 + epsilon]`。"],
        expected_symbols=["torch.min", "torch.maximum", "torch.clamp"],
    )

    assert card.expected_symbols == ["torch.min", "torch.maximum", "torch.clamp"]
