"""Provider failure copy extraction stays behavior-compatible."""

from __future__ import annotations

from app.llm.provider.failure_copy import (
    provider_failure_next_step_text,
    provider_failure_summary_text,
)
from app.llm.provider.quota_copy import provider_quota_copy

CATEGORIES = (
    "invalid_key_or_permission",
    "model_unsupported",
    "model_not_found",
    "language_corruption",
    "malformed_response",
    "truncated_or_empty",
    "streaming_unavailable",
    "rate_limit",
    "timeout",
    "network",
)


def test_every_category_has_localized_summary_and_next_step() -> None:
    for category in CATEGORIES:
        english_summary = provider_failure_summary_text(category, "en-US")
        chinese_summary = provider_failure_summary_text(category, "zh-CN")
        english_next = provider_failure_next_step_text(category, "en-US")
        chinese_next = provider_failure_next_step_text(category, "zh-CN")
        assert english_summary and english_next
        assert chinese_summary and chinese_next
        assert any("\u4e00" <= char <= "\u9fff" for char in chinese_summary)
        assert any("\u4e00" <= char <= "\u9fff" for char in chinese_next)
        assert not any("\u4e00" <= char <= "\u9fff" for char in english_summary)


def test_quota_category_uses_the_structured_quota_copy() -> None:
    summary, next_step = provider_quota_copy("zh-CN")
    assert provider_failure_summary_text("quota_exhausted", "zh-CN") == summary
    assert provider_failure_next_step_text("quota_exhausted", "zh-CN") == next_step


def test_unknown_category_falls_back_without_raising() -> None:
    assert provider_failure_summary_text("unknown-category", "en-US")
    assert provider_failure_next_step_text("unknown-category", "zh-CN")
