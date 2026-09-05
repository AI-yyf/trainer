from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.resources.search import SearchFilters, SearchIndex


def _index_resource(
    index: SearchIndex,
    *,
    resource_id: str,
    title: str,
    path: str | None = None,
    content: str = "coach memory notes and search boundary",
    summary: str | None = None,
    symbols: list[str] | None = None,
    freshness: str,
    trust_score: float = 0.75,
    preview_tier: str = "rich",
    preview_kind: str = "text",
    source_extension: str = ".md",
) -> None:
    index.index_document(
        path=path or f"/workspace/{resource_id}.md",
        title=title,
        content=content,
        resource_id=resource_id,
        metadata={
            "project_scope": "workspace-search",
            "source_type": "local:markdown",
            "file_type": "markdown",
            "kind": "markdown",
            "index_state": "indexed",
            "summary": summary or title,
            "source": path or f"/workspace/{resource_id}.md",
            "symbols": symbols or ["coach_reply"],
            "trust_score": trust_score,
            "trust_state": "trusted",
            "updated_at": datetime(2026, 5, 3, tzinfo=UTC).isoformat(),
            "resource_freshness": freshness,
            "resource_preview_tier": preview_tier,
            "resource_preview_kind": preview_kind,
            "resource_source_extension": source_extension,
        },
    )


def test_metadata_only_search_prefers_freshness_and_exposes_rank_reasons(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    _index_resource(index, resource_id="stale-resource", title="Stale Notes", freshness="stale")
    _index_resource(index, resource_id="fresh-resource", title="Fresh Notes", freshness="fresh")

    response = index.search(
        "",
        filters=SearchFilters(project_scope="workspace-search"),
        top_k=2,
    )

    assert response.ranking_strategy == "metadata_only"
    assert response.total == 2
    assert response.results[0].resource_id == "fresh-resource"
    assert response.results[0].freshness == "fresh"
    assert response.results[0].citation_id == "citation:fresh-resource"
    assert "filtered result" in response.results[0].rank_reasons
    assert "freshness fresh" in response.results[0].rank_reasons
    assert "project scope workspace-search" in response.results[0].rank_reasons
    assert "source type local:markdown" in response.results[0].rank_reasons
    assert "training card eligible" in response.results[0].rank_reasons
    assert response.results[1].resource_id == "stale-resource"
    assert response.results[1].freshness == "stale"
    assert "freshness stale" in response.results[1].rank_reasons


def test_symbol_query_recall_uses_indexed_symbols(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    _index_resource(
        index,
        resource_id="symbol-match",
        title="Coach Notes",
        path="/workspace/guides/coach-reply.md",
        symbols=["coach_reply", "answer_policy"],
        freshness="fresh",
    )
    _index_resource(
        index,
        resource_id="symbol-no-match",
        title="Other Notes",
        path="/workspace/guides/other.md",
        symbols=["plan_update"],
        freshness="fresh",
    )

    response = index.search("coachReply", filters=SearchFilters(project_scope="workspace-search"), top_k=5)

    assert response.total >= 1
    assert response.results[0].resource_id == "symbol-match"
    assert "symbol match" in response.results[0].rank_reasons


def test_path_and_camel_case_queries_expand_into_lexical_terms(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    _index_resource(
        index,
        resource_id="path-match",
        title="Workspace Coach Reply",
        path="/workspace/plans/coachReply.md",
        symbols=["workspace_coach_reply"],
        freshness="fresh",
    )

    response = index.search("coachReply plans", filters=SearchFilters(project_scope="workspace-search"), top_k=5)

    assert response.total == 1
    assert response.results[0].resource_id == "path-match"
    assert "path match" in response.results[0].rank_reasons
    assert "title match" in response.results[0].rank_reasons
    assert {"title", "path"}.issubset(set(response.results[0].matched_fields))


def test_summary_only_resources_are_lexically_retrievable(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    _index_resource(
        index,
        resource_id="summary-match",
        title="Neutral Title",
        path="/workspace/notes/neutral.md",
        content="",
        summary="Workspace neutral handoff checklist",
        freshness="fresh",
    )

    index.index_document(
        path="/workspace/notes/other.md",
        title="Other Title",
        content="",
        resource_id="summary-no-match",
        metadata={
            "project_scope": "workspace-search",
            "source_type": "local:markdown",
            "file_type": "markdown",
            "kind": "markdown",
            "index_state": "indexed",
            "summary": "Unrelated notes",
            "source": "/workspace/notes/other.md",
            "symbols": [],
            "trust_score": 0.75,
            "trust_state": "trusted",
            "updated_at": datetime(2026, 5, 3, tzinfo=UTC).isoformat(),
            "resource_freshness": "fresh",
        },
    )

    response = index.search("handoff", filters=SearchFilters(project_scope="workspace-search"), top_k=5)

    assert response.total == 1
    assert response.results[0].resource_id == "summary-match"
    assert "summary match" in response.results[0].rank_reasons


def test_search_snippet_prefers_body_match_over_title(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    _index_resource(
        index,
        resource_id="body-match",
        title="Neutral Title",
        path="/workspace/notes/grounding.md",
        content=(
            "Intro paragraph.\n\n"
            "First viewport promise: the learner can find, trust, preview, and convert resources "
            "without losing provenance.\n\n"
            "Closing paragraph."
        ),
        summary="Grounding note",
        freshness="fresh",
    )

    response = index.search(
        "first viewport promise",
        filters=SearchFilters(project_scope="workspace-search"),
        top_k=5,
    )

    assert response.total == 1
    hit = response.results[0]
    assert hit.resource_id == "body-match"
    assert "<mark>first</mark>" in hit.snippet.lower()
    assert "learner can find" in hit.snippet.lower()
    assert hit.snippet != "Neutral Title"
    assert "content match" in hit.rank_reasons


def test_preview_semantics_are_preserved_in_search_results(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    _index_resource(
        index,
        resource_id="preview-match",
        title="Office Notes",
        path="/workspace/docs/guide.odt",
        freshness="fresh",
        preview_tier="converted",
        preview_kind="document",
        source_extension=".odt",
    )

    response = index.search("office", filters=SearchFilters(project_scope="workspace-search"), top_k=5)

    assert response.total == 1
    hit = response.results[0]
    assert hit.preview_tier == "converted"
    assert hit.preview_kind == "document"
    assert hit.source_extension == ".odt"
    assert {"title", "content"}.issubset(set(hit.matched_fields))
    assert "training card ready" in hit.match_summary


def test_blocked_trust_resources_explain_why_they_cannot_inject_training_cards(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    index.index_document(
        path="/workspace/blocked/coach-note.md",
        title="Blocked Coach Note",
        content="This blocked coach note still matches the query text.",
        resource_id="blocked-resource",
        metadata={
            "project_scope": "workspace-search",
            "source_type": "local:markdown",
            "file_type": "markdown",
            "kind": "markdown",
            "index_state": "indexed",
            "summary": "Blocked coach note",
            "source": "/workspace/blocked/coach-note.md",
            "symbols": [],
            "trust_score": 0.95,
            "trust_state": "blocked",
            "updated_at": datetime(2026, 5, 3, tzinfo=UTC).isoformat(),
            "resource_freshness": "fresh",
        },
    )

    response = index.search("blocked", filters=SearchFilters(project_scope="workspace-search"), top_k=5)

    assert response.total == 1
    hit = response.results[0]
    assert hit.can_inject_training_card is False
    assert "training card blocked (blocked)" in hit.match_summary


def test_cjk_search_matches_titles_bodies_and_mixed_queries(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    _index_resource(
        index,
        resource_id="cjk-zh",
        title="AI 资料库设计",
        content="这份中文正文讲解机器学习与资料库检索。",
        freshness="fresh",
    )
    _index_resource(
        index,
        resource_id="cjk-ja",
        title="日本語学習",
        content="これは日本語の入門資料です。",
        freshness="fresh",
    )
    _index_resource(
        index,
        resource_id="cjk-ko",
        title="한국어 훈련",
        content="초보자를 위한 한국어 자료입니다.",
        freshness="fresh",
    )
    filters = SearchFilters(project_scope="workspace-search")

    title_response = index.search("资料库", filters=filters, top_k=5)
    body_response = index.search("学习", filters=filters, top_k=5)
    japanese_response = index.search("入門", filters=filters, top_k=5)
    korean_response = index.search("자료", filters=filters, top_k=5)
    mixed_response = index.search("AI 资料库", filters=filters, top_k=5)

    assert [result.resource_id for result in title_response.results] == ["cjk-zh"]
    assert [result.resource_id for result in body_response.results] == ["cjk-zh"]
    assert "<mark>学习</mark>" in body_response.results[0].snippet
    assert [result.resource_id for result in japanese_response.results] == ["cjk-ja"]
    assert [result.resource_id for result in korean_response.results] == ["cjk-ko"]
    assert [result.resource_id for result in mixed_response.results] == ["cjk-zh"]


def test_cjk_index_backfills_existing_rows_and_respects_metadata_filters(tmp_path: Path) -> None:
    database_path = tmp_path / "search.db"
    index = SearchIndex(database_path)
    index.index_document(
        path="/workspace/current.md",
        title="当前资料",
        content="当前工作区包含机器学习笔记。",
        resource_id="current-cjk",
        metadata={
            "project_scope": "current-workspace",
            "source_type": "local:markdown",
            "file_type": "markdown",
            "trust_state": "trusted",
        },
    )
    index.index_document(
        path="/workspace/other.txt",
        title="其他资料",
        content="其他工作区也包含机器学习笔记。",
        resource_id="other-cjk",
        metadata={
            "project_scope": "other-workspace",
            "source_type": "local:text",
            "file_type": "text",
            "trust_state": "trusted",
        },
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE resource_search_cjk")

    reopened = SearchIndex(database_path)
    response = reopened.search(
        "学习",
        filters=SearchFilters(project_scope="current-workspace", source_type="local:markdown"),
        top_k=5,
    )

    assert [result.resource_id for result in response.results] == ["current-cjk"]
    assert reopened.delete_document("current-cjk") is True
    assert reopened.search("学习", filters=SearchFilters(project_scope="current-workspace")).total == 0
    reopened.clear()
    assert reopened.document_count() == 0


def test_cjk_query_normalization_keeps_fts_special_characters_safe(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    _index_resource(
        index,
        resource_id="safe-cjk",
        title="资料库说明",
        content="资料库可用于安全检索。",
        freshness="fresh",
    )
    filters = SearchFilters(project_scope="workspace-search")

    response = index.search('资料库" OR "*', filters=filters, top_k=5)
    invalid_response = index.search('") OR (', filters=filters, top_k=5)

    assert [result.resource_id for result in response.results] == ["safe-cjk"]
    assert invalid_response.total == 0


def test_inferred_file_type_recognizes_eml_and_epub(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")

    assert index._infer_file_type("/workspace/notes/guide.epub") == "epub"
    assert index._infer_file_type("/workspace/mail/coach.eml") == "email"


def test_search_index_requires_explicit_database_path_or_resolver() -> None:
    try:
        SearchIndex(None)
    except RuntimeError as exc:
        assert "explicit database path" in str(exc).lower()
    else:
        raise AssertionError("SearchIndex(None) should require an explicit database path or resolver")
