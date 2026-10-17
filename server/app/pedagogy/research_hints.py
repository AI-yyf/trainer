"""Research-to-pedagogy bridge (P1 #13, §5): consume the preparation engine.

``MaterialIntelligenceService`` used to assemble paper/repo/exercise
candidates that no orchestration loop consumed. This module is the consumer
side the design calls for: background research references for the current
focus area are aggregated into a :class:`~app.research.material_intelligence.MaterialBundle`
and distilled into bounded hint strings that feed the stage-material
composer's prompt. Everything is deterministic, read-only, and degrades to an
empty hint list when the research lane has nothing relevant.
"""

from __future__ import annotations

from typing import Any, cast

from ..research.material_intelligence import MaterialIntelligenceService

_MAX_HINTS = 8
_MAX_HINT_CHARS = 220


def collect_research_hints(
    *,
    research_service: Any,
    workspace_id: str,
    topic: str,
    focus_area: str = "",
    limit: int = 6,
) -> list[str]:
    """Distill background research references into stage-material hints.

    ``research_service`` only needs ``recent_background_references`` — the
    duck type keeps this bridge free of import cycles. Returns at most
    ``_MAX_HINTS`` hints, each capped at ``_MAX_HINT_CHARS`` characters; an
    empty list means "the preparation engine has nothing for this stage",
    which is a fact, not an error.
    """
    reader = getattr(research_service, "recent_background_references", None)
    if not callable(reader):
        return []
    references = cast(
        list[dict[str, Any]],
        reader(
            workspace_id=workspace_id,
            focus_area=focus_area.strip() or None,
            limit=max(1, min(int(limit), 10)),
        ),
    )
    if not references:
        return []

    bundle = MaterialIntelligenceService().build_material_bundle(
        topic=topic.strip() or focus_area.strip() or "stage preparation",
        topic_family="general",
        scenario="guided",
        blueprint={},
        grounding_references=list(references),
    )

    hints: list[str] = []
    hints.extend(bundle.source_lanes)
    hints.extend(bundle.teaching_sequence)
    for reference in bundle.references[:3]:
        title = str(reference.get("title", "") or "").strip()
        why = str(reference.get("why_it_matters", "") or "").strip()
        if title and why:
            hints.append(f"{title}: {why}")

    distilled: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        cleaned = " ".join(str(hint or "").split()).strip()
        if not cleaned:
            continue
        cleaned = cleaned[: _MAX_HINT_CHARS - 1].rstrip() + "…" if len(cleaned) > _MAX_HINT_CHARS else cleaned
        signature = cleaned.lower()
        if signature in seen:
            continue
        seen.add(signature)
        distilled.append(cleaned)
        if len(distilled) >= _MAX_HINTS:
            break
    return distilled
