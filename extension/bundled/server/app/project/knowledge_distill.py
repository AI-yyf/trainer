"""Phase 3 — 项目分析知识 → Knowledge Skill 自动沉淀.

把一次真实项目分析（symbol index + overview + call graph + analysis
providers）固化为可复用的 Knowledge Skill，并建立三处关联：

- **资料库**: metadata.source_resource_id / library_resource_id 指向导入的
  kind=code 资源；正文引用 symbol-index / overview artifact 路径。
- **Coach**: 技能 auto-reviewed+active，trigger 含项目名与「架构/模块/入口/
  依赖」，agentic 选择器按条件注入。
- **学习计划**: 同时写入一条 TeachingKnowledgeAsset（study_guide,
  origin=workspace_understanding），供计划/教练上下文复用。

幂等：同一 commit 重复沉淀返回 updated=False 且版本不变；commit 前进则
版本 +1。分析局限（按名绑定、文件级 caller、provider 不可用原因）原样进入
技能正文 —— 近似关系必须诚实标注。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.project.analysis_adapter import run_analysis_adapters
from app.project.callgraph import build_call_graph
from app.project.overview import build_project_overview, evidence_git_snapshot
from app.project.symbols import build_repo_index
from app.skills.registry import SkillRegistry
from app.skills.runtime import runtime_skill_registry

MAX_MODULES = 6
MAX_ENTRY_POINTS = 4
MAX_LIMITATIONS = 4
SKILL_BODY_BUDGET = 1200


def _skill_id_for(project_name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in project_name.lower())
    return f"{safe.strip('-') or 'project'}-project-knowledge"[:60]


def _resolve_repo_root(runtime: Any, workspace_id: str, resource_id: str) -> tuple[Any, Path]:
    repository = getattr(runtime.resource_service, "repository", None)
    if repository is None:
        raise KeyError("Resource repository is unavailable.")
    for item in repository.list_resources(workspace_id):
        if str(getattr(item, "id", "")) == resource_id:
            source = Path(str(getattr(item, "source", "") or ""))
            if not source.is_dir():
                raise ValueError(f"Project resource source is not a directory: {source}")
            return item, source
    raise KeyError(f"Unknown project resource: {resource_id}")


def _project_body(
    *,
    project_name: str,
    commit_sha: str,
    branch: str,
    file_count: int,
    symbol_count: int,
    modules: list[dict[str, Any]],
    entry_points: list[str],
    edge_count: int,
    unresolved: int,
    providers: list[dict[str, Any]],
    limitations: list[str],
) -> str:
    top_modules = "、".join(
        f"{m['module']}({m['file_count']}文件/{m['symbol_count']}符号)" for m in modules[:MAX_MODULES]
    )
    entries = "、".join(entry_points[:MAX_ENTRY_POINTS]) or "无约定入口"
    provider_line = "；".join(
        f"{p['provider']}={'可用' if p['available'] else '不可用'}"
        + (f"：{p['reason']}" if not p["available"] and p.get("reason") else "")
        for p in providers
    )
    limits = "；".join(limitations[:MAX_LIMITATIONS]) or "无额外限制"
    lines = [
        f"项目身份：{project_name} @ {commit_sha[:10] or 'no-commit'}"
        + (f"（{branch}）" if branch else "")
        + f"，{file_count} 个源文件，{symbol_count} 个符号。",
        f"结构：顶层模块 {top_modules or '未识别'}；约定入口 {entries}。",
        f"关系：仓库内调用边 {edge_count} 条，未解析调用点 {unresolved} 个"
        f"（未解析常意味着被删符号的调用方）。",
        f"分析能力：{provider_line}。",
        "引用：symbol-index 与 overview artifact 由本次导入生成并钉住 commit；"
        "文件行号引用请用 read_project_symbol。",
        f"局限：{limits}。",
    ]
    body = "\n".join(lines)
    return body[:SKILL_BODY_BUDGET]


def distill_project_knowledge(
    runtime: Any,
    workspace_id: str,
    resource_id: str,
) -> dict[str, Any]:
    """Build/refresh the project Knowledge Skill + teaching asset linkage."""

    registry: SkillRegistry | None = runtime_skill_registry(runtime)
    if registry is None:
        raise RuntimeError("Skill registry is unavailable.")
    resource, repo_root = _resolve_repo_root(runtime, workspace_id, resource_id)
    project_name = str(getattr(resource, "name", "") or repo_root.name)

    repo_index = build_repo_index(repo_root)
    snapshot = evidence_git_snapshot(repo_root)
    commit_sha = str(snapshot.get("commit_sha") or "")
    branch = str(snapshot.get("branch") or "")
    overview = build_project_overview(
        repo_root, repo_index, commit_sha=commit_sha, branch=branch
    )
    graph = build_call_graph(repo_root, repo_index)
    analysis = run_analysis_adapters(repo_root, repo_index)

    limitations: list[str] = []
    if repo_index.truncated_files:
        limitations.append("仓库遍历触达文件上限，计数为部分结果")
    if graph.truncated:
        limitations.append("调用图触达边数上限")
    limitations.extend(str(line) for line in analysis.get("limitation_summary", []))
    providers = [
        {
            "provider": item["provider"],
            "available": item["available"],
            "reason": item["reason"],
        }
        for item in analysis.get("providers", [])
    ]

    body = _project_body(
        project_name=project_name,
        commit_sha=commit_sha,
        branch=branch,
        file_count=len(repo_index.files),
        symbol_count=len(repo_index.symbols),
        modules=overview.modules,
        entry_points=overview.entry_points,
        edge_count=len(graph.edges),
        unresolved=sum(len(entries) for entries in graph.unresolved_by_symbol.values()),
        providers=providers,
        limitations=limitations,
    )
    description = (
        f"项目 {project_name} 的结构化知识（{len(repo_index.files)} 文件 / "
        f"{len(repo_index.symbols)} 符号 / {len(overview.modules)} 模块 @ "
        f"{commit_sha[:10] or 'no-commit'}）：模块图、入口、调用关系与诚实局限。"
    )
    triggers = [
        project_name.lower(),
        "项目结构",
        "模块",
        "入口",
        "依赖",
        "架构",
        "understand the project",
        "call graph",
    ]
    metadata = {
        "origin": "project-analysis",
        "source_resource_id": resource_id,
        "library_resource_id": resource_id,
        "repo_root": str(repo_root),
        "commit_sha": commit_sha,
        "branch": branch,
        "evidence": {
            "file_count": len(repo_index.files),
            "symbol_count": len(repo_index.symbols),
            "module_count": len(overview.modules),
            "edge_count": len(graph.edges),
            "unresolved_calls": sum(
                len(entries) for entries in graph.unresolved_by_symbol.values()
            ),
        },
        "front_matter": {
            "name": _skill_id_for(project_name),
            "description": description,
            "triggers": ", ".join(triggers),
        },
    }
    record, created = registry.upsert_knowledge_skill(
        skill_id=_skill_id_for(project_name),
        name=f"{project_name} 项目知识",
        description=description,
        body=body,
        metadata={**metadata, "workspace_id": workspace_id},
        permissions=["read:workspace", "search:resources"],
        workspace_id=workspace_id,
    )

    teaching_asset_id = ""
    memory_service = getattr(runtime, "memory_service", None)
    recorder = getattr(memory_service, "record_teaching_asset", None)
    if callable(recorder):
        from app.core.models import TeachingKnowledgeAsset

        asset = recorder(
            workspace_id,
            TeachingKnowledgeAsset(
                kind="study_guide",
                scope="project",
                title=f"项目结构：{project_name}",
                summary=description,
                concept_card=body,
                exercise_seed=(
                    f"从 {project_name} 的入口文件出发，画出前两个模块的调用链，"
                    "并用 read_project_symbol 引用一个真实函数。"
                ),
                why_it_matters="先把项目结构变成可验证的心智模型，再动手改代码。",
                origin="workspace_understanding",
                source_key=f"project-analysis:{resource_id}",
                source_ids=[resource_id, str(record.skill_id)],
            ),
        )
        teaching_asset_id = str(getattr(asset, "id", "") or "")

    return {
        "ok": True,
        "created": created,
        "updated": not created,
        "skill_id": record.skill_id,
        "version": record.version,
        "status": record.status(),
        "commit_sha": commit_sha or None,
        "body_chars": len(body),
        "library_resource_id": resource_id,
        "teaching_asset_id": teaching_asset_id or None,
        "linked": {
            "library": bool(resource_id),
            "coach": bool(record.active),
            "learning": bool(teaching_asset_id),
        },
        "limitations": limitations[:MAX_LIMITATIONS],
        "evidence": metadata["evidence"],
    }
