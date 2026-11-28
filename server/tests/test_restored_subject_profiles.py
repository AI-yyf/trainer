"""(v) Subject profiles: profile packages ship complete and classify workspaces
    by their real subject family.

Guarantees covered:
  * packaged profiles load in the bundled (VSIX) layout;
  * workspace classification picks the right subject family from real file evidence;
  * taxonomy and profile metadata stay consistent across sources.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_workspace_subject_family.py
  * server/tests/test_subject_profile_dogfood.py
  * server/tests/test_subject_profile_and_epub.py
  * server/tests/test_subject_profile_packaging.py
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.core.models import FirstLookSummary
from app.evaluator.hooks import (
    SUPPORTED_HOOK_LOCALES,
    QuoteBalanceHook,
    hooks_from_card_config,
    normalize_hook_locale,
    unit_count,
)
from app.evaluator.models import CheckStatus
from app.evaluator.verifiers import VERIFIER_REGISTRY
from app.ingest.models import IngestionRequest
from app.ingest.service import IngestService
from app.resources.models import ResourceKind
from app.training.subject_profile import (
    get_subject_profile,
    load_subject_profiles,
    validate_subject_profile,
)
from app.training.subject_taxonomy import verifier_subject_family
from app.workspace.classifier import classify_heuristic
from app.workspace.subject_scan import LITERATURE_DIR_MARKERS, detect_workspace_subject_family

# ---------------------------------------------------------------------------
# Restored from test_workspace_subject_family.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _scan(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "file_count": 8,
        "dir_count": 1,
        "extensions": {},
        "top_level_dirs": [],
        "top_level_files": [],
        "anchors": [],
        "dependency_files": [],
        "model_artifacts": [],
        "scan_limited": False,
    }
    base.update(overrides)
    return base


def test_empty_or_missing_scan_fails_closed_to_code() -> None:
    assert detect_workspace_subject_family(None) == "code"
    assert detect_workspace_subject_family({}) == "code"
    assert detect_workspace_subject_family(_scan(file_count=0)) == "code"


def test_literature_corpus_with_named_directory_flips_to_literature() -> None:
    scan = _scan(
        extensions={".epub": 2, ".txt": 2, ".md": 1},
        top_level_dirs=["novels", "essays"],
    )
    assert detect_workspace_subject_family(scan) == "literature"


def test_literature_cjk_directory_markers_count_the_same() -> None:
    assert "文学" in LITERATURE_DIR_MARKERS and "批注" in LITERATURE_DIR_MARKERS
    scan = _scan(extensions={".epub": 3}, top_level_dirs=["文学"])
    assert detect_workspace_subject_family(scan) == "literature"


def test_dependency_manifest_beats_any_literary_marker() -> None:
    scan = _scan(
        extensions={".epub": 6},
        top_level_dirs=["novels"],
        dependency_files=["package.json"],
    )
    assert detect_workspace_subject_family(scan) == "code"


def test_dominating_code_count_stays_code() -> None:
    scan = _scan(
        extensions={".epub": 1, ".py": 40, ".ts": 22},
        top_level_dirs=["novels"],
    )
    # one marker (2) + one prose carrier (1) = 3 < floor AND < code count
    assert detect_workspace_subject_family(scan) == "code"


def test_mixed_workspace_fails_closed_to_code() -> None:
    scan = _scan(
        extensions={".epub": 1},
        top_level_dirs=["novels"],
    )
    assert detect_workspace_subject_family(scan) == "code"


def test_readme_only_prose_without_any_marker_stays_code() -> None:
    # Two stray txt files alone never clear the floor — a named literary
    # directory or a real prose corpus is required.
    scan = _scan(extensions={".txt": 2, ".md": 3}, top_level_dirs=["docs"])
    assert detect_workspace_subject_family(scan) == "code"


def test_classify_heuristic_marks_literature_workspace(tmp_path: Path) -> None:
    corpus = tmp_path / "novels"
    corpus.mkdir()
    for index in range(3):
        (corpus / f"chapter-{index}.txt").write_text("＿" * 40, encoding="utf-8")
    (tmp_path / "文学.epub").write_bytes(b"PK\x03\x04")
    essays = tmp_path / "essays"
    essays.mkdir()
    (essays / "one.md").write_text("# 一", encoding="utf-8")

    summary = classify_heuristic(str(tmp_path))
    assert summary.subject_family == "literature"


def test_classify_heuristic_keeps_code_workspace_on_code(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "README.md").write_text("# hello\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.txt").write_text("design notes\n", encoding="utf-8")

    summary = classify_heuristic(str(tmp_path))
    assert summary.subject_family == "code"


def test_first_look_summary_defaults_to_code_family() -> None:
    summary = FirstLookSummary()
    assert summary.subject_family == "code"


def test_remote_unknown_first_look_stays_on_code() -> None:
    summary = classify_heuristic(
        "ssh://host/workspace",
        remote_name="host",
        response_language="en-US",
    )
    assert summary.subject_family == "code"


@pytest.mark.asyncio
async def test_llm_refinement_preserves_heuristic_subject_family() -> None:
    # The LLM refines copy only; the family stays a heuristic decision.
    # build a literature heuristic result through a real tmp corpus, then
    # simulate an LLM response that tries to rewrite every field.
    from app.workspace.classifier import _parse_llm_response

    base = FirstLookSummary(
        folder_role="learning_materials",
        project_type_guess="documentation",
        subject_family="literature",
        confidence=0.8,
        why_this_guess="corpus",
    )
    response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"folder_role": "existing_engineering", '
                        '"project_type_guess": "web_app", "confidence": 0.9, '
                        '"why_this_guess": "rewritten", '
                        '"recommended_next_step": "rewritten step"}'
                    )
                }
            }
        ]
    }
    merged = _parse_llm_response(base, response)
    assert merged.subject_family == "literature"
    assert merged.folder_role == "existing_engineering"


# ---------------------------------------------------------------------------
# Restored from test_subject_profile_dogfood.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


DOGFLOOD_IDS = ("japanese-learning", "german-grammar", "french-writing")


_LABEL_LANGUAGES = {
    "zh-CN",
    "en-US",
    "es-ES",
    "fr-FR",
    "de-DE",
    "ja-JP",
    "ko-KR",
    "pt-BR",
}


def test_dogfood_profiles_load_and_pass_fail_closed_validation() -> None:
    profiles = load_subject_profiles()
    for profile_id in DOGFLOOD_IDS:
        profile = profiles[profile_id]
        assert profile.verifier_pack in VERIFIER_REGISTRY
        assert len(profile.dimensions) == len(set(profile.dimensions)) > 0
        assert set(profile.deliverable_kinds) <= {"file_based", "text_payload"}
        assert profile.family == "language-learning"


def test_dogfood_profiles_do_not_hijack_canonical_family_keys() -> None:
    profiles = load_subject_profiles()
    # The canonical families must still resolve to their own profiles even
    # though the language-learning profiles share the verifier pack.
    assert profiles["code"].id == "code"
    assert profiles["literature"].id == "literature"
    for profile_id in DOGFLOOD_IDS:
        resolved = get_subject_profile(profile_id)
        assert resolved.id == profile_id
        assert resolved.family == "language-learning"


def test_dogfood_profiles_resolve_to_the_literature_verifier_pack() -> None:
    for profile_id in DOGFLOOD_IDS:
        assert verifier_subject_family(profile_id) == "literature"
    # Canonical families keep their historical resolution.
    assert verifier_subject_family("code") == "code"
    assert verifier_subject_family("literature") == "literature"
    assert verifier_subject_family("unknown-subject") == "code"


@pytest.mark.parametrize("profile_id", DOGFLOOD_IDS)
def test_dogfood_profile_locale_adaptation_and_labels(profile_id: str) -> None:
    profile = get_subject_profile(profile_id)
    default_locale = profile.locale_adaptation.get("default_content_locale")
    assert default_locale in SUPPORTED_HOOK_LOCALES
    assert profile.dimension_labels.keys() >= _LABEL_LANGUAGES
    for labels in profile.dimension_labels.values():
        assert set(labels.keys()) == set(profile.dimensions)
        assert all(str(value).strip() for value in labels.values())


def test_japanese_learning_is_cjk_counted_and_german_french_are_latin_counted() -> None:
    japanese = get_subject_profile("japanese-learning")
    assert japanese.locale_adaptation.get("counter_mode") == "cjk_char_or_latin_word"
    for profile_id in ("german-grammar", "french-writing"):
        profile = get_subject_profile(profile_id)
        assert profile.locale_adaptation.get("counter_mode") == "latin_word"


# ---------------------------------------------------------------------------
# Restored from test_subject_profile_and_epub.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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
    assert code.dimensions == (
        "comprehension",
        "implementation",
        "debugging",
        "transfer",
        "delayed_recall",
    )
    assert "file_based" in code.deliverable_kinds

    lit = get_subject_profile("literature")
    assert lit.dimensions == (
        "comprehension",
        "expression",
        "appreciation",
        "transfer",
        "delayed_recall",
    )
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


# ---------------------------------------------------------------------------
# Restored from test_subject_profile_packaging.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


SHIPPED_SUBJECTS = {
    "code",
    "literature",
    "french-writing",
    "german-grammar",
    "japanese-learning",
}


LANGUAGE_SUBJECTS = {"french-writing", "german-grammar", "japanese-learning"}


def test_a_language_subject_resolves_to_its_own_profile_and_family() -> None:
    for subject in sorted(SHIPPED_SUBJECTS):
        assert get_subject_profile(subject).id == subject
    for subject in LANGUAGE_SUBJECTS:
        # Language subjects are verified as writing, not as code.
        assert verifier_subject_family(subject) == "literature"
    assert verifier_subject_family("code") == "code"
    assert verifier_subject_family("literature") == "literature"
