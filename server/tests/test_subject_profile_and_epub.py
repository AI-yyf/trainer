"""Tests for P1 #15, #16, #17:
- P1 #17: SubjectProfile data registry + schema validation + 8-locale deterministic hooks
- P1 #15: deliverable_kind (file_based / text_payload) routing in card_request and verify_practice_current_file
- P1 #16: EPUB/TXT ingest + stable paragraph anchors (¶) + content_language metadata & digest cache key
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.evaluator.hooks import (
    SUPPORTED_HOOK_LOCALES,
    QuoteBalanceHook,
    hooks_from_card_config,
    normalize_hook_locale,
    unit_count,
)
from app.evaluator.models import CheckStatus
from app.ingest.models import IngestionRequest
from app.ingest.service import IngestService
from app.llm.tools import ToolContext, build_default_tool_registry
from app.resources.models import ResourceKind
from app.training.card_request import normalize_deliverable_kind
from app.training.subject_profile import (
    get_subject_profile,
    load_subject_profiles,
    validate_subject_profile,
)
from app.training.subject_taxonomy import verifier_subject_family


def _build_minimal_epub_bytes(*, language: str = "zh-CN", paragraphs: list[str] | None = None) -> bytes:
    paras = paragraphs or [
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台。",
        "孔乙己是站着喝酒而穿长衫的唯一的人。",
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "<rootfiles>"
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles>"
            "</container>",
        )
        zf.writestr(
            "OEBPS/content.opf",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>孔乙己</dc:title>"
            f"<dc:language>{language}</dc:language>"
            f"</metadata>"
            f"<manifest>"
            f'<item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
            f"</manifest>"
            f"<spine>"
            f'<itemref idref="ch1"/>'
            f"</spine>"
            f"</package>",
        )
        body_html = "".join(f"<p>{p}</p>" for p in paras)
        zf.writestr(
            "OEBPS/chapter1.xhtml",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>第一章</h1>{body_html}</body></html>',
        )
    return buf.getvalue()


def test_subject_profile_loads_builtin_code_and_literature() -> None:
    profiles = load_subject_profiles()
    assert "code" in profiles
    assert "literature" in profiles
    code = get_subject_profile("code")
    assert code.dimensions == ("comprehension", "implementation", "debugging", "transfer")
    assert "file_based" in code.deliverable_kinds

    lit = get_subject_profile("literature")
    assert lit.dimensions == ("comprehension", "expression", "appreciation", "transfer")
    assert lit.verifier_pack == "literature"
    assert "text_payload" in lit.deliverable_kinds
    assert set(lit.dimension_labels.keys()) == {
        "zh-CN",
        "en-US",
        "es-ES",
        "fr-FR",
        "de-DE",
        "ja-JP",
        "ko-KR",
        "pt-BR",
    }
    assert verifier_subject_family("literature") == "literature"
    assert verifier_subject_family("unknown-subject") == "code"


def test_subject_profile_rejects_governance_overrides_and_unbounded_hooks() -> None:
    base = {
        "_type": "trainer.subject.profile",
        "version": 1,
        "id": "malicious",
        "family": "literature",
        "verifier_pack": "literature",
        "dimensions": ["comprehension", "expression", "appreciation", "transfer"],
        "deliverable_kinds": ["text_payload"],
    }
    with pytest.raises(ValueError, match="governance"):
        validate_subject_profile({**base, "trusted_verification_sources": ["self_reported"]})

    with pytest.raises(ValueError, match="unbounded"):
        validate_subject_profile({**base, "hooks": [{"type": "unbounded"}]})

    with pytest.raises(ValueError, match="empty rubric"):
        validate_subject_profile({**base, "rubric": []})

    with pytest.raises(ValueError, match="unregistered verifier_pack"):
        validate_subject_profile({**base, "verifier_pack": "nonexistent"})


def test_locale_aware_hooks_cover_eight_content_locales() -> None:
    assert SUPPORTED_HOOK_LOCALES == ("zh", "en", "ja", "de", "fr", "ko", "es", "pt")
    for raw, expected in [
        ("zh-CN", "zh"),
        ("en-US", "en"),
        ("ja-JP", "ja"),
        ("de-DE", "de"),
        ("fr-FR", "fr"),
        ("ko-KR", "ko"),
        ("es-ES", "es"),
        ("pt-BR", "pt"),
    ]:
        assert normalize_hook_locale(raw) == expected

    # French elision splits l'homme into 2 words under fr locale
    assert unit_count("l'homme est là", locale="fr-FR") == 4
    # Japanese kana + kanji counted per CJK character
    assert unit_count("吾輩は猫である", locale="ja-JP") == 7
    # German quotes „...“ and French guillemets «...»
    assert QuoteBalanceHook(locale="de").run("Er sagte: „Guten Tag“.").status is CheckStatus.PASSED
    assert QuoteBalanceHook(locale="de").run("Er sagte: „Guten Tag.").status is CheckStatus.FAILED
    assert QuoteBalanceHook(locale="fr").run("Il a dit « bonjour » à l'homme.").status is CheckStatus.PASSED
    assert QuoteBalanceHook(locale="fr").run("Il a dit « bonjour à l'homme.").status is CheckStatus.FAILED

    with pytest.raises(ValueError, match="unbounded"):
        hooks_from_card_config({"unbounded": True})


async def test_deliverable_kind_routes_text_payload_to_rubric_pack() -> None:
    assert normalize_deliverable_kind("text_payload") == "text_payload"
    assert normalize_deliverable_kind(None, subject_family="literature") == "text_payload"
    assert normalize_deliverable_kind(None, subject_family="code") == "file_based"

    registry = build_default_tool_registry()
    ctx = ToolContext(
        runtime=None,
        workspace_id="ws-lit",
        session_id="sess-lit",
        extra={
            "deliverable_kind": "text_payload",
            "subject_family": "literature",
            "text_submission": {
                "content": "从“孔乙己是站着喝酒而穿长衫的唯一的人”可以看出小伙计的冷眼旁观。",
                "locale": "zh-CN",
                "card_config": {
                    "word_count": {"min": 10, "max": 100},
                    "quote_balance": True,
                },
                "rubric_items": [
                    {"statement": "引用长衫原文", "anchor": "孔乙己是站着喝酒而穿长衫的唯一的人"},
                    {"statement": "点出小伙计视角", "anchor": "小伙计"},
                ],
            },
        },
    )
    result = await registry.invoke(
        ctx,
        "verify_practice_current_file",
        {"acceptance_criteria": ["小伙计"]},
    )
    assert result["ok"] is True
    assert result["passed"] is True
    assert result["deliverable_kind"] == "text_payload"
    assert result["subject_family"] == "literature"
    assert result["rubric_review"]["status"] == "passed"
    assert result["practice_evidence_persisted"] is False


def test_epub_and_txt_ingest_produces_stable_paragraph_anchors(tmp_path: Path) -> None:
    epub_bytes = _build_minimal_epub_bytes(language="zh-CN")
    epub_path = tmp_path / "kongyiji.epub"
    epub_path.write_bytes(epub_bytes)

    ingest = IngestService()
    text, warnings, provenance = ingest.describe_source_with_provenance(
        IngestionRequest(source_uri=str(epub_path), kind=ResourceKind.EPUB)
    )
    assert warnings == []
    assert "孔乙己是站着喝酒而穿长衫的唯一的人" in text
    assert provenance.get("content_language") == "zh-CN"
    anchors = provenance.get("paragraph_anchors")
    assert isinstance(anchors, list) and len(anchors) >= 2
    first_anchor = anchors[0]
    assert str(first_anchor["anchor_id"]).startswith("¶spine:ch1:/body/")
    assert first_anchor["kind"] == "epub"
    assert first_anchor["spine_id"] == "ch1"

    # TXT ingest
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("第一段笔记内容。\n\n第二段读书摘录。", encoding="utf-8")
    txt_text, txt_warnings, _ = ingest.describe_source_with_provenance(
        IngestionRequest(source_uri=str(txt_path), kind=ResourceKind.TEXT)
    )
    assert txt_warnings == []
    assert "第一段笔记内容" in txt_text
