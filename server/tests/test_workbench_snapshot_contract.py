from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_MODELS = ROOT / "server" / "app" / "core" / "models.py"
SHARED_PROTOCOL = ROOT / "shared" / "src" / "protocol.ts"


def _collect_python_workbench_snapshot_fields() -> list[str]:
    source = SERVER_MODELS.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVER_MODELS))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "WorkbenchSnapshot":
            fields: list[str] = []
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    fields.append(statement.target.id)
            return fields
    raise AssertionError("WorkbenchSnapshot class not found in server/app/core/models.py")


def _collect_shared_workbench_snapshot_fields() -> list[str]:
    source = SHARED_PROTOCOL.read_text(encoding="utf-8")
    match = re.search(r"export type WorkbenchSnapshot = \{(.*?)\n\};", source, flags=re.S)
    assert match is not None, "WorkbenchSnapshot type not found in shared/src/protocol.ts"
    body = match.group(1)
    fields: list[str] = []
    for line in body.splitlines():
        field_match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\??:\s*", line)
        if field_match:
            fields.append(field_match.group(1))
    return fields


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def test_workbench_snapshot_shared_contract_matches_server_model() -> None:
    server_fields = set(_collect_python_workbench_snapshot_fields())
    shared_fields = _collect_shared_workbench_snapshot_fields()

    assert shared_fields, "expected shared WorkbenchSnapshot to expose public fields"

    missing = [field for field in shared_fields if _camel_to_snake(field) not in server_fields]
    assert missing == [], f"shared WorkbenchSnapshot fields missing in server model: {missing}"

    # These broader server-only fields are part of the current runtime envelope and
    # should stay available even if the public webview surface narrows or expands later.
    expected_server_extras = {
        "project_sources",
        "selected_teaching_assets",
        "exercise_prompt",
    }
    assert expected_server_extras <= server_fields
