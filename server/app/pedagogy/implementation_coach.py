from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.models import CurrentFilePayload, MemorySnapshot, TurnRequest, UserProfile

if TYPE_CHECKING:
    from .service import ImplementationGuide, LearnerState, TeachingDecision


class ImplementationCoachService:
    def build_guide(
        self,
        *,
        request: TurnRequest,
        learner_state: LearnerState,
        decision: TeachingDecision,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
    ) -> ImplementationGuide:
        from .service import ImplementationGuide

        current_file = request.current_file
        idea_summary = self._summarize_idea(
            request.message,
            decision.focus_area,
            profile,
            current_file,
            memory_snapshot,
        )
        scope_boundary = self._scope_boundary(
            request.message,
            current_file,
            memory_snapshot,
            decision.focus_area,
        )
        mvp_definition = self._mvp_definition(
            request.message,
            decision.focus_area,
            current_file,
            memory_snapshot,
        )
        current_step = self._current_step(
            request.message,
            current_file,
            learner_state,
            decision.focus_area,
            memory_snapshot,
        )
        next_steps = self._next_steps(
            request.message,
            current_file,
            memory_snapshot,
            decision.focus_area,
        )
        validation_strategy = self._validation_strategy(current_file, memory_snapshot)
        open_questions = self._open_questions(request, current_file, memory_snapshot)
        entry_points = self._entry_points(current_file, memory_snapshot)
        risk_notes = self._risk_notes(request.message, current_file, learner_state, memory_snapshot)
        teaching_goal = self._teaching_goal(decision.focus_area, memory_snapshot)
        success_signal = self._success_signal(current_file, request.message, decision.focus_area, memory_snapshot)
        fallback_step = self._fallback_step(current_file, request.message, decision.focus_area, memory_snapshot)

        return ImplementationGuide(
            idea_summary=idea_summary,
            scope_boundary=scope_boundary,
            mvp_definition=mvp_definition,
            current_step=current_step,
            next_steps=next_steps,
            validation_strategy=validation_strategy,
            open_questions=open_questions,
            codebase_entry_points=entry_points,
            risk_notes=risk_notes,
            teaching_goal=teaching_goal,
            success_signal=success_signal,
            fallback_step=fallback_step,
        )

    def _summarize_idea(
        self,
        message: str,
        focus_area: str,
        profile: UserProfile | None,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        goal = focus_area.strip() if focus_area.strip() else ""
        entry_point = self._primary_entry_point(current_file, memory_snapshot)
        if goal:
            if entry_point:
                return f"先把 {goal} 压成一个能在 {entry_point} 里看见的行为变化。"
            return f"先把 {goal} 压成一个可验证的行为变化，再考虑扩大范围。"
        cleaned = self._clean_message(message)
        if self._is_broad_idea(message, focus_area, current_file, memory_snapshot):
            return f"先收窄成一个用户能看见的行为，再动多模块：{cleaned}"
        if cleaned:
            return cleaned
        if profile is not None and profile.long_term_goal:
            return f"先把长期目标「{profile.long_term_goal}」压成一个可见的行为变化。"
        return cleaned

    def _scope_boundary(
        self,
        message: str,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
        focus_area: str,
    ) -> str:
        if current_file is not None and current_file.path:
            return f"先从 {current_file.path} 开始，第一步做完并验证后再看相关文件。"
        entry_point = self._primary_entry_point(current_file, memory_snapshot)
        if entry_point:
            secondary = self._secondary_entry_point(current_file, memory_snapshot)
            if secondary:
                return f"先在 {entry_point} 动第一层边界，验证之前不要扩大到 {secondary}。"
            return f"先把第一步留在 {entry_point}，这样补丁更容易复盘。"
        if memory_snapshot and memory_snapshot.current_focus:
            return f"先贴着当前聚焦点 {memory_snapshot.current_focus} 做，别先开旁支。"
        if self._is_broad_idea(message, focus_area, current_file, memory_snapshot):
            return "先选一个表面、一个行为、一个验证结果，再谈第二个模块。"
        return "先只改一条代码路径、一个行为、一个验证闭环。"

    def _mvp_definition(
        self,
        message: str,
        focus_area: str,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        area = self._target_label(message, focus_area, None)
        if current_file is not None and current_file.diagnostics:
            return f"先让 {area} 在最卡的那条路径上跑通，并用一个小检查证明它。"
        entry_point = self._primary_entry_point(current_file, memory_snapshot)
        if entry_point:
            return f"先让 {area} 在 {entry_point} 里有一条能跑通的路径，再考虑第二个行为。"
        if self._is_broad_idea(message, focus_area, current_file, memory_snapshot):
            return f"别一次做完 {area}，先交付一个 happy path，证明这想法值得继续。"
        return f"先交付一个小而可复盘的 {area} 版本，带一个明确行为和一个验证点。"

    def _current_step(
        self,
        message: str,
        current_file: CurrentFilePayload | None,
        learner_state: LearnerState,
        focus_area: str,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        target = self._target_label(message, focus_area, None)
        if current_file is not None and current_file.diagnostics:
            return f"先顺着 {current_file.path} 里第一条失败路径看清楚，再改 {target}。"
        entry_point = self._primary_entry_point(current_file, memory_snapshot)
        if entry_point:
            return f"先打开 {entry_point}，说清楚 {target} 的第一个可见行为，只改这一层边界。"
        if learner_state.needs_rescue:
            return f"先把 {target} 压成一个很小的补丁目标，再继续写。"
        if self._is_broad_idea(message, focus_area, current_file, memory_snapshot):
            return f"先说出 {target} 的第一个可见行为，以及它该出现在哪个模块。"
        return f"先找到 {target} 的第一处切口，在那儿写最小的行为变化。"

    def _next_steps(
        self,
        message: str,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
        focus_area: str,
    ) -> list[str]:
        target = self._target_label(message, focus_area, None)
        steps = [
            f"先用一句话重述 {target} 该表现成什么样。",
            "先改一个分支或函数，不要先重做整条链路。",
            "先跑一次最窄的验证，再考虑扩范围。",
        ]
        if self._is_broad_idea(message, focus_area, current_file, memory_snapshot):
            steps.insert(1, f"先把 {target} 收缩成一个能塞进单轮复盘的可见结果。")
        if current_file is not None and current_file.related_files:
            first_related = current_file.related_files[0].get("path") or current_file.related_files[0].get("file")
            if first_related:
                steps.append(f"只有第一步真的牵扯到依赖时，再看 {first_related}。")
        elif self._secondary_entry_point(current_file, memory_snapshot):
            steps.append(
                f"只有第一入口真的卡住时，再去看 {self._secondary_entry_point(current_file, memory_snapshot)}。"
            )
        if memory_snapshot and memory_snapshot.top_weakness:
            steps.append(f"顺手盯住已知薄弱点：{memory_snapshot.top_weakness}。")
        return steps

    def _validation_strategy(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[str]:
        strategy = ["先跑一个能证明变化的小检查。"]
        if current_file is not None and current_file.diagnostics:
            strategy.append("重新跑一遍最初暴露诊断的失败路径。")
        elif self._primary_entry_point(current_file, memory_snapshot):
            strategy.append(
                f"先验证 {self._primary_entry_point(current_file, memory_snapshot)} 里的第一条工作路径，再碰别的边界。"
            )
        strategy.append("再补一个边界情况，避免只是修好 happy path。")
        return strategy

    def _teaching_goal(self, focus_area: str, memory_snapshot: MemorySnapshot | None) -> str:
        if focus_area:
            return f"教会学习者把「{focus_area}」压成一个自己能执行的安全实现闭环。"
        if memory_snapshot and memory_snapshot.top_weakness:
            return f"教会学习者用一个安全闭环去改善薄弱点「{memory_snapshot.top_weakness}」。"
        return "教会学习者先做出一个安全实现闭环，再继续要更多代码。"

    def _success_signal(
        self,
        current_file: CurrentFilePayload | None,
        message: str,
        focus_area: str,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        target = self._target_label(message, focus_area, None)
        if current_file is not None and current_file.diagnostics:
            return f"先把和 {target} 相关的第一条失败路径修掉，或者至少明显缩小。"
        if current_file is not None and current_file.path:
            return f"{current_file.path} 里的第一个可见行为已经变了，而且能立刻验证。"
        if self._primary_entry_point(current_file, memory_snapshot):
            return f"{self._primary_entry_point(current_file, memory_snapshot)} 里的第一个可见行为变了，而且不用扩大范围就能证明。"
        return f"学习者能指出 {target} 的一个具体行为变化，以及对应的验证动作。"

    def _fallback_step(
        self,
        current_file: CurrentFilePayload | None,
        message: str,
        focus_area: str,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        target = self._target_label(message, focus_area, None)
        if current_file is not None and current_file.path:
            return f"如果 {target} 还是太大，就先留在 {current_file.path} 里，只改一个分支或一个 helper。"
        if self._primary_entry_point(current_file, memory_snapshot):
            return f"如果 {target} 还是太大，就先留在 {self._primary_entry_point(current_file, memory_snapshot)}，只改一处边界。"
        return f"如果 {target} 还是太大，就先压成一个函数、一个分支、一个小检查。"

    def _open_questions(
        self,
        request: TurnRequest,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[str]:
        questions: list[str] = []
        broad_idea = self._is_broad_idea(
            request.message,
            request.focus_area or "",
            current_file,
            memory_snapshot,
        )
        entry_point = self._primary_entry_point(current_file, memory_snapshot)
        if current_file is None and not entry_point:
            questions.append("第一步最安全的入口文件或模块是哪一个？")
        elif current_file is None and entry_point:
            questions.append(f"第一步是从 {entry_point} 开始，还是有更安全的边界？")
        if current_file is not None and not current_file.diagnostics:
            questions.append("这次补丁最快三的可观察成功信号是什么？")
        if broad_idea:
            questions.append("Which single user-visible behavior should ship first, before the broader workflow is touched?")
        if not request.focus_area and memory_snapshot and not memory_snapshot.current_focus:
            questions.append("第一轮到底要交付哪个可见结果？")
        return questions[:3]

    def _entry_points(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[str]:
        if current_file is None:
            understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
            if understanding is not None:
                return list(understanding.entry_points[:3])
            return []
        points = [current_file.path]
        for related in current_file.related_files[:2]:
            path = related.get("path") or related.get("file")
            if path and path not in points:
                points.append(path)
        if memory_snapshot and memory_snapshot.workspace_understanding:
            for path in memory_snapshot.workspace_understanding.entry_points[:2]:
                if path and path not in points:
                    points.append(path)
        return points[:4]

    def _risk_notes(
        self,
        message: str,
        current_file: CurrentFilePayload | None,
        learner_state: LearnerState,
        memory_snapshot: MemorySnapshot | None,
    ) -> list[str]:
        risks = []
        if learner_state.needs_rescue:
            risks.append("The learner is at risk of widening scope before the first verification.")
        if self._is_broad_idea(message, "", current_file, memory_snapshot):
            risks.append("The idea is broad enough to sprawl unless the first slice is reduced to one visible behavior.")
        if current_file is not None and len(current_file.recent_edited_files) >= 3:
            risks.append("Too many recently edited files suggests the patch may sprawl.")
        if current_file is not None and current_file.diagnostics:
            risks.append("Do not treat the current diagnostics as noise; use the first one as the anchor.")
        if memory_snapshot and memory_snapshot.workspace_understanding:
            for item in memory_snapshot.workspace_understanding.risk_zones[:2]:
                if item not in risks:
                    risks.append(item)
        return risks

    def _primary_entry_point(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        if current_file is not None and current_file.path:
            return current_file.path
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding and understanding.entry_points:
            return understanding.entry_points[0]
        return ""

    def _secondary_entry_point(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        if current_file is not None and current_file.related_files:
            path = current_file.related_files[0].get("path") or current_file.related_files[0].get("file")
            if isinstance(path, str) and path.strip():
                return path.strip()
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding and len(understanding.entry_points) >= 2:
            return understanding.entry_points[1]
        return ""

    def _is_broad_idea(
        self,
        message: str,
        focus_area: str,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> bool:
        if focus_area.strip():
            return False
        if current_file is not None and current_file.diagnostics:
            return False
        understanding = memory_snapshot.workspace_understanding if memory_snapshot else None
        if understanding and understanding.entry_points:
            return False
        lowered = message.lower()
        broad_tokens = (
            "system",
            "platform",
            "workflow",
            "end-to-end",
            "整体",
            "全部",
            "完整",
            "长期",
            "整套",
            "系统",
            "工作流",
        )
        return len(self._clean_message(message)) >= 36 or any(token in lowered for token in broad_tokens)

    def _clean_message(self, message: str) -> str:
        return " ".join(str(message or "").strip().split())[:180]

    def _target_label(
        self,
        message: str,
        focus_area: str,
        profile: UserProfile | None,
    ) -> str:
        if focus_area.strip():
            return focus_area.strip()
        cleaned = self._clean_message(message)
        if cleaned:
            return cleaned
        if profile is not None and profile.long_term_goal:
            return profile.long_term_goal.strip()
        return "the current idea"
