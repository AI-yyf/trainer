"""SQLite FTS5 full-text search for resources."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

_CJK_CHAR_CLASS = (
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f"
    r"\u3040-\u30ff\uff66-\uff9f\u1100-\u11ff\u3130-\u318f\uac00-\ud7af"
)
_CJK_SEQUENCE_PATTERN = re.compile(rf"[{_CJK_CHAR_CLASS}]+")
_QUERY_TOKEN_PATTERN = re.compile(rf"[A-Za-z0-9_./:-]+|[{_CJK_CHAR_CLASS}]+")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Search result with ranking metadata
@dataclass(slots=True)
class SearchResult:
    """A single search result with ranking scores."""

    resource_id: str
    path: str
    title: str
    snippet: str
    source: str
    source_type: str
    summary: str
    trust_score: float
    trust_state: str
    freshness: str
    file_type: str
    project_scope: str
    kind: str
    index_state: str
    citation_id: str
    can_inject_training_card: bool
    updated_at: datetime
    preview_tier: str = ""
    preview_kind: str = ""
    source_extension: str = ""
    rank_score: float = 0.0
    rank_reasons: list[str] = field(default_factory=list)
    matched_fields: list[str] = field(default_factory=list)
    match_summary: str = ""


@dataclass(slots=True)
class SearchFilters:
    """Filters for search queries."""

    project_scope: str | None = None
    trust_state: str | None = None
    file_type: str | None = None
    source_type: str | None = None
    kind: str | None = None
    index_state: str | None = None


@dataclass(slots=True)
class SearchResponse:
    """Response from a search query."""

    results: list[SearchResult]
    query: str
    total: int
    filters: SearchFilters
    ranking_strategy: str = "lexical_first"


class ResourceSearchManifest(Protocol):
    """The resource fields needed to populate a search index entry."""

    resource_id: str
    origin_path_or_url: str
    project_scope: str
    trust_state: str
    preview_type: str
    source_type: str
    index_state: str


class SearchIndex:
    """SQLite FTS5-powered search index for resources."""

    def __init__(
        self,
        database_path: Path | None = None,
        *,
        database_path_resolver: Callable[[], Path | None] | None = None,
    ) -> None:
        self._configured_db_path = database_path
        self._database_path_resolver = database_path_resolver
        self._connection: sqlite3.Connection | None = None
        self._initialize()

    def set_database_path_resolver(self, resolver: Callable[[], Path | None] | None) -> None:
        self._database_path_resolver = resolver
        self._close()
        self._initialize()

    def close(self) -> None:
        """Close the cached connection."""
        self._close()

    def _resolved_db_path(self) -> Path:
        if self._database_path_resolver is not None:
            resolved = self._database_path_resolver()
            if resolved is not None:
                path = Path(resolved)
                path.parent.mkdir(parents=True, exist_ok=True)
                return path
        if self._configured_db_path is not None:
            self._configured_db_path.parent.mkdir(parents=True, exist_ok=True)
            return self._configured_db_path
        raise RuntimeError("SearchIndex requires an explicit database path or path resolver")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._resolved_db_path()))
        conn.row_factory = sqlite3.Row
        return conn

    def _close(self) -> None:
        """Close the in-memory connection if cached."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _initialize(self) -> None:
        """Create FTS5 virtual table and metadata table."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            # FTS5 virtual table for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS resource_search
                USING fts5(
                    resource_id,
                    path,
                    title,
                    content,
                    file_type,
                    tokenize='porter unicode61'
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS resource_search_cjk
                USING fts5(
                    resource_id UNINDEXED,
                    terms,
                    tokenize='unicode61'
                )
            """)

            # Metadata table for filtering and ranking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_metadata (
                    resource_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    file_type TEXT NOT NULL DEFAULT '',
                    project_scope TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT '',
                    index_state TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT '',
                    symbols TEXT NOT NULL DEFAULT '',
                    trust_score REAL NOT NULL DEFAULT 0.0,
                    trust_state TEXT NOT NULL DEFAULT 'unverified',
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
            """)

            # Index for common filters
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_search_project
                ON search_metadata(project_scope)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_search_trust
                ON search_metadata(trust_state)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_search_type
                ON search_metadata(file_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_search_source_type
                ON search_metadata(source_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_search_index_state
                ON search_metadata(index_state)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_search_kind
                ON search_metadata(kind)
            """)
            self._backfill_cjk_index(conn)
            conn.commit()
        finally:
            conn.close()

    def index_document(
        self,
        path: str,
        title: str,
        content: str,
        *,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Index a document for search.

        Args:
            path: File path or URI
            title: Document title
            content: Full text content to index
            resource_id: Optional unique ID (generated if not provided)
            metadata: Optional metadata dict (project_scope, trust_score, trust_state, file_type)

        Returns:
            The resource_id of the indexed document
        """
        if resource_id is None:
            resource_id = f"doc_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{hash(path) % 100000:05d}"

        metadata = metadata or {}
        file_type = metadata.get("file_type", self._infer_file_type(path))
        project_scope = metadata.get("project_scope", "")
        source_type = metadata.get("source_type", "")
        index_state = metadata.get("index_state", "")
        summary = metadata.get("summary", title)
        source = metadata.get("source", path)
        kind = metadata.get("kind", file_type)
        symbols_value = metadata.get("symbols", "")
        if isinstance(symbols_value, (list, tuple)):
            symbols = json.dumps([str(item) for item in symbols_value if str(item).strip()])
        else:
            symbols = str(symbols_value or "")
        searchable_content = "\n".join(
            part
            for part in (
                str(content or ""),
                str(title or ""),
                str(path or ""),
                str(summary or ""),
                str(source or ""),
                symbols,
            )
            if part.strip()
        )
        trust_score = float(metadata.get("trust_score", 0.0))
        trust_state = metadata.get("trust_state", "unverified")
        updated_at = metadata.get("updated_at")

        conn = self._connect()
        try:
            conn.execute("DELETE FROM resource_search WHERE resource_id = ?", (resource_id,))
            conn.execute("DELETE FROM resource_search_cjk WHERE resource_id = ?", (resource_id,))
            conn.execute("""
                INSERT INTO resource_search (resource_id, path, title, content, file_type)
                VALUES (?, ?, ?, ?, ?)
            """, (resource_id, path, title, searchable_content, file_type))
            conn.execute(
                "INSERT INTO resource_search_cjk (resource_id, terms) VALUES (?, ?)",
                (resource_id, " ".join(self._cjk_index_terms(searchable_content))),
            )

            conn.execute("""
                INSERT OR REPLACE INTO search_metadata (
                    resource_id, path, title, file_type, project_scope, source_type,
                    index_state, summary, source, kind, symbols,
                    trust_score, trust_state, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                resource_id,
                path,
                title,
                file_type,
                project_scope,
                source_type,
                index_state,
                summary,
                source,
                kind,
                symbols,
                trust_score,
                trust_state,
                updated_at or utc_now().isoformat(),
                json.dumps(metadata),
            ))
            conn.commit()
        finally:
            conn.close()

        return resource_id

    def document_content(self, resource_id: str) -> str:
        """Return previously indexed searchable text for a resource, if any."""

        lookup_id = str(resource_id or "").strip()
        if not lookup_id:
            return ""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT content FROM resource_search WHERE resource_id = ?",
                (lookup_id,),
            ).fetchone()
            if row is None:
                return ""
            return str(row["content"] or "")
        except sqlite3.Error:
            return ""
        finally:
            conn.close()

    def index_from_manifest(
        self,
        manifest: ResourceSearchManifest,
        content: str,
    ) -> str:
        """Index a document from a resource search manifest.

        Args:
            manifest: Resource object exposing search metadata
            content: Full text content to index

        Returns:
            The resource_id of the indexed document
        """
        return self.index_document(
            path=manifest.origin_path_or_url,
            title=manifest.resource_id,
            content=content,
            resource_id=manifest.resource_id,
            metadata={
                "project_scope": manifest.project_scope,
                "trust_state": manifest.trust_state,
                "file_type": manifest.preview_type,
                "source_type": manifest.source_type,
                "index_state": manifest.index_state,
                "kind": manifest.preview_type,
                "summary": manifest.origin_path_or_url,
                "source": manifest.origin_path_or_url,
                "symbols": [],
            },
        )

    def search(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        top_k: int = 10,
        recency_boost_days: int = 30,
        trust_weight: float = 0.6,
        recency_weight: float = 0.4,
    ) -> SearchResponse:
        """Search indexed documents.

        Args:
            query: Search query string
            filters: Optional search filters
            top_k: Maximum number of results
            recency_boost_days: Days to consider "recent" for boosting
            trust_weight: Weight for trust score in ranking (0-1)
            recency_weight: Weight for recency in ranking (0-1)

        Returns:
            SearchResponse with ranked results
        """
        filters = filters or SearchFilters()
        query_text = query.strip()
        if not query_text:
            return self._search_by_filters(filters, top_k)

        fts_query = self._normalize_query(query_text)
        query_terms = self._query_terms(query_text)

        conn = self._connect()
        try:
            fts_results = self._search_fts_rows(
                conn,
                query_text=query_text,
                fts_query=fts_query,
                cjk_query=self._normalize_cjk_query(query_text),
                file_type=filters.file_type,
                limit=max(top_k * 3, top_k),
            )
            if not fts_results:
                return SearchResponse(results=[], query=query_text, total=0, filters=filters)

            resource_ids = [str(row["resource_id"]) for row in fts_results]
            metadata_sql = """
                SELECT
                    resource_id,
                    path,
                    title,
                    file_type,
                    project_scope,
                    source_type,
                    index_state,
                    summary,
                    source,
                    kind,
                    symbols,
                    metadata_json,
                    trust_score,
                    trust_state,
                    updated_at
                FROM search_metadata
                WHERE resource_id IN ({})
            """.format(",".join("?" * len(resource_ids)))

            metadata_rows = conn.execute(metadata_sql, resource_ids).fetchall()
            metadata_by_id = {str(row["resource_id"]): row for row in metadata_rows}

            filtered_results: list[SearchResult] = []
            for fts_row in fts_results:
                resource_id = str(fts_row["resource_id"])
                meta = metadata_by_id.get(resource_id)
                if meta is None:
                    continue

                meta_payload = self._parse_json_metadata(meta["metadata_json"])
                preview_tier = str(
                    meta_payload.get("resource_preview_tier")
                    or meta_payload.get("preview_tier")
                    or ""
                ).strip()
                preview_kind = str(
                    meta_payload.get("resource_preview_kind")
                    or meta_payload.get("preview_kind")
                    or ""
                ).strip()
                source_extension = str(
                    meta_payload.get("resource_source_extension")
                    or meta_payload.get("source_extension")
                    or ""
                ).strip()
                if filters.project_scope and str(meta["project_scope"]) != filters.project_scope:
                    continue
                if filters.trust_state and str(meta["trust_state"]) != filters.trust_state:
                    continue
                if filters.file_type and str(meta["file_type"]) != filters.file_type:
                    continue
                if filters.source_type and str(meta["source_type"]) != filters.source_type:
                    continue
                if filters.kind and str(meta["kind"] or meta["file_type"]) != filters.kind:
                    continue
                if filters.index_state and str(meta["index_state"]) != filters.index_state:
                    continue

                try:
                    updated = datetime.fromisoformat(str(meta["updated_at"]))
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                except Exception:
                    updated = utc_now() - timedelta(days=365)

                trust = float(meta["trust_score"] or 0.0)
                freshness = str(meta_payload.get("resource_freshness") or meta_payload.get("freshness") or "").strip().lower()
                if freshness not in {"fresh", "stale", "unknown"}:
                    freshness = "unknown"
                days_old = max(0, (utc_now() - updated).days)
                recency = 1.0 if days_old <= 1 else max(0.0, 1.0 - (days_old / recency_boost_days))
                freshness_boost = {
                    "fresh": 1.0,
                    "stale": 0.35,
                    "unknown": 0.6,
                }.get(freshness, 0.6)

                field_matches = self._field_match_reasons(
                    query_terms,
                    title=str(meta["title"]),
                    path=str(meta["path"]),
                    summary=str(meta["summary"] or meta["title"]),
                    snippet=str(fts_row["snippet"] or ""),
                    symbols=str(meta["symbols"] or ""),
                )
                lexical_score = self._lexical_score(float(fts_row["fts_rank"] or 0.0), field_matches)
                rank_score = round(
                    (lexical_score * 0.75)
                    + (trust * max(0.0, min(trust_weight, 1.0)) * 0.15)
                    + (recency * max(0.0, min(recency_weight, 1.0)) * 0.07)
                    + (freshness_boost * 0.03),
                    3,
                )
                rank_reasons = [reason for reason, matched in field_matches.items() if matched]
                if trust >= 0.7:
                    rank_reasons.append("high trust")
                elif trust >= 0.35:
                    rank_reasons.append("moderate trust")
                if recency >= 0.8:
                    rank_reasons.append("recent")
                elif recency >= 0.5:
                    rank_reasons.append("somewhat recent")
                if freshness == "fresh":
                    rank_reasons.append("freshness fresh")
                elif freshness == "stale":
                    rank_reasons.append("freshness stale")
                else:
                    rank_reasons.append("freshness unknown")
                if str(meta["project_scope"] or "").strip():
                    rank_reasons.append(f"project scope {str(meta['project_scope'])}")
                if str(meta["source_type"] or meta_payload.get("source_type", "")).strip():
                    rank_reasons.append(f"source type {str(meta['source_type'] or meta_payload.get('source_type', ''))}")
                if str(meta["index_state"]) == "indexed":
                    rank_reasons.append("indexed")
                if bool(trust >= 0.35 and str(meta["trust_state"]) not in {"blocked", "rejected"}):
                    rank_reasons.append("training card eligible")
                matched_fields = [
                    label.removesuffix(" match")
                    for label, matched in field_matches.items()
                    if matched and label in {"title match", "path match", "symbol match", "summary match", "content match"}
                ]
                match_summary = self._match_summary(
                    query_text=query_text,
                    citation_id=f"citation:{resource_id}",
                    project_scope=str(meta["project_scope"]),
                    field_matches=field_matches,
                    trust=trust,
                    trust_state=str(meta["trust_state"]),
                    freshness=freshness,
                    can_inject_training_card=bool(
                        trust >= 0.35 and str(meta["trust_state"]) not in {"blocked", "rejected"}
                    ),
                    metadata_only=False,
                )

                result = SearchResult(
                    resource_id=resource_id,
                    path=str(meta["path"]),
                    title=str(meta["title"]),
                    snippet=str(fts_row["snippet"]) or str(meta["summary"] or meta["title"]),
                    source=str(meta["source"] or meta["path"]),
                    source_type=str(meta["source_type"] or meta_payload.get("source_type", "")),
                    summary=str(meta["summary"] or meta["title"]),
                    trust_score=trust,
                    trust_state=str(meta["trust_state"]),
                    freshness=freshness,
                    file_type=str(meta["file_type"]),
                    project_scope=str(meta["project_scope"]),
                    kind=str(meta["kind"] or meta["file_type"]),
                    index_state=str(meta["index_state"]),
                    citation_id=f"citation:{resource_id}",
                    can_inject_training_card=bool(
                        trust >= 0.35 and str(meta["trust_state"]) not in {"blocked", "rejected"}
                    ),
                    preview_tier=preview_tier,
                    preview_kind=preview_kind,
                    source_extension=source_extension,
                    updated_at=updated,
                    rank_score=rank_score,
                    rank_reasons=rank_reasons,
                    matched_fields=matched_fields,
                    match_summary=match_summary,
                )
                filtered_results.append(result)

            filtered_results.sort(
                key=lambda item: (item.rank_score, item.updated_at.isoformat(), item.title.lower()),
                reverse=True,
            )
            return SearchResponse(
                results=filtered_results[:top_k],
                query=query_text,
                total=len(filtered_results),
                filters=filters,
            )
        finally:
            conn.close()

    def _search_fts_rows(
        self,
        conn: sqlite3.Connection,
        *,
        query_text: str,
        fts_query: str,
        cjk_query: str | None,
        file_type: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows_by_id: dict[str, dict[str, Any]] = {}
        if fts_query != '""':
            fts_sql = """
                SELECT DISTINCT
                    resource_id,
                    path,
                    title,
                    snippet(resource_search, 3, '<mark>', '</mark>', '...', 32) as snippet,
                    bm25(resource_search) as fts_rank
                FROM resource_search
                WHERE resource_search MATCH ?
            """
            params: list[Any] = [fts_query]
            if file_type:
                fts_sql += " AND file_type = ?"
                params.append(file_type)
            fts_sql += " ORDER BY fts_rank LIMIT ?"
            params.append(limit)
            for row in conn.execute(fts_sql, params).fetchall():
                rows_by_id[str(row["resource_id"])] = dict(row)

        if not cjk_query:
            return list(rows_by_id.values())

        cjk_sql = """
            SELECT resource_id, bm25(resource_search_cjk) as fts_rank
            FROM resource_search_cjk
            WHERE resource_search_cjk MATCH ?
        """
        cjk_params: list[Any] = [cjk_query]
        if file_type:
            cjk_sql += """
                AND resource_id IN (
                    SELECT resource_id FROM resource_search WHERE file_type = ?
                )
            """
            cjk_params.append(file_type)
        cjk_sql += " ORDER BY fts_rank LIMIT ?"
        cjk_params.append(limit)
        cjk_rows = conn.execute(cjk_sql, cjk_params).fetchall()
        missing_ids = [
            str(row["resource_id"])
            for row in cjk_rows
            if str(row["resource_id"]) not in rows_by_id
        ]
        if not missing_ids:
            return list(rows_by_id.values())

        document_sql = """
            SELECT resource_id, path, title, content
            FROM resource_search
            WHERE resource_id IN ({})
        """.format(",".join("?" * len(missing_ids)))
        documents_by_id = {
            str(row["resource_id"]): row
            for row in conn.execute(document_sql, missing_ids).fetchall()
        }
        for row in cjk_rows:
            resource_id = str(row["resource_id"])
            document = documents_by_id.get(resource_id)
            if document is None:
                continue
            rows_by_id[resource_id] = {
                "resource_id": resource_id,
                "path": str(document["path"]),
                "title": str(document["title"]),
                "snippet": self._cjk_snippet(str(document["content"] or ""), query_text),
                "fts_rank": float(row["fts_rank"] or 0.0),
            }
        return list(rows_by_id.values())

    def _search_by_filters(
        self,
        filters: SearchFilters,
        top_k: int,
    ) -> SearchResponse:
        """Search by filters only (no text query)."""
        conn = self._connect()
        try:
            sql = """
                SELECT
                    resource_id,
                    path,
                    title,
                    file_type,
                    project_scope,
                    source_type,
                    index_state,
                    summary,
                    source,
                    kind,
                    symbols,
                    metadata_json,
                    trust_score,
                    trust_state,
                    updated_at
                FROM search_metadata
                WHERE 1=1
            """
            params: list[Any] = []

            if filters.project_scope:
                sql += " AND project_scope = ?"
                params.append(filters.project_scope)
            if filters.trust_state:
                sql += " AND trust_state = ?"
                params.append(filters.trust_state)
            if filters.file_type:
                sql += " AND file_type = ?"
                params.append(filters.file_type)
            if filters.source_type:
                sql += " AND source_type = ?"
                params.append(filters.source_type)
            if filters.kind:
                sql += " AND kind = ?"
                params.append(filters.kind)
            if filters.index_state:
                sql += " AND index_state = ?"
                params.append(filters.index_state)

            sql += " ORDER BY trust_score DESC, updated_at DESC LIMIT ?"
            params.append(top_k)

            rows = conn.execute(sql, params).fetchall()

            results: list[SearchResult] = []
            for row in rows:
                try:
                    updated = datetime.fromisoformat(str(row["updated_at"]))
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                except Exception:
                    updated = utc_now()
                payload = self._parse_json_metadata(row["metadata_json"])
                preview_tier = str(
                    payload.get("resource_preview_tier")
                    or payload.get("preview_tier")
                    or ""
                ).strip()
                preview_kind = str(
                    payload.get("resource_preview_kind")
                    or payload.get("preview_kind")
                    or ""
                ).strip()
                source_extension = str(
                    payload.get("resource_source_extension")
                    or payload.get("source_extension")
                    or ""
                ).strip()
                freshness = str(payload.get("resource_freshness") or payload.get("freshness") or "").strip().lower()
                if freshness not in {"fresh", "stale", "unknown"}:
                    freshness = "unknown"
                freshness_boost = {
                    "fresh": 1.0,
                    "stale": 0.35,
                    "unknown": 0.6,
                }.get(freshness, 0.6)

                rank_reasons = ["filtered result", f"freshness {freshness}"]
                if str(row["project_scope"]).strip():
                    rank_reasons.append(f"project scope {str(row['project_scope'])}")
                if str(row["source_type"] or payload.get("source_type", "")).strip():
                    rank_reasons.append(f"source type {str(row['source_type'] or payload.get('source_type', ''))}")
                if str(row["index_state"]) == "indexed":
                    rank_reasons.append("indexed")
                if float(row["trust_score"] or 0.0) >= 0.35 and str(row["trust_state"]) not in {"blocked", "rejected"}:
                    rank_reasons.append("training card eligible")
                matched_fields = ["filtered result"]
                match_summary = self._match_summary(
                    query_text="",
                    citation_id=f"citation:{row['resource_id']}",
                    project_scope=str(row["project_scope"]),
                    field_matches={},
                    trust=float(row["trust_score"] or 0.0),
                    trust_state=str(row["trust_state"]),
                    freshness=freshness,
                    can_inject_training_card=bool(
                        float(row["trust_score"] or 0.0) >= 0.35
                        and str(row["trust_state"]) not in {"blocked", "rejected"}
                    ),
                    metadata_only=True,
                )

                results.append(
                    SearchResult(
                        resource_id=str(row["resource_id"]),
                        path=str(row["path"]),
                        title=str(row["title"]),
                        snippet=str(row["summary"] or row["title"]),
                        source=str(row["source"] or row["path"]),
                        source_type=str(row["source_type"] or payload.get("source_type", "")),
                        summary=str(row["summary"] or row["title"]),
                        trust_score=float(row["trust_score"] or 0.0),
                        trust_state=str(row["trust_state"]),
                        freshness=freshness,
                        file_type=str(row["file_type"]),
                        project_scope=str(row["project_scope"]),
                        kind=str(row["kind"] or row["file_type"]),
                        index_state=str(row["index_state"]),
                        citation_id=f"citation:{row['resource_id']}",
                        can_inject_training_card=bool(
                            float(row["trust_score"] or 0.0) >= 0.35
                            and str(row["trust_state"]) not in {"blocked", "rejected"}
                        ),
                        preview_tier=preview_tier,
                        preview_kind=preview_kind,
                        source_extension=source_extension,
                        updated_at=updated,
                        rank_score=round(
                            (float(row["trust_score"] or 0.0) * 0.85) + (freshness_boost * 0.15),
                            3,
                        ),
                        rank_reasons=rank_reasons,
                        matched_fields=matched_fields,
                        match_summary=match_summary,
                    )
                )

            results.sort(
                key=lambda item: (item.rank_score, item.updated_at.isoformat(), item.title.lower()),
                reverse=True,
            )
            return SearchResponse(
                results=results,
                query="",
                total=len(results),
                filters=filters,
                ranking_strategy="metadata_only",
            )
        finally:
            conn.close()

    def _parse_json_metadata(self, raw: object) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(str(raw))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _backfill_cjk_index(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            DELETE FROM resource_search_cjk
            WHERE resource_id NOT IN (SELECT resource_id FROM resource_search)
        """)
        source_rows = conn.execute("""
            SELECT resource_search.resource_id, resource_search.content
            FROM resource_search
            LEFT JOIN resource_search_cjk
                ON resource_search_cjk.resource_id = resource_search.resource_id
            WHERE resource_search_cjk.resource_id IS NULL
        """).fetchall()
        for row in source_rows:
            resource_id = str(row["resource_id"])
            conn.execute(
                "INSERT INTO resource_search_cjk (resource_id, terms) VALUES (?, ?)",
                (resource_id, " ".join(self._cjk_index_terms(str(row["content"] or "")))),
            )

    def _cjk_index_terms(self, value: str) -> list[str]:
        terms: list[str] = []
        for sequence in _CJK_SEQUENCE_PATTERN.findall(value):
            terms.extend(sequence)
            terms.extend(sequence[index:index + 2] for index in range(len(sequence) - 1))
        return terms

    def _normalize_cjk_query(self, query: str) -> str | None:
        terms: list[str] = []
        for sequence in _CJK_SEQUENCE_PATTERN.findall(query):
            if len(sequence) == 1:
                terms.append(sequence)
            else:
                terms.extend(sequence[index:index + 2] for index in range(len(sequence) - 1))
        if not terms:
            return None
        unique_terms = list(dict.fromkeys(terms))
        return " AND ".join(f'"{term}"' for term in unique_terms)

    def _cjk_snippet(self, content: str, query: str) -> str:
        source = content.strip()
        if not source:
            return ""
        normalized_source = source.casefold()
        for term in _CJK_SEQUENCE_PATTERN.findall(query):
            start = normalized_source.find(term.casefold())
            if start < 0:
                continue
            end = start + len(term)
            excerpt_start = max(0, start - 80)
            excerpt_end = min(len(source), end + 160)
            prefix = "..." if excerpt_start else ""
            suffix = "..." if excerpt_end < len(source) else ""
            excerpt = source[excerpt_start:excerpt_end]
            match_start = start - excerpt_start
            match_end = end - excerpt_start
            return (
                f"{prefix}{excerpt[:match_start]}<mark>{excerpt[match_start:match_end]}</mark>"
                f"{excerpt[match_end:]}{suffix}"
            )
        return source[:256]

    def _query_terms(self, query: str) -> list[str]:
        raw_tokens = _QUERY_TOKEN_PATTERN.findall(query)
        terms: list[str] = []
        seen: set[str] = set()
        for token in raw_tokens:
            if _CJK_SEQUENCE_PATTERN.fullmatch(token):
                lowered = token.lower()
                if lowered not in seen:
                    seen.add(lowered)
                    terms.append(lowered)
                continue
            for fragment in re.split(r"[./:-]+", token):
                if not fragment:
                    continue
                snake_parts = [part for part in fragment.split("_") if part]
                if not snake_parts:
                    snake_parts = [fragment]
                for snake_part in snake_parts:
                    camel_parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", snake_part).split()
                    for part in camel_parts:
                        lowered = part.lower()
                        if lowered and lowered not in seen:
                            seen.add(lowered)
                            terms.append(lowered)
        return terms[:12]

    def _field_match_reasons(
        self,
        query_terms: list[str],
        *,
        title: str,
        path: str,
        summary: str,
        snippet: str,
        symbols: str,
    ) -> dict[str, bool]:
        haystacks = {
            "title match": title.lower(),
            "path match": path.lower(),
            "summary match": summary.lower(),
            "symbol match": symbols.lower(),
            "content match": snippet.lower(),
        }
        if not query_terms:
            return {"title match": True, "path match": True, "summary match": False, "symbol match": False, "content match": False}
        matches: dict[str, bool] = {}
        for reason, haystack in haystacks.items():
            matches[reason] = any(term in haystack for term in query_terms)
        return matches

    def _lexical_score(self, fts_rank: float, field_matches: dict[str, bool]) -> float:
        field_score = 0.0
        field_weights = {
            "title match": 0.35,
            "path match": 0.25,
            "symbol match": 0.2,
            "summary match": 0.1,
            "content match": 0.1,
        }
        for reason, weight in field_weights.items():
            if field_matches.get(reason):
                field_score += weight
        bm25_bonus = 1.0 / (1.0 + abs(fts_rank))
        return min(1.0, field_score + (bm25_bonus * 0.25))

    def _match_summary(
        self,
        *,
        query_text: str,
        citation_id: str,
        project_scope: str,
        field_matches: dict[str, bool],
        trust: float,
        trust_state: str,
        freshness: str,
        can_inject_training_card: bool,
        metadata_only: bool,
    ) -> str:
        cues: list[str] = []
        if metadata_only:
            cues.append("metadata-only search")
        else:
            matched_fields = [
                label.removesuffix(" match")
                for label, matched in field_matches.items()
                if matched and label in {"title match", "path match", "symbol match", "summary match", "content match"}
            ]
            if matched_fields:
                cues.append(f"matched {', '.join(matched_fields[:3])}")
            elif query_text.strip():
                cues.append("matched indexed content")
        if project_scope.strip():
            cues.append(f"project scope {project_scope}")
        if citation_id.strip():
            cues.append(f"citation {citation_id}")
        if freshness == "fresh":
            cues.append("fresh")
        elif freshness == "stale":
            cues.append("stale")
        else:
            cues.append("freshness unknown")
        if trust >= 0.7:
            cues.append("high trust")
        elif trust >= 0.35:
            cues.append("moderate trust")
        else:
            cues.append("low trust")
        if can_inject_training_card:
            cues.append("training card ready")
        else:
            normalized_trust_state = str(trust_state or "").strip().lower()
            if normalized_trust_state in {"blocked", "rejected"}:
                cues.append(f"training card blocked ({normalized_trust_state})")
            else:
                cues.append("training card blocked (low trust)")
        return "; ".join(cues)

    def _normalize_query(self, query: str) -> str:
        """Normalize query for FTS5 search."""
        terms = self._query_terms(query)
        if not terms:
            return '""'

        # Use OR for multiple terms, prefix match with *
        fts_terms = [f'"{term}"*' for term in terms if term.strip()]
        return " OR ".join(fts_terms) if fts_terms else '""'

    def _infer_file_type(self, path: str) -> str:
        """Infer file type from path extension."""
        suffix = Path(path).suffix.lower()
        type_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".md": "markdown",
            ".txt": "text",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".pdf": "pdf",
            ".epub": "epub",
            ".eml": "email",
            ".html": "html",
            ".css": "css",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "header",
        }
        return type_map.get(suffix, "unknown")

    def delete_document(self, resource_id: str) -> bool:
        """Remove a document from the index.

        Args:
            resource_id: The resource ID to remove

        Returns:
            True if document was found and removed
        """
        conn = self._connect()
        try:
            conn.execute("DELETE FROM resource_search WHERE resource_id = ?", (resource_id,))
            conn.execute("DELETE FROM resource_search_cjk WHERE resource_id = ?", (resource_id,))
            conn.execute("DELETE FROM search_metadata WHERE resource_id = ?", (resource_id,))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def clear(self) -> None:
        """Clear all indexed documents."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM resource_search")
            conn.execute("DELETE FROM resource_search_cjk")
            conn.execute("DELETE FROM search_metadata")
            conn.commit()
        finally:
            conn.close()

    def document_count(self) -> int:
        """Get the number of indexed documents."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM search_metadata").fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            conn.close()


# Backward compatibility alias
FullTextSearchIndex = SearchIndex
