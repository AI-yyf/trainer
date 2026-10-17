"""P2 #24: workspace subject-family detection (literature vs code)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import FirstLookSummary
from app.workspace.classifier import classify_heuristic
from app.workspace.subject_scan import (
    LITERATURE_DIR_MARKERS,
    detect_workspace_subject_family,
)

# ---------------------------------------------------------------------------
# detect_workspace_subject_family — pure scan-dict unit behavior
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


# ---------------------------------------------------------------------------
# classify_heuristic end-to-end on real directories
# ---------------------------------------------------------------------------


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
