from __future__ import annotations

import re
import tomllib
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
BUNDLED_SERVER_ROOT = REPO_ROOT / "extension" / "bundled" / "server"


def _canonical_requirement(value: str) -> str:
    match = re.fullmatch(r"\s*([A-Za-z0-9_.-]+)(\[[^]]+\])?(.+?)\s*", value)
    if match is None:
        raise AssertionError(f"Unsupported requirement syntax: {value!r}")
    name, extras, specifier = match.groups()
    normalized_name = re.sub(r"[-_.]+", "-", name).lower()
    normalized_extras = extras.lower() if extras else ""
    return f"{normalized_name}{normalized_extras}{specifier.replace(' ', '')}"


def _project_dependencies(path: Path) -> list[str]:
    with path.open("rb") as handle:
        project = tomllib.load(handle)["project"]
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    return [str(item) for item in dependencies]


def _requirements_dependencies(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_source_and_bundled_runtime_dependencies_match() -> None:
    source_dependencies = _project_dependencies(SERVER_ROOT / "pyproject.toml")
    bundled_dependencies = _project_dependencies(BUNDLED_SERVER_ROOT / "pyproject.toml")

    assert source_dependencies == bundled_dependencies


def test_requirements_matches_editable_install_runtime_dependencies() -> None:
    editable_dependencies = _project_dependencies(SERVER_ROOT / "pyproject.toml")
    requirements_dependencies = _requirements_dependencies(SERVER_ROOT / "requirements.txt")

    assert {_canonical_requirement(item) for item in requirements_dependencies} == {
        _canonical_requirement(item) for item in editable_dependencies
    }


def test_runtime_optional_and_direct_imports_are_declared() -> None:
    dependency_names = {
        _canonical_requirement(item).split(">", 1)[0].split("<", 1)[0].split("=", 1)[0]
        for item in _project_dependencies(SERVER_ROOT / "pyproject.toml")
    }

    assert {"fsrs", "markitdown", "trafilatura"}.issubset(dependency_names)
    assert "aiosqlite" not in dependency_names
