from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Corrupt PDF Index Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-resource-corrupt-pdf.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_resource_index_marks_corrupt_pdf_as_failed_not_500(tmp_path: Path) -> None:
    """Corrupt PDF must fail closed as index_status=failed (no HTTP 500)."""
    workspace_id = "workspace-resource-corrupt-pdf"
    with build_client(tmp_path) as client:
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "pdf",
                "name": "broken.pdf",
                "source": "inline://broken.pdf",
                "content": "%PDF-not-a-real-document",
                "content_encoding": "utf-8",
                "tags": ["corrupt-pdf"],
            },
        )
        assert upload.status_code == 200, upload.text
        resource_id = upload.json()["id"]
        indexed = client.post(
            "/resource/index",
            json={
                "workspace_id": workspace_id,
                "resource_id": resource_id,
                "enable_network": False,
            },
        )

    assert indexed.status_code == 200, indexed.text
    payload = indexed.json()
    assert payload["index_status"] == "failed"
    assert payload["parse_status"] == "failed"
    assert "no_content" in payload["quality_flags"]
    assert any("PDF could not be opened" in warning for warning in payload["warnings"])
    assert payload["trust_state"] == "untrusted"
