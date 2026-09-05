from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..core.models import (
    MemorySnapshot,
    TeachingKnowledgeAsset,
    TurnRequest,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)


@dataclass(slots=True)
class ProjectOpportunitySignal:
    file_path: str
    signal_type: str
    detail: str


@dataclass(slots=True)
class ProjectIdea:
    id: str
    title: str
    summary: str
    source_area: str
    idea_kind: str
    learning_value: str
    engineering_value: str
    difficulty: str
    suggested_scope: str
    first_step: str
    acceptance_signals: list[str] = field(default_factory=list)
    why_now: str = ""


class ProjectIdeaMinerService:
    def build_workspace_understanding(
        self,
        *,
        request: TurnRequest,
        memory_snapshot: MemorySnapshot | None = None,
        resource_context: dict[str, object] | None = None,
    ) -> WorkspaceUnderstandingSnapshot | None:
        current_file = request.current_file
        existing = memory_snapshot.workspace_understanding if memory_snapshot else None
        requested_resources = (
            resource_context.get("requested_resources", [])
            if isinstance(resource_context, dict)
            else []
        )
        requested_resource_paths = (
            resource_context.get("requested_resource_paths", [])
            if isinstance(resource_context, dict)
            else []
        )
        if current_file is None and not requested_resources:
            return existing

        resource_brief = (
            str(resource_context.get("requested_resource_summary") or "").strip()
            if isinstance(resource_context, dict)
            else ""
        )
        entry_points = self._entry_points_from_context(
            current_file,
            requested_resources,
            requested_resource_paths,
            existing,
        )
        opportunities = self._collect_opportunities(request, memory_snapshot)
        feature_lanes = self._feature_lanes(
            current_file=current_file,
            memory_snapshot=memory_snapshot,
            entry_points=entry_points,
            resource_brief=resource_brief,
            requested_resource_paths=requested_resource_paths,
        )
        risk_zones = self._risk_zones(
            current_file=current_file,
            entry_points=entry_points,
            resource_brief=resource_brief,
            requested_resource_paths=requested_resource_paths,
        )
        training_opportunities = self._training_opportunities(
            opportunities,
            entry_points,
            requested_resource_paths=requested_resource_paths,
        )
        repo_summary = self._repo_summary(
            current_file=current_file,
            memory_snapshot=memory_snapshot,
            entry_points=entry_points,
            resource_brief=resource_brief,
            risk_zones=risk_zones,
            requested_resource_paths=requested_resource_paths,
        )
        if not (
            repo_summary
            or entry_points
            or feature_lanes
            or risk_zones
            or training_opportunities
            or resource_brief
        ):
            return existing

        return WorkspaceUnderstandingSnapshot(
            repo_summary=repo_summary,
            entry_points=entry_points,
            feature_lanes=feature_lanes,
            risk_zones=risk_zones,
            training_opportunities=training_opportunities,
            resource_brief=resource_brief,
            firstLookSummary=existing.first_look_summary if existing else None,
        )

    def mine_ideas(
        self,
        *,
        request: TurnRequest,
        learner_state: object,
        decision: object,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        selected_assets: list[TeachingKnowledgeAsset] | None = None,
    ) -> list[ProjectIdea]:
        opportunities = self._collect_opportunities(request, memory_snapshot)
        ideas = [self._idea_from_signal(signal, profile, memory_snapshot) for signal in opportunities[:3]]
        asset_ideas = self._ideas_from_teaching_assets(
            memory_snapshot,
            focus_area=str(getattr(decision, "focus_area", "") or ""),
            selected_assets=selected_assets,
        )
        ideas = self._merge_ideas(asset_ideas + ideas)
        if ideas:
            return self._finalize_ideas(
                ideas,
                needs_rescue=bool(getattr(learner_state, "needs_rescue", False)),
                focus_area=str(getattr(decision, "focus_area", "") or ""),
            )
        return [
            ProjectIdea(
                id=f"idea_{uuid4().hex[:8]}",
                title="把当前目标变成一道可复盘的小练习",
                summary="没有找到更明确的代码热点时，就围绕当前目标提一个很小的训练任务。",
                source_area=memory_snapshot.current_focus if memory_snapshot else (profile.long_term_goal if profile else "workspace"),
                idea_kind="feature",
                learning_value="练习把宽目标收缩成具体补丁。",
                engineering_value="不用凭空造项目，也能继续推进。",
                difficulty="small",
                suggested_scope="一个函数、一个行为、一个验证路径。",
                first_step="先选一个最窄的文件，让目标行为能在那里看见。",
                acceptance_signals=[
                    "补丁只改一个可观察行为。",
                    "一个窄验证能证明它。",
                ],
                why_now="即使代码上下文还很少，也要先用一个薄动作把推进感保住。",
            )
        ]

    def _collect_opportunities(
        self,
        request: TurnRequest,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[ProjectOpportunitySignal]:
        current_file = request.current_file
        opportunities: list[ProjectOpportunitySignal] = []
        if current_file is not None:
            if current_file.diagnostics:
                opportunities.append(
                    ProjectOpportunitySignal(
                        file_path=current_file.path,
                        signal_type="diagnostic_cluster",
                        detail=current_file.diagnostics[0],
                    )
                )
            has_test_anchor = any(
                isinstance(path, str) and "test" in path.lower()
                for path in [
                    current_file.path,
                    *current_file.recent_files,
                    *[
                        related.get("path") or related.get("file") or ""
                        for related in current_file.related_files
                    ],
                ]
            )
            if current_file.path and "test" not in current_file.path.lower() and not has_test_anchor:
                opportunities.append(
                    ProjectOpportunitySignal(
                        file_path=current_file.path,
                        signal_type="missing_test",
                        detail="Current code path has no obvious nearby test anchor.",
                    )
                )
            if len(current_file.related_files) >= 2:
                opportunities.append(
                    ProjectOpportunitySignal(
                        file_path=current_file.path,
                        signal_type="coupling_hotspot",
                        detail="Current file touches multiple related areas.",
                    )
                )
        if memory_snapshot and memory_snapshot.top_weakness:
            opportunities.append(
                ProjectOpportunitySignal(
                    file_path=current_file.path if current_file is not None else "workspace",
                    signal_type="rough_edge",
                    detail=f"Learner weakness suggests a coach-worthy exercise around {memory_snapshot.top_weakness}.",
                )
            )
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding is not None:
            for entry_point in understanding.entry_points[:2]:
                if any(item.file_path == entry_point and item.signal_type == "feature_gap" for item in opportunities):
                    continue
                opportunities.append(
                    ProjectOpportunitySignal(
                        file_path=entry_point,
                        signal_type="feature_gap",
                        detail=f"Workspace understanding points to {entry_point} as a stable first entry point.",
                    )
                )
            for risk in understanding.risk_zones[:1]:
                opportunities.append(
                    ProjectOpportunitySignal(
                        file_path=understanding.entry_points[0] if understanding.entry_points else "workspace",
                        signal_type="rough_edge",
                        detail=risk,
                    )
                )
            for training_lane in understanding.training_opportunities[:1]:
                opportunities.append(
                    ProjectOpportunitySignal(
                        file_path=understanding.entry_points[0] if understanding.entry_points else "workspace",
                        signal_type="feature_gap",
                        detail=training_lane,
                    )
                )
        return opportunities

    def _idea_from_signal(
        self,
        signal: ProjectOpportunitySignal,
        profile: UserProfile | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> ProjectIdea:
        focus = memory_snapshot.current_focus if memory_snapshot and memory_snapshot.current_focus else "current workflow"
        entry_anchor = self._primary_entry_anchor(signal.file_path, memory_snapshot)
        if signal.signal_type == "diagnostic_cluster":
            return ProjectIdea(
                id=f"idea_{uuid4().hex[:8]}",
                title="先稳住失败路径，再谈扩展",
                summary=f"把 {entry_anchor} 里的诊断直接变成一次修复并验证的小练习。",
                source_area=signal.file_path,
                idea_kind="feature",
                learning_value="学会拿真实失败来锚定实现，而不是只谈意图。",
                engineering_value="顺手修掉现有路径里的一个可见毛刺。",
                difficulty="medium",
                suggested_scope="一条失败路径，加一个很窄的验证闭环。",
                first_step=f"先顺着 {entry_anchor} 里第一条失败分支走，再把预期行为写成一个可验证的补丁目标。",
                acceptance_signals=[
                    "原来的失败路径已经恢复正常。",
                    "一个聚焦检查或复现步骤通过。",
                ],
                why_now=self._why_now(
                    default="当前这条活跃诊断就是最值得抓的教练目标。",
                    memory_snapshot=memory_snapshot,
                    extra="它给的是一个具体失败，而不是空泛愿望。",
                ),
            )
        if signal.signal_type == "missing_test":
            return ProjectIdea(
                id=f"idea_{uuid4().hex[:8]}",
                title="给当前行为补一个测试锚点",
                summary=f"在 {entry_anchor} 周围加一个测试，让意图更明确。",
                source_area=signal.file_path,
                idea_kind="test",
                learning_value="练习先定义行为，再扩大实现。",
                engineering_value="给活跃路径加一层未来重构保护。",
                difficulty="small",
                suggested_scope="一个行为，一个测试文件或测试用例。",
                first_step=f"先找出 {entry_anchor} 最小的输入输出例子，把它写成 failing test。",
                acceptance_signals=[
                    "补丁前测试失败，补丁后通过。",
                    "测试名字足够清楚，未来一看就懂。",
                ],
                why_now=self._why_now(
                    default="在更大改动落地前，工作区先需要更紧的反馈回路。",
                    memory_snapshot=memory_snapshot,
                    extra="这是一个很小但信号很强的动作，能强化最容易重复出错的习惯。",
                ),
            )
        if signal.signal_type == "coupling_hotspot":
            return ProjectIdea(
                id=f"idea_{uuid4().hex[:8]}",
                title="在耦合流程里先切一道缝",
                summary=f"把 {entry_anchor} 当成一次小重构练习，先切出一个更清楚的边界。",
                source_area=signal.file_path,
                idea_kind="refactor",
                learning_value="练习用一个测量过的缝降低耦合，而不是重写。",
                engineering_value="让高频区域后续更安全。",
                difficulty="stretch",
                suggested_scope="抽一个 helper、接口或协调边界。",
                first_step=f"先列出 {entry_anchor} 里混在一起的职责，只拆一个边界，不碰剩余流程。",
                acceptance_signals=[
                    "一个职责被移动到更清楚的边界后面。",
                    "行为在现有或聚焦检查下保持稳定。",
                ],
                why_now=self._why_now(
                    default="如果不先切出一道缝，这个热点以后每次补丁都会拖慢。",
                    memory_snapshot=memory_snapshot,
                    extra="只有在更小的验证闭环已经跑通后，再把它当 stretch 题。",
                ),
            )
        if signal.signal_type == "feature_gap":
            return ProjectIdea(
                id=f"idea_{uuid4().hex[:8]}",
                title="从当前入口切入，先交付一个可见改进",
                summary=f"把 {entry_anchor} 当成第一条主线，先落一个行为变化，不扩大范围。",
                source_area=signal.file_path,
                idea_kind="feature",
                learning_value="练习从稳定入口开始，而不是在仓库里乱逛。",
                engineering_value="把工作区理解直接变成一个可复盘的补丁目标。",
                difficulty="small",
                suggested_scope="一个入口、一个行为、一个聚焦验证路径。",
                first_step=f"打开 {entry_anchor}，先说清要改善的第一个可见行为，再只改那一层边界。",
                acceptance_signals=[
                    "第一个入口现在暴露出更清楚或更安全的行为。",
                    "在碰第二个文件之前，一个聚焦检查已经证明变化成立。",
                ],
                why_now=self._why_now(
                    default="教练已经知道哪里最好切入，所以先从这里开始。",
                    memory_snapshot=memory_snapshot,
                    extra="这样可以把搭建成本压低，把下一轮练习的推进感保住。",
                ),
            )
        return ProjectIdea(
            id=f"idea_{uuid4().hex[:8]}",
            title="把已知薄弱点变成真实训练题",
            summary=f"用 {signal.detail} 生成一个既能练习、又能改进代码库的任务。",
            source_area=signal.file_path,
            idea_kind="developer_experience",
            learning_value=f"强化 {focus} 附近的薄弱环节。",
            engineering_value="把抽象教练建议变成真实的代码库改进。",
            difficulty="medium",
            suggested_scope="一个小护栏，或者一条更清楚的实现路径。",
            first_step="先找出这个薄弱点在代码或评审里最小的暴露位置。",
            acceptance_signals=[
                "补丁减少了一类重复错误模式。",
                "学习者能说清楚为什么新路径更安全。",
            ],
            why_now=self._why_now(
                default="最好的下一题应该打到真实薄弱点，而不是造一题玩具题。",
                memory_snapshot=memory_snapshot,
                extra="这样训练会同时显得个人化又和项目相关。",
            ),
        )

    def _entry_points_from_context(
        self,
        current_file: Any,
        requested_resources: object,
        requested_resource_paths: object,
        existing: WorkspaceUnderstandingSnapshot | None,
    ) -> list[str]:
        points: list[str] = []
        if current_file is not None and current_file.path:
            points.append(current_file.path)
            for related in current_file.related_files[:3]:
                path = related.get("path") or related.get("file")
                if path:
                    points.append(str(path))
            for path in current_file.recent_edited_files[:2]:
                points.append(path)
        if isinstance(requested_resources, list):
            for item in requested_resources[:2]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if title:
                    points.append(title)
        if isinstance(requested_resource_paths, list):
            for item in requested_resource_paths[:6]:
                cleaned = str(item or "").strip()
                if cleaned:
                    points.append(cleaned)
        if existing is not None:
            points.extend(existing.entry_points[:2])
        return self._unique_strings(points, limit=4)

    def _feature_lanes(
        self,
        *,
        current_file: Any,
        memory_snapshot: MemorySnapshot | None,
        entry_points: list[str],
        resource_brief: str,
        requested_resource_paths: object,
    ) -> list[str]:
        lanes: list[str] = []
        if current_file is not None and current_file.path:
            lanes.append(f"Keep {current_file.path} as the first implementation boundary.")
        if current_file is not None and current_file.related_files:
            first_related = current_file.related_files[0].get("path") or current_file.related_files[0].get("file")
            if first_related:
                lanes.append(f"Use {first_related} as the first contract or verification anchor.")
        if memory_snapshot and memory_snapshot.current_focus:
            lanes.append(f"Continue the live coaching lane around {memory_snapshot.current_focus}.")
        if not current_file and resource_brief:
            lanes.append("Extract one code-shaped training lane from the attached indexed resources.")
        resource_code_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="code")
        resource_note_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="note")
        resource_test_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="test")
        if resource_code_paths:
            lanes.append(f"Treat {resource_code_paths[0]} as the first attached code boundary.")
        if resource_note_paths:
            lanes.append(f"Use {resource_note_paths[0]} as the first explanation or requirement anchor.")
        if resource_test_paths:
            lanes.append(f"Use {resource_test_paths[0]} as the first verification lane.")
        if not lanes and entry_points:
            lanes.append(f"Start from {entry_points[0]} and keep the first cut narrow.")
        return self._unique_strings(lanes, limit=4)

    def _risk_zones(
        self,
        *,
        current_file: Any,
        entry_points: list[str],
        resource_brief: str,
        requested_resource_paths: object,
    ) -> list[str]:
        risks: list[str] = []
        if current_file is not None:
            for diagnostic in current_file.diagnostics[:2]:
                risks.append(f"Diagnostic hotspot in {current_file.path}: {diagnostic}")
            if len(current_file.recent_edited_files) >= 3:
                risks.append(
                    f"Recent edits already span {len(current_file.recent_edited_files)} files, so the patch could sprawl."
                )
        if len(entry_points) >= 3:
            risks.append("This lane touches multiple entry points, so the first patch should stay inside one boundary.")
        if not current_file and resource_brief:
            risks.append("Only indexed resource summaries are available, so confirm the first boundary before coding.")
        resource_code_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="code")
        resource_note_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="note")
        if len(resource_code_paths) >= 2:
            risks.append(
                f"Attached code anchors span {resource_code_paths[0]} and {resource_code_paths[1]}, so the first patch should stay inside one file."
            )
        if resource_code_paths and resource_note_paths:
            risks.append(
                f"The attached materials mix code and notes ({resource_note_paths[0]}), so confirm whether the first move is implementation or explanation."
            )
        return self._unique_strings(risks, limit=4)

    def _training_opportunities(
        self,
        opportunities: list[ProjectOpportunitySignal],
        entry_points: list[str],
        *,
        requested_resource_paths: object,
    ) -> list[str]:
        mapped: list[str] = []
        for signal in opportunities[:3]:
            if signal.signal_type == "diagnostic_cluster":
                mapped.append(f"Repair the first failing path in {signal.file_path}.")
            elif signal.signal_type == "missing_test":
                mapped.append(f"Add one test anchor around {signal.file_path}.")
            elif signal.signal_type == "coupling_hotspot":
                mapped.append(f"Carve out one seam in {signal.file_path}.")
            elif signal.signal_type == "feature_gap":
                mapped.append(f"Use {signal.file_path} as the starting entry point for the next improvement.")
            else:
                mapped.append(signal.detail)
        resource_code_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="code")
        resource_note_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="note")
        resource_test_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="test")
        if resource_code_paths:
            mapped.append(f"Use {resource_code_paths[0]} as the first attached implementation exercise.")
        if resource_note_paths:
            mapped.append(f"Extract one code-backed exercise from {resource_note_paths[0]}.")
        if resource_test_paths:
            mapped.append(f"Anchor the first verification loop in {resource_test_paths[0]}.")
        if not mapped and entry_points:
            mapped.append(f"先把 {entry_points[0]} 当成最小可见训练面。")
        return self._unique_strings(mapped, limit=4)

    def _repo_summary(
        self,
        *,
        current_file: Any,
        memory_snapshot: MemorySnapshot | None,
        entry_points: list[str],
        resource_brief: str,
        risk_zones: list[str],
        requested_resource_paths: object,
    ) -> str:
        parts: list[str] = []
        if current_file is not None and current_file.path:
            parts.append(f"当前入口文件是 {current_file.path}。")
        if current_file is not None and current_file.related_files:
            related = [
                str(item.get("path") or item.get("file") or "").strip()
                for item in current_file.related_files[:2]
                if str(item.get("path") or item.get("file") or "").strip()
            ]
            if related:
                parts.append(f"附近相关锚点：{', '.join(related)}。")
        if memory_snapshot and memory_snapshot.current_focus:
            parts.append(f"当前教练聚焦点：{memory_snapshot.current_focus}。")
        if resource_brief:
            parts.append(f"附带资源信号：{resource_brief}。")
        resource_code_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="code")
        resource_note_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="note")
        resource_test_paths = self._resource_paths_by_kind(requested_resource_paths, path_kind="test")
        if resource_code_paths:
            code_summary = ", ".join(resource_code_paths[:2])
            parts.append(f"附带代码锚点：{code_summary}。")
        if resource_note_paths:
            parts.append(f"附带说明/笔记锚点：{resource_note_paths[0]}。")
        if resource_test_paths:
            parts.append(f"附带验证锚点：{resource_test_paths[0]}。")
        if not parts and entry_points:
            parts.append(f"已知入口：{', '.join(entry_points[:2])}。")
        if risk_zones:
            parts.append(f"主要风险：{risk_zones[0]}")
        return " ".join(part.strip() for part in parts if part.strip()).strip()

    def _unique_strings(self, values: list[str], *, limit: int) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = str(value or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique.append(cleaned)
            if len(unique) >= limit:
                break
        return unique

    def _resource_paths_by_kind(
        self,
        requested_resource_paths: object,
        *,
        path_kind: str,
    ) -> list[str]:
        if not isinstance(requested_resource_paths, list):
            return []
        matched: list[str] = []
        for item in requested_resource_paths:
            cleaned = str(item or "").strip()
            if not cleaned:
                continue
            if self._path_kind(cleaned) != path_kind:
                continue
            matched.append(cleaned)
        return self._unique_strings(matched, limit=4)

    def _path_kind(self, value: str) -> str:
        lowered = value.lower()
        suffix = value.rsplit(".", 1)[-1].lower() if "." in value else ""
        if "test" in lowered:
            return "test"
        if suffix in {"py", "ts", "tsx", "js", "jsx", "json", "yaml", "yml", "toml", "go", "rs"}:
            return "code"
        if suffix in {"md", "markdown", "txt", "rst"}:
            return "note"
        return "other"

    def _finalize_ideas(
        self,
        ideas: list[ProjectIdea],
        *,
        needs_rescue: bool,
        focus_area: str,
    ) -> list[ProjectIdea]:
        ordered = sorted(
            ideas,
            key=lambda item: (
                1 if needs_rescue and item.difficulty == "stretch" else 0,
                self._difficulty_rank(item.difficulty),
                self._idea_kind_rank(item.idea_kind),
                item.title,
            ),
        )
        if focus_area:
            for idea in ordered:
                if focus_area.lower() not in idea.why_now.lower():
                    idea.why_now = f"{idea.why_now} Keep it tied to {focus_area}.".strip()
        return ordered[:3]

    def _ideas_from_teaching_assets(
        self,
        memory_snapshot: MemorySnapshot | None,
        *,
        focus_area: str,
        selected_assets: list[TeachingKnowledgeAsset] | None = None,
    ) -> list[ProjectIdea]:
        scoped_assets = [
            asset
            for asset in (selected_assets or [])
            if isinstance(asset, TeachingKnowledgeAsset)
        ]
        if scoped_assets:
            assets = scoped_assets[:2]
        elif memory_snapshot is None or not memory_snapshot.teaching_assets:
            return []
        else:
            assets = self._relevant_assets(memory_snapshot, focus_area=focus_area, limit=2)
        ideas: list[ProjectIdea] = []
        memory_focus = memory_snapshot.current_focus if memory_snapshot else ""
        weak_spot = memory_snapshot.top_weakness if memory_snapshot else ""
        for asset in assets:
            if asset.origin == "workspace_understanding" and asset.focus_area == asset.summary:
                continue
            title = asset.title or asset.summary or "Teaching asset drill"
            summary = asset.summary or asset.source_summary or title
            if asset.kind == "implementation_pattern":
                ideas.append(
                    ProjectIdea(
                        id=f"idea_{uuid4().hex[:8]}",
                        title=f"把“{title}”变成一次真实补丁",
                        summary=f"围绕教学资产“{title}”做一次小而真的实现训练：{summary}",
                        source_area=asset.focus_area or focus_area or memory_focus or "workspace",
                        idea_kind="feature",
                        learning_value="练习把已验证的实现模式迁移到当前项目，而不是重新发明路线。",
                        engineering_value="让训练直接改善当前仓库里的一条真实路径。",
                        difficulty="small",
                        suggested_scope="一条行为、一层边界、一次可验证补丁。",
                        first_step=(
                            f"先找出当前项目里最像“{title}”的入口，把它压成一条最薄实现切片。"
                        ),
                        acceptance_signals=[
                            "当前补丁复用了已验证模式，而不是扩大成重写。",
                            "一个窄验证已经证明行为变化成立。",
                        ],
                        why_now=self._why_now(
                            default="最适合继续练的，往往不是新概念，而是把已经沉淀的模式真正迁到当前项目里。",
                            memory_snapshot=memory_snapshot,
                            extra=(
                                f"这条教学资产已经能直接支持当前训练。{' 它也正好对应当前弱点。' if weak_spot and weak_spot.lower() in summary.lower() else ''}"
                            ),
                        ),
                    )
                )
            elif asset.kind == "common_pitfall":
                ideas.append(
                    ProjectIdea(
                        id=f"idea_{uuid4().hex[:8]}",
                        title=f"围绕“{title}”做一次防错训练",
                        summary=f"把常见坑“{title}”变成当前项目里的一道防错练习：{summary}",
                        source_area=asset.focus_area or focus_area or memory_focus or "workspace",
                        idea_kind="developer_experience",
                        learning_value="练习先识别错误模式，再设计更安全的实现路径。",
                        engineering_value="把同类错误的复发概率压下去。",
                        difficulty="medium",
                        suggested_scope="一个旧错误模式、一个护栏、一个验证点。",
                        first_step="先找出这个坑在当前项目里最容易再次出现的那一层边界。",
                        acceptance_signals=[
                            "你能明确说出这类坑是如何暴露出来的。",
                            "补丁或校验已经让这类错误更不容易重复出现。",
                        ],
                        why_now=self._why_now(
                            default="如果教学资产已经总结出常见坑，就应该尽快把它转成真实工程防线。",
                            memory_snapshot=memory_snapshot,
                            extra="这样训练不会只停留在知道，而会落到项目里的防错动作。",
                        ),
                    )
                )
            elif asset.kind in {"exercise_seed", "explanation_recipe", "concept_card"}:
                ideas.append(
                    ProjectIdea(
                        id=f"idea_{uuid4().hex[:8]}",
                        title=f"把“{title}”收束成一道工程练习",
                        summary=f"围绕教学资产“{title}”提炼一道贴当前项目的小练习：{summary}",
                        source_area=asset.focus_area or focus_area or memory_focus or "workspace",
                        idea_kind="test" if asset.kind == "exercise_seed" else "feature",
                        learning_value="让抽象知识资产重新回到代码边界和验证闭环里。",
                        engineering_value="把教练知识重新变成真实仓库里的推进动作。",
                        difficulty="small",
                        suggested_scope="一处代码边界、一条规则、一次验证。",
                        first_step="先指出当前项目里最适合承接这条知识资产的代码边界，再只做那一步。",
                        acceptance_signals=[
                            "这道练习仍然贴着当前项目，不是脱离上下文的玩具题。",
                            "练习结果能通过一个明确验证动作被检查。",
                        ],
                        why_now=self._why_now(
                            default="教练不该只记住资产，还应该把资产反复转成当前项目里的训练动作。",
                            memory_snapshot=memory_snapshot,
                            extra="这样记忆和训练才真正闭环。",
                        ),
                    )
                )
        return ideas

    def _relevant_assets(
        self,
        memory_snapshot: MemorySnapshot,
        *,
        focus_area: str,
        limit: int,
    ) -> list[TeachingKnowledgeAsset]:
        focus_tokens = self._asset_tokens(
            " ".join(
                [
                    focus_area,
                    memory_snapshot.current_focus,
                    memory_snapshot.top_weakness,
                ]
            )
        )
        ranked = sorted(
            memory_snapshot.teaching_assets,
            key=lambda asset: self._asset_rank(asset, focus_area=focus_area, focus_tokens=focus_tokens),
            reverse=True,
        )
        return ranked[:limit]

    def _asset_rank(
        self,
        asset: TeachingKnowledgeAsset,
        *,
        focus_area: str,
        focus_tokens: set[str],
    ) -> tuple[float, float, float, str]:
        kind_score = {
            "implementation_pattern": 6.0,
            "common_pitfall": 5.0,
            "exercise_seed": 4.0,
            "concept_card": 3.0,
            "explanation_recipe": 3.0,
        }.get(asset.kind, 1.0)
        overlap = 0.0
        if focus_area and focus_area.lower() in asset.focus_area.lower():
            overlap += 5.0
        asset_tokens = self._asset_tokens(
            " ".join(
                [
                    asset.title,
                    asset.summary,
                    asset.focus_area,
                    asset.scenario,
                    " ".join(asset.tags),
                    " ".join(asset.retrieval_hints),
                ]
            )
        )
        overlap += float(len(asset_tokens & focus_tokens)) * 2.5 if focus_tokens else 0.0
        trust = float(asset.trust_score or 0.0) + min(float(asset.usage_count or 0), 6.0) * 0.15
        scope = 3.0 if asset.scope == "project" else 2.0 if asset.scope == "personal" else 1.0
        return overlap, kind_score, scope + trust, asset.updated_at or ""

    def _asset_tokens(self, value: str) -> set[str]:
        cleaned = value.replace("/", " ").replace("-", " ").replace("_", " ")
        return {
            token
            for token in re.findall(r"[\w\u4e00-\u9fff]+", cleaned.lower())
            if len(token) > 1
        }

    def _merge_ideas(self, ideas: list[ProjectIdea]) -> list[ProjectIdea]:
        merged: list[ProjectIdea] = []
        seen_titles: set[str] = set()
        for idea in ideas:
            normalized_title = idea.title.strip().lower()
            if not normalized_title or normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            merged.append(idea)
        return merged

    def _difficulty_rank(self, difficulty: str) -> int:
        ranks = {"small": 0, "medium": 1, "stretch": 2}
        return ranks.get(str(difficulty), 3)

    def _idea_kind_rank(self, idea_kind: str) -> int:
        ranks = {
            "test": 0,
            "feature": 1,
            "developer_experience": 2,
            "refactor": 3,
            "architecture": 4,
        }
        return ranks.get(str(idea_kind), 5)

    def _why_now(
        self,
        *,
        default: str,
        memory_snapshot: MemorySnapshot | None,
        extra: str,
    ) -> str:
        parts = [default]
        if memory_snapshot and memory_snapshot.top_weakness:
            parts.append(f"It directly trains the weak spot around {memory_snapshot.top_weakness}.")
        if memory_snapshot and memory_snapshot.recent_wins:
            parts.append(f"It also builds on the recent win: {memory_snapshot.recent_wins[0]}.")
        parts.append(extra)
        return " ".join(part.strip() for part in parts if part.strip())

    def _primary_entry_anchor(self, file_path: str, memory_snapshot: MemorySnapshot | None) -> str:
        if file_path and file_path.strip() and file_path != "workspace":
            return file_path.strip()
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding is not None and understanding.entry_points:
            return understanding.entry_points[0]
        if memory_snapshot and memory_snapshot.current_focus:
            return memory_snapshot.current_focus
        return "the current workflow"
