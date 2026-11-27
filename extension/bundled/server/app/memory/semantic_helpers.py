from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from .models import (
    SearchHit,
)
from .semantic import HashingEmbedder, SemanticMemory

logger = logging.getLogger(__name__)


_CJK_TEXT_CORRECT_THRESHOLD = 0.60


def _contains_cjk_answer_text(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


def _cjk_normalized_answer(value: str) -> str:
    """Drop punctuation like the latin tokenizer, but keep CJK characters."""

    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value)


def _dice_coefficient(left: str, right: str, *, size: int) -> float:
    if len(left) < size or len(right) < size:
        return 1.0 if left and left == right else 0.0
    left_counts = Counter(left[index : index + size] for index in range(len(left) - size + 1))
    right_counts = Counter(right[index : index + size] for index in range(len(right) - size + 1))
    overlap = sum((left_counts & right_counts).values())
    total = sum(left_counts.values()) + sum(right_counts.values())
    return (2.0 * overlap) / total if total else 0.0


def _cjk_answer_similarity(expected: str, answer: str) -> float:
    """Dice similarity for CJK text answers.

    Primary coefficient is the Dice score over character bigrams of the
    whitespace-collapsed strings (punctuation excluded, CJK kept). Short CJK
    paraphrases reorder words, which collapses bigram overlap, so the
    character-level Dice acts as a floor before the answer is failed.
    """

    normalized_expected = _cjk_normalized_answer(expected)
    normalized_answer = _cjk_normalized_answer(answer)
    coefficient = _dice_coefficient(normalized_expected, normalized_answer, size=2)
    if coefficient < _CJK_TEXT_CORRECT_THRESHOLD:
        coefficient = max(
            coefficient,
            _dice_coefficient(normalized_expected, normalized_answer, size=1),
        )
    return coefficient


def _normalize_source_freshness(value: object) -> Literal["fresh", "stale", "unknown"]:
    normalized = str(value or "").strip().lower()
    if normalized == "fresh":
        return "fresh"
    if normalized == "stale":
        return "stale"
    return "unknown"
class SemanticMemoryService(SemanticMemory):
    def __init__(
        self,
        storage_path: Path | None = None,
        *,
        collection_name: str = "trainer_memory",
        embedder: HashingEmbedder | None = None,
        use_qdrant: bool = False,
    ) -> None:
        resolved_path = storage_path or Path(".trainer-memory")
        self.storage_path = resolved_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.collection = collection_name
        self.embedder = embedder or HashingEmbedder()
        self._documents = {}
        self._client = None
        self._client_initialized = False
        self._point_struct = None
        self._qdrant_enabled = use_qdrant
        if use_qdrant:
            super().__init__(
                storage_path=resolved_path,
                collection_name=collection_name,
                embedder=self.embedder,
            )

    def search(
        self,
        text: str,
        limit: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        *,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        return self.search_hits(text, top_k=top_k if top_k is not None else limit, metadata_filter=metadata_filter)

