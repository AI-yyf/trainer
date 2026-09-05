from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.models import (
    CurrentFilePayload,
    MemorySnapshot,
    TeachingKnowledgeAsset,
    TurnRequest,
    UserProfile,
)

if TYPE_CHECKING:
    from .service import LearnerState, TeachingDecision


@dataclass(slots=True)
class PrincipleNote:
    current_principle: str
    why_this_approach: str
    common_wrong_intuition: str
    concrete_anchor: str
    transferable_lesson: str
    follow_up_exercise: str
    related_checks: list[str] = field(default_factory=list)
    source_asset_title: str = ""


class PrincipleExplainerService:
    def explain(
        self,
        *,
        request: TurnRequest,
        learner_state: LearnerState,
        decision: TeachingDecision,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        selected_assets: list[TeachingKnowledgeAsset] | None = None,
    ) -> PrincipleNote:
        current_file = request.current_file
        scenario = getattr(decision, "scenario", "") or getattr(decision, "mode", "")
        focus_area = decision.focus_area or getattr(learner_state, "active_focus", "") or ""
        resolved_assets = (
            [asset for asset in selected_assets if isinstance(asset, TeachingKnowledgeAsset)]
            if selected_assets
            else self._relevant_teaching_assets(
                memory_snapshot,
                scenario=scenario,
                focus_area=focus_area,
                limit=2,
            )
        )
        explanation_asset = self._pick_explanation_asset(resolved_assets)
        principle = self._principle_name(decision.focus_area, current_file, memory_snapshot)
        return PrincipleNote(
            current_principle=principle,
            why_this_approach=self._why_this_approach(
                principle,
                learner_state,
                current_file,
                memory_snapshot,
                explanation_asset,
                scenario,
                profile,
            ),
            common_wrong_intuition=self._wrong_intuition(
                principle,
                current_file,
                memory_snapshot,
                explanation_asset,
                focus_area,
            ),
            concrete_anchor=self._concrete_anchor(
                current_file,
                memory_snapshot,
                explanation_asset,
                focus_area,
            ),
            transferable_lesson=self._transferable_lesson(
                principle,
                current_file,
                memory_snapshot,
                explanation_asset,
                scenario,
            ),
            follow_up_exercise=self._follow_up_exercise(
                principle,
                current_file,
                memory_snapshot,
                explanation_asset,
                scenario,
                focus_area,
            ),
            related_checks=self._related_checks(
                current_file,
                memory_snapshot,
                explanation_asset,
                scenario,
                focus_area,
            ),
            source_asset_title=explanation_asset.title if explanation_asset is not None else "",
        )

    def _principle_name(
        self,
        focus_area: str,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        if focus_area:
            return f"Keep {focus_area} grounded in one observable behavior before abstracting."
        if current_file is not None and current_file.diagnostics:
            return "Anchor explanation to the failing mechanism before proposing broader fixes."
        if memory_snapshot and memory_snapshot.current_focus:
            return f"Use {memory_snapshot.current_focus} as the anchor for explaining tradeoffs."
        return "Explain the mechanism by tying it to one concrete behavior and one concrete boundary."

    def _why_this_approach(
        self,
        principle: str,
        learner_state: LearnerState,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
        explanation_asset: TeachingKnowledgeAsset | None,
        scenario: str,
        profile: UserProfile | None,
    ) -> str:
        if current_file is not None and current_file.diagnostics:
            why = (
                f"{principle} because the current code already exposes a real failure signal, "
                "so the explanation should stay attached to the broken mechanism instead of drifting into theory."
            )
            if explanation_asset is not None:
                why = f"{why} Reuse the saved teaching asset '{explanation_asset.title}' as the stable framing."
            return why
        if learner_state.needs_rescue:
            why = (
                f"{principle} because a compressed principle helps the learner recover without adding more branches to hold in working memory."
            )
            if explanation_asset is not None:
                asset_anchor = explanation_asset.summary or explanation_asset.title
                if asset_anchor == explanation_asset.title:
                    why = f"{why} Keep the rescue explanation aligned with the saved teaching asset '{explanation_asset.title}'."
                else:
                    why = (
                        f"{why} Keep the rescue explanation aligned with the saved teaching asset "
                        f"'{explanation_asset.title}': {asset_anchor}."
                    )
            return why
        if scenario == "concept_teaching":
            why = (
                f"{principle} because concept teaching works best when the learner can connect the rule to one live code boundary "
                "and then transfer it to a nearby case."
            )
        else:
            why = (
                f"{principle} because stable engineering understanding comes from connecting the code change to the concrete problem it solves."
            )
        if explanation_asset is not None:
            why = f"{why} Reuse the saved teaching asset '{explanation_asset.title}' as the stable framing."
        if memory_snapshot is not None and memory_snapshot.top_weakness:
            why = f"{why} That is especially important because the repeated weak spot is {memory_snapshot.top_weakness}."
        if profile is not None and profile.teaching_style == "hands-on":
            why = f"{why} Keep the explanation short enough that it still points back to the next patch."
        return why

    def _wrong_intuition(
        self,
        principle: str,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
        explanation_asset: TeachingKnowledgeAsset | None,
        focus_area: str,
    ) -> str:
        if current_file is not None and current_file.diagnostics:
            intuition = (
                f"A common mistake is to discuss '{principle}' abstractly, instead of tracing how it changes the exact failing branch or guard in {current_file.path}."
            )
        elif memory_snapshot is not None and memory_snapshot.top_weakness:
            intuition = (
                f"A common mistake is to treat '{principle}' as remembered understanding, while repeating the old weakness around {memory_snapshot.top_weakness} in the next patch."
            )
        elif focus_area:
            intuition = (
                f"A common mistake is to talk about '{principle}' without checking where it changes the concrete behavior for {focus_area}."
            )
        else:
            intuition = (
                f"A common mistake is to treat '{principle}' as a generic slogan, instead of checking where it changes an actual branch, dependency, or verification path."
            )
        if explanation_asset is not None and explanation_asset.anti_pattern:
            intuition = f"{intuition} The saved anti-pattern to avoid is: {explanation_asset.anti_pattern.strip()}."
        return intuition

    def _concrete_anchor(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
        explanation_asset: TeachingKnowledgeAsset | None,
        focus_area: str,
    ) -> str:
        if current_file is not None:
            anchor = f"Locate the first relevant branch or boundary in {current_file.path} and explain the principle there."
            if current_file.selection_range:
                anchor = f"{anchor} Start from the selected range {current_file.selection_range} if it already contains the live decision point."
            return anchor
        if explanation_asset is not None and explanation_asset.focus_area:
            return f"Use the saved teaching asset focus '{explanation_asset.focus_area}' as the concrete teaching anchor before widening."
        if memory_snapshot and memory_snapshot.current_focus:
            return f"Use the active focus '{memory_snapshot.current_focus}' as the concrete teaching anchor."
        if focus_area:
            return f"Use '{focus_area}' as the first concrete teaching anchor and attach it to one branch or boundary."
        return "Pick one function or one edge case where the principle changes the implementation choice."

    def _transferable_lesson(
        self,
        principle: str,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
        explanation_asset: TeachingKnowledgeAsset | None,
        scenario: str,
    ) -> str:
        if current_file is not None:
            lesson = (
                f"The transferable lesson is to apply '{principle}' anywhere this repository asks you to widen scope before one boundary has been verified."
            )
        elif memory_snapshot is not None and memory_snapshot.workspace_understanding is not None:
            entry_points = memory_snapshot.workspace_understanding.entry_points[:2]
            if entry_points:
                lesson = (
                    f"The transferable lesson is to reuse '{principle}' across nearby entry points such as {', '.join(entry_points)} whenever a broad request can be compressed into one behavior."
                )
            else:
                lesson = (
                    f"The transferable lesson is to apply '{principle}' whenever a broad request can be compressed into one smaller behavior, one code boundary, and one verification loop."
                )
        else:
            lesson = (
                f"The transferable lesson is to apply '{principle}' whenever a broad request can be compressed into one smaller behavior, one code boundary, and one verification loop."
            )
        if scenario == "concept_teaching":
            lesson = f"{lesson} After the learner names the rule once, immediately ask where the same rule transfers next."
        if explanation_asset is not None and explanation_asset.why_it_matters:
            lesson = f"{lesson} The saved teaching asset reinforces this with: {explanation_asset.why_it_matters.strip()}."
        return lesson

    def _follow_up_exercise(
        self,
        principle: str,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
        explanation_asset: TeachingKnowledgeAsset | None,
        scenario: str,
        focus_area: str,
    ) -> str:
        if scenario == "concept_teaching":
            if current_file is not None:
                prompt = (
                    f"Use {current_file.path} to teach this concept back: point at one branch, restate '{principle}' in plain words, then say what bug or design drift it prevents there."
                )
            else:
                prompt = (
                    f"Teach '{principle}' back through one tiny example: name the boundary, the rule, and the failure mode it prevents."
                )
        elif current_file is not None:
            prompt = (
                f"Point at one line or branch in {current_file.path}, explain how '{principle}' shows up there, and state what would break if that rule were ignored."
            )
        else:
            prompt = (
                f"Create a tiny example where ignoring '{principle}' causes a bug or confusing review outcome, then restate the correction in one sentence."
            )
        if memory_snapshot is not None and memory_snapshot.top_weakness:
            prompt = f"{prompt} Keep an eye on the repeated weak spot around {memory_snapshot.top_weakness}."
        if focus_area:
            prompt = f"{prompt} Keep it tied to {focus_area}."
        if explanation_asset is not None and explanation_asset.example:
            prompt = f"{prompt} Reuse the saved example '{explanation_asset.example.strip()}' if it helps."
        return prompt

    def _related_checks(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
        explanation_asset: TeachingKnowledgeAsset | None,
        scenario: str,
        focus_area: str,
    ) -> list[str]:
        checks = ["Name one concrete branch, line, or edge case where the principle matters."]
        if current_file is not None:
            checks.append(f"Reconnect the explanation to {current_file.path} before widening the explanation.")
        if current_file is not None and current_file.diagnostics:
            checks.append("Reconnect the explanation to the current failing signal.")
        if scenario == "concept_teaching":
            checks.append("Restate the rule in plain language before returning to code.")
        if focus_area:
            checks.append(f"Say how this changes the implementation choice for {focus_area}.")
        if memory_snapshot is not None and memory_snapshot.top_weakness:
            checks.append(f"Name how this avoids repeating the weak spot around {memory_snapshot.top_weakness}.")
        if explanation_asset is not None and explanation_asset.title:
            checks.append(f"Reuse the saved teaching asset '{explanation_asset.title}' instead of inventing a broader explanation.")
        checks.append("State what would likely go wrong if the principle were ignored.")
        checks.append("Describe the smallest code change or verification step that proves you understood it.")
        return checks

    def _relevant_teaching_assets(
        self,
        memory_snapshot: MemorySnapshot | None,
        *,
        scenario: str,
        focus_area: str,
        limit: int,
    ) -> list[TeachingKnowledgeAsset]:
        if memory_snapshot is None or not memory_snapshot.teaching_assets:
            return []
        focus_tokens = self._tokens(" ".join([scenario, focus_area]))
        ranked = sorted(
            memory_snapshot.teaching_assets,
            key=lambda item: self._asset_rank(item, scenario=scenario, focus_area=focus_area, focus_tokens=focus_tokens),
            reverse=True,
        )
        return ranked[:limit]

    def _pick_explanation_asset(
        self,
        assets: list[TeachingKnowledgeAsset],
    ) -> TeachingKnowledgeAsset | None:
        if not assets:
            return None
        for asset in assets:
            if asset.kind in {"explanation_recipe", "concept_card", "common_pitfall"}:
                return asset
        return assets[0]

    def _asset_rank(
        self,
        asset: TeachingKnowledgeAsset,
        *,
        scenario: str,
        focus_area: str,
        focus_tokens: set[str],
    ) -> tuple[float, float, float, str]:
        kind_weight = {
            "principle_explanation": {
                "explanation_recipe": 6.0,
                "concept_card": 5.0,
                "common_pitfall": 4.0,
            },
            "concept_teaching": {
                "concept_card": 6.0,
                "explanation_recipe": 5.0,
                "common_pitfall": 4.0,
            },
        }.get(scenario, {})
        scenario_score = kind_weight.get(asset.kind, 1.0)
        if asset.scenario.strip().lower() == scenario:
            scenario_score += 3.0
        overlap = 0.0
        if focus_area and focus_area.lower() in asset.focus_area.lower():
            overlap += 5.0
        overlap += float(len(self._tokens(" ".join([asset.title, asset.summary, asset.focus_area])) & focus_tokens)) * 2.5
        trust = float(asset.trust_score or 0.0) + min(float(asset.usage_count or 0), 6.0) * 0.15
        return overlap, scenario_score, trust, asset.updated_at or ""

    def _tokens(self, value: str) -> set[str]:
        cleaned = value.replace("/", " ").replace("-", " ").replace("_", " ")
        return {
            token
            for token in re.findall(r"[\w\u4e00-\u9fff]+", cleaned.lower())
            if len(token) > 1
        }
