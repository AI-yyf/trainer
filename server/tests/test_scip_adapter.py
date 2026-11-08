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
    assert any("binary protobuf" in item for item in report.limitations)


def test_scip_missing_index_reports_honest_reason(tmp_path: Path) -> None:
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is False
    assert "No SCIP index" in report.reason


def test_scip_invalid_binary_reports_decode_failure(tmp_path: Path) -> None:
    (tmp_path / "index.scip").write_bytes(b"not-a-json-index")
    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is False
    assert "binary index could not be decoded" in report.reason


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field_varint(number: int, value: int) -> bytes:
    return _varint((number << 3) | 0) + _varint(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _scip_binary_index() -> bytes:
    symbol = "scip-python python pkg 0.1 `lib.py`/foo()."
    lib_symbol = _field_bytes(1, symbol.encode()) + _field_bytes(5, b"foo")
    lib_document = (
        _field_bytes(1, b"lib.py")
        + _field_bytes(3, lib_symbol)
    )
    reference = _field_bytes(2, symbol.encode()) + _field_varint(3, 8)
    app_document = _field_bytes(1, b"app.py") + _field_bytes(2, reference)
    return _field_bytes(2, lib_document) + _field_bytes(2, app_document)


def test_scip_binary_protobuf_references_become_compiler_evidence(tmp_path: Path) -> None:
    path = tmp_path / ".trainer" / "scip" / "index.scip"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_scip_binary_index())

    report = LspScipProvider().run(tmp_path, _index(tmp_path))
    assert report.available is True
    assert report.confidence == "scip_reference"
    assert len(report.edges) == 1
    edge = report.edges[0]
    assert edge.caller_file == "app.py"
    assert edge.callee_file == "lib.py"
    assert edge.callee_symbol == "foo"
    assert any("index.scip" in item for item in report.limitations)


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
