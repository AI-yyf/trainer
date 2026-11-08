"""Behavior tests for the SCIP JSON analysis provider."""

from __future__ import annotations

import json
from pathlib import Path

from app.project.analysis_adapter import LspScipProvider
from app.project.symbols import RepoIndex


def _index(root: Path) -> RepoIndex:
    return RepoIndex(root=root, files=[], symbols=[], truncated_files=False)


def _write_index(root: Path, payload: object) -> Path:
    path = root / ".trainer" / "scip" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_scip_json_references_become_compiler_evidence(tmp_path: Path) -> None:
    _write_index(
        tmp_path,
        {
            "documents": [
                {
                    "relativePath": "src/a.py",
                    "symbols": [
                        {
                            "symbol": "scip-python python pkg a/Foo#",
                            "displayName": "Foo",
                        }
                    ],
                    "occurrences": [
                        {
                            "symbol": "scip-python python pkg a/Foo#",
                            "symbolRoles": 1,
                            "range": [3, 0, 3],
                        }
                    ],
                },
                {
                    "relative_path": "src/b.py",
                    "occurrences": [
                        {
                            "symbol": "scip-python python pkg a/Foo#",
                            "symbol_roles": 8,
                            "range": [10, 4, 7],
                        }
                    ],
                },
            ]
        },
    )

    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is True
    assert report.confidence == "scip_reference"
    assert len(report.edges) == 1
    edge = report.edges[0]
    assert edge.caller_file == "src/b.py"
    assert edge.callee_file == "src/a.py"
    assert edge.callee_symbol == "Foo"
    assert edge.confidence == "scip_reference"
    assert any("binary .scip" in item for item in report.limitations)


def test_scip_missing_index_reports_honest_reason(tmp_path: Path) -> None:
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is False
    assert "No SCIP JSON index" in report.reason


def test_scip_binary_only_mentions_json_export(tmp_path: Path) -> None:
    (tmp_path / "index.scip").write_bytes(b"not-a-json-index")
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is False
    assert "scip print --json" in report.reason


def test_scip_invalid_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "index.scip.json"
    path.write_text("{not json", encoding="utf-8")
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is False
    assert "could not be read" in report.reason


def test_scip_skips_unmapped_and_self_file_references(tmp_path: Path) -> None:
    _write_index(
        tmp_path,
        {
            "documents": [
                {
                    "relativePath": "src/a.py",
                    "symbols": [{"symbol": "sym-a", "displayName": "A"}],
                    "occurrences": [
                        {"symbol": "unknown-symbol", "symbolRoles": 8},
                        {"symbol": "sym-a", "symbolRoles": 8},
                    ],
                },
                {
                    "relativePath": "src/b.py",
                    "occurrences": [
                        {"symbol": "unknown-symbol", "symbolRoles": 8},
                    ],
                },
            ]
        },
    )
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is True
    assert report.edges == []
