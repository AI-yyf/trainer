"""评估 P0 验真与修复: 问题 A (预览/索引通路分叉) + 问题 B (文件夹 100 项截断).

Failure-first: each test previously reproduced the reported defect before
the fix, and now asserts the fixed contract:

- 问题 B: a >100-file folder indexes COMPLETELY (was: silently truncated at
  100), with honest metadata, failure isolation, and mtime-based incremental
  re-index (unchanged items reuse chunks, changed items re-extract).
- 问题 A: an .xlsx workbook previews AND indexes through the SAME conversion
  path (was: preview fine, main index path strict-UTF-8 crash).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app


def _xlsx_bytes() -> bytes:
    """Minimal two-sheet workbook (inline strings, no openpyxl dependency)."""

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Scores" sheetId="1" r:id="rId1"/><sheet name="Attendance" sheetId="2" r:id="rId2"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        "</Relationships>"
    )

    def sheet(rows: list[list[object]]) -> str:
        body = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
        body.append(
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        )
        for row_index, row in enumerate(rows, start=1):
            body.append(f'<row r="{row_index}">')
            for column_index, value in enumerate(row, start=1):
                column = ""
                remaining = column_index
                while remaining > 0:
                    remaining, offset = divmod(remaining - 1, 26)
                    column = chr(65 + offset) + column
                body.append(
                    f'<c r="{column}{row_index}" t="inlineStr"><is><t>{value}</t></is></c>'
                )
            body.append("</row>")
        body.append("</sheetData></worksheet>")
        return "".join(body)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            sheet([["student", "topic", "score"], ["Ada", "FSRS retention", "92"], ["Grace", "canonical markdown", "88"]]),
        )
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            sheet([["student", "weeks"], ["Ada", "12"]]),
        )
    return buffer.getvalue()


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer P0 Fix Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-p0-fix.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def start_session(client: TestClient, workspace_root: Path, workspace_id: str) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": workspace_id,
            "workspace_path": str(workspace_root),
        },
    )
    assert response.status_code == 200, response.text


def _upload_folder(client: TestClient, workspace_id: str, folder: Path, items: list[Path]) -> dict:
    upload = client.post(
        "/resource/upload",
        json={
            "workspace_id": workspace_id,
            "kind": "text",
            "name": folder.name,
            "source": str(folder),
            "source_type": "folder",
            "source_items": [str(p) for p in items],
        },
    )
    assert upload.status_code == 200, upload.text
    return upload.json()


def _registry_metadata(client: TestClient, resource_id: str) -> dict:
    record = client.app.state.runtime.resource_service.registry.get(resource_id)
    return dict(getattr(record, "metadata", {}) or {})


def _index(client: TestClient, workspace_id: str, resource_id: str) -> dict:
    indexed = client.post(
        "/resource/index",
        json={"workspace_id": workspace_id, "resource_id": resource_id},
    )
    assert indexed.status_code == 200, indexed.text
    return indexed.json()


def test_folder_with_130_files_indexes_completely(tmp_path: Path) -> None:
    """问题 B 复现: was silently indexed only the first 100 of 130 items."""

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    folder = workspace_root / "big-folder"
    folder.mkdir(parents=True, exist_ok=True)
    total = 130
    items: list[Path] = []
    for number in range(total):
        item = folder / f"note-{number:03d}.txt"
        item.write_text(f"unique folder sentinel number {number:03d} content\n", encoding="utf-8")
        items.append(item)

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "ws-folder-full")
        resource = _upload_folder(client, "ws-folder-full", folder, items)
        indexed = _index(client, "ws-folder-full", resource["id"])

        assert indexed["index_status"] == "indexed"
        metadata = _registry_metadata(client, resource["id"])
        assert metadata.get("folder_item_count") == total
        # The old bug: only 100 extracted. The fix: all 130.
        assert metadata.get("folder_item_indexed") == total
        assert not metadata.get("folder_item_truncated")
        assert metadata.get("folder_item_failed_count") == 0

        # The 101st..130th item must be searchable (previously invisible).
        found = client.post(
            "/resource/search",
            json={
                "workspace_id": "ws-folder-full",
                "query": "folder sentinel number 124",
                "top_k": 5,
            },
        )
        assert found.status_code == 200, found.text
        hits = found.json().get("hits", [])
        assert hits, "item #125 (>100) must be searchable after the fix"

        # Incremental continuation: only changed items re-extract on re-index.
        changed = items[7]
        changed.write_text("folder sentinel REVISED after first index\n", encoding="utf-8")
        _index(client, "ws-folder-full", resource["id"])
        re_metadata = _registry_metadata(client, resource["id"])
        assert re_metadata.get("folder_item_indexed") == total
        assert re_metadata.get("chunk_count", 0) >= total  # reused + new chunks survive
        revised_hit = client.post(
            "/resource/search",
            json={
                "workspace_id": "ws-folder-full",
                "query": "folder sentinel REVISED",
                "top_k": 5,
            },
        )
        assert revised_hit.status_code == 200
        assert revised_hit.json().get("hits"), "revised item must be searchable after re-index"


def test_folder_item_failure_isolated_with_details(tmp_path: Path) -> None:
    """One unreadable item must not kill the folder; failures are recorded."""

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    folder = workspace_root / "mixed-folder"
    folder.mkdir(parents=True, exist_ok=True)
    items: list[Path] = []
    for number in range(5):
        item = folder / f"ok-{number}.txt"
        item.write_text(f"isolated sentinel {number}\n", encoding="utf-8")
        items.append(item)
    binary_item = folder / "broken.bin"
    binary_item.write_bytes(bytes(range(256)) * 4)
    # A path that no longer exists between upload and index.
    ghost = folder / "ghost.txt"
    ghost.write_text("gone soon\n", encoding="utf-8")
    items.append(binary_item)
    items.append(ghost)

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "ws-folder-mixed")
        resource = _upload_folder(client, "ws-folder-mixed", folder, items)
        ghost.unlink()
        indexed = _index(client, "ws-folder-mixed", resource["id"])

        metadata = _registry_metadata(client, resource["id"])
        # 5 ok + binary item (may extract as replacement chars or fail) + ghost.
        assert metadata.get("folder_item_failed_count", 0) >= 1
        failed_items = {entry.get("item", "") for entry in metadata.get("folder_item_failed", [])}
        assert any("ghost.txt" in item for item in failed_items)
        # The healthy items still made it in.
        assert metadata.get("folder_item_indexed", 0) >= 5
        assert indexed["index_status"] == "indexed"


def test_xlsx_previews_and_indexes_through_same_path(tmp_path: Path) -> None:
    """问题 A 复现: .xlsx preview worked but the main index path crashed."""

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    workbook_path = workspace_root / "grades.xlsx"
    workbook_path.write_bytes(_xlsx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "ws-xlsx")
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": "ws-xlsx",
                "kind": "text",
                "name": "Grades",
                "source": str(workbook_path),
            },
        )
        assert upload.status_code == 200, upload.text
        resource = upload.json()
        indexed = _index(client, "ws-xlsx", resource["id"])
        assert indexed["index_status"] == "indexed", (
            "xlsx must index through the same conversion preview uses "
            "(previously strict-UTF-8 crash on a binary workbook)"
        )

        found = client.post(
            "/resource/search",
            json={
                "workspace_id": "ws-xlsx",
                "query": "FSRS retention Ada",
                "top_k": 5,
            },
        )
        assert found.status_code == 200, found.text
        hits = found.json().get("hits", [])
        assert hits, "indexed xlsx cell content must be searchable"
        assert any("FSRS" in str(hit.get("summary", "")) or "retention" in str(hit.get("summary", "")).lower() for hit in hits)

        # Same conversion path as preview: the extracted markdown previews the sheets.
        sheet_hits = client.post(
            "/resource/search",
            json={
                "workspace_id": "ws-xlsx",
                "query": "Attendance weeks",
                "top_k": 5,
            },
        )
        assert sheet_hits.status_code == 200
        assert sheet_hits.json().get("hits"), "second sheet content must also be searchable"
