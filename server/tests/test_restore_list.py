"""Tests for the _restore_list schema-evolution fix."""

from app.memory.models import TeachingStrategyEffectivenessRecord
from app.memory.service import StructuredMemoryService


class FakeModel:
    def __init__(self, key: str, value: str = ""):
        self.key = key
        self.value = value


def test_restore_list_filters_unknown_fields():
    """Unknown fields should be silently ignored during deserialization."""
    payload = [
        {"key": "a", "value": "1", "relationship_stage": "intake"},
        {"key": "b", "unknown_field": "x"},
    ]
    result = StructuredMemoryService._restore_list(payload, FakeModel)
    assert len(result) == 2
    assert result[0].key == "a"
    assert result[0].value == "1"
    assert result[1].key == "b"
    assert result[1].value == ""


def test_restore_list_skips_empty_dicts():
    """Empty dicts should be skipped to avoid Pydantic validation failures."""
    payload = [
        {"key": "a", "value": "1"},
        {},
        {"key": "b"},
    ]
    result = StructuredMemoryService._restore_list(payload, FakeModel)
    assert len(result) == 2
    assert result[0].key == "a"
    assert result[1].key == "b"


def test_restore_list_dataclass_with_unknown_field():
    """Dataclass models should ignore unknown fields gracefully."""
    payload = [
        {
            "key": "test",
            "scenario": "s1",
            "relationship_stage": "active",  # field no longer exists
            "focus_area": "fa",
        }
    ]
    result = StructuredMemoryService._restore_list(payload, TeachingStrategyEffectivenessRecord)
    assert len(result) == 1
    assert result[0].key == "test"
    assert result[0].scenario == "s1"
    assert result[0].focus_area == "fa"
