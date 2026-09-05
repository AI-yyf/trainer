from __future__ import annotations

import math
import os
from importlib import import_module
from typing import Any, Sequence


class EmbeddingProvider:
    """Base class for embedding providers."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError


class HashingEmbedder(EmbeddingProvider):
    """Fallback embedder using simple hashing (no external dependencies)."""

    def __init__(self, *, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = [token for token in text.lower().split() if token]
        if not tokens:
            return vector
        for token in tokens:
            vector[hash(token) % self.dimensions] += 1.0
        magnitude = math.sqrt(sum(component * component for component in vector))
        return [component / magnitude for component in vector] if magnitude else vector


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Real embedding using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any | None = None
        self._dimensions = 384  # Default for all-MiniLM-L6-v2

    def _load_model(self) -> Any:
        model = self._model
        if model is None:
            try:
                sentence_transformers: Any = import_module("sentence_transformers")
                model_factory = sentence_transformers.SentenceTransformer
                model = model_factory(self.model_name)
                self._model = model
                self._dimensions = model.get_sentence_embedding_dimension()
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                ) from exc
        return model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load_model()
        embeddings = model.encode(list(texts), convert_to_numpy=True)
        return embeddings.tolist()

    @property
    def dimensions(self) -> int:
        return self._dimensions


class OpenAIEmbedder(EmbeddingProvider):
    """Embedding using OpenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self._dimensions = dimensions
        self._client = None

    def _load_client(self):
        if self._client is None:
            try:
                import openai

                self._client = openai.OpenAI(api_key=self.api_key)
            except ImportError as exc:
                raise RuntimeError("openai not installed. Install with: pip install openai") from exc
        return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        client = self._load_client()
        response = client.embeddings.create(model=self.model, input=list(texts))
        return [item.embedding for item in response.data]

    @property
    def dimensions(self) -> int:
        return self._dimensions


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False)) if left and right else 0.0
