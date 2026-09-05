"""Quick smoke test for preview tier selection."""
import json
import tarfile
import zipfile
from contextlib import nullcontext
from pathlib import Path

import pytest

import app.resources.preview as preview_module
from app.resources.preview import (
    TIER_CONVERTED,
    TIER_METADATA,
    TIER_RICH,
    PreviewService,
    _xlsx_collect_sheet_preview,
    get_structured_preview_data,
    get_structured_preview_markdown,
)


@pytest.fixture
def svc() -> PreviewService:
    return PreviewService()


def _write_minimal_docx(path: Path, paragraphs: list[str]) -> None:
    xml_paragraphs = "".join(
        f"<w:p><w:r><w:t>{paragraph.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{xml_paragraphs}</w:body>
</w:document>""",
        )


def _write_minimal_pptx(path: Path, paragraphs: list[str]) -> None:
    xml_paragraphs = "".join(
        f"""
<p:sp>
  <p:txBody>
    <a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <a:r><a:t>{paragraph.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</a:t></a:r>
    </a:p>
  </p:txBody>
</p:sp>"""
        for paragraph in paragraphs
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld>
    <p:spTree>{xml_paragraphs}</p:spTree>
  </p:cSld>
</p:sld>""",
        )


def _escape_xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write_minimal_odt(path: Path, paragraphs: list[str]) -> None:
    content_xml = "".join(f"<text:p>{_escape_xml_text(paragraph)}</text:p>" for paragraph in paragraphs)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "content.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:text>{content_xml}</office:text>
  </office:body>
</office:document-content>""",
        )


def _write_minimal_ods(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    row_xml: list[str] = []
    all_rows = [headers, *rows]
    for row in all_rows:
        cell_xml = "".join(
            f"<table:table-cell><text:p>{_escape_xml_text(cell)}</text:p></table:table-cell>"
            for cell in row
        )
        row_xml.append(f"<table:table-row>{cell_xml}</table:table-row>")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "content.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Sheet1">
        {''.join(row_xml)}
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>""",
        )


def _write_minimal_odp(path: Path, slides: list[list[str]]) -> None:
    slide_xml: list[str] = []
    for index, paragraphs in enumerate(slides, start=1):
        body = "".join(f"<text:p>{_escape_xml_text(paragraph)}</text:p>" for paragraph in paragraphs)
        slide_xml.append(
            f"""
      <draw:page draw:name="Slide {index}" draw:style-name="dp1" draw:master-page-name="Default">
        <draw:frame>
          <draw:text-box>{body}</draw:text-box>
        </draw:frame>
      </draw:page>"""
        )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "content.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:presentation>{''.join(slide_xml)}
    </office:presentation>
  </office:body>
</office:document-content>""",
        )


def _escape_rtf_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _write_minimal_rtf(path: Path, text: str) -> None:
    path.write_text(
        "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Calibri;}}\\pard " + _escape_rtf_text(text) + "\\par}",
        encoding="latin-1",
    )


def _write_minimal_eml(path: Path, *, subject: str, body: str) -> None:
    path.write_text(
        (
            "From: coach@example.com\n"
            "To: learner@example.com\n"
            f"Subject: {subject}\n"
            "Date: Mon, 1 Jan 2024 10:00:00 +0000\n"
            'Content-Type: text/plain; charset="utf-8"\n'
            "\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )


def _write_minimal_epub(path: Path, title: str, body_paragraphs: list[str]) -> None:
    chapter_html = "".join(f"<p>{_escape_xml_text(paragraph)}</p>" for paragraph in body_paragraphs)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{_escape_xml_text(title)}</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
  </spine>
</package>""",
        )
        archive.writestr(
            "OEBPS/chapter1.xhtml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>{_escape_xml_text(title)}</title></head>
  <body>{chapter_html}</body>
</html>""",
        )


def _write_minimal_pdf(path: Path, text: str) -> None:
    def escape_pdf_text(value: str) -> str:
        return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    content_stream = "\n".join(
        [
            "BT",
            "/F1 12 Tf",
            "72 720 Td",
            f"({escape_pdf_text(text)}) Tj",
            "ET",
            "",
        ]
    )
    header = "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    objects = [
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n",
        f"4 0 obj\n<< /Length {len(content_stream.encode('latin-1'))} >>\nstream\n{content_stream}endstream\nendobj\n",
        "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    offsets: list[int] = []
    body_parts = [header]
    for obj in objects:
        offsets.append(len("".join(body_parts).encode("latin-1")))
        body_parts.append(obj)

    body = "".join(body_parts)
    xref_start = len(body.encode("latin-1"))
    xref_entries = ["0000000000 65535 f \n"]
    xref_entries.extend(f"{offset:010d} 00000 n \n" for offset in offsets)
    xref = "xref\n0 6\n" + "".join(xref_entries)
    trailer = f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n"
    path.write_bytes((body + xref + trailer).encode("latin-1"))


class TestSelectTier:
    def test_code_text_json_yaml_html_xml_markdown_are_rich(self, svc: PreviewService) -> None:
        for name in [
            "foo.py",
            "bar.ts",
            "baz.tsx",
            "qux.js",
            "quux.jsx",
            "main.go",
            "lib.rs",
            "App.java",
            "code.c",
            "header.h",
            "script.sh",
            "config.ini",
            "readme.md",
            "data.json",
            "config.yaml",
            "page.html",
            "schema.xml",
            "diff.patch",
            "table.csv",
            "scores.tsv",
            "notebook.ipynb",
        ]:
            assert svc.select_tier(name) == TIER_RICH, f"Expected TIER_RICH for {name}"

    def test_pdf_docx_xlsx_pptx_odf_and_rtf_are_converted(self, svc: PreviewService) -> None:
        for name in [
            "report.pdf",
            "doc.docx",
            "doc.docm",
            "old.doc",
            "sheet.xlsx",
            "sheet.xlsm",
            "slides.pptx",
            "slides.pptm",
            "book.ppt",
            "notes.odt",
            "table.ods",
            "deck.odp",
            "letter.rtf",
            "old.xls",
            "book.epub",
            "message.eml",
        ]:
            assert svc.select_tier(name) == TIER_CONVERTED, f"Expected TIER_CONVERTED for {name}"

    def test_image_audio_video_are_rich_native(self, svc: PreviewService) -> None:
        for name in [
            "photo.png",
            "shot.jpg",
            "anim.gif",
            "icon.svg",
            "song.mp3",
            "ring.wav",
            "track.flac",
            "movie.mp4",
            "clip.webm",
            "scene.mov",
        ]:
            assert svc.select_tier(name) == TIER_RICH, f"Expected TIER_RICH for {name}"

    def test_archive_converted_tier_priority(self, svc: PreviewService) -> None:
        for name in ["archive.zip", "bundle.tar", "bundle.tgz", "bundle.tar.gz", "bundle.tar.bz2", "bundle.txz", "bundle.tbz2"]:
            assert svc.select_tier(name) == TIER_CONVERTED, f"Expected TIER_CONVERTED for {name}"
        for name in ["dump.gz", "backup.7z", "data.rar", "old.bz2"]:
            assert svc.select_tier(name) == TIER_METADATA, f"Expected TIER_METADATA for {name}"

    def test_unknown_extension_defaults_to_rich(self, svc: PreviewService) -> None:
        assert svc.select_tier("something.unknownext") == TIER_RICH


class TestGetPreview:
    def test_auto_tier_for_py_is_rich(self, svc: PreviewService) -> None:
        result = svc.get_preview("test.py")
        assert result.tier == TIER_RICH

    def test_auto_tier_for_pdf_is_converted(self, svc: PreviewService) -> None:
        result = svc.get_preview("test.pdf")
        assert result.tier == TIER_CONVERTED

    def test_pdf_and_docx_converted_previews_produce_html(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(preview_module, "_convert_with_markitdown", lambda _path: None)

        pdf_path = tmp_path / "coach-notes.pdf"
        _write_minimal_pdf(pdf_path, "PDF preview keeps the converted path grounded.")

        docx_path = tmp_path / "coach-notes.docx"
        _write_minimal_docx(docx_path, ["DOCX preview keeps the converted path grounded."])

        pdf_result = PreviewService().get_preview(str(pdf_path))
        docx_result = PreviewService().get_preview(str(docx_path))

        assert pdf_result.tier == TIER_CONVERTED
        assert pdf_result.content is not None
        assert pdf_result.html is not None
        assert "PDF preview keeps the converted path grounded." in pdf_result.content
        assert pdf_result.metadata["kind"] == "document"
        assert pdf_result.metadata["format"] == "pdf"
        assert pdf_result.metadata["pageCount"] == 1

        assert docx_result.tier == TIER_CONVERTED
        assert docx_result.content is not None
        assert docx_result.html is not None
        assert "DOCX preview keeps the converted path grounded." in docx_result.content

    def test_epub_and_eml_converted_previews_produce_html(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(preview_module, "_convert_with_markitdown", lambda _path: None)

        epub_path = tmp_path / "coach-notes.epub"
        _write_minimal_epub(epub_path, "EPUB preview keeps the converted path grounded.", ["Chapter one keeps the preview path grounded."])

        eml_path = tmp_path / "coach-notes.eml"
        _write_minimal_eml(
            eml_path,
            subject="Email preview keeps the converted path grounded.",
            body="Body text keeps the converted path grounded.",
        )

        epub_result = PreviewService().get_preview(str(epub_path))
        eml_result = PreviewService().get_preview(str(eml_path))

        assert epub_result.tier == TIER_CONVERTED
        assert epub_result.content is not None
        assert epub_result.html is not None
        assert "EPUB preview keeps the converted path grounded." in epub_result.content
        assert "Chapter one keeps the preview path grounded." in epub_result.content

        assert eml_result.tier == TIER_CONVERTED
        assert eml_result.content is not None
        assert eml_result.html is not None
        assert "Email preview keeps the converted path grounded." in eml_result.content
        assert "Body text keeps the converted path grounded." in eml_result.content

    @pytest.mark.parametrize("filename", ["legacy.doc", "legacy.xls", "legacy.ppt"])
    def test_legacy_office_files_fall_back_to_metadata_when_conversion_is_unavailable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        filename: str,
    ) -> None:
        monkeypatch.setattr(preview_module, "_convert_with_markitdown", lambda _path: None)

        file_path = tmp_path / filename
        file_path.write_bytes(b"\x00\x01\x02Trainer legacy office preview")

        result = PreviewService().get_preview(str(file_path))

        assert result.tier == TIER_METADATA
        assert result.can_native_open is True
        assert result.metadata["extension"] == f".{filename.split('.')[-1]}"
        assert "Extension:" in (result.content or "")
        assert file_path.name in (result.content or "")

    def test_auto_tier_for_zip_is_converted(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("notes/readme.md", "# Archive Preview\nKeep the converted path grounded.\n")
            archive.writestr("data/values.csv", "name,value\nalpha,1\n")

        result = PreviewService().get_preview(str(zip_path))

        assert result.tier == TIER_CONVERTED
        assert result.content is not None
        assert "notes/readme.md" in result.content
        assert "Keep the converted path grounded." in result.content
        assert result.html is not None
        assert result.metadata["kind"] == "archive"
        assert result.metadata["format"] == "zip"
        assert result.metadata["entryCount"] == 2
        assert result.metadata["previewEntries"][0]["path"] == "notes/readme.md"

    def test_explicit_metadata_tier_respected(self, svc: PreviewService) -> None:
        result = svc.get_preview("test.py", tier=TIER_METADATA)
        assert result.tier == TIER_METADATA

    def test_fallback_when_richer_tier_unsupported(self, svc: PreviewService) -> None:
        result = svc.get_preview("test.pdf", tier=TIER_RICH)
        assert result.tier == TIER_CONVERTED

    def test_tar_preview_falls_back_to_archive_index_when_markitdown_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tar_path = tmp_path / "bundle.tar"
        with tarfile.open(tar_path, "w") as archive:
            text_path = tmp_path / "bundle-note.txt"
            text_path.write_text("Tar archive previews should still be useful.", encoding="utf-8")
            archive.add(text_path, arcname="notes/bundle-note.txt")

        monkeypatch.setattr(preview_module, "_convert_with_markitdown", lambda _path: None)

        result = PreviewService().get_preview(str(tar_path))

        assert result.tier == TIER_CONVERTED
        assert result.content is not None
        assert "notes/bundle-note.txt" in result.content
        assert "Tar archive previews should still be useful." in result.content
        assert result.metadata["kind"] == "archive"
        assert result.metadata["format"] == "tar"

    @pytest.mark.parametrize(
        "filename,writer,writer_args,expected_fragments",
        [
            ("fallback.odt", _write_minimal_odt, (["Coach preview extraction stays grounded.", "One thin slice at a time."],), ["Coach preview extraction stays grounded.", "One thin slice at a time."]),
            ("fallback.ods", _write_minimal_ods, (["Name", "Score"], [["alpha", "1"], ["beta", "2"]]), ["| Name | Score |", "| alpha | 1 |"]),
            ("fallback.odp", _write_minimal_odp, ([["Trainer stays desktop-first.", "Keep the preview path thin."]],), ["## Slide 1", "Trainer stays desktop-first."]),
            ("fallback.rtf", _write_minimal_rtf, ("Rich text fallback keeps the preview path grounded.",), ["Rich text fallback keeps the preview path grounded."]),
        ],
    )
    def test_odf_and_rtf_preview_falls_back_to_local_conversion(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        filename: str,
        writer,
        writer_args,
        expected_fragments: list[str],
    ) -> None:
        file_path = tmp_path / filename
        writer(file_path, *writer_args)

        monkeypatch.setattr(preview_module, "_convert_with_markitdown", lambda _path: None)

        result = PreviewService().get_preview(str(file_path))

        assert result.tier == TIER_CONVERTED
        assert result.content is not None
        assert result.html is not None
        for fragment in expected_fragments:
            assert fragment in result.content


class TestStructuredPreviewData:
    def test_csv_preview_uses_small_sample_only(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "small.csv"
        csv_path.write_text("name,score\nalpha,1\nbeta,2\ngamma,3\n", encoding="utf-8")

        preview = get_structured_preview_data(str(csv_path))

        assert preview["kind"] == "table"
        assert preview["rowCount"] == 3
        assert preview["sampleRows"][0] == ["alpha", "1"]

    def test_ipynb_preview_reports_cells_without_extra_payload(self, tmp_path: Path) -> None:
        notebook_path = tmp_path / "tiny.ipynb"
        notebook_path.write_text(
            json.dumps(
                {
                    "cells": [
                        {
                            "cell_type": "markdown",
                            "source": ["# Title\n", "Keep this small."],
                            "outputs": [],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        preview = get_structured_preview_data(str(notebook_path))

        assert preview["kind"] == "notebook"
        assert preview["cellCount"] == 1
        assert preview["cellSummaries"][0]["cellType"] == "markdown"

    def test_xlsx_preview_reports_table_summary_without_openpyxl(self, tmp_path: Path) -> None:
        xlsx_path = tmp_path / "small.xlsx"
        with zipfile.ZipFile(xlsx_path, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
            )
            archive.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
            )
            archive.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>Name</t></is></c>
      <c r="B1" t="inlineStr"><is><t>Score</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>alpha</t></is></c>
      <c r="B2"><v>1</v></c>
    </row>
    <row r="3">
      <c r="A3" t="inlineStr"><is><t>beta</t></is></c>
      <c r="B3"><v>2</v></c>
    </row>
  </sheetData>
</worksheet>""",
            )

        preview = get_structured_preview_data(str(xlsx_path))
        markdown = get_structured_preview_markdown(str(xlsx_path))

        assert preview["kind"] == "table"
        assert preview["format"] == "xlsx"
        assert preview["sheetName"] == "Sheet1"
        assert preview["rowCount"] == 2
        assert preview["sampleRows"][0] == ["alpha", "1"]
        assert markdown is not None
        assert "### Sheet1" in markdown
        assert "| Name | Score |" in markdown

    def test_xlsm_preview_reports_table_summary_without_openpyxl(self, tmp_path: Path) -> None:
        xlsm_path = tmp_path / "small.xlsm"
        with zipfile.ZipFile(xlsm_path, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
            )
            archive.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
            )
            archive.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>Name</t></is></c>
      <c r="B1" t="inlineStr"><is><t>Score</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>alpha</t></is></c>
      <c r="B2"><v>1</v></c>
    </row>
  </sheetData>
</worksheet>""",
            )

        preview = get_structured_preview_data(str(xlsm_path))
        markdown = get_structured_preview_markdown(str(xlsm_path))

        assert preview["kind"] == "table"
        assert preview["format"] == "xlsx"
        assert preview["sheetName"] == "Sheet1"
        assert preview["rowCount"] == 1
        assert preview["sampleRows"][0] == ["alpha", "1"]
        assert markdown is not None
        assert "| Name | Score |" in markdown

    def test_xlsx_preview_scans_only_the_preview_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeArchive:
            def open(self, _sheet_path: str):
                return nullcontext(object())

        yield_count = 0
        row_tag = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"
        cell_tag = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"
        inline_tag = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is"
        text_tag = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"

        def fake_iterparse(_handle, events=("end",)):
            del _handle, events

            def iterator():
                nonlocal yield_count
                for row_index in range(1, 101):
                    row = _xlsx_collect_sheet_preview.__globals__["ET"].Element(row_tag)
                    for column, value in (("A", "Name" if row_index == 1 else f"row-{row_index}"), ("B", "Score" if row_index == 1 else str(row_index))):
                        cell = _xlsx_collect_sheet_preview.__globals__["ET"].Element(cell_tag, {"r": f"{column}{row_index}", "t": "inlineStr"})
                        is_node = _xlsx_collect_sheet_preview.__globals__["ET"].SubElement(cell, inline_tag)
                        text_node = _xlsx_collect_sheet_preview.__globals__["ET"].SubElement(is_node, text_tag)
                        text_node.text = value
                        row.append(cell)
                    yield_count += 1
                    yield "end", row

            return iterator()

        monkeypatch.setattr(_xlsx_collect_sheet_preview.__globals__["ET"], "iterparse", fake_iterparse)

        row_count, _max_column, sample_row_maps, shared_indices = _xlsx_collect_sheet_preview(
            FakeArchive(),
            "xl/worksheets/sheet1.xml",
            max_preview_rows=5,
        )

        assert yield_count == 7
        assert row_count == 7
        assert len(sample_row_maps) == 6
        assert shared_indices == set()

    @pytest.mark.parametrize(
        "filename,content,expected_kind,expected_format,expected_fragment",
        [
            (
                "sample.json",
                json.dumps({"coach": True, "mode": "guided", "steps": ["read", "reflect"]}),
                "structured-text",
                "json",
                '"coach": true',
            ),
            (
                "sample.toml",
                "coach = true\nmode = \"guided\"\n",
                "structured-text",
                "toml",
                '"mode": "guided"',
            ),
            (
                "sample.yaml",
                "coach: true\nmode: guided\n",
                "structured-text",
                "yaml",
                '"coach": true',
            ),
        ],
    )
    def test_structured_text_preview_formats_are_normalized(
        self,
        tmp_path: Path,
        filename: str,
        content: str,
        expected_kind: str,
        expected_format: str,
        expected_fragment: str,
    ) -> None:
        file_path = tmp_path / filename
        file_path.write_text(content, encoding="utf-8")

        preview = get_structured_preview_data(str(file_path))
        markdown = get_structured_preview_markdown(str(file_path))

        assert preview["kind"] == expected_kind
        assert preview["format"] == expected_format
        assert preview["content"]
        assert expected_fragment in preview["content"]
        assert markdown is not None
        assert expected_fragment in markdown

    @pytest.mark.parametrize(
        "filename,content,expected_kind,expected_format,expected_fragment",
        [
            (
                "sample.html",
                "<html><head><title>Trainer Guide</title></head><body><h1>Coach</h1><p>Stay grounded.</p></body></html>",
                "markup",
                "html",
                "# Trainer Guide",
            ),
            (
                "sample.xml",
                "<root><section><title>Trainer Guide</title><item>Stay grounded.</item></section></root>",
                "markup",
                "xml",
                "<root>",
            ),
        ],
    )
    def test_markup_preview_formats_are_outlined(
        self,
        tmp_path: Path,
        filename: str,
        content: str,
        expected_kind: str,
        expected_format: str,
        expected_fragment: str,
    ) -> None:
        file_path = tmp_path / filename
        file_path.write_text(content, encoding="utf-8")

        preview = get_structured_preview_data(str(file_path))
        markdown = get_structured_preview_markdown(str(file_path))

        assert preview["kind"] == expected_kind
        assert preview["format"] == expected_format
        assert preview["content"]
        assert expected_fragment in preview["content"]
        assert markdown is not None
        assert expected_fragment in markdown

    def test_email_and_epub_preview_formats_are_structured(
        self,
        tmp_path: Path,
    ) -> None:
        eml_path = tmp_path / "sample.eml"
        _write_minimal_eml(
            eml_path,
            subject="Trainer coach note",
            body="Keep the preview path narrow.\n\nTeach from the evidence.",
        )
        epub_path = tmp_path / "sample.epub"
        _write_minimal_epub(epub_path, "Trainer handbook", ["Keep the preview path narrow.", "Teach from the evidence."])

        eml_preview = get_structured_preview_data(str(eml_path))
        eml_markdown = get_structured_preview_markdown(str(eml_path))
        epub_preview = get_structured_preview_data(str(epub_path))
        epub_markdown = get_structured_preview_markdown(str(epub_path))

        assert eml_preview["kind"] == "document"
        assert eml_preview["format"] == "eml"
        assert eml_preview["subject"] == "Trainer coach note"
        assert "Keep the preview path narrow." in eml_preview["content"]
        assert eml_markdown is not None
        assert "Trainer coach note" in eml_markdown

        assert epub_preview["kind"] == "document"
        assert epub_preview["format"] == "epub"
        assert epub_preview["title"] == "Trainer handbook"
        assert epub_preview["sectionCount"] == 1
        assert "Keep the preview path narrow." in epub_preview["content"]
        assert epub_markdown is not None
        assert "Trainer handbook" in epub_markdown

    def test_docx_preview_falls_back_to_openxml_text_when_markitdown_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        docx_path = tmp_path / "fallback.docx"
        _write_minimal_docx(docx_path, ["Coach preview extraction stays grounded.", "One thin slice at a time."])

        monkeypatch.setattr(preview_module, "_convert_with_markitdown", lambda _path: None)

        result = PreviewService().get_preview(str(docx_path))

        assert result.tier == TIER_CONVERTED
        assert result.content is not None
        assert "Coach preview extraction stays grounded." in result.content
        assert "One thin slice at a time." in result.content
        assert result.metadata["kind"] == "document"
        assert result.metadata["format"] == "docx"
        assert result.metadata["paragraphCount"] == 2
        assert result.html is not None

    def test_pptx_preview_falls_back_to_openxml_text_when_markitdown_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pptx_path = tmp_path / "fallback.pptx"
        _write_minimal_pptx(pptx_path, ["Trainer stays desktop-first.", "Keep the preview path thin."])

        monkeypatch.setattr(preview_module, "_convert_with_markitdown", lambda _path: None)

        result = PreviewService().get_preview(str(pptx_path))

        assert result.tier == TIER_CONVERTED
        assert result.content is not None
        assert "# fallback.pptx" in result.content
        assert "## Slide 1" in result.content
        assert "Trainer stays desktop-first." in result.content
        assert "Keep the preview path thin." in result.content
        assert result.html is not None

    def test_pdf_preview_falls_back_to_pymupdf_text_when_markitdown_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pdf_path = tmp_path / "fallback.pdf"
        _write_minimal_pdf(pdf_path, "PDF fallback keeps the preview path grounded.")

        monkeypatch.setattr(preview_module, "_convert_with_markitdown", lambda _path: None)

        result = PreviewService().get_preview(str(pdf_path))

        assert result.tier == TIER_CONVERTED
        assert result.content is not None
        assert "PDF fallback keeps the preview path grounded." in result.content
        assert result.html is not None
