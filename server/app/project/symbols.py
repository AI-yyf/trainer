"""Deterministic, non-LLM symbol extraction for source files (P2 §六).

Trainer's project understanding is grounded in deterministic parsing first:
file trees, symbol tables and line numbers come from regex extraction here,
never from a model. Consumers: the token benchmark (layered mode) and the
GitHub/local project importer's symbol-index artifact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_SUFFIXES = {
    ".md": "markdown",
    ".rst": "rst",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    ".next",
    ".tox",
}

MAX_FILE_BYTES = 512_000
MAX_FILES = 5_000


@dataclass(slots=True)
class SymbolLocation:
    path: str  # POSIX-style, relative to the repo root
    name: str
    line: int  # 1-based
    kind: str  # "function" | "class" | "method" | "const"


@dataclass(slots=True)
class RepoIndex:
    root: Path
    files: list[str]
    symbols: list[SymbolLocation]
    truncated_files: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "root": self.root.as_posix(),
            "file_count": len(self.files),
            "symbol_count": len(self.symbols),
            "truncated_files": self.truncated_files,
            "files": list(self.files),
            "symbols": [
                {"path": s.path, "name": s.name, "line": s.line, "kind": s.kind}
                for s in self.symbols[:2_000]
            ],
        }


def walk_source_files(root: Path) -> tuple[list[Path], bool]:
    """Sorted source files, skipping vendored/build dirs. Returns (files, truncated)."""

    files: list[Path] = []
    truncated = False
    stack = [root]
    while stack and len(files) < MAX_FILES:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIP_DIRS:
                    continue
                stack.append(entry)
                continue
            if entry.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            try:
                if entry.stat().st_size > MAX_FILE_BYTES:
                    truncated = True
                    continue
            except OSError:
                continue
            files.append(entry)
            if len(files) >= MAX_FILES:
                truncated = True
                return files, truncated
    return files, truncated


_SYMBOL_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "python": (
        re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)"),
        re.compile(r"^class\s+([A-Za-z_]\w*)"),
    ),
    "typescript": (
        re.compile(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
        re.compile(r"(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
        re.compile(r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\(|function)"),
    ),
    "javascript": (
        re.compile(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
        re.compile(r"(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),
        re.compile(r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\(|function)"),
    ),
    "go": (re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"),),
    "rust": (
        re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)"),
    ),
    "java": (re.compile(r"(?:public|private|protected)\s+(?:[\w<>\[\]]+\s+)+([A-Za-z_]\w*)\s*\("),),
}


def extract_symbols(path: Path) -> list[SymbolLocation]:
    language = SOURCE_SUFFIXES.get(path.suffix.lower())
    patterns = _SYMBOL_PATTERNS.get(language) if language else None
    if not patterns:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    symbols: list[SymbolLocation] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*", "/*")):
            continue
        for pattern in patterns:
            match = pattern.search(stripped)
            if match:
                name = match.group(1)
                kind = "class" if "class" in pattern.pattern else "function"
                symbols.append(
                    SymbolLocation(
                        path=path.name,  # caller rebases to repo-relative
                        name=name,
                        line=number,
                        kind="method" if line.startswith((" ", "\t")) and kind == "function" else kind,
                    )
                )
                break
    return symbols


def build_repo_index(root: Path) -> RepoIndex:
    """Deterministic file list + symbol table for a repository root."""

    files, truncated = walk_source_files(root)
    symbols: list[SymbolLocation] = []
    relative_files: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        relative_files.append(relative)
        for symbol in extract_symbols(path):
            symbols.append(
                SymbolLocation(
                    path=relative,
                    name=symbol.name,
                    line=symbol.line,
                    kind=symbol.kind,
                )
            )
    return RepoIndex(
        root=root,
        files=relative_files,
        symbols=symbols,
        truncated_files=truncated,
    )
