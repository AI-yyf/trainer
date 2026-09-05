from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.models import CurrentFilePayload, MemorySnapshot, TurnRequest, UserProfile

if TYPE_CHECKING:
    from .service import LearnerState, TeachingDecision


@dataclass(slots=True)
class ProjectAdaptationGuide:
    target_outcome: str
    current_constraints: list[str] = field(default_factory=list)
    affected_areas: list[str] = field(default_factory=list)
    preserve_areas: list[str] = field(default_factory=list)
    first_migration_step: str = ""
    migration_sequence: list[str] = field(default_factory=list)
    validation_checkpoints: list[str] = field(default_factory=list)
    rollback_notes: list[str] = field(default_factory=list)


class ProjectAdaptationCoachService:
    def build_guide(
        self,
        *,
        request: TurnRequest,
        learner_state: LearnerState,
        decision: TeachingDecision,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
    ) -> ProjectAdaptationGuide:
        current_file = request.current_file
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        target_outcome = self._target_outcome(request.message, decision.focus_area, profile)
        current_constraints = self._constraints(current_file, learner_state, memory_snapshot)
        affected_areas = self._affected_areas(current_file, memory_snapshot)
        preserve_areas = self._preserve_areas(current_file, memory_snapshot)
        first_migration_step = self._first_step(current_file, decision.focus_area, memory_snapshot)
        migration_sequence = self._migration_sequence(current_file, decision.focus_area, memory_snapshot)
        validation_checkpoints = self._validation_checkpoints(current_file, memory_snapshot)
        rollback_notes = self._rollback_notes(current_file, memory_snapshot)

        if understanding is not None:
            for entry_point in understanding.entry_points[:2]:
                if entry_point and entry_point not in affected_areas:
                    affected_areas.append(entry_point)
            for risk in understanding.risk_zones[:2]:
                if risk and risk not in current_constraints:
                    current_constraints.append(risk)
            for lane in understanding.feature_lanes[:1]:
                if lane and lane not in preserve_areas:
                    preserve_areas.append(f"Keep this lane stable while migrating: {lane}")
            for opportunity in understanding.training_opportunities[:1]:
                if opportunity and opportunity not in validation_checkpoints:
                    validation_checkpoints.append(opportunity)

        return ProjectAdaptationGuide(
            target_outcome=target_outcome,
            current_constraints=current_constraints[:4],
            affected_areas=affected_areas[:5],
            preserve_areas=preserve_areas[:4],
            first_migration_step=first_migration_step,
            migration_sequence=migration_sequence[:5],
            validation_checkpoints=validation_checkpoints[:4],
            rollback_notes=rollback_notes[:3],
        )

    def _target_outcome(self, message: str, focus_area: str, profile: UserProfile | None) -> str:
        if focus_area:
            return f"把现有项目改到 {focus_area} 更清楚、更安全，也更容易继续演进。"
        if profile is not None and profile.long_term_goal:
            return f"围绕长期目标「{profile.long_term_goal}」来改造这个项目。"
        return message.strip()[:180]

    def _constraints(
        self,
        current_file: CurrentFilePayload | None,
        learner_state: LearnerState,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[str]:
        constraints = ["Keep the change incremental and reviewable rather than proposing a rewrite."]
        if current_file is not None and current_file.diagnostics:
            constraints.append("改造时不要让现有诊断变得更差。")
        if learner_state.needs_rescue:
            constraints.append("当前只需要一小段迁移，不需要多层重设计。")
        if memory_snapshot and memory_snapshot.current_focus:
            constraints.append(f"保持和当前聚焦点一致：{memory_snapshot.current_focus}。")
        if current_file is not None and current_file.related_files:
            related = current_file.related_files[0].get("path") or current_file.related_files[0].get("file")
            if related:
                constraints.append(f"在 {current_file.path} 第一层边界稳定前，不要扩大到 {related}。")
        constraints.append("先把第一层边界说清楚，再决定要不要碰第二层。")
        return constraints

    def _affected_areas(self, current_file: CurrentFilePayload | None, memory_snapshot: MemorySnapshot | None) -> list[str]:
        areas: list[str] = []
        if current_file is not None:
            areas.append(current_file.path)
            for related in current_file.related_files[:3]:
                path = related.get("path") or related.get("file")
                if path and path not in areas:
                    areas.append(path)
            for path in current_file.recent_edited_files[:2]:
                if path and path not in areas:
                    areas.append(path)
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding is not None:
            for path in understanding.entry_points[:2]:
                if path and path not in areas:
                    areas.append(path)
        elif memory_snapshot and memory_snapshot.current_focus:
            areas.append(memory_snapshot.current_focus)
        return areas or ["entry surface", "first downstream dependency"]

    def _preserve_areas(self, current_file: CurrentFilePayload | None, memory_snapshot: MemorySnapshot | None) -> list[str]:
        preserved = ["Unrelated flows should remain untouched in the first migration."]
        if current_file is not None and current_file.recent_files:
            preserved.append(f"Avoid widening into unrelated recent files beyond {current_file.recent_files[:2]}.")
        if memory_snapshot and memory_snapshot.recent_wins:
            preserved.append("Keep the most recently stabilized behavior intact while migrating.")
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding is not None and understanding.feature_lanes:
            preserved.append(f"Do not break the existing lane: {understanding.feature_lanes[0]}")
        preserved.append("先保住已经能解释清楚的那条主线，不要顺手重做别的边界。")
        return preserved

    def _first_step(
        self,
        current_file: CurrentFilePayload | None,
        focus_area: str,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        area = focus_area or "the requested adaptation"
        if current_file is not None:
            return f"先画出 {area} 现在如何进入 {current_file.path}，再只改第一层边界，不碰下游层。"
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding is not None and understanding.entry_points:
            return (
                f"先从 {understanding.entry_points[0]} 开始，画出 {area} 在这里如何显现，再只改第一层边界。"
            )
        return f"先找出 {area} 最先显现的模块，然后只定义一个边界变化。"

    def _migration_sequence(
        self,
        current_file: CurrentFilePayload | None,
        focus_area: str,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[str]:
        area = focus_area or "the adaptation target"
        sequence = [
            f"先用一句话说清 {area} 的目标改造成什么样。",
            "先改最外层边界（boundary），让迁移只有一个稳定入口。",
            "一次只移动一条依赖路径，不要整套子系统一起切换。",
            "第一条路径验证通过后，再扩大到下一层依赖。",
        ]
        if current_file is not None and current_file.path:
            sequence.insert(1, f"先把 {current_file.path} 作为第一层迁移边界（boundary），后面的清理不要混进第一轮。")
        if current_file is not None and current_file.related_files:
            path = current_file.related_files[0].get("path") or current_file.related_files[0].get("file")
            if path:
                sequence.insert(2, f"先判断 {path} 需不需要 adapter，而不是直接重写。")
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding is not None and len(understanding.entry_points) >= 2:
            sequence.append(
                f"只有 {understanding.entry_points[0]} 这层先跑通后，才去动 {understanding.entry_points[1]}。"
            )
        return sequence

    def _validation_checkpoints(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[str]:
        checkpoints = ["改造后的路径仍能支持一个具体、可见的用户场景。"]
        if current_file is not None and current_file.diagnostics:
            checkpoints.append("迁移后，现有诊断不能变得更宽或更严重。")
        if current_file is not None and current_file.related_files:
            related = current_file.related_files[0].get("path") or current_file.related_files[0].get("file")
            if related:
                checkpoints.append(f"如果边界改动碰到共享行为，就先用 {related} 做验证锚点。")
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding is not None and understanding.training_opportunities:
            checkpoints.append(f"保住这条教练主线：{understanding.training_opportunities[0]}")
        checkpoints.append("第一步迁移必须能独立复盘，后面的清理先别混进去。")
        return checkpoints

    def _rollback_notes(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[str]:
        notes = ["Keep the first migration step isolated enough to revert without backing out unrelated changes."]
        if current_file is not None:
            notes.append(f"把 {current_file.path} 的改动和后续清理分开，这样回退才便宜。")
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding is not None and understanding.entry_points:
            notes.append(
                f"不要同时迁移多个入口；先让 {understanding.entry_points[0]} 能独立回退。"
            )
        notes.append("如果第一步还不好回退，说明边界还没收得够小。")
        return notes
