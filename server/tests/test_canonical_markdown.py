"""Canonical Markdown digestion: DOCX / PPTX / PDF / HTML / text behaviour."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.resources.canonical import (  # noqa: E402
    CanonicalParseError,
    build_canonical_document,
    build_canonical_from_text,
    read_front_matter,
    source_type_for_path,
    strip_front_matter,
)
from app.resources.canonical_store import (  # noqa: E402
    markdown_path_for,
    original_dir_for,
    write_canonical_artifact,
)

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _docx_bytes() -> bytes:
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_W}" xmlns:r="{_R}" xmlns:a="{_A}"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Distributed Systems Notes</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Replication</w:t></w:r></w:p>
    <w:p><w:r><w:t>Replication keeps copies consistent.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Quorum</w:t></w:r></w:p>
    <w:p><w:r><w:t>Read the original paper </w:t></w:r>
      <w:hyperlink r:id="rIdLink"><w:r><w:t>here</w:t></w:r></w:hyperlink>
      <w:r><w:footnoteReference w:id="2"/></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Quorum</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Meaning</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>R + W &gt; N</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Reads see the latest write</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:p><w:r><w:drawing><wp:inline><a:graphic><a:graphicData>
      <a:blip r:embed="rIdImage"/>
    </a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
  </w:body>
</w:document>"""
    rels = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_PKG}">
  <Relationship Id="rIdLink" Type="{_R}/hyperlink" Target="https://example.org/paper" TargetMode="External"/>
  <Relationship Id="rIdImage" Type="{_R}/image" Target="media/image1.png"/>
</Relationships>"""
    footnotes = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="{_W}">
  <w:footnote w:id="2"><w:p><w:r><w:t>Quorum reads and writes intersect.</w:t></w:r></w:p></w:footnote>
</w:footnotes>"""
    app = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Pages>2</Pages>
</Properties>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="png" ContentType="image/png"/>
</Types>"""
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", rels)
        archive.writestr("word/footnotes.xml", footnotes)
        archive.writestr("word/media/image1.png", _TINY_PNG)
        archive.writestr("docProps/app.xml", app)
    return buffer.getvalue()


def _pptx_bytes() -> bytes:
    slide_1 = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="{_P}" xmlns:a="{_A}" xmlns:r="{_R}">
  <p:cSld><p:spTree>
    <p:sp><p:nvSpPr><p:nvPr><p:ph type="ctrTitle"/></p:nvPr></p:nvSpPr>
      <p:txBody><a:p><a:r><a:t>Consensus</a:t></a:r></a:p></p:txBody></p:sp>
    <p:sp><p:nvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>
      <p:txBody>
        <a:p><a:pPr><a:buChar char="•"/></a:pPr><a:r><a:t>Majority vote</a:t></a:r></a:p>
        <a:p><a:pPr lvl="1"><a:buChar char="•"/></a:pPr><a:r><a:t>Term numbers</a:t></a:r></a:p>
      </p:txBody></p:sp>
    <p:graphicFrame><a:graphic><a:graphicData><a:tbl>
      <a:tr><a:tc><a:txBody><a:p><a:r><a:t>State</a:t></a:r></a:p></a:txBody></a:tc>
            <a:tc><a:txBody><a:p><a:r><a:t>Meaning</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
      <a:tr><a:tc><a:txBody><a:p><a:r><a:t>Follower</a:t></a:r></a:p></a:txBody></a:tc>
            <a:tc><a:txBody><a:p><a:r><a:t>Receives entries</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
    </a:tbl></a:graphicData></a:graphic></p:graphicFrame>
    <p:pic><p:blipFill><a:blip r:embed="rIdImg1"/></p:blipFill></p:pic>
  </p:spTree></p:cSld>
</p:sld>"""
    slide_2 = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="{_P}" xmlns:a="{_A}" xmlns:r="{_R}" show="0">
  <p:cSld><p:spTree>
    <p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
      <p:txBody><a:p><a:r><a:t>Draft appendix</a:t></a:r></a:p></p:txBody></p:sp>
    <p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>
      <p:txBody><a:p><a:r><a:t>Not shown in the deck.</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"""
    slide_3 = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="{_P}" xmlns:a="{_A}" xmlns:r="{_R}">
  <p:cSld><p:spTree>
    <p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
      <p:txBody><a:p><a:r><a:t>Paxos</a:t></a:r></a:p></p:txBody></p:sp>
    <p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>
      <p:txBody><a:p><a:r><a:t>Two phases.</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"""
    slide_1_rels = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_PKG}">
  <Relationship Id="rIdImg1" Type="{_R}/image" Target="../media/image1.png"/>
  <Relationship Id="rIdNotes1" Type="{_R}/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
</Relationships>"""
    notes_1 = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes xmlns:p="{_P}" xmlns:a="{_A}">
  <p:cSld><p:spTree>
    <p:sp><p:nvSpPr><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr>
      <p:txBody><a:p><a:r><a:t>7</a:t></a:r></a:p></p:txBody></p:sp>
    <p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>
      <p:txBody><a:p><a:r><a:t>Explain why a majority is enough.</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:notes>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="png" ContentType="image/png"/>
</Types>"""
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("ppt/slides/slide1.xml", slide_1)
        archive.writestr("ppt/slides/slide2.xml", slide_2)
        archive.writestr("ppt/slides/slide3.xml", slide_3)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", slide_1_rels)
        archive.writestr("ppt/notesSlides/notesSlide1.xml", notes_1)
        archive.writestr("ppt/media/image1.png", _TINY_PNG)
    return buffer.getvalue()


def _pdf_bytes(pages: list[str]) -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    for _index, text in enumerate(pages, start=1):
        page = document.new_page()
        page.insert_text((72, 72), text or " ", fontsize=12)
    data = document.tobytes()
    document.close()
    return data


def test_source_type_detection() -> None:
    assert source_type_for_path("a.docx") == "docx"
    assert source_type_for_path("a.PPTX") == "pptx"
    assert source_type_for_path("a.pdf") == "pdf"
    assert source_type_for_path("a.html") == "html"
    assert source_type_for_path("a.md") == "markdown"
    assert source_type_for_path("a.png") == "image"
    assert source_type_for_path("a.exe") is None


def test_docx_digest_keeps_structure_links_tables_images_and_footnotes(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    path.write_bytes(_docx_bytes())
    document = build_canonical_document(path, resource_id="res_docx")
    body = document.body

    assert "# Distributed Systems Notes" in body
    assert "## Replication" in body
    assert "### Quorum" in body
    assert "[here](https://example.org/paper)" in body
    assert "| Quorum | Meaning |" in body
    assert "| R + W > N | Reads see the latest write |" in body
    assert "![docx-image-001](assets/docx-image-001.png)" in body
    assert "[^2]" in body
    assert "[^2]: Quorum reads and writes intersect." in body
    assert document.page_count == 2
    assert document.source_type == "docx"
    assert document.parser == "docx-v1"
    assert {asset.filename for asset in document.assets} == {"docx-image-001.png"}
    assert [anchor.label for anchor in document.anchors] == [
        "Distributed Systems Notes",
        "Replication",
        "Quorum",
        "Footnotes",
    ]


def test_docx_front_matter_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    path.write_bytes(_docx_bytes())
    document = build_canonical_document(path, resource_id="res_docx", version_id="rv-1")
    rendered = document.render()
    assert rendered.startswith("---\n")
    front = read_front_matter(rendered)
    assert front["resource_id"] == "res_docx"
    assert front["source_type"] == "docx"
    assert front["original_filename"] == "notes.docx"
    assert front["version_id"] == "rv-1"
    assert front["content_hash"].startswith("sha256:")
    assert front["parser"] == "docx-v1"
    assert front["page_count"] == 2
    assert front["anchors"][0]["kind"] == "heading"
    assert strip_front_matter(rendered).startswith("# Distributed Systems Notes")


def test_pptx_digest_sections_notes_hidden_slides_and_tables(tmp_path: Path) -> None:
    path = tmp_path / "deck.pptx"
    path.write_bytes(_pptx_bytes())
    document = build_canonical_document(path, resource_id="res_pptx")
    body = document.body

    assert "## Slide 1 — Consensus" in body
    assert "## Slide 2 — Draft appendix" in body
    assert "## Slide 3 — Paxos" in body
    assert "- Majority vote" in body
    assert "  - Term numbers" in body
    assert "| State | Meaning |" in body
    assert "#### Speaker notes" in body
    assert "Explain why a majority is enough." in body
    assert "7" not in body.split("#### Speaker notes", 1)[1]  # slide number placeholder skipped
    assert "<!-- slide-hidden: true -->" in body
    assert document.slide_count == 3
    assert document.parser == "pptx-v1"
    assert [anchor.kind for anchor in document.anchors] == ["slide", "slide", "slide"]
    assert [anchor.label for anchor in document.anchors] == ["Consensus", "Draft appendix", "Paxos"]
    assert any("Slide 2 is hidden" in warning for warning in document.warnings)
    assert {asset.filename for asset in document.assets} == {"slide-image-001.png"}


def test_pdf_digest_marks_page_anchors(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(_pdf_bytes(["First page body", "Second page body"]))
    document = build_canonical_document(path, resource_id="res_pdf")
    body = document.body
    assert "<!-- page: 1 -->" in body
    assert "<!-- page: 2 -->" in body
    assert body.index("First page body") < body.index("Second page body")
    assert document.page_count == 2
    assert [anchor.index for anchor in document.anchors] == [1, 2]
    assert [anchor.kind for anchor in document.anchors] == ["page", "page"]
    assert document.parser == "pdf-v1"


def test_html_digest_drops_scripts_and_keeps_headings(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_bytes(
        b"<html><head><title>Reading Notes</title><script>alert(1)</script></head>"
        b"<body><nav>menu</nav><h1>Lesson</h1><p>Body text.</p>"
        b"<ul><li>Point A</li></ul></body></html>"
    )
    document = build_canonical_document(path, resource_id="res_html")
    body = document.body
    assert "Body text." in body
    assert "alert(1)" not in body
    assert "menu" not in body
    assert document.source_type == "html"
    assert document.parser == "html-v1"


def test_legacy_office_formats_fail_with_actionable_message(tmp_path: Path) -> None:
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0legacy")
    with pytest.raises(CanonicalParseError) as error:
        build_canonical_document(path, resource_id="res_old")
    assert "save the file as docx" in str(error.value)


def test_scanned_pdf_without_text_reports_failure_instead_of_empty_document(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    document.new_page()  # no text layer at all
    data = document.tobytes()
    document.close()
    path = tmp_path / "scan.pdf"
    path.write_bytes(data)
    with pytest.raises(CanonicalParseError) as error:
        build_canonical_document(path, resource_id="res_scan")
    assert "OCR" in str(error.value)


def test_image_source_never_fabricates_text(tmp_path: Path) -> None:
    path = tmp_path / "diagram.png"
    path.write_bytes(_TINY_PNG)
    document = build_canonical_document(path, resource_id="res_img")
    assert "No OCR text was extracted" in document.body
    assert document.assets[0].filename.startswith("original-diagram")


def test_scanned_pdf_uses_ocr_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    from app.resources import canonical as canonical_module
    from app.resources.ocr import OcrResult

    document = pymupdf.open()
    document.new_page()
    path = tmp_path / "scan.pdf"
    path.write_bytes(document.tobytes())
    document.close()
    monkeypatch.setattr(
        canonical_module,
        "ocr_image_bytes",
        lambda _data, **_kwargs: OcrResult(text="OCR fallback page text", available=True),
    )
    built = build_canonical_document(path, resource_id="res_scan_ocr")
    assert "OCR fallback page text" in built.body
    assert any("Tesseract OCR" in warning for warning in built.warnings)


def test_image_uses_ocr_text_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.resources import canonical as canonical_module
    from app.resources.ocr import OcrResult

    path = tmp_path / "diagram.png"
    path.write_bytes(_TINY_PNG)
    monkeypatch.setattr(
        canonical_module,
        "ocr_image_bytes",
        lambda _data, **_kwargs: OcrResult(text="Queue lock diagram", available=True),
    )
    built = build_canonical_document(path, resource_id="res_img_ocr")
    assert "## OCR text" in built.body
    assert "Queue lock diagram" in built.body
    assert any("Tesseract OCR" in warning for warning in built.warnings)


def test_html_text_builder_keeps_source_url() -> None:
    document = build_canonical_from_text(
        "# Captured\n\nBody.",
        resource_id="res_url",
        original_filename="capture.md",
        source_url="https://example.org/a",
    )
    front = read_front_matter(document.render())
    assert front["source_url"] == "https://example.org/a"
    assert front["source_type"] == "html"


def test_store_writes_originals_markdown_and_assets(tmp_path: Path) -> None:
    source = tmp_path / "notes.docx"
    source.write_bytes(_docx_bytes())
    document = build_canonical_document(source, resource_id="resource-abc")
    artifact = write_canonical_artifact(
        tmp_path / "workspace",
        document,
        original_bytes=source.read_bytes(),
        original_filename="notes.docx",
    )
    expected_markdown = markdown_path_for(tmp_path / "workspace", "resource-abc")
    expected_original = original_dir_for(tmp_path / "workspace", "resource-abc") / "notes.docx"
    assert artifact.markdown_path == expected_markdown
    assert expected_markdown.is_file()
    assert expected_original.is_file()
    assert (artifact.assets_dir / "docx-image-001.png").is_file()
    assert read_text(expected_markdown).startswith("---\n")
    assert artifact.markdown_relative.startswith("Trainer Library/.trainer-resources/markdown/")
    assert artifact.original_relative is not None
    assert artifact.original_relative.startswith("Trainer Library/.trainer-resources/originals/")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_plain_text_preview_strips_markdown_syntax() -> None:
    from app.resources.canonical import plain_text_preview

    body = (
        "# Notes\n\n## Quorum\n\nSee the [paper](https://example.org).\n\n"
        "<!-- page: 2 -->\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
        "![chart](assets/x.png) Read after write.[^1]\n"
    )
    preview = plain_text_preview(body, max_chars=120)
    assert "#" not in preview
    assert "[" not in preview
    assert "<!--" not in preview
    assert "Notes" in preview
    assert "Quorum" in preview
    assert "Read after write." in preview
    assert "|" not in preview
    assert " : " not in preview
