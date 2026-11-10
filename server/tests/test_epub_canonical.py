from __future__ import annotations

import io
import zipfile
from pathlib import Path

from tests.test_canonical_markdown import _TINY_PNG
from tests.test_canonical_resource_pipeline import start_session, upload_and_index


def _epub_bytes() -> bytes:
    container = '''<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>'''
    opf = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:language>en</dc:language></metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="img" href="images/diagram.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="ch1"/><itemref idref="ch2"/></spine>
</package>'''
    ch1 = '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Foundations</title></head><body>
<h1>Foundations</h1>
<p>Quorum reads intersect with the latest acknowledged write.</p>
<table><tr><th>Quorum</th><th>Meaning</th></tr>
<tr><td>R + W &gt; N</td><td>Reads see the latest write</td></tr></table>
<img src="images/diagram.png" alt="Quorum diagram"/>
</body></html>'''
    ch2 = '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Formulas</title></head><body>
<h1>Formulas</h1>
<p>The energy relation is <math><mi>E</mi><mo>=</mo><mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></math>.</p>
</body></html>'''
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/ch1.xhtml", ch1)
        archive.writestr("OEBPS/ch2.xhtml", ch2)
        archive.writestr("OEBPS/images/diagram.png", _TINY_PNG)
    return buffer.getvalue()


def test_epub_becomes_canonical_markdown_with_tables_images_and_math(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-epub"
    epub_path = workspace_root / "docs" / "systems.epub"
    epub_path.parent.mkdir(parents=True, exist_ok=True)
    epub_path.write_bytes(_epub_bytes())

    with __import__("tests.test_canonical_resource_pipeline", fromlist=["build_client"]).build_client(
        tmp_path
    ) as client:
        session_id = start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="epub",
            name="Systems Notes",
            source=epub_path,
        )
        assert indexed["parse_status"] == "parsed", indexed.get("warnings")
        assert indexed["index_status"] == "indexed"
        assert indexed["parser"] == "epub-v1"
        markdown_relative = indexed["canonical_markdown_path"]
        markdown_path = workspace_root / markdown_relative
        assert markdown_path.is_file()
        markdown = markdown_path.read_text(encoding="utf-8")
        assert "# Foundations" in markdown
        assert "| Quorum | Meaning |" in markdown
        assert "| R + W > N | Reads see the latest write |" in markdown
        assert "![Quorum diagram](assets/" in markdown
        assert "# Formulas" in markdown
        assert "$E = m c 2$" in markdown
        assert (markdown_path.parent / "assets").is_dir()

        search = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "session_id": session_id,
                "query": "quorum reads intersect",
                "top_k": 5,
            },
        )
        assert search.status_code == 200, search.text
        hit = search.json()["hits"][0]
        assert hit["resource_id"] == indexed["id"]
        assert hit["location"].get("heading") == "Foundations"
