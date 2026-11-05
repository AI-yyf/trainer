"""GitHub / local repository import (P2 §六).

Pipeline per VNEXT-PROGRAM.md: clone → Source registration → symbol index.

- The clone lives under the sidecar's managed ``projects`` directory (never
  inside a user workspace), pinned to the cloned commit SHA.
- The Source is a real :class:`ResourceRecord` (kind ``code``) registered
  through :class:`ResourceService.upload`, so search/versioning/provenance
  behave exactly like any other resource.
- The symbol index is a deterministic Artifact (JSON) written beside the
  resource library: file tree + symbols + commit, no LLM involved.

Trainer never writes into the cloned repo; the checkout is read-only input.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # noqa: S404 - git is invoked with an argv list, no shell
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.project.symbols import build_repo_index

_GITHUB_URL = re.compile(
    r"^(?:https?://)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?"
    r"(?:/tree/(?P<branch>[^/]+))?$",
    re.IGNORECASE,
)


def parse_github_url(url: str) -> dict[str, str]:
    """Parse owner/repo (and optional branch) from a GitHub URL or slug."""

    cleaned = str(url or "").strip()
    match = _GITHUB_URL.match(cleaned)
    if match:
        groups = match.groupdict()
        return {
            "owner": groups["owner"],
            "repo": groups["repo"].removesuffix(".git"),
            "branch": groups.get("branch") or "",
            "clone_url": f"https://github.com/{groups['owner']}/{groups['repo']}.git",
        }
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", cleaned):
        owner, repo = cleaned.split("/", 1)
        return {
            "owner": owner,
            "repo": repo.removesuffix(".git"),
            "branch": "",
            "clone_url": f"https://github.com/{owner}/{repo}.git",
        }
    raise ValueError(f"Not a recognized GitHub repository reference: {url!r}")


@dataclass(slots=True)
class RepoImportResult:
    resource_id: str
    resource_name: str
    repo_root: Path
    commit_sha: str
    branch: str
    file_count: int
    symbol_count: int
    symbol_artifact_path: Path | None
    warnings: list[str] = field(default_factory=list)


def clone_github_repo(
    url: str,
    *,
    projects_root: Path,
    depth: int = 1,
) -> tuple[Path, str, str]:
    """Clone ``url`` under ``projects_root`` and pin the commit.

    Returns ``(repo_root, commit_sha, branch)``. Raises RuntimeError with an
    operator-readable message when git is missing or the clone fails.
    """

    parsed = parse_github_url(url)
    slug = f"{parsed['owner']}-{parsed['repo']}"
    projects_root.mkdir(parents=True, exist_ok=True)
    target = projects_root / slug
    if target.exists():
        raise RuntimeError(f"Project directory already exists: {target}")
    command = ["git", "clone", "--depth", str(max(1, depth))]
    if parsed["branch"]:
        command += ["--branch", parsed["branch"]]
    command += [parsed["clone_url"], str(target)]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is not available on the sidecar host.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Clone timed out after {exc.timeout} seconds.") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Clone failed: {(completed.stderr or completed.stdout).strip()[:300]}")
    commit = _git_output(["git", "-C", str(target), "rev-parse", "HEAD"])
    branch = parsed["branch"] or _git_output(["git", "-C", str(target), "rev-parse", "--abbrev-ref", "HEAD"])
    return target, commit, branch


def import_local_repo(source_dir: str | Path) -> tuple[Path, str, str]:
    """Register an already-cloned/local repository. Returns (root, commit, branch)."""

    repo_root = Path(str(source_dir)).expanduser().resolve(strict=False)
    if not repo_root.is_dir():
        raise RuntimeError(f"Repository path is not a directory: {repo_root}")
    commit = _git_output(["git", "-C", str(repo_root), "rev-parse", "HEAD"])
    branch = _git_output(["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"])
    return repo_root, commit, branch


def _git_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip()


def write_symbol_artifact(
    artifact_path: Path,
    *,
    repo_url: str,
    commit_sha: str,
    branch: str,
    index_payload: dict[str, Any],
) -> Path:
    """Write the deterministic symbol-index Artifact (JSON, versioned)."""

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "artifact": "trainer.project.symbol-index",
        "version": 1,
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "branch": branch,
        "generated_at": datetime.now(UTC).isoformat(),
        **index_payload,
    }
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return artifact_path


def _is_within_managed_lane(repo_root: Path, clone_root: Path) -> bool:
    try:
        repo_root.resolve(strict=False).relative_to(clone_root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _copy_into_managed_lane(repo_root: Path, clone_root: Path) -> Path:
    base = clone_root / repo_root.name
    target = base
    suffix = 2
    while target.exists():
        target = clone_root / f"{repo_root.name}-{suffix}"
        suffix += 1
    shutil.copytree(repo_root, target, symlinks=True)
    return target


def import_repository(
    *,
    repo_url: str,
    repo_root: str | Path,
    clone_root: Path,
    artifact_root: Path,
    register_source: Any,
) -> RepoImportResult:
    """Clone (or reuse a local path), register the Source and the symbol index.

    ``register_source`` is the ResourceService upload callable so Source
    registration flows through the same governance as any other import.
    """

    warnings: list[str] = []
    is_remote = bool(repo_url)
    if is_remote:
        repo_root_path, commit_sha, branch = clone_github_repo(
            repo_url, projects_root=clone_root
        )
    else:
        repo_root_path, commit_sha, branch = import_local_repo(repo_root)
        # Governance lane: a source outside any registered workspace root is
        # only importable through Trainer's managed sandbox directory, exactly
        # like single-file sandbox imports. The original is never mutated.
        if not _is_within_managed_lane(repo_root_path, clone_root):
            repo_root_path = _copy_into_managed_lane(repo_root_path, clone_root)
    repo_index = build_repo_index(repo_root_path)
    index_payload = repo_index.to_payload()

    resource_name = repo_root_path.name
    upload = register_source(
        {
            "kind": "code",
            "name": resource_name,
            "source": str(repo_root_path),
            "source_type": "folder",
            "source_items": [str(repo_root_path / relative) for relative in index_payload["files"][:100]],
            "summary": (
                f"Imported repository {repo_url or repo_root_path.name} "
                f"@ {commit_sha[:10] if commit_sha else 'no-commit'} "
                f"({index_payload['file_count']} files, "
                f"{index_payload['symbol_count']} symbols)."
            ),
            "tags": ["project-import", "p2"],
        }
    )
    resource_id = ""
    if isinstance(upload, dict):
        resource_id = str(upload.get("id") or upload.get("resource_id") or "")
    elif hasattr(upload, "id"):
        resource_id = str(getattr(upload, "id", ""))

    artifact_rel = Path("project-artifacts") / f"{resource_id or resource_name}.symbol-index.json"
    artifact_path = artifact_root / artifact_rel
    write_symbol_artifact(
        artifact_path,
        repo_url=repo_url or str(repo_root),
        commit_sha=commit_sha,
        branch=branch,
        index_payload=index_payload,
    )
    if not commit_sha:
        warnings.append("Directory is not a git repository; no commit SHA pinned.")

    return RepoImportResult(
        resource_id=resource_id,
        resource_name=resource_name,
        repo_root=repo_root_path,
        commit_sha=commit_sha,
        branch=branch,
        file_count=int(index_payload["file_count"]),
        symbol_count=int(index_payload["symbol_count"]),
        symbol_artifact_path=artifact_path,
        warnings=warnings,
    )


