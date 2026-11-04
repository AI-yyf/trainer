from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.models import ResourceIndexRequest, ResourceRecord, ResourceUploadRequest
from app.llm.tools import ToolContext, build_default_tool_registry
from app.resources.capture import CapturedSource


def _context(
    resource_service: object,
    *,
    mode: str = "download",
    active_view: str = "resources",
    runtime: object | None = None,
) -> ToolContext:
    return ToolContext(
        runtime=runtime or SimpleNamespace(resource_service=resource_service),
        workspace_id="workspace-url-tool",
        session_id="session-url-tool",
        extra={
            "active_view": active_view,
            "resource_composer_intent": {"mode": mode},
        },
    )


def _captured_source() -> CapturedSource:
    return CapturedSource(
        kind="web",
        source_url="https://final.example/source",
        title="Imported source",
        content="# Imported source\n\nBody with [link](https://example.com).\n",
        content_encoding=None,
        upload_kind="markdown",
        tags=(
            "trainer-capture:web",
            "captured-from:https://origin.example/source",
        ),
        capture_url="https://final.example/source",
        content_hash="hash",
        selection_present=False,
        source_domain="example.com",
        captured_at="2026-07-30T00:00:00+00:00",
    )


def _resource(
    *,
    resource_id: str,
    index_status: str,
    parse_status: str,
    canonical_source: str = "",
    fetched_at: str | None = None,
    warnings: list[str] | None = None,
    quality_flags: list[str] | None = None,
) -> ResourceRecord:
    return ResourceRecord(
        id=resource_id,
        kind="markdown",
        name="Imported source",
        source="/library/imported-source.md",
        summary="Imported summary",
        parse_status=parse_status,
        index_status=index_status,
        canonical_source=canonical_source,
        fetched_at=fetched_at,
        warnings=warnings or [],
        quality_flags=quality_flags or [],
    )


@pytest.mark.asyncio
async def test_import_resource_url_captures_markdown_and_returns_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded = _resource(resource_id="resource-url-1", index_status="pending", parse_status="pending")
    indexed = _resource(
        resource_id="resource-url-1",
        index_status="indexed",
        parse_status="parsed",
        canonical_source="https://final.example/source",
        fetched_at="2026-07-30T00:00:00+00:00",
    )
    registry = SimpleNamespace(
        get=Mock(
            return_value=SimpleNamespace(
                metadata={
                    "source_provenance": {
                        "status": "fetched",
                        "final_url": "https://final.example/source",
                        "fetched_at": "2026-07-30T00:00:00+00:00",
                        "content_type": "text/html",
                    }
                }
            )
        )
    )
    service = SimpleNamespace(
        registry=registry,
        upload=Mock(return_value=uploaded),
        index=Mock(return_value=indexed),
    )
    monkeypatch.setattr("app.llm.tools.capture_source", lambda *args, **kwargs: _captured_source())

    result = await build_default_tool_registry().invoke(
        _context(service),
        "import_resource_url",
        {"url": "https://origin.example/source", "tags": ["docs"]},
    )

    assert result["ok"] is True
    assert result["resource_id"] == "resource-url-1"
    assert result["status"] == "indexed"
    assert result["source"]["requested_url"] == "https://origin.example/source"
    assert result["source"]["canonical_url"] == "https://final.example/source"
    assert result["source"]["content_format"] == "markdown"
    assert result["source"]["provenance"]["status"] == "fetched"
    upload_request = service.upload.call_args.args[1]
    index_request = service.index.call_args.args[1]
    assert isinstance(upload_request, ResourceUploadRequest)
    assert upload_request.kind == "markdown"
    assert upload_request.source.startswith("inline://trainer-capture/web/")
    assert "# Imported source" in (upload_request.content or "")
    assert "docs" in upload_request.tags
    assert isinstance(index_request, ResourceIndexRequest)
    assert index_request.enable_network is True


@pytest.mark.asyncio
async def test_import_resource_url_returns_failed_index_facts_without_hiding_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded = _resource(resource_id="resource-url-failed", index_status="pending", parse_status="pending")
    failed = _resource(
        resource_id="resource-url-failed",
        index_status="failed",
        parse_status="failed",
        warnings=["URL fetch skipped because network fetch is not enabled."],
        quality_flags=["network_disabled", "placeholder"],
    )
    service = SimpleNamespace(
        registry=SimpleNamespace(get=Mock(return_value=SimpleNamespace(metadata={}))),
        upload=Mock(return_value=uploaded),
        index=Mock(return_value=failed),
    )
    monkeypatch.setattr("app.llm.tools.capture_source", lambda *args, **kwargs: _captured_source())

    result = await build_default_tool_registry().invoke(
        _context(service),
        "import_resource_url",
        {"url": "https://example.com/source"},
    )

    assert result["ok"] is False
    assert result["error"] == "resource_import_failed"
    assert result["status"] == "failed"
    assert "network_disabled" in result["quality_flags"]
    assert result["warnings"]


@pytest.mark.asyncio
async def test_import_resource_url_runs_from_an_ordinary_coach_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded = _resource(resource_id="resource-url-coach", index_status="pending", parse_status="pending")
    indexed = _resource(resource_id="resource-url-coach", index_status="indexed", parse_status="parsed")
    service = SimpleNamespace(
        registry=SimpleNamespace(get=Mock(return_value=SimpleNamespace(metadata={}))),
        upload=Mock(return_value=uploaded),
        index=Mock(return_value=indexed),
    )
    monkeypatch.setattr("app.llm.tools.capture_source", lambda *args, **kwargs: _captured_source())

    result = await build_default_tool_registry().invoke(
        _context(service, mode="locate", active_view="coach"),
        "import_resource_url",
        {"url": "https://example.com/source"},
    )

    assert result["ok"] is True
    service.upload.assert_called_once()
    service.index.assert_called_once()


@pytest.mark.asyncio
async def test_import_resource_url_rejects_missing_and_invalid_urls_before_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(upload=Mock(), index=Mock())
    capture = Mock()
    monkeypatch.setattr("app.llm.tools.capture_source", capture)
    registry = build_default_tool_registry()
    context = _context(service)

    missing = await registry.invoke(context, "import_resource_url", {})
    invalid = await registry.invoke(context, "import_resource_url", {"url": "http://127.0.0.1:8765/private"})

    assert missing == {
        "ok": False,
        "error": "missing_url",
        "detail": "import_resource_url requires a non-empty url.",
    }
    assert invalid["ok"] is False
    assert invalid["error"] == "invalid_url"
    capture.assert_not_called()
    service.upload.assert_not_called()
    service.index.assert_not_called()


def test_resource_management_tools_are_always_visible() -> None:
    names = {
        schema["function"]["name"]
        for schema in build_default_tool_registry().as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
        )
    }
    for name in (
        "import_resource_url",
        "organize_resources",
        "list_resources",
        "delete_resource",
        "restore_resource",
        "refresh_resource_index",
    ):
        assert name in names


@pytest.mark.asyncio
async def test_delete_and_restore_resource_tools_use_reversible_trash() -> None:
    restored_resource = _resource(
        resource_id="resource-trash-1",
        index_status="pending",
        parse_status="pending",
    )
    service = SimpleNamespace(
        delete=Mock(return_value={"removed": True, "recoverable": True, "detail": "trashed"}),
        restore_resource=Mock(
            return_value={"resource": restored_resource, "reindex_required": True}
        ),
    )
    runtime = SimpleNamespace(resource_service=service, sandbox_service=None)
    context = _context(service, runtime=runtime)
    registry = build_default_tool_registry()

    deleted = await registry.invoke(context, "delete_resource", {"resource_id": "resource-trash-1"})
    restored = await registry.invoke(context, "restore_resource", {"resource_id": "resource-trash-1"})

    assert deleted["ok"] is True
    assert deleted["removed"] is True
    assert deleted["recoverable"] is True
    assert restored["ok"] is True
    assert restored["reindex_required"] is True
    assert restored["resource"]["id"] == "resource-trash-1"
    service.delete.assert_called_once()
    service.restore_resource.assert_called_once()
