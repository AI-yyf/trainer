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
