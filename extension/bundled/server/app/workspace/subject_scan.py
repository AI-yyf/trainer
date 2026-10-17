"""§1.21.2  Workspace subject-family scanning — literature vs code.

P2 #24: the workspace classifier records a first-class subject family beside
the folder role so coach copy, course packs, and the skill deck can scope
themselves without re-guessing from card titles at second use.

Detection is deliberately conservative: ``literature`` requires positive
literary signals (clearly named novel/essay/poetry directories or a prose
corpus of EPUB/TXT/DOC/DOCX files) AND no engineering evidence (dependency
manifests, model artifacts, or a dominating code-file count). Anything
uncertain stays ``code`` — the historical default — so existing workspaces
never change meaning.
"""
from __future__ import annotations

from typing import Any, Literal, Mapping

WorkspaceSubjectFamily = Literal["code", "literature"]

LITERATURE_DIR_MARKERS: frozenset[str] = frozenset({
    "novels",
    "novel",
    "essays",
    "essay",
    "poems",
    "poetry",
    "poem",
    "prose",
    "literature",
    "anthology",
    "anthologies",
    "fiction",
    "manuscript",
    "manuscripts",
    "close-reading",
    "精读",
    "小说",
    "散文",
    "诗歌",
    "文学",
    "文论",
    "批注",
})

LITERATURE_PROSE_EXTENSIONS: frozenset[str] = frozenset({
    ".epub",
    ".txt",
    ".doc",
    ".docx",
})

CODE_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".c",
    ".h",
    ".cpp",
    ".cs",
    ".kt",
    ".swift",
    ".m",
    ".R",
    ".jl",
    ".ipynb",
    ".html",
    ".vue",
    ".svelte",
    ".sh",
    ".bat",
    ".ps1",
    ".sql",
})

# One named literary directory plus one stray EPUB must not flip a repo. A
# directory marker counts double (naming a folder is a deliberate act) while
# each prose carrier counts once; the family only flips to ``literature`` when
# that signal clears the floor AND beats the code-file count.
_MIN_LITERATURE_SIGNAL = 4


def _signal_count(raw: Any) -> int:
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def detect_workspace_subject_family(
    scan: Mapping[str, Any] | None,
) -> WorkspaceSubjectFamily:
    """Classify a heuristic scan dict; fail closed to ``code``."""
    if not isinstance(scan, Mapping):
        return "code"
    # Dependency manifests and model artifacts are unambiguous engineering
    # evidence and outweigh any literary marker.
    if scan.get("dependency_files") or scan.get("model_artifacts"):
        return "code"
    extensions = scan.get("extensions")
    ext_counts: Mapping[str, Any] = extensions if isinstance(extensions, Mapping) else {}
    prose_count = sum(
        _signal_count(ext_counts.get(ext)) for ext in LITERATURE_PROSE_EXTENSIONS
    )
    code_count = sum(_signal_count(ext_counts.get(ext)) for ext in CODE_EXTENSIONS)
    raw_dirs = scan.get("top_level_dirs")
    dir_iter = (
        [str(entry) for entry in raw_dirs]
        if isinstance(raw_dirs, (list, tuple, set))
        else []
    )
    marker_count = sum(
        1
        for entry in dir_iter
        if entry.strip().lower().rstrip("/\\") in LITERATURE_DIR_MARKERS
    )
    literature_signal = marker_count * 2 + prose_count
    if literature_signal >= _MIN_LITERATURE_SIGNAL and literature_signal > code_count:
        return "literature"
    return "code"
