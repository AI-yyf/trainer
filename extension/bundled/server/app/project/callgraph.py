"""P1 项目理解深化 — function-level call graph + git-diff change impact.

确定性、非 LLM，建立在 `symbols.py` 的符号索引之上：

- **调用链解析**: within each source file, call sites `name(` that resolve to
  a repo-defined symbol produce caller→callee edges. Python resolves the
  enclosing function via indent tracking (function-level granularity); brace
  languages (TS/JS/Go/Rust/Java) fall back to file-level callers, labelled
  honestly as ``kind="file"``.
- **改动影响面**: `git diff` (explicit ``since`` commit, or the working tree
  when omitted) → changed files → changed symbols (added/modified via the
  current index, removed via the old blob's symbols) → affected callers,
  expanded transitively up to ``depth`` hops with a hard caller cap.

Trainer never executes repo code; this is static, read-only analysis.
"""

from __future__ import annotations

import re
import subprocess  # noqa: S404 - git is invoked with an argv list, no shell
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.project.symbols import SOURCE_SUFFIXES, RepoIndex, SymbolLocation

MAX_CALL_EDGES = 4000
MAX_AFFECTED_CALLERS = 60
MAX_DIFF_FILES = 500

_CALL_SITE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_DEF_GUARDS = ("def ", "fn ", "func ", "function ")
_FUNCTION_KINDS = {"function", "method"}


@dataclass(slots=True)
class CallEdge:
    caller_file: str
    caller_symbol: str  # function/method name, or the file path when file-level
    caller_kind: str  # "function" | "method" | "file"
    callee_symbol: str
    callee_file: str

    def as_payload(self) -> dict[str, str]:
        return {
            "caller_file": self.caller_file,
            "caller_symbol": self.caller_symbol,
            "caller_kind": self.caller_kind,
            "callee_symbol": self.callee_symbol,
            "callee_file": self.callee_file,
        }


@dataclass(slots=True)
class CallGraph:
    root: Path
    edges: list[CallEdge] = field(default_factory=list)
    callers_by_symbol: dict[str, list[CallEdge]] = field(default_factory=dict)
    # Call sites whose callee has no current definition — exactly the broken
    # callers when a symbol gets removed (P1 改动影响面).
    unresolved_by_symbol: dict[str, list[CallEdge]] = field(default_factory=dict)
    truncated: bool = False

    def to_payload(self, *, limit: int = 200) -> dict[str, Any]:
        return {
            "artifact": "trainer.project.callgraph",
            "version": 1,
            "root": self.root.as_posix(),
            "edge_count": len(self.edges),
            "unresolved_caller_count": sum(
                len(entries) for entries in self.unresolved_by_symbol.values()
            ),
            "truncated": self.truncated,
            "edges": [edge.as_payload() for edge in self.edges[:limit]],
        }


def _definitions_by_name(repo_index: RepoIndex) -> dict[str, list[SymbolLocation]]:
    definitions: dict[str, list[SymbolLocation]] = {}
    for symbol in repo_index.symbols:
        definitions.setdefault(symbol.name, []).append(symbol)
    return definitions


def _python_caller_stack(line: str, stack: list[tuple[int, str, str]]) -> None:
    """Maintain the enclosing (indent, name, kind) stack for one Python line.

    Conservative: only ``def`` lines push scope; a non-def line dedented to
    the same or shallower indent as the stack top closes that scope. Blank
    and comment lines never pop. Continuation lines aligned at column 0
    (multi-line calls) may close a scope early — an accepted, documented
    limitation of indent-level tracking.
    """

    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return
    indent = len(line) - len(line.lstrip(" "))
    match = re.match(r"(?:async\s+)?def\s+([A-Za-z_]\w*)", stripped)
    if match:
        while stack and stack[-1][0] >= indent:
            stack.pop()
        kind = "method" if indent > 0 else "function"
        stack.append((indent, match.group(1), kind))
        return
    while stack and indent <= stack[-1][0]:
        stack.pop()


def _call_edges_for_python(
    relative: str,
    text: str,
    definitions: dict[str, list[SymbolLocation]],
    edges: list[CallEdge],
    unresolved: dict[str, list[CallEdge]],
) -> bool:
    truncated = False
    stack: list[tuple[int, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        _python_caller_stack(line, stack)
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for match in _CALL_SITE.finditer(stripped):
            name = match.group(1)
            if any(stripped.startswith(guard) and stripped[len(guard):].strip().startswith(name) for guard in _DEF_GUARDS):
                continue  # the definition line itself, not a call site
            caller = stack[-1] if stack else None
            if caller is not None:
                caller_key = (caller[1], caller[2])
            else:
                caller_key = (relative, "file")
            key = (name, caller_key[0])
            if key in seen:
                continue
            seen.add(key)
            known = definitions.get(name)
            if known:
                for callee in known[:1]:
                    edges.append(
                        CallEdge(
                            caller_file=relative,
                            caller_symbol=caller_key[0],
                            caller_kind=caller_key[1],
                            callee_symbol=name,
                            callee_file=callee.path,
                        )
                    )
            else:
                unresolved.setdefault(name, []).append(
                    CallEdge(
                        caller_file=relative,
                        caller_symbol=caller_key[0],
                        caller_kind=caller_key[1],
                        callee_symbol=name,
                        callee_file="",
                    )
                )
            if len(edges) >= MAX_CALL_EDGES:
                return True
        if len(edges) >= MAX_CALL_EDGES:
            truncated = True
            break
    return truncated


def _call_edges_for_generic(
    relative: str,
    text: str,
    definitions: dict[str, list[SymbolLocation]],
    edges: list[CallEdge],
    unresolved: dict[str, list[CallEdge]],
) -> bool:
    """Brace languages: honest file-level callers (kind="file")."""

    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "*", "/*")):
            continue
        for match in _CALL_SITE.finditer(stripped):
            name = match.group(1)
            if name in seen:
                continue
            if any(stripped.startswith(guard) and stripped[len(guard):].strip().startswith(name) for guard in _DEF_GUARDS):
                continue
            seen.add(name)
            known = definitions.get(name)
            if known:
                for callee in known[:1]:
                    edges.append(
                        CallEdge(
                            caller_file=relative,
                            caller_symbol=relative,
                            caller_kind="file",
                            callee_symbol=name,
                            callee_file=callee.path,
                        )
                    )
            else:
                unresolved.setdefault(name, []).append(
                    CallEdge(
                        caller_file=relative,
                        caller_symbol=relative,
                        caller_kind="file",
                        callee_symbol=name,
                        callee_file="",
                    )
                )
            if len(edges) >= MAX_CALL_EDGES:
                return True
    return len(edges) >= MAX_CALL_EDGES


def build_call_graph(repo_root: Path, repo_index: RepoIndex) -> CallGraph:
    """Deterministic caller→callee edges over the repo's own symbols."""

    definitions = _definitions_by_name(repo_index)
    graph = CallGraph(root=repo_root)
    for relative in repo_index.files:
        language = SOURCE_SUFFIXES.get(Path(relative).suffix.lower())
        if not language or language in {"markdown", "rst"}:
            continue
        try:
            text = (repo_root / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if language == "python":
            truncated = _call_edges_for_python(
                relative, text, definitions, graph.edges, graph.unresolved_by_symbol
            )
        else:
            truncated = _call_edges_for_generic(
                relative, text, definitions, graph.edges, graph.unresolved_by_symbol
            )
        if truncated:
            graph.truncated = True
            break
    for edge in graph.edges:
        graph.callers_by_symbol.setdefault(edge.callee_symbol, []).append(edge)
    return graph


# --- git diff → changed files/symbols → affected callers -------------------


def _git(args: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    # rstrip only: `git status --porcelain` columns are positional, the
    # leading status byte/space must survive (`.strip()` shifted them).
    return completed.stdout.rstrip()


def changed_files_from_diff(repo_root: Path, *, since: str = "") -> tuple[list[str], str]:
    """Changed files from ``since..HEAD`` (or the working tree when omitted).

    Returns ``(files, basis)`` where basis documents the diff source honestly.
    """

    if since.strip():
        output = _git(["diff", "--name-only", f"{since.strip()}..HEAD"], repo_root)
        basis = f"git diff {since.strip()}..HEAD"
        files = [line.strip() for line in output.splitlines() if line.strip()]
    else:
        output = _git(["status", "--porcelain"], repo_root)
        basis = "git status --porcelain (working tree vs HEAD)"
        files = []
        for line in output.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip().strip('"')
            if path.startswith("-> "):
                path = path[3:]
            if path and not path.endswith("/"):
                files.append(path)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in files:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:MAX_DIFF_FILES], basis


def _old_file_symbols(repo_root: Path, relative: str, since: str) -> list[str]:
    """Symbol names present in ``since``'s version of the file (removed check)."""

    if not since.strip():
        return []
    blob = _git(["show", f"{since.strip()}:{relative}"], repo_root)
    if not blob:
        return []
    names: list[str] = []
    for line in blob.splitlines():
        stripped = line.strip()
        match = re.match(r"(?:async\s+)?def\s+([A-Za-z_]\w*)", stripped)
        if not match:
            match = re.match(r"(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)", stripped)
        if not match:
            match = re.match(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", stripped)
        if match:
            names.append(match.group(1))
    return names


@dataclass(slots=True)
class ChangeImpact:
    basis: str
    changed_files: list[str]
    changed_symbols: list[str]
    removed_symbols: list[str]
    affected_callers: list[dict[str, Any]]
    truncated: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact": "trainer.project.change-impact",
            "version": 1,
            "basis": self.basis,
            "changed_file_count": len(self.changed_files),
            "changed_files": self.changed_files[:40],
            "changed_symbols": self.changed_symbols[:60],
            "removed_symbols": self.removed_symbols[:40],
            "affected_caller_count": len(self.affected_callers),
            "affected_callers": self.affected_callers[:MAX_AFFECTED_CALLERS],
            "truncated": self.truncated,
        }


def compute_change_impact(
    repo_root: Path,
    repo_index: RepoIndex,
    graph: CallGraph,
    *,
    since: str = "",
    depth: int = 2,
) -> ChangeImpact:
    """Changed symbols → affected callers (transitive, bounded)."""

    changed_files, basis = changed_files_from_diff(repo_root, since=since)
    current_names_by_file: dict[str, set[str]] = {}
    for symbol in repo_index.symbols:
        current_names_by_file.setdefault(symbol.path, set()).add(symbol.name)

    changed_symbols: list[str] = []
    seen_symbols: set[str] = set()
    removed_symbols: list[str] = []
    for relative in changed_files:
        names = current_names_by_file.get(relative, set())
        for name in sorted(names):
            if name not in seen_symbols:
                seen_symbols.add(name)
                changed_symbols.append(name)
        old_names = _old_file_symbols(repo_root, relative, since)
        for name in old_names:
            if name not in names and name not in removed_symbols:
                removed_symbols.append(name)

    # Direct + transitive callers of every changed/removed symbol. Removed
    # symbols additionally surface their unresolved call sites — the broken
    # callers the removal leaves behind.
    frontier: dict[str, int] = {name: 1 for name in (*changed_symbols, *removed_symbols)}
    removed_set = set(removed_symbols)
    affected: dict[tuple[str, str, str], dict[str, Any]] = {}
    max_depth = max(1, min(int(depth), 3))
    for hop in range(1, max_depth + 1):
        next_frontier: dict[str, int] = {}
        for name in frontier:
            incoming = list(graph.callers_by_symbol.get(name, []))
            if name in removed_set:
                incoming = incoming + list(graph.unresolved_by_symbol.get(name, []))
            for edge in incoming:
                key = (edge.caller_file, edge.caller_symbol, edge.caller_kind)
                entry = affected.get(key)
                if entry is None:
                    entry = {
                        "caller_file": edge.caller_file,
                        "caller_symbol": edge.caller_symbol,
                        "caller_kind": edge.caller_kind,
                        "via_symbol": name,
                        "hops": hop,
                        "broken": name in removed_set,
                    }
                    affected[key] = entry
                else:
                    if hop < int(entry.get("hops", hop)):
                        entry["hops"] = hop
                    if name in removed_set:
                        entry["broken"] = True
                if edge.caller_symbol != edge.caller_file:
                    next_frontier.setdefault(edge.caller_symbol, hop + 1)
        if len(affected) >= MAX_AFFECTED_CALLERS:
            break
        frontier = {
            name: distance
            for name, distance in next_frontier.items()
            if name not in affected and distance <= max_depth
        }
        if not frontier:
            break

    caller_list = sorted(
        affected.values(),
        key=lambda item: (item["hops"], item["caller_file"], item["caller_symbol"]),
    )
    return ChangeImpact(
        basis=basis,
        changed_files=changed_files,
        changed_symbols=changed_symbols,
        removed_symbols=removed_symbols,
        affected_callers=caller_list,
        truncated=len(affected) > MAX_AFFECTED_CALLERS,
    )
