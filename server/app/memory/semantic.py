from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence, cast

from .embedder import EmbeddingProvider, HashingEmbedder, cosine_similarity
from .models import MemoryDocument, SearchHit, SemanticCollectionInfo


class SemanticMemory:
    def __init__(
        self,
        storage_path: Path,
        *,
        collection_name: str = "trainer_memory",
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.collection = collection_name
        self.embedder = embedder or HashingEmbedder()
        self._documents: dict[str, MemoryDocument] = {}
        self._client = None
        self._client_initialized = False
        self._point_struct = None
        self._qdrant_enabled = True

    def _ensure_client(self) -> None:
        """Open Qdrant lazily so sidecar health does not wait on it."""
        if self._client_initialized:
            return
        self._client_initialized = True
        if not self._qdrant_enabled:
            return
        try:
            from qdrant_client import QdrantClient  # type: ignore
            from qdrant_client.http.models import (  # type: ignore
                Distance,
                PointStruct,
                VectorParams,
            )

            self._client = QdrantClient(path=str(self.storage_path))
            self._point_struct = PointStruct
            self._ensure_collection(PointStruct, VectorParams, Distance)
        except Exception:
            self._client = None

    def _ensure_collection(self, PointStruct: Any, VectorParams: Any, Distance: Any) -> None:
        if self._client is None:
            return
        client = cast(Any, self._client)
        collections = [item.name for item in client.get_collections().collections]
        if self.collection not in collections:
            # Get dimensions from embedder if available
            dimensions = getattr(self.embedder, "dimensions", 64)
            client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=dimensions,
                    distance=Distance.COSINE,
                ),
            )

    def upsert_text(self, record_id: str, text: str, payload: dict[str, Any]) -> None:
        document = MemoryDocument(id=record_id, text=text, metadata=dict(payload))
        self.upsert_documents([document])

    def delete_text(self, record_id: str) -> bool:
        self._ensure_client()
        removed = self._documents.pop(record_id, None) is not None
        if self._client is None:
            return removed
        client = cast(Any, self._client)
        try:
            client.delete(
                collection_name=self.collection,
                points_selector={"points": [_normalize_point_id(record_id)]},
            )
            return True
        except Exception:
            return removed

    def upsert_documents(self, documents: Sequence[MemoryDocument]) -> None:
        self._ensure_client()
        vectors = self.embedder.embed([document.text for document in documents])
        if self._client is not None:
            points = []
            point_struct = cast(Any, self._point_struct)
            client = cast(Any, self._client)
            for document, vector in zip(documents, vectors, strict=False):
                point_id = _normalize_point_id(document.id)
                points.append(
                    point_struct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "text": document.text,
                            "metadata": document.metadata,
                            "original_id": document.id,
                        },
                    )
                )
            if points:
                client.upsert(collection_name=self.collection, points=points)
            return
        for document, vector in zip(documents, vectors, strict=False):
            self._documents[document.id] = replace(document, vector=vector)

    def search(
        self,
        text: str,
        limit: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        *,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        effective_limit = top_k if top_k is not None else limit
        return self.search_hits(
            text,
            top_k=effective_limit,
            metadata_filter=metadata_filter,
        )

    def search_hits(
        self,
        text: str,
        *,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        self._ensure_client()
        metadata_filter = metadata_filter or {}
        if self._client is not None:
            query_vector = self.embedder.embed([text])[0]
            client = cast(Any, self._client)
            if hasattr(client, "search"):
                raw_points = client.search(
                    collection_name=self.collection,
                    query_vector=query_vector,
                    limit=top_k,
                )
            else:
                response = client.query_points(
                    collection_name=self.collection,
                    query=query_vector,
                    limit=top_k,
                )
                raw_points = response.points
            hits: list[SearchHit] = []
            for point in raw_points:
                payload = point.payload or {}
                metadata = dict(payload.get("metadata", {}))
                if not _match_metadata(metadata, metadata_filter):
                    continue
                hits.append(
                    SearchHit(
                        document=MemoryDocument(
                            id=str(payload.get("original_id", point.id)),
                            text=str(payload.get("text", "")),
                            metadata=metadata,
                            vector=None,
                        ),
                        score=float(point.score or 0.0),
                    )
                )
            return hits

        query_vector = self.embedder.embed([text])[0]
        hits = []
        for document in self._documents.values():
            if not _match_metadata(document.metadata, metadata_filter):
                continue
            hits.append(SearchHit(document=document, score=cosine_similarity(query_vector, document.vector or [])))
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]

    def info(self) -> SemanticCollectionInfo:
        self._ensure_client()
        if self._client is not None:
            collection = cast(Any, self._client).get_collection(self.collection)
            return SemanticCollectionInfo(
                backend="qdrant-local",
                collection_name=self.collection,
                document_count=int(collection.points_count or 0),
                path=str(self.storage_path),
            )
        return SemanticCollectionInfo(
            backend="memory",
            collection_name=self.collection,
            document_count=len(self._documents),
            path=str(self.storage_path),
        )

    def close(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            client.close()

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        try:
            self.close()
        except Exception:
            pass


def _match_metadata(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _normalize_point_id(raw_id: str) -> str:
    try:
        return str(uuid.UUID(str(raw_id)))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, str(raw_id)))
