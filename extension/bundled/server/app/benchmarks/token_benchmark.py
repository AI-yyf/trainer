"""bench:token — three-mode injection benchmark (§四 必须验证的效果).

Compares, over the same repository and the same question set, how many
tokens each strategy must inject to answer with the expected code located:

1. ``full_repository``  — concatenate every source file (the naive dump).
2. ``plain_rag``        — fixed-size chunk retrieval ranked by keyword overlap.
3. ``layered``          — file tree → symbol index → targeted excerpts.

No LLM is invoked: this measures the *injection* budget each strategy needs,
using the same chars/4 estimator as the harness, plus a deterministic
localization score (was each expected file selected, and how early).
Deterministic by construction so the benchmark is repeatable in CI.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.llm.harness import estimate_tokens
from app.project.symbols import build_repo_index

CHUNK_LINES = 40
RAG_TOP_K = 8
LAYER_EXCERPT_LINES = 18
MAX_FULL_CHARS = 2_000_000

_QUERY_KEYWORD_STOP = {
    "the", "a", "an", "of", "in", "for", "to", "and", "is", "are", "how",
    "what", "where", "which", "does", "do", "with", "on", "at", "from",
    "show", "find", "explain", "me", "it", "this", "that", "by", "be",
    "can", "use", "using", "used", "围绕", "的", "是", "在", "和", "与",
}


@dataclass(slots=True)
class BenchmarkQuery:
    question: str
    expect_paths: list[str]  # repo-relative files a correct answer must cite
    keywords: list[str] = field(default_factory=list)

    def terms(self) -> list[str]:
        base = [
            term.lower()
            for term in re.split(r"[^A-Za-z0-9_\u4e00-\u9fff]+", self.question)
            if term and term.lower() not in _QUERY_KEYWORD_STOP
        ]
        extra = [k.lower() for k in self.keywords]
        return list(dict.fromkeys(base + extra))


@dataclass(slots=True)
class ModeResult:
    mode: str
    tokens: int
    injected_chars: int
    localization_hit_rate: float
    queries_hit: int
    truncated: bool = False
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "tokens": self.tokens,
            "injected_chars": self.injected_chars,
            "localization_hit_rate": round(self.localization_hit_rate, 4),
            "queries_hit": self.queries_hit,
            "truncated": self.truncated,
            "notes": list(self.notes),
        }


def _chunk_file(text: str, chunk_lines: int = CHUNK_LINES) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    for start in range(0, len(lines), chunk_lines):
        chunk = "\n".join(lines[start : start + chunk_lines]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _keyword_score(chunk: str, terms: list[str]) -> int:
    lowered = chunk.lower()
    return sum(lowered.count(term) for term in terms if term)


def _full_repository_mode(files: dict[str, str]) -> ModeResult:
    parts: list[str] = []
    used = 0
    truncated = False
    for relative in sorted(files):
        text = files[relative]
        if used + len(text) > MAX_FULL_CHARS:
            truncated = True
            break
        parts.append(f"--- {relative} ---\n{text}")
        used += len(text)
    injected = "\n\n".join(parts)
    return ModeResult(
        mode="full_repository",
        tokens=estimate_tokens([{"role": "user", "content": injected}]),
        injected_chars=len(injected),
        localization_hit_rate=1.0 if parts and not truncated else 0.0,
        queries_hit=0,
        truncated=truncated,
        notes=[
            "Everything is in context by construction, so localization is "
            "'perfect' only while the whole repo still fits the cap; token "
            "cost is the product's real problem."
        ],
    )


def _plain_rag_mode(
    files: dict[str, str],
    queries: list[BenchmarkQuery],
    top_k: int = RAG_TOP_K,
) -> tuple[ModeResult, dict[str, list[str]]]:
    chunks: list[tuple[str, str]] = []  # (path, chunk)
    for relative in sorted(files):
        for chunk in _chunk_file(files[relative]):
            chunks.append((relative, chunk))
    total_tokens = 0
    hits = 0
    selected_by_query: dict[str, list[str]] = {}
    for query in queries:
        terms = query.terms()
        ranked = sorted(
            chunks,
            key=lambda item: _keyword_score(item[1], terms),
            reverse=True,
        )
        selected = ranked[:top_k]
        chosen_paths: list[str] = []
        injected_for_query = ""
        for relative, chunk in selected:
            chosen_paths.append(relative)
            injected_for_query += chunk
        selected_by_query[query.question] = chosen_paths
        total_tokens += estimate_tokens(
            [{"role": "user", "content": injected_for_query}]
        )
        hit = any(path in query.expect_paths for path in chosen_paths)
        if hit:
            hits += 1
    rate = hits / len(queries) if queries else 0.0
    return (
        ModeResult(
            mode="plain_rag",
            tokens=total_tokens,
            injected_chars=0,
            localization_hit_rate=rate,
            queries_hit=hits,
            notes=[
                f"top_k={top_k}, chunk_lines={CHUNK_LINES}; per-query budget is "
                "the sum of the selected chunks' estimates."
            ],
        ),
        selected_by_query,
    )


def _layered_mode(
    files: dict[str, str],
    index: Any,
    queries: list[BenchmarkQuery],
    excerpt_lines: int = LAYER_EXCERPT_LINES,
) -> tuple[ModeResult, dict[str, list[str]]]:
    # Stage 1 — the tree + symbol table is injected once (deterministic).
    tree_text = "\n".join(index.files)
    tree_tokens = estimate_tokens([{"role": "user", "content": tree_text}])
    symbols_by_file: dict[str, list[str]] = {}
    for symbol in index.symbols:
        symbols_by_file.setdefault(symbol.path, []).append(symbol.name)

    total_tokens = tree_tokens
    hits = 0
    selected_by_query: dict[str, list[str]] = {}
    per_query_notes: list[str] = []
    for query in queries:
        terms = [t.lower() for t in query.terms()]
        scored_files: list[tuple[str, int]] = []
        for relative in sorted(files):
            name_hits = sum(
                1
                for name in symbols_by_file.get(relative, [])
                if any(term in name.lower() for term in terms)
            )
            path_hits = sum(1 for term in terms if term in relative.lower())
            # Content-term density: weaker than symbol/path signals but catches
            # matches that pure name matching misses (§四 分级检索 step 2).
            content_hits = _keyword_score(files[relative], terms)
            score = name_hits * 4 + path_hits * 2 + (1 if content_hits >= 3 else 0)
            # Real project understanding skips test/fixture files entirely:
            # they have high keyword density but are not the implementation.
            lowered_path = relative.lower()
            if "/test_" in lowered_path or lowered_path.startswith("test_") or "/tests/" in lowered_path:
                continue
            if name_hits or path_hits or content_hits >= 3:
                scored_files.append((relative, score))
        scored_files.sort(key=lambda item: (-item[1], item[0]))
        picked = [relative for relative, _ in scored_files[:2]]
        if not picked and scored_files:
            picked = [scored_files[0][0]]
        injected = ""
        for relative in picked:
            text = files[relative]
            if terms:
                # Deterministic excerpt: first block containing any term,
                # bounded to excerpt_lines.
                lines = text.splitlines()
                start = 0
                for offset, line in enumerate(lines):
                    lowered = line.lower()
                    if any(term in lowered for term in terms):
                        start = max(0, offset - 2)
                        break
                window = lines[start : start + excerpt_lines]
                injected += f"--- {relative}:{start + 1} ---\n" + "\n".join(window)
        selected_by_query[query.question] = picked
        total_tokens += estimate_tokens([{"role": "user", "content": injected}])
        hit = any(path in query.expect_paths for path in picked)
        if hit:
            hits += 1
        else:
            per_query_notes.append(f"miss: {query.question[:60]}")

    rate = hits / len(queries) if queries else 0.0
    return (
        ModeResult(
            mode="layered",
            tokens=total_tokens,
            injected_chars=0,
            localization_hit_rate=rate,
            queries_hit=hits,
            notes=per_query_notes,
        ),
        selected_by_query,
    )


def run_token_benchmark(
    repo_root: str | Path,
    queries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the three-mode comparison over one repository. No LLM involved."""

    root = Path(repo_root).expanduser().resolve(strict=False)
    repo_index = build_repo_index(root)
    parsed_queries = [
        BenchmarkQuery(
            question=str(item.get("question") or "").strip(),
            expect_paths=[str(p) for p in item.get("expect_paths", [])],
            keywords=[str(k) for k in item.get("keywords", [])],
        )
        for item in queries
        if str(item.get("question") or "").strip()
    ]
    if not parsed_queries:
        raise ValueError("At least one benchmark query is required.")

    contents: dict[str, str] = {}
    for relative in repo_index.files:
        try:
            contents[relative] = (root / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

    full = _full_repository_mode(contents)
    rag, rag_selection = _plain_rag_mode(contents, parsed_queries)
    layered, layered_selection = _layered_mode(contents, repo_index, parsed_queries)

    per_query = []
    for query in parsed_queries:
        per_query.append(
            {
                "question": query.question,
                "expect_paths": query.expect_paths,
                "rag_selected": rag_selection.get(query.question, []),
                "layered_selected": layered_selection.get(query.question, []),
            }
        )

    layered_qualifies = (
        layered.localization_hit_rate >= rag.localization_hit_rate
        and layered.tokens < full.tokens
    )
    return {
        "repo": root.as_posix(),
        "repo_file_count": len(repo_index.files),
        "repo_symbol_count": len(repo_index.symbols),
        "query_count": len(parsed_queries),
        "modes": {
            "full_repository": full.to_payload(),
            "plain_rag": rag.to_payload(),
            "layered": layered.to_payload(),
        },
        "per_query": per_query,
        "verdict": {
            "layered_tokens_less_than_full": layered.tokens < full.tokens,
            "layered_localization_not_worse_than_rag": (
                layered.localization_hit_rate >= rag.localization_hit_rate
            ),
            "layered_qualifies": layered_qualifies,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m app.benchmarks.token_benchmark --repo <dir> [--queries <json>]"""

    import argparse

    parser = argparse.ArgumentParser(description="bench:token three-mode comparison")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--queries", default="[]", help="JSON list of {question, expect_paths, keywords}")
    args = parser.parse_args(argv if argv is not None else None)
    report = run_token_benchmark(args.repo, json.loads(args.queries))
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
