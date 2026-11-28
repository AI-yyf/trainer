"""(t) Resources: canonicalization, organization and teaching use of library content
    stay grounded and never destroy the only copy.

Guarantees covered:
  * DOCX / PDF / EPUB / Markdown digest into canonical Markdown with real assets;
  * the Markdown-only migration never destroys the only copy of a resource;
  * agent organization stays inside the library; teaching digests cite the resource actually used.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_canonical_markdown.py
  * server/tests/test_stage_material_composer.py
  * server/tests/test_resource_project_teaching.py
  * server/tests/test_resource_composer_intent.py
  * server/tests/test_canonical_resource_pipeline.py
  * server/tests/test_ocr.py
  * server/tests/test_resource_agent_organization.py
  * server/tests/test_resource_teaching_digest.py
"""

from __future__ import annotations

import asyncio
import json
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.event_ledger import EventLedgerService
from app.core.models import SessionMessageRequest, UserProfile
from app.core.settings import AppSettings
from app.llm.prompts import build_coaching_messages, build_coaching_system_prompt
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app
from app.pedagogy.stage_material_composer import (
    StageMaterialComposer,
    compose_principle_explainer_asset,
)
from app.resources.canonical import (
    CanonicalParseError,
    build_canonical_document,
    build_canonical_from_text,
    read_front_matter,
    source_type_for_path,
    strip_front_matter,
)
from app.resources.canonical_store import (
    markdown_path_for,
    original_dir_for,
    write_canonical_artifact,
)
from app.resources.ocr import ocr_image_bytes
from app.sandbox.service import SandboxService
from app.skills.registry import SkillRegistry
from app.skills.runtime import record_skill_usage, select_active_skills
from app.training.attempt_store import AttemptStore
from app.training.skill_projection import project_skills
from app.workspace.authority import PermissionLevel, WorkspaceAuthority

# ---------------------------------------------------------------------------
# Restored from test_canonical_markdown.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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
    assert "![docx-image-001](assets/res_docx/docx-image-001.png)" in body
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


def test_image_source_never_fabricates_text(tmp_path: Path) -> None:
    path = tmp_path / "diagram.png"
    path.write_bytes(_TINY_PNG)
    document = build_canonical_document(path, resource_id="res_img")
    assert "No OCR text was extracted" in document.body
    assert document.assets[0].filename.startswith("original-diagram")


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


def test_store_writes_markdown_and_assets_without_originals(tmp_path: Path) -> None:
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
    expected_original_dir = original_dir_for(tmp_path / "workspace", "resource-abc")
    assert artifact.markdown_path == expected_markdown
    assert expected_markdown.is_file()
    assert not expected_original_dir.exists()
    assert artifact.original_path is None
    assert artifact.original_relative is None
    assert (artifact.assets_dir / "docx-image-001.png").is_file()
    stored_markdown = read_text(expected_markdown)
    assert "![docx-image-001](assets/resource-abc/docx-image-001.png)" in stored_markdown
    assert stored_markdown.startswith("---\n")
    assert artifact.markdown_relative.startswith("Trainer Library/.trainer-resources/markdown/")


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


# ---------------------------------------------------------------------------
# Restored from test_stage_material_composer.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


_MATERIAL_KINDS = ("study_guide", "cheat_sheet", "exercise_set", "code_examples")


_COMPOSE_KWARGS: dict[str, Any] = {
    "workspace_id": "ws-stage",
    "plan_title": "Plan: HTTPX mastery",
    "stage_id": "stage-1",
    "stage_title": "Timeouts and retries",
    "stage_goal": "Understand connect vs read timeouts.",
    "stage_outcomes": ["outcome-a", "outcome-b"],
    "stage_exercises": ["exercise-a"],
}


class _ScriptedProvider:
    """Fake provider returning the same payload on every chat_completion call."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0
        self.temperatures: list[float] = []

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        self.calls += 1
        self.temperatures.append(temperature)
        return self.payload


def _llm_material(kind: str, title: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "summary": f"Summary of {title}",
        "content": f"Full content for {title}",
        "sources": ["Indexed resource A"],
    }


def _valid_materials_payload() -> str:
    return json.dumps(
        {
            "materials": [
                _llm_material("study_guide", "LLM study guide"),
                _llm_material("cheat_sheet", "LLM cheat sheet"),
                _llm_material("exercise_set", "LLM exercise set"),
                _llm_material("code_examples", "LLM code examples"),
            ],
        },
    )


class TestStageMaterialComposerFallback(unittest.TestCase):
    """Without a provider the composer must produce deterministic templates."""

    def test_provider_none_returns_four_fallback_assets(self) -> None:
        composer = StageMaterialComposer(provider_service=None)
        assets = asyncio.run(composer.compose_stage_materials(**_COMPOSE_KWARGS))

        self.assertEqual(len(assets), 4)
        self.assertEqual({asset.kind for asset in assets}, set(_MATERIAL_KINDS))
        for asset in assets:
            self.assertEqual(asset.plan_stage_id, "stage-1")
            self.assertEqual(asset.workspace_id, "ws-stage")
            self.assertEqual(asset.scope, "project")
            self.assertEqual(asset.source_ids, ["plan_stage:stage-1"])
            self.assertTrue(asset.title.strip())
            content = asset.concept_card or asset.example or asset.exercise_seed
            self.assertTrue(content.strip())
            if asset.kind == "exercise_set":
                self.assertIn("exercise-a", content)
            elif asset.kind == "code_examples":
                self.assertIn("Understand connect vs read timeouts.", content)
            else:
                self.assertIn("outcome-a", content)

    def test_fallback_reflects_stage_language(self) -> None:
        composer = StageMaterialComposer(provider_service=None)
        assets = asyncio.run(
            composer.compose_stage_materials(**_COMPOSE_KWARGS, response_language="zh-CN"),
        )
        study_guide = next(asset for asset in assets if asset.kind == "study_guide")
        self.assertIn("学习指南", study_guide.title)


class TestStageMaterialComposerLLM(unittest.TestCase):
    """With a provider the composer should use the LLM payload verbatim."""

    def test_valid_llm_payload_becomes_assets_without_fallback_marker(self) -> None:
        provider = _ScriptedProvider(_valid_materials_payload())
        composer = StageMaterialComposer(provider_service=provider)
        assets = asyncio.run(composer.compose_stage_materials(**_COMPOSE_KWARGS))

        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.temperatures, [0.7])
        self.assertEqual(len(assets), 4)
        titles = {asset.title for asset in assets}
        self.assertIn("LLM study guide", titles)
        self.assertIn("LLM code examples", titles)
        for asset in assets:
            self.assertNotIn("stage-material-fallback", asset.tags)
        guide = next(asset for asset in assets if asset.kind == "study_guide")
        self.assertEqual(guide.concept_card, "Full content for LLM study guide")
        self.assertEqual(guide.evidence_snippets, ["Indexed resource A"])

    def test_invalid_materials_are_dropped(self) -> None:
        payload = json.dumps(
            {
                "materials": [
                    _llm_material("study_guide", "Kept guide"),
                    _llm_material("unknown_kind", "Dropped unknown kind"),
                    {"kind": "cheat_sheet", "title": "Dropped empty content", "content": "  "},
                ],
            },
        )
        provider = _ScriptedProvider(payload)
        composer = StageMaterialComposer(provider_service=provider)
        assets = asyncio.run(composer.compose_stage_materials(**_COMPOSE_KWARGS))

        self.assertEqual([asset.kind for asset in assets], ["study_guide"])
        self.assertEqual(assets[0].title, "Kept guide")

    def test_garbage_json_retries_once_then_falls_back(self) -> None:
        provider = _ScriptedProvider("this is not json at all {")
        composer = StageMaterialComposer(provider_service=provider)
        assets = asyncio.run(composer.compose_stage_materials(**_COMPOSE_KWARGS))

        self.assertEqual(provider.calls, 2)
        self.assertEqual(provider.temperatures, [0.7, 0.9])
        self.assertEqual(len(assets), 4)
        self.assertEqual({asset.kind for asset in assets}, set(_MATERIAL_KINDS))
        for asset in assets:
            self.assertIn("stage-material-fallback", asset.tags)


class TestComposePrincipleExplainerAsset(unittest.TestCase):
    """The deterministic facade should map PrincipleNote into a concept asset."""

    def test_returns_non_empty_concept_card_asset(self) -> None:
        asset = compose_principle_explainer_asset(
            workspace_id="ws-stage",
            principle="Small verifiable steps",
            context="Learner is refactoring an HTTP client timeout path.",
            focus_area="httpx timeouts",
        )

        self.assertEqual(asset.kind, "concept_card")
        self.assertEqual(asset.plan_stage_id, "")
        self.assertEqual(asset.origin, "manual")
        self.assertEqual(asset.workspace_id, "ws-stage")
        self.assertEqual(asset.title, "Small verifiable steps")
        self.assertTrue(asset.concept_card.strip())
        self.assertTrue(asset.summary.strip())
        self.assertTrue(asset.why_it_matters.strip())
        self.assertTrue(asset.example.strip())


# ---------------------------------------------------------------------------
# Restored from test_resource_project_teaching.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_resource_version_change_stales_old_evidence_until_reverified(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(workspace_id="ws", card_id="card")
    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="artifact-hash",
        result="passed",
        resource_id="resource-paper",
        resource_version_id="rv-1",
        resource_content_hash="old-hash",
        resource_location={"path": "papers/queue.md"},
    )
    assert evidence is not None
    assert project_skills(store.list_evidence(attempt["attempt_id"]))["implementation"]["state"] == "independent"

    marked = store.mark_evidence_resource_version_stale(
        workspace_id="ws",
        resource_id="resource-paper",
        current_content_hash="new-hash",
    )
    assert marked == 1
    stale = store.list_evidence(attempt["attempt_id"])[0]
    assert stale["source_stale"] is True
    assert stale["source_stale_reason"] == "resource_version_changed"
    assert stale["is_current"] is False
    assert project_skills([stale])["implementation"]["state"] == "not_verified"

    # A verified citation for the new version is live.
    updated = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="artifact-hash",
        result="passed",
        resource_id="resource-paper",
        resource_version_id="rv-2",
        resource_content_hash="new-hash",
        resource_location={"path": "papers/queue.md"},
    )
    assert updated is not None
    current = next(
        item for item in store.list_evidence(attempt["attempt_id"]) if item.get("is_current")
    )
    assert current["resource_content_hash"] == "new-hash"
    assert project_skills([current])["implementation"]["state"] == "independent"


def test_same_resource_version_restore_clears_stale_flag(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(workspace_id="ws", card_id="card")
    store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="artifact-hash",
        result="passed",
        resource_id="resource-paper",
        resource_content_hash="same-hash",
    )
    store.mark_evidence_resource_version_stale(
        workspace_id="ws",
        resource_id="resource-paper",
        current_content_hash="other-hash",
    )
    cleared = store.clear_evidence_resource_version_stale(
        workspace_id="ws",
        resource_id="resource-paper",
        current_content_hash="same-hash",
    )
    assert cleared == 1
    evidence = store.list_evidence(attempt["attempt_id"])[0]
    assert evidence["source_stale"] is False
    assert evidence["is_current"] is True


def test_project_skill_stales_on_source_change_and_reactivates_on_redistill(
    tmp_path: Path,
) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    metadata = {
        "origin": "project-analysis",
        "source_resource_id": "resource-project",
        "source_content_hash": "old-content",
        "commit_sha": "commit-1",
        "front_matter": {"triggers": "项目结构, 架构, call graph"},
    }
    record, created = registry.upsert_knowledge_skill(
        skill_id="project-knowledge",
        name="Project knowledge",
        description="Modules, entry points and call graph.",
        body="项目结构：modules and calls.",
        metadata=metadata,
        workspace_id="ws",
    )
    assert created is True and record.active is True
    assert any(
        skill.skill_id == record.skill_id
        for skill in select_active_skills(registry, "帮我理解项目结构和架构", workspace_id="ws")
    )

    # Same source content: no stale flag.
    assert (
        registry.mark_project_skill_stale_for_content(
            workspace_id="ws",
            resource_id="resource-project",
            current_content_hash="old-content",
        )
        == 0
    )
    assert record.active is True

    # New source content: stale, inactive, excluded from agent selection.
    assert (
        registry.mark_project_skill_stale_for_content(
            workspace_id="ws",
            resource_id="resource-project",
            current_content_hash="new-content",
        )
        == 1
    )
    assert record.active is False
    assert record.status() == "stale"
    assert select_active_skills(registry, "帮我理解项目结构和架构", workspace_id="ws") == []

    refreshed, created_again = registry.upsert_knowledge_skill(
        skill_id="project-knowledge",
        name="Project knowledge",
        description="Modules, entry points and call graph.",
        body="项目结构：modules and calls.",
        metadata={**metadata, "source_content_hash": "new-content"},
        workspace_id="ws",
    )
    assert created_again is False
    assert refreshed.active is True
    assert refreshed.metadata.get("stale") is None
    assert refreshed.status() == "ready"
    assert any(
        skill.skill_id == refreshed.skill_id
        for skill in select_active_skills(registry, "帮我理解项目结构和架构", workspace_id="ws")
    )


def test_skill_usage_feedback_is_not_learner_mastery(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    record, _ = registry.upsert_knowledge_skill(
        skill_id="project-knowledge",
        name="Project knowledge",
        description="Project structure.",
        body="项目结构。",
        metadata={
            "origin": "project-analysis",
            "source_resource_id": "resource-project",
            "front_matter": {"triggers": "项目结构"},
        },
        workspace_id="ws",
    )
    registry.record_usage(
        record.skill_id,
        applied=True,
        workspace_id="ws",
        session_id="session-1",
        evidence={"basis": "contract_markers"},
    )
    refreshed = registry._skills[record.skill_id]
    assert refreshed.metadata["usage_count"] == 1
    assert refreshed.metadata["applied_count"] == 1
    assert "mastery" not in refreshed.metadata


def test_record_skill_usage_writes_registry_facts_only(tmp_path: Path) -> None:
    class Runtime:
        skill_registry = SkillRegistry(tmp_path / "skills")

    registry = Runtime.skill_registry
    record, _ = registry.upsert_knowledge_skill(
        skill_id="project-knowledge",
        name="Project knowledge",
        description="Project structure.",
        body="项目结构。",
        metadata={
            "origin": "project-analysis",
            "source_resource_id": "resource-project",
            "front_matter": {"triggers": "项目结构"},
        },
        workspace_id="ws",
    )
    selected = select_active_skills(registry, "项目结构是什么", workspace_id="ws")
    assert selected
    usages = record_skill_usage(
        Runtime(),
        "ws",
        "session-1",
        selected,
        stop_reason="completed",
        final_content=f"Used {record.skill_id}: modules.",
        tool_events=[],
    )
    assert usages and usages[0]["skill_id"] == record.skill_id
    assert registry._skills[record.skill_id].metadata["usage_count"] == 1


# ---------------------------------------------------------------------------
# Restored from test_resource_composer_intent.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_resource_composer_intent_is_semantic_only_and_alias_safe() -> None:
    request = SessionMessageRequest.model_validate(
        {
            "message": "Keep this focused.",
            "resourceComposerIntent": {
                "mode": "organize",
                "resourceIds": ["resource-1", "resource-1", "resource:note-2"],
            },
        }
    )

    assert request.resource_composer_intent is not None
    assert request.resource_composer_intent.mode == "organize"
    assert request.resource_composer_intent.resource_ids == ["resource-1", "resource:note-2"]
    assert request.model_dump(by_alias=True)["resourceComposerIntent"] == {
        "mode": "organize",
        "resourceIds": ["resource-1", "resource:note-2"],
    }

    with pytest.raises(ValidationError):
        SessionMessageRequest.model_validate(
            {
                "message": "Move this material.",
                "resource_composer_intent": {
                    "mode": "organize",
                    "targetPath": "C:\\outside-workspace",
                },
            }
        )
    with pytest.raises(ValidationError):
        SessionMessageRequest.model_validate(
            {
                "message": "Use this material.",
                "resource_composer_intent": {
                    "mode": "locate",
                    "resource_ids": ["../not-a-resource-id"],
                },
            }
        )


@pytest.mark.parametrize("mode", ["locate", "analyze", "download", "organize", "cards"])
def test_resource_composer_intent_accepts_each_supported_mode(mode: str) -> None:
    request = SessionMessageRequest.model_validate(
        {
            "message": "Keep the resource task focused.",
            "resource_composer_intent": {"mode": mode},
        }
    )

    assert request.resource_composer_intent is not None
    assert request.resource_composer_intent.mode == mode


@pytest.mark.parametrize("suffix", ["", "不用安排练习。"])
def test_library_comparison_exercise_uses_the_original_numbered_passages(suffix: str) -> None:
    context = {
        "resource_composer_intent": {"mode": "analyze"},
        "resource_fragments": [
            {"excerpt": "# 路线 A\n这是第一篇论文介绍的场景。\n> 将输入变成离散标记，再预测下一个标记。"},
            {"excerpt": "先学习结构化交通约束，再预测未来状态。"},
        ],
    }
    profile = UserProfile()
    message = f"比较这两个研究路线，并安排下一阶段学习。{suffix}"
    prompt = build_coaching_messages(profile, message, coach_context=context)[0]["content"]
    assert ("two small work products" in prompt) == (not suffix)
    result = ProviderService().finalize_coaching_reply(
        "两条路线的预测目标不同。",
        profile=profile, message=message, response_language="zh-CN", coach_context=context,
    )
    assert "两条路线的预测目标不同。" in result
    if suffix:
        assert "### 练习" not in result
    else:
        assert "按「先做什么 → 要学习或预测什么」各写一行" in result
        assert "> [1] 将输入变成离散标记，再预测下一个标记。" in result
        assert "> [2] 先学习结构化交通约束，再预测未来状态。" in result
        assert "这是第一篇论文介绍的场景" not in result


def test_single_source_practice_keeps_both_cases_and_removes_the_models_drill() -> None:
    profile = UserProfile()
    message = "分析两种结束方式在训练目标上的区别，给我一道练习。\n\n当前阶段：验证边界条件"
    context = {
        "resource_composer_intent": {"mode": "analyze"},
        "resource_fragments": [{"excerpt": (
            "# Episode boundaries\n"
            "> Returning a terminal state ends reward collection. The value afterward is zero. "
            "In contrast, truncation can stop sampling before the task ends. "
            "The target then uses an estimate of the final state's value."
        )}],
    }
    messages = build_coaching_messages(profile, message, coach_context=context)
    assert messages[-1]["content"] == "分析两种结束方式在训练目标上的区别\n\n当前阶段：验证边界条件"
    result = ProviderService().finalize_coaching_reply(
        "两种情况影响目标值。[1]\n\n```text\n# Practice\n```\n\n"
        "### 练习题目\n\n模型重复出的题。\n\n### 参考答案\n\n模型给的答案。\n\n"
        "### 学习建议\n\n先写出两种情况的预期值，再写测试。",
        profile=profile, message=message, response_language="zh-CN", coach_context=context,
    )
    assert result.count("### 练习") == 1
    assert "模型重复出的题" not in result and "模型给的答案" not in result
    assert "### 学习建议" in result and "```text\n# Practice\n```" in result
    assert "什么时候发生 → 结果怎么处理" in result
    assert "> [1] The value afterward is zero." in result
    assert "> [1] The target then uses an estimate of the final state's value." in result


def test_resource_composer_prompt_is_advisory_and_keeps_governance_explicit() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn resource-grounded coaching"),
        message="Help me decide what to do with this source.",
        coach_context={
            "active_view": "resources",
            "resource_composer_intent": {
                "mode": "cards",
                "resource_ids": ["resource-note-1"],
            },
        },
    )

    assert "Resource task: derive one or two grounded learning-card candidates" in prompt
    assert "never authorizes writing the learner's project" in prompt
    assert "Managed sandbox library tools may still list, edit, and index" in prompt
    assert "Do not mention internal routing, metadata, or UI controls" in prompt
    assert "Formal Plan changes still require the explicit formal-plan mutation path" in prompt
    assert (
        "Do not create or activate a Training card solely because this Resources action was selected"
        in prompt
    )


# ---------------------------------------------------------------------------
# Restored from test_canonical_resource_pipeline.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Canonical Pipeline Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-canonical.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def start_session(client: TestClient, workspace_root: Path, workspace_id: str) -> str:
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
    return response.json()["session_id"]


def upload_and_index(
    client: TestClient,
    *,
    workspace_id: str,
    kind: str,
    name: str,
    source: Path,
) -> dict:
    upload = client.post(
        "/resource/upload",
        json={
            "workspace_id": workspace_id,
            "kind": kind,
            "name": name,
            "source": str(source),
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
    return indexed.json()


def test_legacy_doc_reports_actionable_failure_not_a_fake_import(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-legacy"
    doc_path = workspace_root / "old.doc"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_bytes(b"\xd0\xcf\x11\xe0legacy-word")

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Legacy Doc",
            source=doc_path,
        )
        assert indexed["index_status"] == "failed"
        assert indexed["parse_status"] == "failed"
        assert any("save the file as .docx" in warning for warning in indexed["warnings"])
        assert indexed["canonical_markdown_path"] in {None, ""}


def test_analyze_reports_legacy_office_failure_without_writing(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-staged-legacy"
    legacy = workspace_root / "old.doc"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"\xd0\xcf\x11\xe0legacy")

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "docx",
                "name": "Legacy",
                "source": str(legacy),
            },
        ).json()
        analyzed = client.post(
            "/resource/canonicalize/analyze",
            json={"workspace_id": workspace_id, "resource_ids": [upload["id"]]},
        )
        item = analyzed.json()["items"][0]
        assert analyzed.json()["ok"] is False
        assert item["ok"] is False
        assert "save the file as .docx" in item["error"]


# ---------------------------------------------------------------------------
# Restored from test_ocr.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_ocr_reports_missing_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.resources.ocr.shutil.which", lambda _name: None)
    result = ocr_image_bytes(b"image-bytes")
    assert result.text == ""
    assert result.available is False
    assert any("Tesseract is not installed" in warning for warning in result.warnings)


def test_ocr_returns_tesseract_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.resources.ocr.shutil.which", lambda _name: "/usr/bin/tesseract")

    class Completed:
        returncode = 0
        stdout = b"Queue lock protects shared items\n"
        stderr = b""

    monkeypatch.setattr(
        "app.resources.ocr.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )
    result = ocr_image_bytes(b"image-bytes")
    assert result.available is True
    assert result.text == "Queue lock protects shared items"


# ---------------------------------------------------------------------------
# Restored from test_resource_agent_organization.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _context(
    runtime: object,
    *,
    host_confirmed: bool = False,
    workspace_id: str = "workspace-resource-organize",
) -> ToolContext:
    extra: dict[str, object] = {
        "active_view": "resources",
        "resource_composer_intent": {"mode": "organize"},
    }
    if host_confirmed:
        extra["resource_organization_confirmed"] = True
    return ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="session-resource-organize",
        extra=extra,
    )


def _authority_wired_sandbox(
    tmp_path: Path,
    *,
    workspace_id: str,
    workspace_trusted: bool,
    remote_name: str = "",
) -> tuple[SandboxService, WorkspaceAuthority, Path, Path, EventLedgerService]:
    """Sandbox + project authority under the post-landing destructive gate."""
    project_root = tmp_path / f"project-{workspace_id}"
    project_root.mkdir()
    # Sentinel: organize must never mutate the opened project root.
    project_sentinel = project_root / "user-project.txt"
    project_sentinel.write_text("project-owned", encoding="utf-8")
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.INSPECT,
        remote_name=remote_name or None,
    )
    project_authority.set_workspace_context(workspace_trusted=workspace_trusted)
    ledger = EventLedgerService()
    sandbox = SandboxService(
        data_root=tmp_path / f"data-{workspace_id}",
        event_ledger=ledger,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    return sandbox, project_authority, project_root, project_sentinel, ledger


def _runtime(**kwargs: object) -> SimpleNamespace:
    base = {
        "event_ledger": None,
        "resource_organization_history": {},
        "resource_organization_pending": {},
        "resolve_workspace_path": lambda _workspace_id: None,
        "refresh_workspace_sessions": lambda _workspace_id: 0,
        "repository": SimpleNamespace(
            list_resources=lambda _workspace_id: [], save_resource=lambda *_args: None
        ),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_resource_organization_cancel_route_clears_server_pending(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from app.core.settings import AppSettings
    from app.main import create_app

    settings = AppSettings(
        app_name="Trainer Organize Cancel Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-organize-cancel.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    client = TestClient(app)
    runtime = app.state.runtime
    workspace_id = "workspace-organize-cancel-route"
    runtime.resource_organization_pending[workspace_id] = {
        "operations": [{"op": "move", "source": "a.md", "target": "b/a.md"}]
    }

    response = client.post(
        "/resource/organization/cancel",
        json={"workspace_id": workspace_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["cleared"] is True
    assert body.get("cancelled") is True
    assert body.get("already_committed") is False
    assert workspace_id not in runtime.resource_organization_pending

    again = client.post(
        "/resource/organization/cancel",
        json={"workspace_id": workspace_id},
    )
    assert again.status_code == 200
    assert again.json()["cleared"] is False
    assert again.json().get("already_committed") is not True


@pytest.mark.asyncio
async def test_agent_tools_cannot_write_outside_sandbox_into_project_sentinel(
    tmp_path: Path,
) -> None:
    """Learning OS fail-closed: no project write tool; organize stays sandbox-only."""
    workspace_id = "workspace-agent-no-project-write"
    sandbox, _authority, project_root, project_sentinel, ledger = _authority_wired_sandbox(
        tmp_path,
        workspace_id=workspace_id,
        workspace_trusted=True,
    )
    root = sandbox.ensure_workspace_root(workspace_id)
    (root / "notes.md").write_text("sandbox-notes", encoding="utf-8")
    runtime = _runtime(
        sandbox_service=sandbox,
        event_ledger=ledger,
        resolve_workspace_path=lambda _workspace_id: str(project_root),
    )
    registry = build_default_tool_registry()
    names = set(registry.names())
    assert "write_file" not in names
    assert "apply_patch" not in names
    assert "edit_file" not in names

    # Absolute / traversal paths must not touch the opened project sentinel.
    for operations in (
        [{"op": "mkdir", "path": str(project_root / "agent-wrote")}],
        [{"op": "mkdir", "path": "../user-project.txt"}],
        [
            {
                "op": "move",
                "source": "notes.md",
                "target": str(project_root / "stolen-notes.md"),
            }
        ],
        [{"op": "delete", "path": str(project_sentinel)}],
    ):
        proposal = await registry.invoke(
            _context(runtime, workspace_id=workspace_id),
            "organize_resources",
            {"operations": operations},
        )
        if proposal.get("ok") and proposal.get("requires_confirmation"):
            committed = await registry.invoke(
                _context(runtime, host_confirmed=True, workspace_id=workspace_id),
                "organize_resources",
                {"operations": operations},
            )
            assert committed.get("committed") is not True or not (
                project_root / "agent-wrote"
            ).exists()
        assert project_sentinel.read_text(encoding="utf-8") == "project-owned"
        assert not (project_root / "agent-wrote").exists()
        assert not (project_root / "stolen-notes.md").exists()
        assert (root / "notes.md").exists() or (root / "archive" / "notes.md").exists()


# ---------------------------------------------------------------------------
# Restored from test_resource_teaching_digest.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


WORKSPACE_ID = "ws-teaching-digest"


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer teaching digest",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-teaching-digest.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


class StubProviderService:
    has_api_key = True

    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        self.calls += 1
        return (
            '{"summary": "旋转护栏在重试队列排空之前执行。", '
            '"practice_questions": ["护栏为何先于队列运行？", "跳过护栏会怎样？", "如何临时禁用它？"], '
            '"intuitive_examples": ["像门禁先于闸机放行。", "像编译前的语法检查。"], '
            '"common_pitfalls": ["误以为护栏在队列之后运行。", "把禁用当成配置错误。"]}'
        )


def _indexed_resource(client: TestClient) -> dict:
    session_id = client.post(
        "/session/start",
        json={"workspace_id": WORKSPACE_ID, "workspace_name": "Digest"},
    ).json()["session_id"]
    upload = client.post(
        "/resource/upload",
        json={
            "session_id": session_id,
            "workspace_id": WORKSPACE_ID,
            "kind": "markdown",
            "name": "Rotation guard notes",
            "source": "notes/rotation-guard.md",
            "content": "# Rotation guard\n\nThe rotation guard runs before the retry queue drains.",
            "source_type": "file",
        },
    )
    assert upload.status_code == 200, upload.text
    record = upload.json()
    indexed = client.post(
        "/resource/index",
        json={
            "session_id": session_id,
            "workspace_id": WORKSPACE_ID,
            "resource_id": record["id"],
            "enable_network": False,
        },
    )
    assert indexed.status_code == 200, indexed.text
    return indexed.json()


def test_digest_skips_without_provider_or_unindexed_resource(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    runtime = app.state.runtime
    record = _indexed_resource(TestClient(app))

    # No provider configured: a quiet skip, never an error surfaced to a turn.
    assert asyncio.run(runtime.digest_resource_for_teaching(WORKSPACE_ID, record["id"])) is None

    runtime.provider_service = StubProviderService()
    # An unknown/unindexed id is skipped as well.
    assert asyncio.run(runtime.digest_resource_for_teaching(WORKSPACE_ID, "resource-nope")) is None
