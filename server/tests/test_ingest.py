from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest import IngestionRequest, ResourceIngestor
from app.ingest.service import IngestService
from app.network_fetch import ControlledFetchResponse
from app.resources.models import ResourceKind
from app.resources.service import ResourceRegistry


class ResourceIngestorTests(unittest.TestCase):
    def test_detects_code_and_preserves_line_ranges(self) -> None:
        registry = ResourceRegistry()
        ingestor = ResourceIngestor(registry)
        result = ingestor.ingest(
            IngestionRequest(
                source_uri="example.py",
                content="print('a')\nprint('b')\nprint('c')",
                chunk_size=10,
            )
        )
        self.assertEqual(result.record.kind, ResourceKind.CODE)
        self.assertGreaterEqual(len(result.chunks), 2)
        self.assertEqual(result.chunks[0].start_line, 1)

    def test_image_without_vision_returns_warning(self) -> None:
        registry = ResourceRegistry()
        ingestor = ResourceIngestor(registry)
        result = ingestor.ingest(IngestionRequest(source_uri="diagram.png"), vision_enabled=False)
        self.assertEqual(result.record.kind, ResourceKind.IMAGE)
        self.assertTrue(result.warnings)
        self.assertIsNone(result.vision_payload)

    @patch("app.ingest.service.fetch_url")
    def test_url_ingest_fetches_html_body_when_enable_network_true_and_url_allowed(self, mock_fetch_url) -> None:
        mock_fetch_url.return_value = ControlledFetchResponse(
            body=b"<html><body><main><h1>Trainer</h1><p>Coach the next patch.</p></main></body></html>",
            final_url="https://example.com/trainer",
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-07-12T00:00:00+00:00",
        )
        registry = ResourceRegistry()
        ingestor = ResourceIngestor(registry, IngestService(network_fetch_enabled=True))
        result = ingestor.ingest(
            IngestionRequest(
                source_uri="https://example.com/trainer",
                enable_network=True,
            )
        )
        self.assertEqual(result.record.kind, ResourceKind.URL)
        self.assertIn("Coach the next patch.", result.summary.text_preview)
        self.assertFalse(result.warnings)

    @patch("app.ingest.service.fetch_url")
    def test_url_ingest_requires_global_network_configuration(self, mock_fetch_url) -> None:
        registry = ResourceRegistry()
        ingestor = ResourceIngestor(registry, IngestService(network_fetch_enabled=False))

        result = ingestor.ingest(
            IngestionRequest(
                source_uri="https://example.com/configuration-gate",
                enable_network=True,
            )
        )

        mock_fetch_url.assert_not_called()
        self.assertEqual(result.source_provenance["reason_code"], "network_disabled")
        self.assertIn("network fetch is not enabled", result.warnings[0].lower())

    def test_url_ingest_rejects_loopback_private_and_metadata_hosts(self) -> None:
        registry = ResourceRegistry()
        ingestor = ResourceIngestor(registry, IngestService(network_fetch_enabled=True))
        result = ingestor.ingest(
            IngestionRequest(
                source_uri="http://127.0.0.1/private",
                enable_network=True,
            )
        )
        self.assertTrue(result.warnings)
        self.assertIn("blocked", result.warnings[0].lower())

    def test_folder_resource_summary_is_capped_and_keeps_multiple_files_visible(self) -> None:
        registry = ResourceRegistry()
        ingestor = ResourceIngestor(registry)
        text = "\n".join(f"line {index}" for index in range(600))
        result = ingestor.ingest(
            IngestionRequest(
                source_uri="workspace-folder",
                kind=ResourceKind.CODE,
                display_name="workspace-folder",
                content=text,
                chunk_size=40,
                chunk_overlap=0,
            )
        )
        self.assertEqual(result.record.kind, ResourceKind.CODE)
        self.assertGreaterEqual(len(result.chunks), 2)
        self.assertTrue(result.summary.text_preview)


if __name__ == "__main__":
    unittest.main()
