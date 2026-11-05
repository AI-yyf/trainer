"""P2 深化 — deterministic project overview Artifact (架构图/模块依赖图).

Pure-regex, no LLM, no network:

- **Module map**: top-level directory → file / symbol / language counts.
- **Dependency graph**: import / require / use statements resolved to
  internal repo files, aggregated into module-level edges with fan-in /
  fan-out — the 架构图 source for the mermaid rendering.
- **Entry points + hotspots**: conventional entry files, highest-fan-in
  modules and largest-symbol files, so a coach can answer "where do I
  start reading this project" deterministically.

Git SHA pinning (Git SHA→Evidence):

- Every overview artifact carries ``commit_sha`` in its front matter.
- :func:`evidence_git_snapshot` reads the live repo state.
- :func:`resolve_resource_git_sha` maps a resource id back to the pinned
  commit from its symbol-index artifact; the evidence route embeds that
  server-side so a client cannot forge the pin.
"""

from __future__ import annotations

import json
import posixpath
import re
import subprocess  # noqa: S404 - git is invoked with an argv list, no shell
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.project.symbols import SOURCE_SUFFIXES, RepoIndex

MAX_EDGES = 400
MAX_MERMAID_NODES = 24
MAX_MERMAID_EDGES = 30
MAX_EXTERNAL_IMPORTS = 20

_ENTRY_FILE_NAMES = {
    "main.py",
    "app.py",
    "manage.py",
    "server.py",
    "server.ts",
    "server.js",
    "server.go",
    "main.ts",
    "main.js",
    "main.go",
    "index.ts",
    "index.js",
}

_PYTHON_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.,\s]+))")
_TS_IMPORT = re.compile(r"""(?:import\s[^'"]*?from|import|require)\s*\(?\s*["']([^"']+)["']""")
_GO_IMPORT = re.compile(r'^\s*(?:[_\w]+\s+)?"([\w./-]+)"\s*$')
_RUST_USE = re.compile(r"^\s*(?:pub\s+)?use\s+crate::([\w:]+)")

_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs")


def _iter_import_strings(text: str, language: str) -> list[str]:
    """Raw imported module specifiers for one file, in order."""

    specifiers: list[str] = []
    for stripped in (line.strip() for line in text.splitlines()):
        if not stripped or stripped.startswith(("#", "//", "*", "/*")):
            continue
        if language == "python":
            match = _PYTHON_IMPORT.match(stripped)
            if not match:
                continue
            if match.group(1):
                specifiers.append(match.group(1))
            else:
                for chunk in (match.group(2) or "").split(","):
                    name = chunk.strip().split(" as ")[0].strip()
                    if name:
                        specifiers.append(name)
        elif language in {"typescript", "javascript"}:
            for match in _TS_IMPORT.finditer(stripped):
                specifiers.append(match.group(1))
        elif language == "go":
            match = _GO_IMPORT.match(stripped)
            if match:
                specifiers.append(match.group(1))
        elif language == "rust":
            match = _RUST_USE.match(stripped)
            if match:
                specifiers.append("crate::" + match.group(1))
    return specifiers


def _resolve_internal(
    from_file: str,
    specifier: str,
    file_set: set[str],
    language: str,
) -> str | None:
    """Resolve one import specifier to an internal repo-relative file."""

    if language == "python":
        parts = specifier.split(".")
        for depth in range(len(parts), 0, -1):
            base = "/".join(parts[:depth])
            if f"{base}.py" in file_set:
                return f"{base}.py"
            if f"{base}/__init__.py" in file_set:
                return f"{base}/__init__.py"
        return None
    if language in {"typescript", "javascript"}:
        if not specifier.startswith("."):
            return None  # bare specifier (npm package) — external
        base = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), specifier))
        if base in file_set:
            return base
        for ext in _TS_EXTENSIONS:
            if f"{base}{ext}" in file_set:
                return f"{base}{ext}"
        for ext in _TS_EXTENSIONS:
            candidate = f"{base}/index{ext}"
            if candidate in file_set:
                return candidate
        return None
    if language == "go":
        if f"{specifier}.go" in file_set:
            return f"{specifier}.go"
        matches = [f for f in file_set if f.startswith(specifier + "/")]
        if matches:
            return matches[0]
        return None
    if language == "rust":
        if specifier.startswith("crate::"):
            base = "src/" + specifier.removeprefix("crate::").replace("::", "/")
            if f"{base}.rs" in file_set:
                return f"{base}.rs"
            if f"{base}/mod.rs" in file_set:
                return f"{base}/mod.rs"
        return None
    return None


def _top_module(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "."


@dataclass(slots=True)
class ProjectOverview:
    """Deterministic overview payload (also serialized into the artifact)."""

    root: str
    repo_url: str
    commit_sha: str
    branch: str
    file_count: int
    symbol_count: int
    modules: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, str]] = field(default_factory=list)
    module_edges: list[dict[str, Any]] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    hotspot_files: list[dict[str, Any]] = field(default_factory=list)
    hotspot_modules: list[dict[str, Any]] = field(default_factory=list)
    external_imports: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact": "trainer.project.overview",
            "version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "root": self.root,
            "repo_url": self.repo_url,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "file_count": self.file_count,
            "symbol_count": self.symbol_count,
            "modules": self.modules,
            "edges": self.edges,
            "module_edges": self.module_edges,
            "entry_points": self.entry_points,
            "hotspot_files": self.hotspot_files,
            "hotspot_modules": self.hotspot_modules,
            "external_imports": self.external_imports,
            "truncated": self.truncated,
        }


def build_dependency_edges(
    repo_root: Path,
    files: list[str],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], bool]:
    """Internal file-level import edges + external import counts (capped)."""

    file_set = set(files)
    edges: dict[tuple[str, str], None] = {}
    external: dict[str, int] = {}
    truncated = False
    for relative in files:
        language = SOURCE_SUFFIXES.get(posixpath.splitext(relative)[1].lower())
        if not language or language == "markdown" or language == "rst":
            continue
        try:
            text = (repo_root / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for specifier in _iter_import_strings(text, language):
            resolved = _resolve_internal(relative, specifier, file_set, language)
            if resolved is None:
                if not specifier.startswith("."):
                    external[specifier.split(".")[0]] = external.get(specifier.split(".")[0], 0) + 1
                continue
            if resolved == relative:
                continue
            edges.setdefault((relative, resolved), None)
            if len(edges) >= MAX_EDGES:
                truncated = True
                break
        if truncated:
            break
    edge_list = [{"src": src, "dst": dst} for src, dst in edges]
    external_list = [
        {"module": name, "count": count}
        for name, count in sorted(external.items(), key=lambda item: (-item[1], item[0]))
    ][:MAX_EXTERNAL_IMPORTS]
    return edge_list, external_list, truncated


def _detect_entry_points(repo_root: Path, files: list[str]) -> list[str]:
    entry_points = [f for f in files if posixpath.basename(f).lower() in _ENTRY_FILE_NAMES]
    for relative in files:
        if not relative.endswith(".py"):
            continue
        try:
            text = (repo_root / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if '__name__ == "__main__"' in text or "__name__ == '__main__'" in text:
            if relative not in entry_points:
                entry_points.append(relative)
    return sorted(set(entry_points))[:20]


def build_project_overview(
    repo_root: Path,
    repo_index: RepoIndex,
    *,
    repo_url: str = "",
    commit_sha: str = "",
    branch: str = "",
) -> ProjectOverview:
    """Deterministic 架构图 payload: module map + dependency graph + hotspots."""

    files = repo_index.files
    edge_list, external_list, truncated = build_dependency_edges(repo_root, files)

    symbols_by_file: dict[str, int] = {}
    for symbol in repo_index.symbols:
        symbols_by_file[symbol.path] = symbols_by_file.get(symbol.path, 0) + 1

    module_names = sorted({_top_module(f) for f in files})
    languages_by_module: dict[str, set[str]] = {m: set() for m in module_names}
    files_by_module: dict[str, list[str]] = {m: [] for m in module_names}
    for relative in files:
        module = _top_module(relative)
        files_by_module[module].append(relative)
        suffix = posixpath.splitext(relative)[1].lower()
        language = SOURCE_SUFFIXES.get(suffix)
        if language:
            languages_by_module[module].add(language)

    module_fan_in: dict[str, int] = {m: 0 for m in module_names}
    module_fan_out: dict[str, int] = {m: 0 for m in module_names}
    aggregated: dict[tuple[str, str], int] = {}
    for edge in edge_list:
        src_module = _top_module(edge["src"])
        dst_module = _top_module(edge["dst"])
        if src_module == dst_module:
            continue
        aggregated[(src_module, dst_module)] = aggregated.get((src_module, dst_module), 0) + 1
        module_fan_out[src_module] += 1
        module_fan_in[dst_module] += 1

    modules_payload = []
    for module in module_names:
        symbol_total = sum(symbols_by_file.get(f, 0) for f in files_by_module[module])
        modules_payload.append(
            {
                "module": module,
                "file_count": len(files_by_module[module]),
                "symbol_count": symbol_total,
                "languages": sorted(languages_by_module[module]),
                "fan_in": module_fan_in[module],
                "fan_out": module_fan_out[module],
            }
        )

    module_edges_payload = [
        {"src": src, "dst": dst, "weight": weight}
        for (src, dst), weight in sorted(
            aggregated.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
    ]

    hotspot_files = sorted(
        (
            {"path": f, "symbol_count": count}
            for f, count in symbols_by_file.items()
        ),
        key=lambda item: (-item["symbol_count"], item["path"]),
    )[:8]
    hotspot_modules = sorted(
        modules_payload, key=lambda item: (-item["fan_in"], item["module"])
    )[:5]
    hotspot_modules = [
        {"module": m["module"], "fan_in": m["fan_in"], "symbol_count": m["symbol_count"]}
        for m in hotspot_modules
        if m["fan_in"] > 0
    ]

    return ProjectOverview(
        root=repo_root.as_posix(),
        repo_url=repo_url,
        commit_sha=commit_sha,
        branch=branch,
        file_count=len(files),
        symbol_count=len(repo_index.symbols),
        modules=modules_payload,
        edges=edge_list,
        module_edges=module_edges_payload,
        entry_points=_detect_entry_points(repo_root, files),
        hotspot_files=hotspot_files,
        hotspot_modules=hotspot_modules,
        external_imports=external_list,
        truncated=truncated or repo_index.truncated_files,
    )


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def render_overview_markdown(overview: ProjectOverview) -> str:
    """Human/agent-readable 架构图 artifact: front matter + tables + mermaid."""

    lines = [
        "---",
        "artifact: trainer.project.overview",
        "version: 1",
        f"repo_url: {_yaml_scalar(overview.repo_url)}",
        f"commit_sha: {_yaml_scalar(overview.commit_sha)}",
        f"branch: {_yaml_scalar(overview.branch)}",
        f"generated_at: {_yaml_scalar(datetime.now(UTC).isoformat())}",
        f"file_count: {overview.file_count}",
        f"symbol_count: {overview.symbol_count}",
        "---",
        "",
        f"# Project Overview: {Path(overview.root).name}",
        "",
        f"- Commit: `{overview.commit_sha or 'no-commit'}`"
        + (f" (branch `{overview.branch}`)" if overview.branch else ""),
        f"- Files: {overview.file_count}, symbols: {overview.symbol_count}",
        "",
        "## Modules",
        "",
        "| module | files | symbols | languages | fan-in | fan-out |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for module in overview.modules:
        lines.append(
            f"| {module['module']} | {module['file_count']} | {module['symbol_count']} "
            f"| {', '.join(module['languages'])} | {module['fan_in']} | {module['fan_out']} |"
        )

    lines += ["", "## Dependency graph", ""]
    module_edges = overview.module_edges[:MAX_MERMAID_EDGES]
    nodes = sorted(
        {_top_module(edge["src"]) for edge in overview.edges}
        | {_top_module(edge["dst"]) for edge in overview.edges}
    )[:MAX_MERMAID_NODES]
    if nodes and module_edges:
        lines.append("```mermaid")
        lines.append("graph LR")
        for module in nodes:
            lines.append(f'  {module.replace(".", "_")}["{module}"]')
        for edge in module_edges:
            src = edge["src"].replace(".", "_")
            dst = edge["dst"].replace(".", "_")
            weight = f" |{edge['weight']}x|" if edge.get("weight", 1) > 1 else ""
            lines.append(f"  {src} -->{weight} {dst}")
        lines.append("```")
    else:
        lines.append("_No internal cross-module dependencies detected._")

    lines += ["", "## Entry points", ""]
    if overview.entry_points:
        lines += [f"- `{path}`" for path in overview.entry_points]
    else:
        lines.append("_No conventional entry file detected._")

    lines += ["", "## Hotspots", ""]
    if overview.hotspot_modules:
        lines += [
            f"- Highest fan-in: {m['module']} ({m['fan_in']} inbound)"
            for m in overview.hotspot_modules
        ]
    if overview.hotspot_files:
        lines += [
            f"- Symbol-dense: `{item['path']}` ({item['symbol_count']} symbols)"
            for item in overview.hotspot_files[:5]
        ]
    if overview.external_imports:
        lines += ["", "## External dependencies", ""]
        lines += [
            f"- `{item['module']}` ×{item['count']}" for item in overview.external_imports[:10]
        ]
    lines.append("")
    return "\n".join(lines)


def write_overview_artifact(artifact_path: Path, overview: ProjectOverview) -> Path:
    """Write the Markdown overview artifact (架构图) beside the symbol index."""

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(render_overview_markdown(overview), encoding="utf-8")
    return artifact_path


def evidence_git_snapshot(repo_root: str | Path) -> dict[str, Any]:
    """Git SHA→Evidence: live repo commit/branch/dirty for evidence pinning."""

    root = Path(repo_root)
    snapshot: dict[str, Any] = {"commit_sha": "", "branch": "", "dirty": False}

    def git(*args: str) -> str:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ""
        return completed.stdout.strip()

    snapshot["commit_sha"] = git("rev-parse", "HEAD")
    snapshot["branch"] = git("rev-parse", "--abbrev-ref", "HEAD")
    status = git("status", "--porcelain")
    snapshot["dirty"] = bool(status)
    if not snapshot["commit_sha"]:
        return {"commit_sha": "", "branch": "", "dirty": False}
    return snapshot


def resolve_resource_git_sha(artifact_root: Path, resource_id: str) -> str | None:
    """Commit SHA pinned for an imported project resource, server-side only.

    Reads ``<resource_id>.symbol-index.json`` written by :func:`import_repository`;
    returns ``None`` when the resource is not an imported project.
    """

    artifact_path = artifact_root / f"{resource_id}.symbol-index.json"
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    commit_sha = str(payload.get("commit_sha") or "").strip()
    return commit_sha or None
