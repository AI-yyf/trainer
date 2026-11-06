"""Phase 2 — Analysis Adapter: pluggable, honest code-analysis providers.

Every provider reports ``available`` plus a ``reason`` when it cannot run, and
labels each edge with its evidence level:

- ``syntax_exact``   — call site located by an AST (tree-sitter). The *site* is
  exact; resolving the callee across files is still by name.
- ``approximate``    — the indentation/file-level heuristic (regex callgraph).
- ``name_resolution``— plain name→definition matching (shared by AST paths).

Limitations are reported per provider, never hidden behind a merged graph
(v1.5: 对于不支持或只能近似推断的关系必须诚实标注). LSP/SCIP is declared as a
non-configured provider until a real index is supplied — it never fabricates
edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.project.symbols import SOURCE_SUFFIXES, RepoIndex

MAX_EDGES_PER_PROVIDER = 4000


@dataclass(slots=True)
class AdapterEdge:
    caller_file: str
    caller_symbol: str
    callee_symbol: str
    callee_file: str
    confidence: str  # syntax_exact | approximate
    provider: str

    def as_payload(self) -> dict[str, str]:
        return {
            "caller_file": self.caller_file,
            "caller_symbol": self.caller_symbol,
            "callee_symbol": self.callee_symbol,
            "callee_file": self.callee_file,
            "confidence": self.confidence,
            "provider": self.provider,
        }


@dataclass(slots=True)
class AdapterReport:
    name: str
    available: bool
    reason: str = ""
    confidence: str = ""
    edges: list[AdapterEdge] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def as_payload(self, *, sample: int = 40) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": self.available,
            "reason": self.reason,
            "confidence": self.confidence,
            "edge_count": len(self.edges),
            "limitations": list(self.limitations),
            "edges_sample": [edge.as_payload() for edge in self.edges[:sample]],
        }


class AnalysisProvider(Protocol):
    name: str

    def run(self, repo_root: Path, repo_index: RepoIndex) -> AdapterReport: ...


class RegexCallGraphProvider:
    """Existing deterministic callgraph; honest about its heuristic limits."""

    name = "regex-callgraph"

    def run(self, repo_root: Path, repo_index: RepoIndex) -> AdapterReport:
        from app.project.callgraph import build_call_graph

        graph = build_call_graph(repo_root, repo_index)
        edges = [
            AdapterEdge(
                caller_file=edge.caller_file,
                caller_symbol=edge.caller_symbol,
                callee_symbol=edge.callee_symbol,
                callee_file=edge.callee_file,
                confidence="approximate",
                provider=self.name,
            )
            for edge in graph.edges[:MAX_EDGES_PER_PROVIDER]
        ]
        limitations = [
            "Python callers resolved by indentation tracking (continuation lines "
            "aligned at column 0 may close a scope early).",
            "Brace languages fall back to file-level callers (kind=file).",
            "Callees resolve by name, not by import binding.",
        ]
        if graph.truncated:
            limitations.append(f"Edge list truncated at {MAX_EDGES_PER_PROVIDER}.")
        return AdapterReport(
            name=self.name,
            available=True,
            confidence="approximate",
            edges=edges,
            limitations=limitations,
        )


def _load_tree_sitter() -> tuple[Any, Any]:
    """Dynamic import: the grammar is an optional integration, and a static
    import would make every no-deps Pyright run fail on the missing package."""

    import importlib

    tree_sitter = importlib.import_module("tree_sitter")
    grammar = importlib.import_module("tree_sitter_python")
    return tree_sitter, grammar


def _tree_sitter_available() -> tuple[bool, str]:
    try:
        _load_tree_sitter()
    except Exception as exc:  # pragma: no cover - depends on install extras
        return False, f"tree-sitter grammar not installed ({exc.__class__.__name__})"
    return True, ""


class TreeSitterPythonProvider:
    """AST call sites for Python via tree-sitter (exact positions, name binding)."""

    name = "tree-sitter-python"

    def run(self, repo_root: Path, repo_index: RepoIndex) -> AdapterReport:
        available, reason = _tree_sitter_available()
        if not available:
            return AdapterReport(name=self.name, available=False, reason=reason)

        tree_sitter, grammar = _load_tree_sitter()
        parser = tree_sitter.Parser(tree_sitter.Language(grammar.language()))
        definitions: set[str] = {symbol.name for symbol in repo_index.symbols}
        symbol_path = {symbol.name: symbol.path for symbol in repo_index.symbols}
        edges: list[AdapterEdge] = []
        seen: set[tuple[str, str, str]] = set()

        def enclosing_function(node: Any) -> str | None:
            current = node.parent
            while current is not None:
                if current.type == "function_definition":
                    name_node = current.child_by_field_name("name")
                    if name_node is not None:
                        return name_node.text.decode("utf-8", "replace")
                current = current.parent
            return None

        for relative in repo_index.files:
            if not relative.endswith(".py"):
                continue
            suffix_language = SOURCE_SUFFIXES.get(Path(relative).suffix.lower())
            if suffix_language != "python":
                continue
            try:
                source = (repo_root / relative).read_bytes()
            except OSError:
                continue
            tree = parser.parse(source)
            stack = [tree.root_node]
            while stack:
                node = stack.pop()
                if node.type == "call":
                    fn = node.child_by_field_name("function")
                    if fn is not None and fn.type == "identifier":
                        fn_text = fn.text
                        callee = fn_text.decode("utf-8", "replace") if fn_text else ""
                        if callee in definitions:
                            caller = enclosing_function(node) or relative
                            key = (relative, caller, callee)
                            if key not in seen:
                                seen.add(key)
                                edges.append(
                                    AdapterEdge(
                                        caller_file=relative,
                                        caller_symbol=caller,
                                        callee_symbol=callee,
                                        callee_file=symbol_path.get(callee, ""),
                                        confidence="syntax_exact",
                                        provider=self.name,
                                    )
                                )
                                if len(edges) >= MAX_EDGES_PER_PROVIDER:
                                    break
                stack.extend(node.children)
            if len(edges) >= MAX_EDGES_PER_PROVIDER:
                break

        return AdapterReport(
            name=self.name,
            available=True,
            confidence="syntax_exact",
            edges=edges,
            limitations=[
                "Call-site positions come from the AST; cross-file callee binding "
                "is still name-based (no import/type resolution).",
                "Only direct `name(...)` calls are recorded; method calls on "
                "objects (obj.method()) are not attributed to a definition.",
            ],
        )


class _LspSession:
    """Minimal LSP client over stdio (Content-Length framed JSON-RPC)."""

    def __init__(self, root: Path, *, timeout_s: float = 20.0) -> None:
        import subprocess  # noqa: S404 - argv list, no shell
        import sys

        self._timeout_s = timeout_s
        self._next_id = 0
        self._proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "pylsp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(root),
        )
        self._root = root
        self._initialize()

    def _send(self, message: dict[str, Any]) -> None:
        import json

        payload = json.dumps(message).encode("utf-8")
        assert self._proc.stdin is not None
        self._proc.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()

    def _read(self) -> dict[str, Any] | None:
        import json
        import selectors

        assert self._proc.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(self._proc.stdout, selectors.EVENT_READ)
        try:
            if not selector.select(self._timeout_s):
                return None
            headers: dict[str, str] = {}
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    return None
                decoded = line.decode("utf-8", "replace").strip()
                if not decoded:
                    break
                key, _, value = decoded.partition(":")
                headers[key.strip().lower()] = value.strip()
            length = int(headers.get("content-length") or 0)
            if length <= 0:
                return None
            body = self._proc.stdout.read(length)
            return json.loads(body.decode("utf-8", "replace"))
        finally:
            selector.close()

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline_reads = 200
        while deadline_reads > 0:
            deadline_reads -= 1
            message = self._read()
            if message is None:
                raise RuntimeError(f"LSP timeout waiting for {method}")
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"LSP {method} error: {message['error']}")
                return message.get("result")
            # Ignore server-initiated notifications during the wait.
        raise RuntimeError(f"LSP {method} produced no response")

    def _initialize(self) -> None:
        root_uri = self._root.resolve().as_uri()
        self._request(
            "initialize",
            {
                "processId": None,
                "rootUri": root_uri,
                "workspaceFolders": [{"uri": root_uri, "name": self._root.name}],
                "capabilities": {},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    def open_file(self, relative: str, text: str) -> str:
        uri = (self._root / relative).resolve().as_uri()
        self._send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "python",
                        "version": 1,
                        "text": text,
                    }
                },
            }
        )
        return uri

    def references(self, uri: str, line: int, character: int) -> list[dict[str, Any]]:
        result = self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": False},
            },
        )
        return list(result or [])

    def close(self) -> None:
        try:
            self._send({"jsonrpc": "2.0", "method": "shutdown", "id": 0, "params": None})
            self._proc.terminate()
        except (OSError, RuntimeError):
            pass
        finally:
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()


MAX_LSP_FILES = 40
MAX_LSP_SYMBOLS = 40
LSP_DEADLINE_S = 75.0


class LspPythonProvider:
    """Real LSP references via python-lsp-server (jedi-backed name resolution)."""

    name = "lsp-python"

    def _server_available(self) -> tuple[bool, str]:
        try:
            import importlib.util

            if importlib.util.find_spec("pylsp") is None:
                return False, "python-lsp-server is not installed"
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"python-lsp-server probe failed ({exc.__class__.__name__})"
        return True, ""

    def run(self, repo_root: Path, repo_index: RepoIndex) -> AdapterReport:
        import time

        available, reason = self._server_available()
        if not available:
            return AdapterReport(name=self.name, available=False, reason=reason)

        py_files = [f for f in repo_index.files if f.endswith(".py")][:MAX_LSP_FILES]
        if not py_files:
            return AdapterReport(
                name=self.name,
                available=False,
                reason="No Python files in this repository.",
            )
        definitions = [
            symbol
            for symbol in repo_index.symbols
            if symbol.path.endswith(".py") and symbol.kind in {"function", "class"}
        ][:MAX_LSP_SYMBOLS]
        if not definitions:
            return AdapterReport(
                name=self.name, available=False, reason="No Python definitions to resolve."
            )

        edges: list[AdapterEdge] = []
        seen: set[tuple[str, str]] = set()
        deadline = time.monotonic() + LSP_DEADLINE_S
        session: _LspSession | None = None
        limitation = ""
        try:
            session = _LspSession(repo_root)
            source_by_file: dict[str, str] = {}
            uris: dict[str, str] = {}
            for relative in py_files:
                try:
                    text = (repo_root / relative).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                source_by_file[relative] = text
                uris[relative] = session.open_file(relative, text)

            uri_to_file = {uri: relative for relative, uri in uris.items()}
            for symbol in definitions:
                if time.monotonic() > deadline:
                    limitation = (
                        f"LSP reference lookup hit the {int(LSP_DEADLINE_S)}s deadline; "
                        "edges are partial."
                    )
                    break
                text = source_by_file.get(symbol.path)
                if text is None:
                    continue
                lines = text.splitlines()
                if symbol.line - 1 >= len(lines):
                    continue
                line_text = lines[symbol.line - 1]
                column = line_text.find(symbol.name)
                if column < 0:
                    continue
                try:
                    locations = session.references(uris[symbol.path], symbol.line - 1, column)
                except RuntimeError:
                    continue
                for location in locations:
                    try:
                        ref_uri = str(location.get("uri") or "")
                        caller_file = uri_to_file.get(ref_uri)
                        if not caller_file or caller_file == symbol.path:
                            continue
                        key = (caller_file, symbol.name)
                        if key in seen:
                            continue
                        seen.add(key)
                        edges.append(
                            AdapterEdge(
                                caller_file=caller_file,
                                caller_symbol=caller_file,
                                callee_symbol=symbol.name,
                                callee_file=symbol.path,
                                confidence="lsp_reference",
                                provider=self.name,
                            )
                        )
                    except (AttributeError, TypeError):
                        continue
        except (RuntimeError, OSError) as exc:
            return AdapterReport(
                name=self.name,
                available=False,
                reason=f"LSP server failed to start or answer: {exc}",
            )
        finally:
            if session is not None:
                session.close()

        limitations = [
            "Python only; callers are file-level because LSP references report positions, "
            "not enclosing definitions.",
            "Bounded: first 40 files and 40 definitions within a 75s deadline.",
            "Requires python-lsp-server on the sidecar host (optional analysis extra).",
        ]
        if limitation:
            limitations.append(limitation)
        return AdapterReport(
            name=self.name,
            available=True,
            confidence="lsp_reference",
            edges=edges[:MAX_EDGES_PER_PROVIDER],
            limitations=limitations,
        )


class LspScipProvider:
    """Placeholder: no LSP/SCIP index is configured yet — reported, not faked."""

    name = "lsp-scip"

    def run(self, repo_root: Path, repo_index: RepoIndex) -> AdapterReport:
        _ = (repo_root, repo_index)
        return AdapterReport(
            name=self.name,
            available=False,
            reason="No LSP client or SCIP index is configured for this workspace.",
        )


DEFAULT_PROVIDERS: tuple[AnalysisProvider, ...] = (
    LspPythonProvider(),
    TreeSitterPythonProvider(),
    RegexCallGraphProvider(),
    LspScipProvider(),
)


def run_analysis_adapters(
    repo_root: Path,
    repo_index: RepoIndex,
    providers: tuple[AnalysisProvider, ...] = DEFAULT_PROVIDERS,
) -> dict[str, Any]:
    """Run every provider; merge edges preferring the highest evidence level."""

    reports = [provider.run(repo_root, repo_index) for provider in providers]
    rank = {"lsp_reference": 3, "syntax_exact": 2, "approximate": 1}
    merged: dict[tuple[str, str, str], AdapterEdge] = {}
    for report in reports:
        if not report.available:
            continue
        for edge in report.edges:
            key = (edge.caller_file, edge.caller_symbol, edge.callee_symbol)
            current = merged.get(key)
            if current is None or rank.get(edge.confidence, 0) > rank.get(current.confidence, 0):
                merged[key] = edge
    merged_edges = sorted(
        merged.values(),
        key=lambda edge: (edge.caller_file, edge.caller_symbol, edge.callee_symbol),
    )
    return {
        "artifact": "trainer.project.analysis-adapters",
        "version": 1,
        "root": repo_root.as_posix(),
        "providers": [report.as_payload() for report in reports],
        "merged_edge_count": len(merged_edges),
        "merged_edges": [edge.as_payload() for edge in merged_edges[:200]],
        "limitation_summary": [
            f"{report.name}: {limitation}"
            for report in reports
            if report.available
            for limitation in report.limitations
        ],
    }
