"""§1.21 / §1.21.1  Project context classification — heuristic + LLM-enhanced.

Heuristic classifier uses file counts, extension tallies, dependency-file
detection, and directory-name patterns to classify a folder into one of six
FolderRole values.  When LLM is available, the heuristic result is optionally
refined by a structured prompt.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, Mapping, cast
from uuid import uuid4

from ..core.models import (
    FirstLookSummary,
    FolderRole,
    ProjectTypeGuess,
)

if TYPE_CHECKING:
    from .authority import WorkspaceAuthority


ProjectDiscoveryDecision = Literal["adopt", "browse", "ignore"]
ProjectDiscoveryStatus = Literal[
    "awaiting_decision",
    "adoption_requested",
    "browse_only",
    "ignored",
    "adopted",
    "unavailable",
]

_DISCOVERY_DECISIONS: tuple[ProjectDiscoveryDecision, ...] = ("adopt", "browse", "ignore")
_ADOPTION_PROVISIONING_KEYS: tuple[str, ...] = (
    "project_id",
    "project_memory_id",
    "project_plan_id",
    "project_training_id",
    "project_agent_context_id",
)


@dataclass(frozen=True, slots=True)
class ProjectDiscovery:
    """A project candidate whose ownership is deliberately unresolved by default.

    Classification only observes a candidate. It never creates project memory,
    a plan, training state, or write authority. Those are allowed only after an
    explicit decision and, for adoption, independently verifiable provisioning.
    """

    discovery_id: str
    project_path: str
    project_name: str
    summary: FirstLookSummary
    status: ProjectDiscoveryStatus
    available_decisions: tuple[ProjectDiscoveryDecision, ...]
    discovered_at: str
    selected_decision: ProjectDiscoveryDecision | None = None
    trusted_boundary: bool = False
    is_managed: bool = False
    is_browse_only: bool = False
    persistent_memory_created: bool = False
    provisioning_required: bool = False
    adoption_artifacts: dict[str, str] | None = None
    adoption_job_id: str | None = None
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        """Return a route-ready JSON payload without implying project takeover."""
        return {
            "discovery_id": self.discovery_id,
            "project_path": self.project_path,
            "project_name": self.project_name,
            "summary": self.summary.model_dump(mode="json"),
            "status": self.status,
            "available_decisions": list(self.available_decisions),
            "selected_decision": self.selected_decision,
            "trusted_boundary": self.trusted_boundary,
            "is_managed": self.is_managed,
            "is_browse_only": self.is_browse_only,
            "persistent_memory_created": self.persistent_memory_created,
            "provisioning_required": self.provisioning_required,
            "adoption_artifacts": dict(self.adoption_artifacts or {}),
            "adoption_job_id": self.adoption_job_id,
            "reason": self.reason,
            "discovered_at": self.discovered_at,
        }

# ---------------------------------------------------------------------------
# Extension / filename constants
# ---------------------------------------------------------------------------

DEPENDENCY_FILES: frozenset[str] = frozenset({
    "package.json",
    "requirements.txt",
    "setup.py",
    "Pipfile",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "CMakeLists.txt",
    "Makefile",
    "bazel",
    "WORKSPACE",
    "pubspec.yaml",
    "mix.exs",
    "composer.json",
    "nuget.config",
    "*.csproj",
    "*.sln",
    "Podfile",
    "Package.swift",
})

BUILD_DIRS: frozenset[str] = frozenset({
    "src",
    "lib",
    "pkg",
    "cmd",
    "internal",
    "app",
    "dist",
    "build",
    "out",
    "bin",
    "target",
    "node_modules",
})

IGNORED_SCAN_DIRS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
    ".turbo",
    "dist",
    "build",
    "out",
    "coverage",
})

LEARNING_DIRS: frozenset[str] = frozenset({
    "notes",
    "docs",
    "papers",
    "references",
    "lectures",
    "slides",
    "cheatsheets",
    "books",
    "tutorials",
    "examples",
    "exercises",
    "practice",
    "homework",
    "assignments",
    "readings",
})

LEARNING_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".epub",
    ".pptx",
    ".ppt",
    ".docx",
    ".doc",
})

ALGO_MODEL_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".ipynb",
    ".m",
    ".R",
    ".jl",
    ".cpp",
    ".c",
    ".java",
    ".kt",
    ".swift",
})

MODEL_ARTIFACT_FILES: frozenset[str] = frozenset({
    "model.pkl",
    "model.joblib",
    "model.pt",
    "model.h5",
    "model.onnx",
    "model.bin",
    "model.safetensors",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "training_args.bin",
    "trainer_state.json",
})

NOTEBOOK_EXTENSIONS: frozenset[str] = frozenset({".ipynb"})

WEB_EXTENSIONS: frozenset[str] = frozenset({
    ".html",
    ".css",
    ".jsx",
    ".tsx",
    ".vue",
    ".svelte",
})

WEB_FILES: frozenset[str] = frozenset({
    "next.config.js",
    "next.config.ts",
    "next.config.mjs",
    "vite.config.ts",
    "vite.config.js",
    "webpack.config.js",
    "webpack.config.ts",
    "nuxt.config.ts",
    "nuxt.config.js",
    "angular.json",
    ".angular-cli.json",
})

API_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".kt",
})

CLI_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".go",
    ".rs",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
})

MOBILE_FILES: frozenset[str] = frozenset({
    "AndroidManifest.xml",
    "Info.plist",
    "AppDelegate.swift",
    "MainActivity.java",
    "MainActivity.kt",
    "build.gradle",
    "Podfile",
})

GAME_FILES: frozenset[str] = frozenset({
    "unity",
    "unreal",
    "godot",
    "gamemaker",
})

DATA_PIPELINE_FILES: frozenset[str] = frozenset({
    "airflow",
    "dag",
    "pipeline",
    "workflow",
    "etl",
})

CONFIG_DOTFILE_EXTENSIONS: frozenset[str] = frozenset({
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".json",
})

CONFIG_DOTFILE_NAMES: frozenset[str] = frozenset({
    ".gitconfig",
    ".bashrc",
    ".zshrc",
    ".vimrc",
    ".tmux.conf",
    ".editorconfig",
    ".prettierrc",
    ".eslintrc",
    "settings.json",
    "preferences.json",
})

FUNCTION_GUIDANCE_CODE_SUFFIXES: frozenset[str] = frozenset({
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".swift",
    ".cs",
    ".cpp",
    ".cc",
    ".cxx",
    ".c",
    ".h",
    ".hpp",
    ".hh",
    ".php",
    ".rb",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".sql",
    ".dart",
    ".lua",
    ".scala",
    ".ex",
    ".exs",
    ".erl",
    ".hrl",
    ".nim",
    ".zig",
    ".fs",
    ".fsx",
    ".vue",
    ".svelte",
    ".astro",
    ".ipynb",
})


def is_code_like_path(path: str | None) -> bool:
    if not path:
        return False
    normalized = str(path).replace("\\", "/").strip()
    if not normalized:
        return False
    suffix = Path(normalized).suffix.lower()
    return suffix in FUNCTION_GUIDANCE_CODE_SUFFIXES


def is_code_like_current_file(current_file: dict[str, Any] | None) -> bool:
    if not isinstance(current_file, dict):
        return False
    return is_code_like_path(str(current_file.get("path") or ""))


def is_code_like_entry_point(entry_point: str | None) -> bool:
    if not entry_point:
        return False
    normalized = str(entry_point).replace("\\", "/").strip()
    if not normalized:
        return False
    if normalized.endswith("/"):
        return True
    return is_code_like_path(normalized)


# ---------------------------------------------------------------------------
# Directory-scanning helpers
# ---------------------------------------------------------------------------


def _scan_directory(
    folder_path: Path,
    *,
    max_depth: int = 3,
    scan_budget_ms: int = 250,
) -> dict[str, Any]:
    """Lightweight directory scan — counts files by extension, detects anchors."""
    extensions: dict[str, int] = {}
    file_count = 0
    dir_count = 0
    top_level_dirs: list[str] = []
    top_level_files: list[str] = []
    anchors: list[str] = []
    found_dependency_files: list[str] = []
    found_model_artifacts: list[str] = []
    max_files = 2000  # safety cap
    workspace_root = folder_path.resolve(strict=False)
    scan_started = perf_counter()
    scan_limited = False

    def _scan_budget_exhausted() -> bool:
        if scan_budget_ms < 0:
            return False
        return (perf_counter() - scan_started) * 1000.0 >= float(scan_budget_ms)

    def _is_reparse_point(path: Path) -> bool:
        """Return whether a path is a symlink, junction, or Windows reparse point."""
        try:
            if path.is_symlink():
                return True
            is_junction = getattr(path, "is_junction", None)
            if is_junction is not None and is_junction():
                return True
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
        except OSError:
            return False

    def _resolves_within_workspace(path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(workspace_root)
            return True
        except (OSError, RuntimeError, ValueError):
            return False

    def _walk(current: Path, depth: int) -> None:
        nonlocal file_count, dir_count, scan_limited
        if depth > max_depth or file_count >= max_files or _scan_budget_exhausted():
            if _scan_budget_exhausted():
                scan_limited = True
            return
        try:
            entries = sorted(os.listdir(current))
        except (PermissionError, OSError):
            return
        for entry_name in entries:
            if file_count >= max_files or _scan_budget_exhausted():
                if _scan_budget_exhausted():
                    scan_limited = True
                break
            entry_path = current / entry_name
            if entry_path.is_dir():
                entry_name_lower = entry_name.lower()
                if entry_name.startswith(".") or entry_name_lower in IGNORED_SCAN_DIRS:
                    continue
                if _is_reparse_point(entry_path) and not _resolves_within_workspace(entry_path):
                    continue
                dir_count += 1
                if depth == 0:
                    top_level_dirs.append(entry_name)
                if entry_name_lower in BUILD_DIRS or entry_name_lower in LEARNING_DIRS:
                    anchors.append(entry_name)
                _walk(entry_path, depth + 1)
            elif entry_path.is_file():
                file_count += 1
                suffix = entry_path.suffix.lower()
                extensions[suffix] = extensions.get(suffix, 0) + 1
                if depth == 0:
                    top_level_files.append(entry_name)
                if entry_name in DEPENDENCY_FILES:
                    found_dependency_files.append(entry_name)
                if entry_name in MODEL_ARTIFACT_FILES:
                    found_model_artifacts.append(entry_name)

    _walk(folder_path, 0)

    return {
        "file_count": file_count,
        "dir_count": dir_count,
        "extensions": extensions,
        "top_level_dirs": top_level_dirs,
        "top_level_files": top_level_files,
        "anchors": anchors,
        "dependency_files": found_dependency_files,
        "model_artifacts": found_model_artifacts,
        "scan_limited": scan_limited,
    }


def _scan_workspace_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the heuristic scan dict from a host workspace file snapshot.

    Remote SSH project roots are not local directories on the sidecar. The host
    snapshot is the only tree Trainer can classify without inventing emptiness.
    """
    files: list[dict[str, Any]] = []
    payload = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    raw_files = payload.get("files")
    if isinstance(raw_files, list):
        for item in raw_files:
            if isinstance(item, dict) and str(item.get("path") or "").strip():
                files.append(item)
    contents = payload.get("contents")
    if isinstance(contents, Mapping):
        existing = {
            str(item.get("path") or "").replace("\\", "/").lstrip("./") for item in files
        }
        for key in contents:
            relative = str(key or "").replace("\\", "/").lstrip("./")
            if relative and relative not in existing:
                files.append({"path": relative})
    extensions: dict[str, int] = {}
    top_level_files: list[str] = []
    anchors: list[str] = []
    found_dependency_files: list[str] = []
    found_model_artifacts: list[str] = []
    dir_names: list[str] = []
    seen_dirs: set[str] = set()
    for item in files:
        relative = str(item.get("path") or "").replace("\\", "/").lstrip("./")
        if not relative:
            continue
        parts = [part for part in relative.split("/") if part]
        if not parts:
            continue
        name = parts[-1]
        if len(parts) == 1:
            top_level_files.append(name)
        else:
            top = parts[0]
            if top not in seen_dirs:
                seen_dirs.add(top)
                dir_names.append(top)
            if top.lower() in BUILD_DIRS or top.lower() in LEARNING_DIRS:
                anchors.append(top)
        suffix = Path(name).suffix.lower()
        if suffix:
            extensions[suffix] = extensions.get(suffix, 0) + 1
        if name in DEPENDENCY_FILES:
            found_dependency_files.append(name)
        if name in MODEL_ARTIFACT_FILES:
            found_model_artifacts.append(name)
    return {
        "file_count": len(files),
        "dir_count": len(dir_names),
        "extensions": extensions,
        "top_level_dirs": dir_names,
        "top_level_files": top_level_files,
        "anchors": list(dict.fromkeys(anchors)),
        "dependency_files": found_dependency_files,
        "model_artifacts": found_model_artifacts,
        "scan_limited": False,
    }


def _first_look_from_scan(
    scan: dict[str, Any],
    *,
    response_language: str | None = None,
) -> FirstLookSummary:
    folder_role, confidence, role_reason = _classify_folder_role(scan)
    project_type, type_reason = _guess_project_type(scan, folder_role)
    entry_points = _derive_entry_points(scan)
    risk_zones = _derive_risk_zones(scan, folder_role)
    training_opportunities = _derive_training_opportunities(scan, folder_role, project_type)
    unknowns = _derive_unknowns(scan, folder_role)
    recommended_next_step = _derive_recommended_next_step(folder_role, project_type, confidence)
    why_this_guess = f"{role_reason} {type_reason}".strip()
    return _localize_heuristic_summary(
        FirstLookSummary(
            folder_role=folder_role,
            project_type_guess=project_type,
            confidence=round(confidence, 2),
            why_this_guess=why_this_guess,
            entry_points=entry_points,
            directory_anchors=scan["anchors"][:6],
            core_modules_or_materials=[
                directory
                for directory in scan["top_level_dirs"][:8]
                if directory.lower() not in {".git", "node_modules", "__pycache__", ".venv", "venv"}
            ],
            risk_zones=risk_zones,
            training_opportunities=training_opportunities,
            unknowns=unknowns,
            recommended_next_step=recommended_next_step,
            classification_method="heuristic",
        ),
        response_language,
    )


def _is_remote_workspace_identity(
    folder_path: str,
    *,
    remote_name: str | None = None,
    snapshot: Mapping[str, Any] | None = None,
) -> bool:
    if str(remote_name or "").strip():
        return True
    if isinstance(snapshot, Mapping) and snapshot.get("is_remote") is True:
        return True
    return "://" in str(folder_path or "")


# ---------------------------------------------------------------------------
# Heuristic scoring
# ---------------------------------------------------------------------------


def _classify_folder_role(scan: dict[str, Any]) -> tuple[FolderRole, float, str]:
    """Return (folder_role, confidence, reason)."""
    file_count = scan["file_count"]
    extensions = scan["extensions"]
    top_level_dirs = [d.lower() for d in scan["top_level_dirs"]]
    dependency_files = scan["dependency_files"]
    model_artifacts = scan["model_artifacts"]

    # --- Empty / new project ---
    if file_count == 0:
        return "empty_new_project", 0.95, "Folder is empty."

    # --- Very few files, no dependency file → likely empty/new ---
    if file_count <= 2 and not dependency_files:
        return "empty_new_project", 0.7, "Very few files and no dependency manifest found."

    # --- Algorithm / model ---
    notebook_count = sum(extensions.get(ext, 0) for ext in NOTEBOOK_EXTENSIONS)
    py_count = extensions.get(".py", 0)
    has_model_artifacts = bool(model_artifacts)
    has_training_artifacts = any(
        name in {"train.py", "train.sh", "finetune.py", "trainer_state.json"}
        for name in scan["top_level_files"]
    )
    algo_score = 0.0
    if has_model_artifacts:
        algo_score += 0.4
    if notebook_count > 0 and py_count > 0:
        algo_score += 0.3
    if "models" in top_level_dirs or "checkpoints" in top_level_dirs:
        algo_score += 0.2
    if has_training_artifacts:
        algo_score += 0.15
    if algo_score >= 0.5:
        reason = "Found model artifacts or training scripts."
        if has_model_artifacts:
            reason = f"Found model artifacts: {', '.join(model_artifacts[:3])}."
        return "algorithm_model", min(algo_score, 0.95), reason

    # --- Learning materials ---
    learning_dir_count = sum(1 for d in top_level_dirs if d in LEARNING_DIRS)
    learning_ext_count = sum(extensions.get(ext, 0) for ext in LEARNING_EXTENSIONS)
    total_learning = learning_dir_count * 5 + learning_ext_count
    if file_count > 0 and total_learning / max(file_count, 1) > 0.4:
        return (
            "learning_materials",
            0.75,
            f"Dominant learning-material indicators: {learning_dir_count} learning dirs, {learning_ext_count} document files.",
        )

    # --- Idea / scratchpad ---
    md_count = extensions.get(".md", 0)
    idea_score = 0.0
    if file_count <= 8 and not dependency_files:
        idea_score += 0.3
    if md_count >= 2 and file_count <= 15 and not dependency_files:
        idea_score += 0.4
    readme_only = file_count <= 3 and md_count >= 1
    if readme_only:
        idea_score += 0.3
    if idea_score >= 0.5:
        return (
            "idea_scratchpad",
            min(idea_score, 0.8),
            "Few files, mostly markdown/text, no dependency manifests.",
        )

    # --- Existing engineering ---
    has_dep = bool(dependency_files)
    has_src = any(d in BUILD_DIRS for d in top_level_dirs)
    code_extensions = {".py", ".ts", ".js", ".go", ".rs", ".java", ".kt", ".cs", ".rb", ".php", ".cpp", ".c", ".swift"}
    code_count = sum(extensions.get(ext, 0) for ext in code_extensions)
    eng_score = 0.0
    if has_dep:
        eng_score += 0.4
    if has_src:
        eng_score += 0.3
    if code_count >= 5:
        eng_score += 0.2
    elif code_count >= 2:
        eng_score += 0.1
    if eng_score >= 0.5:
        reason_parts = []
        if dependency_files:
            reason_parts.append(f"dependency files ({', '.join(dependency_files[:3])})")
        if has_src:
            reason_parts.append("source directories")
        if code_count:
            reason_parts.append(f"{code_count} source files")
        return (
            "existing_engineering",
            min(eng_score, 0.95),
            f"Detected {', '.join(reason_parts)}.",
        )

    # --- Mixed / uncertain ---
    return "mixed_uncertain", 0.4, "Contents do not strongly match any single category."


def _guess_project_type(
    scan: dict[str, Any],
    folder_role: FolderRole,
) -> tuple[ProjectTypeGuess, str]:
    """Best-guess at the project type from scanned contents."""
    extensions = scan["extensions"]
    top_level_files = [f.lower() for f in scan["top_level_files"]]
    top_level_dirs = [d.lower() for d in scan["top_level_dirs"]]
    dependency_files = [f.lower() for f in scan["dependency_files"]]

    if folder_role == "learning_materials":
        return "documentation", "Folder classified as learning materials."

    if folder_role == "idea_scratchpad":
        return "unknown", "Folder classified as idea scratchpad."

    if folder_role == "empty_new_project":
        return "unknown", "Empty or new project."

    if folder_role == "algorithm_model":
        if any(ext in extensions for ext in NOTEBOOK_EXTENSIONS):
            return "notebook_research", "Contains Jupyter notebooks and/or model artifacts."
        return "ml_model", "Contains model artifacts or training scripts."

    # Web app detection
    has_web_ext = sum(extensions.get(ext, 0) for ext in WEB_EXTENSIONS) > 0
    has_web_config = any(f in WEB_FILES for f in top_level_files)
    has_package_json = "package.json" in dependency_files
    if has_web_ext or has_web_config or (has_package_json and has_web_ext):
        if "next.config.js" in top_level_files or "next.config.ts" in top_level_files or "next.config.mjs" in top_level_files:
            return "web_app", "Next.js configuration detected."
        if "vite.config.ts" in top_level_files or "vite.config.js" in top_level_files:
            return "web_app", "Vite configuration detected."
        return "web_app", "Web-related file extensions or frameworks detected."

    # Mobile app detection
    has_mobile = any(f in top_level_files for f in MOBILE_FILES) or any(
        d in top_level_dirs for d in {"android", "ios", "flutter"}
    )
    if has_mobile:
        return "mobile_app", "Mobile platform files or directories detected."

    # Game detection
    has_game = any(d in top_level_dirs for d in GAME_FILES) or any(
        f.endswith(".unity") or f.endswith(".gd") for f in top_level_files
    )
    if has_game:
        return "game", "Game engine artifacts detected."

    # Data pipeline
    has_pipeline = any(d in top_level_dirs for d in DATA_PIPELINE_FILES) or any(
        "dag" in f or "pipeline" in f or "airflow" in f for f in top_level_files
    )
    if has_pipeline:
        return "data_pipeline", "Pipeline or DAG artifacts detected."

    # Config / dotfiles
    config_count = sum(extensions.get(ext, 0) for ext in CONFIG_DOTFILE_EXTENSIONS)
    has_dotfiles = any(f in CONFIG_DOTFILE_NAMES for f in top_level_files)
    total_files = scan["file_count"]
    if total_files > 0 and has_dotfiles and config_count / max(total_files, 1) > 0.5:
        return "config_dotfiles", "Dominant config/dotfile content."

    # API service
    has_api_indicators = (
        "main.py" in top_level_files
        or "app.py" in top_level_files
        or "server.py" in top_level_files
        or "api" in top_level_dirs
        or "routes" in top_level_dirs
    )
    py_count = extensions.get(".py", 0)
    if has_api_indicators and py_count >= 3:
        return "api_service", "API entry points and routes detected."

    # CLI tool
    has_cli_indicators = (
        "cli.py" in top_level_files
        or "main.go" in top_level_files
        or "main.rs" in top_level_files
        or "cli" in top_level_dirs
        or "cmd" in top_level_dirs
    )
    if has_cli_indicators:
        return "cli_tool", "CLI entry points detected."

    # Monorepo
    if len(top_level_dirs) >= 5 and len(dependency_files) >= 2:
        return "monorepo", "Multiple top-level directories with multiple dependency manifests."

    # Library / package
    has_lib = "lib" in top_level_dirs or "pkg" in top_level_dirs
    if has_lib and not has_api_indicators:
        return "library_package", "Library/package directory structure detected."

    # Fallback
    if py_count > 5:
        return "api_service", "Python-heavy project, likely a service or library."
    ts_count = extensions.get(".ts", 0) + extensions.get(".tsx", 0)
    if ts_count > 5:
        return "web_app", "TypeScript-heavy project."

    return "unknown", "Could not determine specific project type."


def _derive_entry_points(scan: dict[str, Any]) -> list[str]:
    """Derive likely entry-point paths from scan data."""
    top_files = scan["top_level_files"]
    top_dirs = scan["top_level_dirs"]
    candidates: list[str] = []
    entry_names = {
        "main.py",
        "app.py",
        "server.py",
        "index.ts",
        "index.js",
        "main.go",
        "main.rs",
        "lib.rs",
        "index.html",
        "manage.py",
        "wsgi.py",
        "asgi.py",
        "cli.py",
        "__main__.py",
    }
    for name in top_files:
        if name in entry_names:
            candidates.append(name)
    for dirname in ("src", "app", "cmd", "lib"):
        if dirname in top_dirs:
            candidates.append(f"{dirname}/")
    return candidates[:6]


def _derive_risk_zones(
    scan: dict[str, Any],
    folder_role: FolderRole,
) -> list[str]:
    """Identify potential risk zones."""
    risks: list[str] = []
    if folder_role == "existing_engineering":
        top_dirs = [d.lower() for d in scan["top_level_dirs"]]
        if "migrations" in top_dirs:
            risks.append("Database migrations present — schema changes need caution.")
        extensions = scan["extensions"]
        test_count = sum(
            extensions.get(ext, 0)
            for ext in {".test.ts", ".spec.ts", ".test.js", ".spec.js", "_test.py", ".test.py"}
        )
        if test_count == 0 and scan["file_count"] > 5:
            risks.append("No test files detected — unverified codebase.")
        if "node_modules" in top_dirs:
            risks.append("node_modules present — dependency tree may be stale.")
    if folder_role == "algorithm_model":
        risks.append("Model artifacts present — verify before retraining.")
    if folder_role == "mixed_uncertain":
        risks.append("Folder classification uncertain — manual review recommended.")
    return risks[:4]


def _derive_training_opportunities(
    scan: dict[str, Any],
    folder_role: FolderRole,
    project_type: ProjectTypeGuess,
) -> list[str]:
    """Identify training opportunities from scan + classification."""
    opportunities: list[str] = []
    if folder_role == "empty_new_project":
        opportunities.append("Fresh start — ideal for guided project scaffolding.")
    elif folder_role == "idea_scratchpad":
        opportunities.append("Turn scattered ideas into a structured implementation plan.")
    elif folder_role == "learning_materials":
        opportunities.append("Extract practice exercises from learning materials.")
    elif folder_role == "existing_engineering":
        extensions = scan["extensions"]
        test_count = sum(
            extensions.get(ext, 0)
            for ext in {".test.ts", ".spec.ts", ".test.js", ".spec.js", "_test.py", ".test.py"}
        )
        if test_count == 0:
            opportunities.append("Add first tests to existing code — high training value.")
        if project_type in {"api_service", "web_app"}:
            opportunities.append("Practice API design or endpoint implementation.")
        if project_type == "library_package":
            opportunities.append("Practice library interface design and documentation.")
    elif folder_role == "algorithm_model":
        opportunities.append("Practice model evaluation and hyperparameter tuning.")
    elif folder_role == "mixed_uncertain":
        opportunities.append("Clarify the folder purpose first, then pick a training lane.")
    return opportunities[:4]


def _derive_unknowns(
    scan: dict[str, Any],
    folder_role: FolderRole,
) -> list[str]:
    """List things we could not determine."""
    unknowns: list[str] = []
    if folder_role == "mixed_uncertain":
        unknowns.append("Exact purpose of this folder is unclear.")
    if not scan["dependency_files"]:
        unknowns.append("No dependency manifest — tech stack may be implicit.")
    extensions = scan["extensions"]
    code_extensions = {".py", ".ts", ".js", ".go", ".rs", ".java", ".kt", ".cs", ".rb", ".php"}
    if not any(extensions.get(ext, 0) > 0 for ext in code_extensions):
        unknowns.append("No recognized source-code extensions found.")
    return unknowns[:4]


def _derive_recommended_next_step(
    folder_role: FolderRole,
    project_type: ProjectTypeGuess,
    confidence: float,
) -> str:
    """§1.21 recommended_next_step based on classification."""
    if folder_role == "empty_new_project":
        return "Scaffold a new project with the first thin implementation slice."
    if folder_role == "idea_scratchpad":
        return "Pick the most promising idea and create a minimal project scaffold."
    if folder_role == "learning_materials":
        return "Choose one resource and create a practice exercise from it."
    if folder_role == "algorithm_model":
        return "Inspect the model artifacts and plan an evaluation or improvement experiment."
    if folder_role == "existing_engineering":
        if confidence >= 0.7:
            return "Explore the codebase entry points and pick the first thin training task."
        return "Explore the codebase to clarify the architecture before picking a task."
    # mixed_uncertain
    return "Manually review the folder contents and clarify the project purpose."


_HEURISTIC_SUMMARY_COPY: dict[str, dict[str, str]] = {
    "zh": {
        "why.path_missing": "找不到这个路径：{path}",
        "why.not_directory": "这个路径不是文件夹：{path}",
        "why.empty_new_project": "目录为空或文件很少，适合作为新项目的起点。",
        "why.idea_scratchpad": "目录以零散想法或文档为主，尚未形成完整项目。",
        "why.learning_materials": "目录主要包含学习资料和文档。",
        "why.algorithm_model": "检测到模型文件、笔记本或训练脚本。",
        "why.existing_engineering": "检测到依赖配置、源码目录或多个源文件。",
        "why.mixed_uncertain": "目录内容不足以确定单一用途，建议先确认目标。",
        "why.default": "已根据目录内容做出初步判断。",
        "risk.migrations": "发现数据库迁移文件，修改数据结构时要谨慎。",
        "risk.no_tests": "没有发现测试文件，改动前后需要额外验证。",
        "risk.node_modules": "发现 node_modules，依赖版本可能已过期。",
        "risk.model_artifacts": "发现模型产物，重新训练前先确认来源和结果。",
        "risk.uncertain": "目录用途还不明确，建议先人工确认。",
        "risk.default": "发现需要进一步确认的风险点。",
        "opportunity.fresh_start": "可以从引导式搭建项目开始练习。",
        "opportunity.ideas": "可以把零散想法整理成可执行的实现计划。",
        "opportunity.materials": "可以从学习资料中提取练习题。",
        "opportunity.first_tests": "可以先为现有代码补上测试。",
        "opportunity.api": "可以练习 API 设计或接口实现。",
        "opportunity.library": "可以练习库接口设计和文档编写。",
        "opportunity.model": "可以练习模型评估和参数调优。",
        "opportunity.clarify": "先确认目录用途，再选择练习方向。",
        "opportunity.default": "可以从这里安排一个小练习。",
        "unknown.path_missing": "找不到这个路径：{path}",
        "unknown.not_directory": "提供的路径是文件，不是文件夹。",
        "unknown.purpose": "这个目录的具体用途还不明确。",
        "unknown.no_manifest": "还没有发现依赖清单，技术栈可能需要进一步确认。",
        "unknown.no_source": "还没有发现可识别的源代码文件。",
        "unknown.default": "还有一些信息需要进一步确认。",
        "next.path_missing": "先创建这个文件夹，再搭建新项目。",
        "next.not_directory": "请提供一个文件夹路径。",
        "next.empty_new_project": "先搭建新项目的第一个最小功能。",
        "next.idea_scratchpad": "先选出最值得做的想法，并搭一个最小项目骨架。",
        "next.learning_materials": "先选一份资料，把它做成一个练习。",
        "next.algorithm_model": "先检查模型产物，再安排一次评估或改进实验。",
        "next.existing_engineering_high": "先查看入口文件，并确定第一个小练习任务。",
        "next.existing_engineering_low": "先浏览代码结构，再确定第一个练习任务。",
        "next.mixed_uncertain": "先查看目录内容，确认这个项目要解决什么问题。",
        "next.default": "先确认目录用途，再安排下一步。",
    },
    "es": {
        "why.path_missing": "No se encontró la ruta: {path}",
        "why.not_directory": "La ruta no es una carpeta: {path}",
        "why.empty_new_project": "La carpeta está vacía o tiene pocos archivos; es un buen inicio para un proyecto nuevo.",
        "why.idea_scratchpad": "La carpeta contiene sobre todo ideas o documentos sueltos; aún no es un proyecto completo.",
        "why.learning_materials": "La carpeta contiene principalmente materiales de aprendizaje y documentos.",
        "why.algorithm_model": "Se detectaron archivos de modelo, cuadernos o scripts de entrenamiento.",
        "why.existing_engineering": "Se detectaron configuraciones de dependencias, directorios de código fuente o varios archivos de código.",
        "why.mixed_uncertain": "El contenido no permite identificar un único propósito; conviene confirmar el objetivo.",
        "why.default": "Se hizo una primera lectura del contenido de la carpeta.",
        "risk.migrations": "Se encontraron migraciones de base de datos; ten cuidado al cambiar el esquema.",
        "risk.no_tests": "No se detectaron archivos de prueba; conviene verificar los cambios con más cuidado.",
        "risk.node_modules": "Se encontró node_modules; las dependencias pueden estar desactualizadas.",
        "risk.model_artifacts": "Se detectaron archivos de modelo; verifícalos antes de volver a entrenar.",
        "risk.uncertain": "El propósito de la carpeta aún no está claro; conviene revisarlo manualmente.",
        "risk.default": "Hay un punto de riesgo que conviene revisar.",
        "opportunity.fresh_start": "Un buen inicio para crear el proyecto paso a paso con guía.",
        "opportunity.ideas": "Convierte las ideas sueltas en un plan de implementación claro.",
        "opportunity.materials": "Extrae ejercicios prácticos de los materiales de aprendizaje.",
        "opportunity.first_tests": "Añade las primeras pruebas al código existente.",
        "opportunity.api": "Practica el diseño de API o la implementación de endpoints.",
        "opportunity.library": "Practica el diseño de interfaces de biblioteca y la documentación.",
        "opportunity.model": "Practica la evaluación de modelos y el ajuste de hiperparámetros.",
        "opportunity.clarify": "Aclara primero el propósito de la carpeta y luego elige una práctica.",
        "opportunity.default": "Puedes preparar aquí una práctica breve.",
        "unknown.path_missing": "No se encontró la ruta: {path}",
        "unknown.not_directory": "La ruta proporcionada es un archivo, no una carpeta.",
        "unknown.purpose": "El propósito exacto de esta carpeta aún no está claro.",
        "unknown.no_manifest": "No se encontró un archivo de dependencias; hay que confirmar la tecnología.",
        "unknown.no_source": "No se encontraron extensiones de código fuente reconocibles.",
        "unknown.default": "Aún falta confirmar alguna información.",
        "next.path_missing": "Crea la carpeta y luego inicia el proyecto.",
        "next.not_directory": "Indica la ruta de una carpeta.",
        "next.empty_new_project": "Crea la primera función pequeña del proyecto nuevo.",
        "next.idea_scratchpad": "Elige la idea más prometedora y crea una base mínima.",
        "next.learning_materials": "Elige un material y conviértelo en un ejercicio.",
        "next.algorithm_model": "Revisa los archivos del modelo y prepara una evaluación o mejora.",
        "next.existing_engineering_high": "Revisa los puntos de entrada y elige la primera tarea breve de práctica.",
        "next.existing_engineering_low": "Explora la estructura del código antes de elegir una práctica.",
        "next.mixed_uncertain": "Revisa el contenido y aclara qué problema resolverá el proyecto.",
        "next.default": "Confirma el propósito de la carpeta y decide el siguiente paso.",
    },
    "fr": {
        "why.path_missing": "Chemin introuvable : {path}",
        "why.not_directory": "Le chemin n'est pas un dossier : {path}",
        "why.empty_new_project": "Le dossier est vide ou contient peu de fichiers : il convient pour démarrer un nouveau projet.",
        "why.idea_scratchpad": "Le dossier contient surtout des idées ou documents épars ; ce n'est pas encore un projet complet.",
        "why.learning_materials": "Le dossier contient principalement des ressources d'apprentissage et des documents.",
        "why.algorithm_model": "Des fichiers de modèle, notebooks ou scripts d'entraînement ont été détectés.",
        "why.existing_engineering": "Des fichiers de dépendances, des dossiers source ou plusieurs fichiers de code ont été détectés.",
        "why.mixed_uncertain": "Le contenu ne permet pas d'identifier un seul usage ; confirmez d'abord l'objectif.",
        "why.default": "Une première lecture du contenu du dossier a été faite.",
        "risk.migrations": "Des migrations de base de données sont présentes ; soyez prudent avec le schéma.",
        "risk.no_tests": "Aucun fichier de test n'a été détecté ; vérifiez davantage les changements.",
        "risk.node_modules": "node_modules est présent ; les dépendances peuvent être anciennes.",
        "risk.model_artifacts": "Des artefacts de modèle sont présents ; vérifiez-les avant un nouvel entraînement.",
        "risk.uncertain": "Le rôle du dossier reste incertain ; une vérification manuelle est utile.",
        "risk.default": "Un point de risque mérite une vérification.",
        "opportunity.fresh_start": "Un bon point de départ pour construire le projet avec un accompagnement.",
        "opportunity.ideas": "Transformez les idées éparses en plan de mise en œuvre clair.",
        "opportunity.materials": "Tirez des exercices pratiques des ressources d'apprentissage.",
        "opportunity.first_tests": "Ajoutez les premiers tests au code existant.",
        "opportunity.api": "Entraînez-vous à concevoir une API ou à implémenter un endpoint.",
        "opportunity.library": "Entraînez-vous à concevoir une interface de bibliothèque et sa documentation.",
        "opportunity.model": "Entraînez-vous à évaluer le modèle et à régler les hyperparamètres.",
        "opportunity.clarify": "Clarifiez d'abord le rôle du dossier, puis choisissez un exercice.",
        "opportunity.default": "Vous pouvez préparer ici un petit exercice.",
        "unknown.path_missing": "Chemin introuvable : {path}",
        "unknown.not_directory": "Le chemin fourni est un fichier, pas un dossier.",
        "unknown.purpose": "L'objectif exact de ce dossier reste incertain.",
        "unknown.no_manifest": "Aucun fichier de dépendances n'a été trouvé ; la technologie reste à confirmer.",
        "unknown.no_source": "Aucune extension de code source reconnue n'a été trouvée.",
        "unknown.default": "Certaines informations restent à confirmer.",
        "next.path_missing": "Créez le dossier, puis démarrez le projet.",
        "next.not_directory": "Indiquez le chemin d'un dossier.",
        "next.empty_new_project": "Créez la première petite fonctionnalité du nouveau projet.",
        "next.idea_scratchpad": "Choisissez l'idée la plus prometteuse et créez une base minimale.",
        "next.learning_materials": "Choisissez une ressource et transformez-la en exercice.",
        "next.algorithm_model": "Vérifiez les artefacts du modèle, puis préparez une évaluation ou une amélioration.",
        "next.existing_engineering_high": "Examinez les points d'entrée et choisissez une première petite tâche d'entraînement.",
        "next.existing_engineering_low": "Parcourez la structure du code avant de choisir un exercice.",
        "next.mixed_uncertain": "Examinez le contenu et clarifiez le problème que le projet doit résoudre.",
        "next.default": "Confirmez le rôle du dossier, puis choisissez la suite.",
    },
    "de": {
        "why.path_missing": "Pfad nicht gefunden: {path}",
        "why.not_directory": "Der Pfad ist kein Ordner: {path}",
        "why.empty_new_project": "Der Ordner ist leer oder enthält nur wenige Dateien und eignet sich als Start für ein neues Projekt.",
        "why.idea_scratchpad": "Der Ordner enthält vor allem lose Ideen oder Dokumente; es ist noch kein vollständiges Projekt.",
        "why.learning_materials": "Der Ordner enthält hauptsächlich Lernmaterialien und Dokumente.",
        "why.algorithm_model": "Modelldateien, Notebooks oder Trainingsskripte wurden erkannt.",
        "why.existing_engineering": "Abhängigkeitsdateien, Quellordner oder mehrere Quelldateien wurden erkannt.",
        "why.mixed_uncertain": "Der Inhalt lässt keinen eindeutigen Zweck erkennen. Klären Sie zuerst das Ziel.",
        "why.default": "Der Ordnerinhalt wurde zunächst eingeordnet.",
        "risk.migrations": "Datenbankmigrationen wurden gefunden. Änderungen am Schema brauchen besondere Vorsicht.",
        "risk.no_tests": "Keine Testdateien gefunden. Änderungen sollten zusätzlich geprüft werden.",
        "risk.node_modules": "node_modules ist vorhanden; die Abhängigkeiten könnten veraltet sein.",
        "risk.model_artifacts": "Modellartefakte wurden gefunden. Prüfen Sie sie vor einem erneuten Training.",
        "risk.uncertain": "Der Zweck des Ordners ist noch unklar; eine manuelle Prüfung hilft.",
        "risk.default": "Ein Risikopunkt sollte noch geprüft werden.",
        "opportunity.fresh_start": "Ein guter Start für den angeleiteten Aufbau eines Projekts.",
        "opportunity.ideas": "Machen Sie aus losen Ideen einen klaren Umsetzungsplan.",
        "opportunity.materials": "Leiten Sie praktische Übungen aus den Lernmaterialien ab.",
        "opportunity.first_tests": "Ergänzen Sie erste Tests für den bestehenden Code.",
        "opportunity.api": "Üben Sie API-Design oder die Implementierung von Endpunkten.",
        "opportunity.library": "Üben Sie Bibliotheksschnittstellen und Dokumentation.",
        "opportunity.model": "Üben Sie Modellevaluierung und Hyperparameter-Optimierung.",
        "opportunity.clarify": "Klären Sie erst den Zweck des Ordners und wählen Sie dann eine Übung.",
        "opportunity.default": "Hier lässt sich eine kleine Übung planen.",
        "unknown.path_missing": "Pfad nicht gefunden: {path}",
        "unknown.not_directory": "Der angegebene Pfad ist eine Datei, kein Ordner.",
        "unknown.purpose": "Der genaue Zweck dieses Ordners ist noch unklar.",
        "unknown.no_manifest": "Keine Abhängigkeitsdatei gefunden; der Technologie-Stack muss noch geklärt werden.",
        "unknown.no_source": "Keine erkannten Quellcode-Dateiendungen gefunden.",
        "unknown.default": "Einige Informationen müssen noch geklärt werden.",
        "next.path_missing": "Erstellen Sie den Ordner und starten Sie dann das Projekt.",
        "next.not_directory": "Geben Sie den Pfad zu einem Ordner an.",
        "next.empty_new_project": "Erstellen Sie die erste kleine Funktion des neuen Projekts.",
        "next.idea_scratchpad": "Wählen Sie die vielversprechendste Idee und bauen Sie ein minimales Grundgerüst.",
        "next.learning_materials": "Wählen Sie ein Material und machen Sie daraus eine Übung.",
        "next.algorithm_model": "Prüfen Sie die Modellartefakte und planen Sie dann eine Bewertung oder Verbesserung.",
        "next.existing_engineering_high": "Prüfen Sie die Einstiegspunkte und wählen Sie die erste kleine Übungsaufgabe.",
        "next.existing_engineering_low": "Erkunden Sie die Codestruktur, bevor Sie eine Übung wählen.",
        "next.mixed_uncertain": "Prüfen Sie den Inhalt und klären Sie, welches Problem das Projekt lösen soll.",
        "next.default": "Klären Sie den Zweck des Ordners und entscheiden Sie dann den nächsten Schritt.",
    },
    "ja": {
        "why.path_missing": "このパスは見つかりません: {path}",
        "why.not_directory": "このパスはフォルダーではありません: {path}",
        "why.empty_new_project": "フォルダーが空か、ファイルが少ないため、新しいプロジェクトの出発点に適しています。",
        "why.idea_scratchpad": "フォルダーにはアイデアや文書が中心で、まだ完成したプロジェクトではありません。",
        "why.learning_materials": "フォルダーには学習資料や文書が中心にあります。",
        "why.algorithm_model": "モデルファイル、ノートブック、または学習スクリプトが見つかりました。",
        "why.existing_engineering": "依存関係の設定、ソースフォルダー、または複数のソースファイルが見つかりました。",
        "why.mixed_uncertain": "フォルダーの用途を一つに絞れません。先に目的を確認してください。",
        "why.default": "フォルダーの内容から初期判断を行いました。",
        "risk.migrations": "データベース移行ファイルが見つかりました。スキーマ変更は慎重に行ってください。",
        "risk.no_tests": "テストファイルが見つかりません。変更前後に追加の確認が必要です。",
        "risk.node_modules": "node_modules があり、依存関係が古い可能性があります。",
        "risk.model_artifacts": "モデル成果物が見つかりました。再学習の前に確認してください。",
        "risk.uncertain": "フォルダーの用途がまだ不明です。手動で確認してください。",
        "risk.default": "確認が必要なリスクがあります。",
        "opportunity.fresh_start": "ガイド付きでプロジェクトの土台づくりから始められます。",
        "opportunity.ideas": "散らばったアイデアを実行しやすい計画に整理できます。",
        "opportunity.materials": "学習資料から実践的な練習問題を作れます。",
        "opportunity.first_tests": "既存コードに最初のテストを追加できます。",
        "opportunity.api": "API 設計やエンドポイント実装を練習できます。",
        "opportunity.library": "ライブラリのインターフェース設計と文書化を練習できます。",
        "opportunity.model": "モデル評価とハイパーパラメーター調整を練習できます。",
        "opportunity.clarify": "まずフォルダーの用途を確認してから、練習を選びましょう。",
        "opportunity.default": "ここから小さな練習を始められます。",
        "unknown.path_missing": "このパスは見つかりません: {path}",
        "unknown.not_directory": "指定されたパスはファイルで、フォルダーではありません。",
        "unknown.purpose": "このフォルダーの正確な用途はまだ不明です。",
        "unknown.no_manifest": "依存関係の設定ファイルが見つからず、技術構成は追加確認が必要です。",
        "unknown.no_source": "認識できるソースコードファイルが見つかりません。",
        "unknown.default": "確認が必要な情報が残っています。",
        "next.path_missing": "フォルダーを作成してから、プロジェクトを始めましょう。",
        "next.not_directory": "フォルダーのパスを指定してください。",
        "next.empty_new_project": "新しいプロジェクトの最初の小さな機能を作りましょう。",
        "next.idea_scratchpad": "最も有望なアイデアを選び、最小限の土台を作りましょう。",
        "next.learning_materials": "資料を一つ選び、練習問題にしましょう。",
        "next.algorithm_model": "モデル成果物を確認してから、評価または改善を計画しましょう。",
        "next.existing_engineering_high": "エントリーポイントを確認し、最初の小さな練習課題を決めましょう。",
        "next.existing_engineering_low": "練習を選ぶ前に、コード構造を確認しましょう。",
        "next.mixed_uncertain": "内容を確認し、このプロジェクトが解決する問題をはっきりさせましょう。",
        "next.default": "フォルダーの用途を確認してから、次の一手を決めましょう。",
    },
    "ko": {
        "why.path_missing": "경로를 찾을 수 없습니다: {path}",
        "why.not_directory": "이 경로는 폴더가 아닙니다: {path}",
        "why.empty_new_project": "폴더가 비어 있거나 파일이 적어 새 프로젝트를 시작하기 좋습니다.",
        "why.idea_scratchpad": "폴더에는 흩어진 아이디어나 문서가 주로 있으며 아직 완성된 프로젝트는 아닙니다.",
        "why.learning_materials": "폴더에는 학습 자료와 문서가 주로 있습니다.",
        "why.algorithm_model": "모델 파일, 노트북 또는 학습 스크립트를 찾았습니다.",
        "why.existing_engineering": "의존성 설정, 소스 디렉터리 또는 여러 소스 파일을 찾았습니다.",
        "why.mixed_uncertain": "폴더의 용도를 하나로 판단하기 어렵습니다. 먼저 목표를 확인하세요.",
        "why.default": "폴더 내용을 바탕으로 첫 판단을 만들었습니다.",
        "risk.migrations": "데이터베이스 마이그레이션 파일이 있습니다. 스키마 변경은 주의가 필요합니다.",
        "risk.no_tests": "테스트 파일을 찾지 못했습니다. 변경 전후로 추가 확인이 필요합니다.",
        "risk.node_modules": "node_modules가 있어 의존성이 오래되었을 수 있습니다.",
        "risk.model_artifacts": "모델 산출물이 있습니다. 다시 학습하기 전에 확인하세요.",
        "risk.uncertain": "폴더의 용도가 아직 불분명합니다. 직접 확인하는 것이 좋습니다.",
        "risk.default": "확인이 필요한 위험 지점이 있습니다.",
        "opportunity.fresh_start": "안내를 따라 프로젝트 뼈대부터 연습할 수 있습니다.",
        "opportunity.ideas": "흩어진 아이디어를 실행 가능한 계획으로 정리할 수 있습니다.",
        "opportunity.materials": "학습 자료에서 실습 문제를 만들 수 있습니다.",
        "opportunity.first_tests": "기존 코드에 첫 테스트를 추가해 보세요.",
        "opportunity.api": "API 설계나 엔드포인트 구현을 연습해 보세요.",
        "opportunity.library": "라이브러리 인터페이스 설계와 문서 작성을 연습해 보세요.",
        "opportunity.model": "모델 평가와 하이퍼파라미터 조정을 연습해 보세요.",
        "opportunity.clarify": "먼저 폴더의 용도를 확인하고 연습을 고르세요.",
        "opportunity.default": "여기서 작은 연습을 시작할 수 있습니다.",
        "unknown.path_missing": "경로를 찾을 수 없습니다: {path}",
        "unknown.not_directory": "입력한 경로는 폴더가 아니라 파일입니다.",
        "unknown.purpose": "이 폴더의 정확한 용도는 아직 불분명합니다.",
        "unknown.no_manifest": "의존성 설정 파일을 찾지 못해 기술 구성을 더 확인해야 합니다.",
        "unknown.no_source": "인식할 수 있는 소스 코드 파일을 찾지 못했습니다.",
        "unknown.default": "추가로 확인할 정보가 남아 있습니다.",
        "next.path_missing": "폴더를 만든 뒤 프로젝트를 시작하세요.",
        "next.not_directory": "폴더 경로를 입력하세요.",
        "next.empty_new_project": "새 프로젝트의 첫 번째 작은 기능을 만들어 보세요.",
        "next.idea_scratchpad": "가장 유망한 아이디어를 고르고 최소한의 뼈대를 만드세요.",
        "next.learning_materials": "자료 하나를 골라 연습 문제로 만들어 보세요.",
        "next.algorithm_model": "모델 산출물을 확인한 뒤 평가나 개선을 계획하세요.",
        "next.existing_engineering_high": "진입 파일을 확인하고 첫 번째 작은 연습 과제를 정하세요.",
        "next.existing_engineering_low": "연습을 고르기 전에 코드 구조를 살펴보세요.",
        "next.mixed_uncertain": "내용을 확인하고 이 프로젝트가 해결할 문제를 분명히 하세요.",
        "next.default": "폴더의 용도를 확인한 뒤 다음 단계를 정하세요.",
    },
    "pt": {
        "why.path_missing": "Caminho não encontrado: {path}",
        "why.not_directory": "O caminho não é uma pasta: {path}",
        "why.empty_new_project": "A pasta está vazia ou tem poucos arquivos; é um bom começo para um projeto novo.",
        "why.idea_scratchpad": "A pasta contém principalmente ideias ou documentos soltos; ainda não é um projeto completo.",
        "why.learning_materials": "A pasta contém principalmente materiais de estudo e documentos.",
        "why.algorithm_model": "Foram encontrados arquivos de modelo, notebooks ou scripts de treinamento.",
        "why.existing_engineering": "Encontramos configurações de dependências, diretórios de código ou vários arquivos-fonte.",
        "why.mixed_uncertain": "O conteúdo não indica um único objetivo; confirme primeiro a meta.",
        "why.default": "Foi feita uma primeira leitura do conteúdo da pasta.",
        "risk.migrations": "Há migrações de banco de dados; tenha cuidado ao alterar o esquema.",
        "risk.no_tests": "Não foram encontrados arquivos de teste. Verifique as alterações com mais cuidado.",
        "risk.node_modules": "node_modules está presente; as dependências podem estar desatualizadas.",
        "risk.model_artifacts": "Há artefatos de modelo; verifique-os antes de treinar novamente.",
        "risk.uncertain": "O objetivo da pasta ainda não está claro; vale revisar manualmente.",
        "risk.default": "Há um ponto de risco que precisa de revisão.",
        "opportunity.fresh_start": "Um bom começo para montar o projeto com orientação.",
        "opportunity.ideas": "Transforme ideias soltas em um plano claro de implementação.",
        "opportunity.materials": "Extraia exercícios práticos dos materiais de estudo.",
        "opportunity.first_tests": "Adicione os primeiros testes ao código existente.",
        "opportunity.api": "Pratique o design de API ou a implementação de endpoints.",
        "opportunity.library": "Pratique interfaces de biblioteca e documentação.",
        "opportunity.model": "Pratique avaliação de modelos e ajuste de hiperparâmetros.",
        "opportunity.clarify": "Primeiro esclareça o objetivo da pasta e depois escolha um exercício.",
        "opportunity.default": "Você pode preparar aqui um exercício curto.",
        "unknown.path_missing": "Caminho não encontrado: {path}",
        "unknown.not_directory": "O caminho informado é um arquivo, não uma pasta.",
        "unknown.purpose": "O objetivo exato desta pasta ainda não está claro.",
        "unknown.no_manifest": "Não foi encontrado arquivo de dependências; é preciso confirmar a tecnologia.",
        "unknown.no_source": "Não foram encontradas extensões de código-fonte reconhecidas.",
        "unknown.default": "Ainda há informações a confirmar.",
        "next.path_missing": "Crie a pasta e depois inicie o projeto.",
        "next.not_directory": "Informe o caminho de uma pasta.",
        "next.empty_new_project": "Crie a primeira pequena funcionalidade do projeto novo.",
        "next.idea_scratchpad": "Escolha a ideia mais promissora e crie uma base mínima.",
        "next.learning_materials": "Escolha um material e transforme-o em exercício.",
        "next.algorithm_model": "Verifique os artefatos do modelo e planeje uma avaliação ou melhoria.",
        "next.existing_engineering_high": "Veja os pontos de entrada e escolha a primeira tarefa curta de prática.",
        "next.existing_engineering_low": "Explore a estrutura do código antes de escolher um exercício.",
        "next.mixed_uncertain": "Revise o conteúdo e esclareça o problema que o projeto deve resolver.",
        "next.default": "Confirme o objetivo da pasta e decida o próximo passo.",
    },
}

_HEURISTIC_RISK_KEYS = {
    "Database migrations present — schema changes need caution.": "risk.migrations",
    "No test files detected — unverified codebase.": "risk.no_tests",
    "node_modules present — dependency tree may be stale.": "risk.node_modules",
    "Model artifacts present — verify before retraining.": "risk.model_artifacts",
    "Folder classification uncertain — manual review recommended.": "risk.uncertain",
}

_HEURISTIC_OPPORTUNITY_KEYS = {
    "Fresh start — ideal for guided project scaffolding.": "opportunity.fresh_start",
    "Turn scattered ideas into a structured implementation plan.": "opportunity.ideas",
    "Extract practice exercises from learning materials.": "opportunity.materials",
    "Add first tests to existing code — high training value.": "opportunity.first_tests",
    "Practice API design or endpoint implementation.": "opportunity.api",
    "Practice library interface design and documentation.": "opportunity.library",
    "Practice model evaluation and hyperparameter tuning.": "opportunity.model",
    "Clarify the folder purpose first, then pick a training lane.": "opportunity.clarify",
}

_HEURISTIC_UNKNOWN_KEYS = {
    "Provided path is a file, not a directory.": "unknown.not_directory",
    "Exact purpose of this folder is unclear.": "unknown.purpose",
    "No dependency manifest — tech stack may be implicit.": "unknown.no_manifest",
    "No recognized source-code extensions found.": "unknown.no_source",
}


def _heuristic_summary_language(response_language: str | None) -> str | None:
    normalized = str(response_language or "").strip().lower().replace("_", "-")
    language = normalized.split("-", maxsplit=1)[0]
    return language if language in _HEURISTIC_SUMMARY_COPY else None


_LLM_RESPONSE_LANGUAGE_INSTRUCTIONS = {
    "zh": "Respond in Simplified Chinese (zh-CN).",
    "en": "Respond in English (en-US).",
    "es": "Respond in Spanish (es-ES).",
    "fr": "Respond in French (fr-FR).",
    "de": "Respond in German (de-DE).",
    "ja": "Respond in Japanese (ja-JP).",
    "ko": "Respond in Korean (ko-KR).",
    "pt": "Respond in Brazilian Portuguese (pt-BR).",
}


def _llm_response_language_instruction(response_language: str | None) -> str:
    language = _heuristic_summary_language(response_language)
    return _LLM_RESPONSE_LANGUAGE_INSTRUCTIONS.get(
        language or "",
        _LLM_RESPONSE_LANGUAGE_INSTRUCTIONS["en"],
    )


def _localize_heuristic_summary(
    summary: FirstLookSummary,
    response_language: str | None,
) -> FirstLookSummary:
    language = _heuristic_summary_language(response_language)
    if language is None:
        return summary

    copy = _HEURISTIC_SUMMARY_COPY[language]
    is_missing_path = summary.why_this_guess.startswith("Path does not exist: ")
    is_not_directory = summary.why_this_guess.startswith("Path is not a directory: ")
    if is_missing_path:
        why_this_guess = copy["why.path_missing"].format(
            path=summary.why_this_guess.removeprefix("Path does not exist: ")
        )
    elif is_not_directory:
        why_this_guess = copy["why.not_directory"].format(
            path=summary.why_this_guess.removeprefix("Path is not a directory: ")
        )
    else:
        why_this_guess = copy.get(f"why.{summary.folder_role}", copy["why.default"])

    def localize_unknown(item: str) -> str:
        if item.startswith("Path ") and item.endswith(" does not exist."):
            path = item.removeprefix("Path ").removesuffix(" does not exist.")
            return copy["unknown.path_missing"].format(path=path)
        return copy.get(_HEURISTIC_UNKNOWN_KEYS.get(item, ""), copy["unknown.default"])

    if is_missing_path:
        next_step_key = "next.path_missing"
    elif is_not_directory:
        next_step_key = "next.not_directory"
    elif summary.folder_role == "existing_engineering":
        next_step_key = (
            "next.existing_engineering_high"
            if summary.confidence >= 0.7
            else "next.existing_engineering_low"
        )
    else:
        next_step_key = f"next.{summary.folder_role}"

    return summary.model_copy(
        update={
            "why_this_guess": why_this_guess,
            "risk_zones": [
                copy.get(_HEURISTIC_RISK_KEYS.get(item, ""), copy["risk.default"])
                for item in summary.risk_zones
            ],
            "training_opportunities": [
                copy.get(_HEURISTIC_OPPORTUNITY_KEYS.get(item, ""), copy["opportunity.default"])
                for item in summary.training_opportunities
            ],
            "unknowns": [localize_unknown(item) for item in summary.unknowns],
            "recommended_next_step": copy.get(next_step_key, copy["next.default"]),
        }
    )


def _resolve_discovery_path(folder_path: str) -> Path | None:
    """Resolve a candidate path without treating a failed resolution as a project."""
    raw_path = str(folder_path or "").strip()
    if not raw_path:
        return None
    try:
        return Path(raw_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def discover_project(
    folder_path: str,
    *,
    summary: FirstLookSummary | None = None,
    authority: WorkspaceAuthority | None = None,
    remote_workspace: bool = False,
) -> ProjectDiscovery:
    """Create a non-owning project discovery record.

    This is intentionally separate from ``classify_heuristic`` so existing
    classification callers stay read-only. A route can return this record next
    to the first-look summary and require a follow-up decision endpoint before
    it asks runtime services to create any long-lived project state.
    """
    resolved_path = None if remote_workspace else _resolve_discovery_path(folder_path)
    first_look = summary or classify_heuristic(folder_path)
    discovered_at = datetime.now(UTC).isoformat()
    if remote_workspace:
        identity = str(folder_path or "").strip()
        name = Path(identity.replace("\\", "/").rstrip("/")).name or "remote-project"
        return ProjectDiscovery(
            discovery_id=f"project-discovery-{uuid4().hex[:12]}",
            project_path=identity,
            project_name=name,
            summary=first_look,
            status="awaiting_decision",
            available_decisions=("browse", "ignore"),
            discovered_at=discovered_at,
            is_browse_only=True,
            reason=(
                "Remote project is readable through the host snapshot. "
                "Trainer library stays local; browse or ignore before any project state is created."
            ),
        )
    if resolved_path is None or not resolved_path.exists() or not resolved_path.is_dir():
        unavailable_path = str(resolved_path) if resolved_path is not None else str(folder_path or "")
        return ProjectDiscovery(
            discovery_id=f"project-discovery-{uuid4().hex[:12]}",
            project_path=unavailable_path,
            project_name=resolved_path.name if resolved_path is not None else "",
            summary=first_look,
            status="unavailable",
            available_decisions=(),
            discovered_at=discovered_at,
            reason="The selected project path is unavailable; no project has been adopted or opened.",
        )

    trusted_boundary = False
    if authority is not None and authority.has_active_workspace_root:
        _, trusted_boundary = authority.normalize_and_validate(resolved_path, allow_outside=True)

    return ProjectDiscovery(
        discovery_id=f"project-discovery-{uuid4().hex[:12]}",
        project_path=str(resolved_path),
        project_name=resolved_path.name,
        summary=first_look,
        status="awaiting_decision",
        available_decisions=_DISCOVERY_DECISIONS,
        discovered_at=discovered_at,
        trusted_boundary=trusted_boundary,
        reason="Project discovered. Choose adopt, browse, or ignore before Trainer creates any project state.",
    )


def resolve_project_discovery(
    discovery: ProjectDiscovery,
    decision: ProjectDiscoveryDecision | str,
    *,
    authority: WorkspaceAuthority | None = None,
) -> ProjectDiscovery:
    """Apply one explicit discovery choice without bypassing root authority.

    ``adopt`` only requests provisioning; it does not report an adopted project
    until ``complete_project_adoption`` receives the independent runtime
    artifacts. ``browse`` remains read-only and intentionally creates no
    persistent project memory.
    """
    normalized_decision = str(decision).strip().lower()
    if normalized_decision not in _DISCOVERY_DECISIONS:
        raise ValueError("Project decision must be one of: adopt, browse, ignore.")
    if discovery.status != "awaiting_decision":
        raise ValueError("Project discovery is no longer awaiting a decision.")
    remote_browse_only = discovery.is_browse_only or "adopt" not in discovery.available_decisions
    if remote_browse_only and normalized_decision == "adopt":
        raise ValueError("Remote projects cannot be adopted as a local managed root.")
    if normalized_decision not in discovery.available_decisions:
        raise ValueError("Project decision is not available for this discovery record.")

    selected_decision = cast(ProjectDiscoveryDecision, normalized_decision)
    if selected_decision == "ignore":
        return replace(
            discovery,
            status="ignored",
            selected_decision="ignore",
            trusted_boundary=False,
            is_managed=False,
            is_browse_only=False,
            persistent_memory_created=False,
            provisioning_required=False,
            reason="Project ignored. Trainer created no project identity, memory, plan, or training state.",
        )

    if remote_browse_only:
        if selected_decision != "browse":
            raise ValueError("Remote projects cannot be adopted as a local managed root.")
        return replace(
            discovery,
            status="browse_only",
            selected_decision="browse",
            trusted_boundary=False,
            is_managed=False,
            is_browse_only=True,
            persistent_memory_created=False,
            provisioning_required=False,
            reason=(
                "Remote project opened in browse-only mode. "
                "Trainer library stays local and the remote tree is not a managed root."
            ),
        )

    candidate_path = _resolve_discovery_path(discovery.project_path)
    if candidate_path is None or not candidate_path.exists() or not candidate_path.is_dir():
        raise ValueError("Discovered project is no longer an available directory.")
    if authority is None or not authority.has_active_workspace_root:
        raise PermissionError("A configured active workspace root is required before opening a project.")

    from .authority import OperationType

    candidate, is_within_root = authority.normalize_and_validate(
        candidate_path,
        allow_outside=True,
    )
    if not is_within_root:
        raise PermissionError("Discovered project must be inside the active workspace root.")
    if not authority.check_permission(OperationType.READ, candidate):
        raise PermissionError("Read permission is required before opening a discovered project.")

    if selected_decision == "browse":
        return replace(
            discovery,
            status="browse_only",
            selected_decision="browse",
            trusted_boundary=True,
            is_managed=False,
            is_browse_only=True,
            persistent_memory_created=False,
            provisioning_required=False,
            reason="Project opened in browse-only mode. No persistent project state was created.",
        )

    return replace(
        discovery,
        status="adoption_requested",
        selected_decision="adopt",
        trusted_boundary=True,
        is_managed=False,
        is_browse_only=False,
        persistent_memory_created=False,
        provisioning_required=True,
        reason="Adoption requested. Project state remains unmanaged until provisioning evidence is recorded.",
    )


def complete_project_adoption(
    discovery: ProjectDiscovery,
    provisioning: Mapping[str, str],
) -> ProjectDiscovery:
    """Mark adoption complete only after required project artifacts exist."""
    if discovery.status != "adoption_requested" or discovery.selected_decision != "adopt":
        raise ValueError("Only an adoption request can be marked as adopted.")
    if not isinstance(provisioning, Mapping):
        raise ValueError("Project adoption provisioning evidence must be an object.")

    artifacts: dict[str, str] = {}
    for key in _ADOPTION_PROVISIONING_KEYS:
        value = provisioning.get(key)
        normalized_value = str(value).strip() if value is not None else ""
        if not normalized_value:
            raise ValueError(f"Project adoption requires provisioning evidence for {key}.")
        artifacts[key] = normalized_value

    return replace(
        discovery,
        status="adopted",
        trusted_boundary=True,
        is_managed=True,
        is_browse_only=False,
        persistent_memory_created=True,
        provisioning_required=False,
        adoption_artifacts=artifacts,
        reason="Project adoption is provisioned. Future writes still require workspace authority checks.",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_heuristic(
    folder_path: str,
    *,
    response_language: str | None = None,
    workspace_file_snapshot: Mapping[str, Any] | None = None,
    remote_name: str | None = None,
) -> FirstLookSummary:
    """Classify a folder using heuristic rules only (no LLM).

    This is the fallback when no LLM provider is configured.
    Remote SSH roots are classified from the host snapshot instead of treating
    a missing local path as an empty new project.
    """
    snapshot = workspace_file_snapshot if isinstance(workspace_file_snapshot, Mapping) else None
    remote = _is_remote_workspace_identity(
        folder_path, remote_name=remote_name, snapshot=snapshot
    )
    raw = str(folder_path or "").strip()
    local_dir = False
    if raw and "://" not in raw:
        try:
            path = Path(raw).expanduser()
            local_dir = path.exists() and path.is_dir()
        except OSError:
            local_dir = False
        if local_dir:
            return _first_look_from_scan(
                _scan_directory(path),
                response_language=response_language,
            )
    if snapshot and (snapshot.get("files") or snapshot.get("contents")):
        return _first_look_from_scan(
            _scan_workspace_snapshot(snapshot),
            response_language=response_language,
        )
    if remote:
        return _localize_heuristic_summary(
            FirstLookSummary(
                folder_role="mixed_uncertain",
                project_type_guess="unknown",
                confidence=0.4,
                why_this_guess=(
                    "Remote workspace is not a local directory on the Trainer sidecar; "
                    "a host file snapshot is required before guessing the project type."
                ),
                recommended_next_step=(
                    "Open a file in the remote repository so Trainer can snapshot and analyze it locally."
                ),
                unknowns=["Remote project files are not on the sidecar disk."],
                classification_method="heuristic",
            ),
            response_language,
        )
    if raw:
        try:
            path = Path(raw).expanduser()
            if path.exists() and not path.is_dir():
                return _localize_heuristic_summary(
                    FirstLookSummary(
                        folder_role="mixed_uncertain",
                        project_type_guess="unknown",
                        confidence=0.5,
                        why_this_guess=f"Path is not a directory: {folder_path}",
                        recommended_next_step="Provide a directory path.",
                        unknowns=["Provided path is a file, not a directory."],
                        classification_method="heuristic",
                    ),
                    response_language,
                )
        except OSError:
            pass
    return _localize_heuristic_summary(
        FirstLookSummary(
            folder_role="empty_new_project",
            project_type_guess="unknown",
            confidence=0.95,
            why_this_guess=f"Path does not exist: {folder_path}",
            recommended_next_step="Create the folder and scaffold a new project.",
            unknowns=[f"Path {folder_path} does not exist."],
            classification_method="heuristic",
        ),
        response_language,
    )


async def classify_with_llm(
    folder_path: str,
    provider_service: Any,
    *,
    heuristic_result: FirstLookSummary | None = None,
    response_language: str | None = None,
) -> FirstLookSummary:
    """Classify a folder using heuristic + LLM refinement.

    Falls back to heuristic if LLM call fails.
    """
    base = (
        _localize_heuristic_summary(heuristic_result, response_language)
        if heuristic_result is not None
        else classify_heuristic(folder_path, response_language=response_language)
    )

    if not provider_service or not provider_service.has_api_key:
        return base

    prompt = _build_llm_prompt(folder_path, base, response_language)
    try:
        response = await provider_service.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
        )
        return _parse_llm_response(base, response)
    except Exception:
        return base


def _build_llm_prompt(
    folder_path: str,
    heuristic_result: FirstLookSummary,
    response_language: str | None,
) -> str:
    lang_note = _llm_response_language_instruction(response_language)
    return f"""You are a project context classifier. Given a heuristic classification of a folder, refine it.

Folder path: {folder_path}
Heuristic classification:
- folder_role: {heuristic_result.folder_role}
- project_type_guess: {heuristic_result.project_type_guess}
- confidence: {heuristic_result.confidence}
- why_this_guess: {heuristic_result.why_this_guess}
- entry_points: {heuristic_result.entry_points}
- directory_anchors: {heuristic_result.directory_anchors}
- core_modules_or_materials: {heuristic_result.core_modules_or_materials}

Return a JSON object with these exact fields:
{{
  "folder_role": one of ["empty_new_project", "existing_engineering", "algorithm_model", "idea_scratchpad", "learning_materials", "mixed_uncertain"],
  "project_type_guess": one of ["web_app", "api_service", "cli_tool", "library_package", "ml_model", "notebook_research", "mobile_app", "desktop_app", "embedded_iot", "data_pipeline", "monorepo", "documentation", "game", "config_dotfiles", "unknown"],
  "confidence": float 0.0 to 1.0,
  "why_this_guess": "string explanation",
  "risk_zones": ["string", ...],
  "training_opportunities": ["string", ...],
  "unknowns": ["string", ...],
  "recommended_next_step": "string"
}}

{lang_note}
Write every human-readable string value in that language. Keep JSON field names, enum values,
file paths, package names, and code identifiers unchanged.
Return ONLY the JSON object, no markdown fences."""


def _parse_llm_response(base: FirstLookSummary, response: Any) -> FirstLookSummary:
    """Parse LLM JSON response and merge with heuristic base."""
    content = ""
    if isinstance(response, dict):
        choices = response.get("choices", [])
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            content = str(message.get("content", "")).strip()
    elif isinstance(response, str):
        content = response.strip()
    else:
        return base

    # Strip markdown fences
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        base.classification_method = "heuristic"
        return base

    if not isinstance(parsed, dict):
        base.classification_method = "heuristic"
        return base

    valid_roles = {
        "empty_new_project",
        "existing_engineering",
        "algorithm_model",
        "idea_scratchpad",
        "learning_materials",
        "mixed_uncertain",
    }
    valid_types = {
        "web_app", "api_service", "cli_tool", "library_package",
        "ml_model", "notebook_research", "mobile_app", "desktop_app",
        "embedded_iot", "data_pipeline", "monorepo", "documentation",
        "game", "config_dotfiles", "unknown",
    }

    folder_role = parsed.get("folder_role", base.folder_role)
    if folder_role not in valid_roles:
        folder_role = base.folder_role

    project_type_guess = parsed.get("project_type_guess", base.project_type_guess)
    if project_type_guess not in valid_types:
        project_type_guess = base.project_type_guess

    confidence = parsed.get("confidence", base.confidence)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = base.confidence

    def _str_list(key: str) -> list[str]:
        raw = parsed.get(key, [])
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if isinstance(item, (str, int, float))][:6]

    return FirstLookSummary(
        folder_role=folder_role,
        project_type_guess=project_type_guess,
        confidence=round(confidence, 2),
        why_this_guess=str(parsed.get("why_this_guess", base.why_this_guess)),
        entry_points=base.entry_points,
        directory_anchors=base.directory_anchors,
        core_modules_or_materials=base.core_modules_or_materials,
        risk_zones=_str_list("risk_zones") or base.risk_zones,
        training_opportunities=_str_list("training_opportunities") or base.training_opportunities,
        unknowns=_str_list("unknowns") or base.unknowns,
        recommended_next_step=str(parsed.get("recommended_next_step", base.recommended_next_step)),
        classification_method="llm_enhanced",
    )
