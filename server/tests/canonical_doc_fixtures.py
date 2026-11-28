"""Byte builders for small Office/PDF fixtures, shared by canonical-pipeline tests.

Restored verbatim from the helpers of server/tests/test_canonical_markdown.py at df0a3e2a^
(the test file itself was deleted in df0a3e2a). Standard library only.
"""

from __future__ import annotations

import io
import zipfile

import pytest

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
