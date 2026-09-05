from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.models import ResourceIndexRequest, ResourceRecord, ResourceUploadRequest
from app.llm.tools import ToolContext, build_default_tool_registry


def _context(resource_service: object, *, mode: str = "download", active_view: str = "resources") -> ToolContext:
    return ToolContext(
        runtime=SimpleNamespace(resource_service=resource_service),
        workspace_id="workspace-url-tool",
        session_id="session-url-tool",
        extra={
            "active_view": active_view,
            "resource_composer_intent": {"mode": mode},
        },
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
        kind="url",
        name="Imported source",
        source="https://origin.example/source",
        summary="Imported summary",
        parse_status=parse_status,
        index_status=index_status,
        canonical_source=canonical_source,
        fetched_at=fetched_at,
        warnings=warnings or [],
        quality_flags=quality_flags or [],
    )


@pytest.mark.asyncio
async def test_import_resource_url_calls_resource_service_and_returns_provenance() -> None:
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
    assert result["source"]["provenance"]["status"] == "fetched"
    upload_request = service.upload.call_args.args[1]
    index_request = service.index.call_args.args[1]
    assert isinstance(upload_request, ResourceUploadRequest)
    assert upload_request.kind == "url"
    assert upload_request.source_type == "url"
    assert isinstance(index_request, ResourceIndexRequest)
    assert index_request.enable_network is True


@pytest.mark.asyncio
async def test_import_resource_url_returns_failed_index_facts_without_hiding_error() -> None:
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
async def test_import_resource_url_rejects_non_download_or_non_resources_turn() -> None:
    service = SimpleNamespace(upload=Mock(), index=Mock())

    result = await build_default_tool_registry().invoke(
        _context(service, mode="locate", active_view="resources"),
        "import_resource_url",
        {"url": "https://example.com/source"},
    )

    assert result["ok"] is False
    assert result["error"] == "resource_import_not_allowed"
    service.upload.assert_not_called()
    service.index.assert_not_called()


@pytest.mark.asyncio
async def test_import_resource_url_rejects_missing_and_invalid_urls_before_service_call() -> None:
    service = SimpleNamespace(upload=Mock(), index=Mock())
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
    service.upload.assert_not_called()
    service.index.assert_not_called()
