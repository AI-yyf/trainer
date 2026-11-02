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
