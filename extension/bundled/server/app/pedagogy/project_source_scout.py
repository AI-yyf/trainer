from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..core.models import MemorySnapshot, TurnRequest, UserProfile
from ..resources.source_governance import (
    commercial_reuse_eligibility_reason_codes,
    commercial_reuse_governance_status,
    is_external_reference_source,
    source_governance_payload,
)


@dataclass(slots=True)
class ProjectSourceSuggestion:
    title: str
    source_kind: str
    repo_hint: str
    fit_reason: str
    training_value: str
    first_filter: str
    first_task: str
    caution: str = ""
    tags: list[str] = field(default_factory=list)
    source_url: str = ""
    retrieved_at: str = ""
    trust_score: float = 0.0
    quality_flags: list[str] = field(default_factory=list)


class ProjectSourceScoutService:
    def suggest_sources(
        self,
        *,
        request: TurnRequest,
        focus_area: str,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        external_references: list[dict[str, object]] | None = None,
    ) -> list[ProjectSourceSuggestion]:
        target = focus_area or self._infer_target(request, profile, memory_snapshot)
        weak_spot = memory_snapshot.top_weakness if memory_snapshot and memory_snapshot.top_weakness else ""
        suggestions: list[ProjectSourceSuggestion] = []
        suggestions.extend(self._suggest_from_external_references(target, external_references))
        suggestions.extend([
            ProjectSourceSuggestion(
                title="Small production-shaped web app",
                source_kind="reference_repo",
                repo_hint="Search for a compact FastAPI / Next.js / full-stack starter with tests and one clear feature lane.",
                fit_reason=(
                    f"It gives you a realistic surface for practicing {target} without burying the training inside a giant codebase."
                ),
                training_value=(
                    "Good for idea implementation, feature slicing, and learning how one behavior travels through UI, API, and persistence."
                ),
                first_filter="Prefer repos with tests, recent maintenance, and fewer than roughly 40 core source files.",
                first_task=(
                    f"Clone one candidate, map the feature boundary for {target}, and identify the first thin modification lane."
                ),
                caution="Avoid template-heavy repos where the interesting work is hidden by framework scaffolding.",
                tags=["web", "full-stack", "feature-work"],
                source_url="https://github.com/topics/fastapi",
                retrieved_at=self._now_iso(),
                trust_score=0.72,
                quality_flags=["search_seed", "discovery_only", "commercial_reuse_not_auto_promoted"],
            ),
            ProjectSourceSuggestion(
                title="CLI or tooling project with focused modules",
                source_kind="reference_repo",
                repo_hint="Search for a Python or TypeScript CLI/tooling repo with command parsing, validation, and tests.",
                fit_reason=(
                    f"It compresses the feedback loop for {target} and keeps verification cheaper than a large UI-heavy app."
                ),
                training_value=(
                    "Good for edge cases, principle explanation, refactor drills, and one-behavior-at-a-time coaching."
                ),
                first_filter="Prefer repos with obvious module boundaries and direct command-level verification steps.",
                first_task=(
                    "Choose one command or one data-processing path, then turn it into a tiny adaptation or review exercise."
                ),
                caution="Avoid repos whose main behavior depends on external services you cannot easily run locally.",
                tags=["cli", "tooling", "verification-first"],
                source_url="https://github.com/topics/cli",
                retrieved_at=self._now_iso(),
                trust_score=0.68,
                quality_flags=["search_seed", "discovery_only", "commercial_reuse_not_auto_promoted"],
            ),
            ProjectSourceSuggestion(
                title="Issue-sized slice from a maintained library",
                source_kind="reference_impl",
                repo_hint="Search closed issues and small PRs in an actively maintained library related to the target topic.",
                fit_reason=(
                    f"It gives you real engineering pressure around {target} while keeping scope tied to one known defect or behavior."
                ),
                training_value=(
                    "Good for review-style training, reading real diffs, and learning what maintainers actually accept."
                ),
                first_filter="Prefer issues with reproduction steps, tests, and patch-sized discussions.",
                first_task=(
                    "Pick one issue, restate the failing path, and draft the narrowest fix or explanation route before coding."
                ),
                caution="Do not start with architecture-wide issue threads; stay with bug-sized slices.",
                tags=["library", "bugfix", "real-world-review"],
                source_url="https://github.com/issues",
                retrieved_at=self._now_iso(),
                trust_score=0.62,
                quality_flags=["search_seed", "discovery_only", "commercial_reuse_not_auto_promoted"],
            ),
        ])
        if weak_spot:
            suggestions.append(
                ProjectSourceSuggestion(
                    title="Practice repo matched to the current weak spot",
                    source_kind="training_repo",
                    repo_hint=f"Search for a compact repo where '{weak_spot}' is exercised repeatedly and visibly.",
                    fit_reason=(
                        f"Your repeated gap around {weak_spot} means the best outside project should expose that move over and over."
                    ),
                    training_value="Turns a known weakness into deliberate practice instead of vague reading.",
                    first_filter="Prefer small repos where that weak spot is visible in tests, adapters, or validation flows.",
                    first_task=(
                        f"Pick one slice where {weak_spot} matters, then ask the coach to extract the first training task from it."
                    ),
                    caution="Do not pick a repo so large that setup cost swallows the training value.",
                    tags=["weak-spot", "deliberate-practice"],
                    source_url="https://github.com/topics",
                    retrieved_at=self._now_iso(),
                    trust_score=0.6,
                    quality_flags=[
                        "search_seed",
                        "weak-spot-targeted",
                        "discovery_only",
                        "commercial_reuse_not_auto_promoted",
                    ],
                )
            )
        ranked = sorted(
            suggestions,
            key=lambda item: (
                "search_seed" in item.quality_flags,
                -(item.trust_score or 0.0),
                item.title.lower(),
            ),
        )
        deduped: list[ProjectSourceSuggestion] = []
        seen_titles: set[str] = set()
        for suggestion in ranked:
            normalized_title = suggestion.title.strip().lower()
            if not normalized_title or normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            deduped.append(suggestion)
            if len(deduped) >= 3:
                break
        return deduped

    def _infer_target(
        self,
        request: TurnRequest,
        profile: UserProfile | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        for candidate in (
            request.focus_area,
            memory_snapshot.current_focus if memory_snapshot else "",
            memory_snapshot.coach_anchor if memory_snapshot else "",
            profile.long_term_goal if profile is not None else "",
        ):
            if candidate:
                return candidate
        return "the current training goal"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _suggest_from_external_references(
        self,
        target: str,
        external_references: list[dict[str, object]] | None,
    ) -> list[ProjectSourceSuggestion]:
        suggestions: list[ProjectSourceSuggestion] = []
        if not isinstance(external_references, list):
            return suggestions
        for item in external_references:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "") or "").strip()
            snippet = str(item.get("snippet", "") or "").strip()
            if not source or not snippet:
                continue
            automatic_reuse_allowed, governance_quality_flags = (
                self._external_reference_is_auto_reuse_eligible(item, source=source)
            )
            if not automatic_reuse_allowed:
                continue
            focus_area = str(item.get("focus_area", target) or target).strip()
            raw_trust_score = item.get("trust_score", 0.0)
            if isinstance(raw_trust_score, (str, int, float)):
                try:
                    trust_score = float(raw_trust_score)
                except ValueError:
                    trust_score = 0.0
            else:
                trust_score = 0.0
            custom_title = str(item.get("title", "") or "").strip()
            custom_repo_hint = str(item.get("repo_hint", "") or "").strip()
            custom_first_task = str(item.get("first_task", "") or "").strip()
            custom_fit_reason = str(item.get("fit_reason", "") or "").strip()
            custom_training_value = str(item.get("training_value", "") or "").strip()
            custom_first_filter = str(item.get("first_filter", "") or "").strip()
            custom_caution = str(item.get("caution", "") or "").strip()
            custom_source_kind = str(item.get("source_kind", "") or "").strip()
            source_kind = (
                custom_source_kind
                if custom_source_kind in {"reference_repo", "reference_impl", "training_repo"}
                else "reference_impl"
                if source.startswith("http")
                else "training_repo"
            )
            raw_tags = item.get("tags", [])
            tags = (
                [str(tag).strip() for tag in raw_tags if str(tag).strip()]
                if isinstance(raw_tags, list)
                else []
            )
            raw_quality_flags = item.get("quality_flags", [])
            quality_flags = (
                [str(flag).strip() for flag in raw_quality_flags if str(flag).strip()]
                if isinstance(raw_quality_flags, list)
                else []
            )
            suggestions.append(
                ProjectSourceSuggestion(
                    title=custom_title or f"Grounded source for {focus_area}",
                    source_kind=source_kind,
                    repo_hint=custom_repo_hint
                    or f"Start from {source} and extract one narrow implementation lane around {focus_area}.",
                    fit_reason=custom_fit_reason
                    or (
                        "This source is already grounded in the trainer workspace, so the next project suggestion can start from real material instead of a generic search seed."
                    ),
                    training_value=custom_training_value
                    or f"Good for turning outside material about {focus_area} into a scoped implementation or explanation exercise.",
                    first_filter=custom_first_filter
                    or "Prefer one behavior, one module boundary, and one cheap verification step.",
                    first_task=custom_first_task
                    or (
                        f"Read the cited source, restate the key behavior in your own words, then extract the first tiny coding move for {focus_area}."
                    ),
                    caution=custom_caution
                    or "Do not widen into a full rewrite before the first grounded slice is verified.",
                    tags=tags or ["grounded-source", "external-reference"],
                    source_url=source,
                    retrieved_at=str(item.get('fetched_at') or item.get('created_at') or self._now_iso()),
                    trust_score=trust_score,
                    quality_flags=list(
                        dict.fromkeys(
                            [
                                *quality_flags,
                                "grounded_reference",
                                *governance_quality_flags,
                            ]
                        )
                    ),
                )
            )
        return suggestions

    def _external_reference_is_auto_reuse_eligible(
        self,
        item: dict[str, object],
        *,
        source: str,
    ) -> tuple[bool, list[str]]:
        source_type = str(item.get("source_type", "") or "").strip()
        if not is_external_reference_source(source, source_type):
            return True, []

        governance = source_governance_payload(item.get("source_governance"))
        if governance is None:
            return False, ["commercial_reuse_review_required", "source_governance_missing"]
        status = commercial_reuse_governance_status(governance)
        raw_reason_codes = governance.get("commercial_reuse_reason_codes", [])
        reason_code_values = raw_reason_codes if isinstance(raw_reason_codes, list) else []
        reason_codes = [
            str(code).strip()
            for code in reason_code_values
            if str(code).strip()
        ]
        if status != "eligible":
            normalized_status = status if status in {"review_required", "blocked"} else "review_required"
            return (
                False,
                list(
                    dict.fromkeys(
                        [
                            f"commercial_reuse_{normalized_status}",
                            "commercial_reuse_not_auto_promoted",
                            *[f"source_governance_reason:{code}" for code in reason_codes[:4]],
                        ]
                    )
                ),
            )
        eligibility_reasons = commercial_reuse_eligibility_reason_codes(governance)
        if eligibility_reasons:
            return (
                False,
                list(
                    dict.fromkeys(
                        [
                            "commercial_reuse_review_required",
                            "commercial_reuse_not_auto_promoted",
                            *[
                                f"source_governance_reason:{code}"
                                for code in [*reason_codes, *eligibility_reasons][:4]
                            ],
                        ]
                    )
                ),
            )
        return (
            True,
            list(
                dict.fromkeys(
                    [
                        "commercial_reuse_eligible",
                        "controlled_source",
                        *[f"source_governance_reason:{code}" for code in reason_codes[:4]],
                    ]
                )
            ),
        )
