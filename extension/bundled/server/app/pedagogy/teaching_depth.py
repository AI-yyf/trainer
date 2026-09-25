"""§八/§九: teaching depth ladder with over-teaching suppression.

Every coach turn gets an explicit depth decision before the reply is shaped:

* L0 direct answer — lookup questions, explicit "just tell me", urgent rescue
* L1 explain + example — default when the skill state is unknown or stale
* L2 explain then check — learner has not verified this skill yet
* L3 guided practice — learner previously completed it with assistance
* L4 independent practice — learner completed it independently; do not hand
  over the finished solution
* L5 transfer — repeatedly verified; verify mastery on a new problem

§九 honesty rules beat the ladder: an explicit "just tell me" request is
answered directly (no quiz, no forced practice), and an urgent rescue is
fix-first with an optional light practice offer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SkillState = str | None
"""One of: needs_review | not_verified | assisted | independent |
repeat_verified — the per-dimension state from the skill projection."""


@dataclass(slots=True)
class TeachingDepthDecision:
    level: int
    label: str
    rationale: str
    direct_answer_override: bool = False
    offer_light_practice: bool = False
    evidence: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, object]:
        return {
            "level": self.level,
            "label": self.label,
            "rationale": self.rationale,
            "direct_answer_override": self.direct_answer_override,
            "offer_light_practice": self.offer_light_practice,
            "evidence": list(self.evidence),
        }


_LEVEL_LABELS: dict[int, str] = {
    0: "direct answer",
    1: "explain with an example",
    2: "explain then check",
    3: "guided practice",
    4: "independent practice",
    5: "transfer to a new problem",
}

_SKILL_LADDER: dict[str, int] = {
    "needs_review": 1,
    "not_verified": 2,
    "assisted": 3,
    "independent": 4,
    "repeat_verified": 5,
}

_DIRECT_ANSWER_CUES = (
    "直接告诉我",
    "直接给我",
    "直接说",
    "别问我",
    "只要答案",
    "把代码给我",
    "直接给我代码",
    "just tell me",
    "just give me",
    "tell me directly",
    "give me the answer",
    "no exercises",
    "don't quiz me",
    "stop asking me",
)

_URGENT_RESCUE_CUES = (
    "赶紧",
    "急",
    "线上",
    "生产事故",
    "帮我定位",
    "快帮",
    "urgent",
    "asap",
    "production down",
    "outage",
    "help me debug",
    "fix it now",
)

_DEFINITION_CUES = (
    "什么是",
    "是什么意思",
    "定义一下",
    "what is ",
    "what are ",
    "define ",
    "definition of",
    "meaning of",
)

_PRACTICE_REQUEST_CUES = (
    "带我练",
    "出一个练习",
    "给我出题",
    "练习一下",
    "give me an exercise",
    "give me a practice",
    "let me practice",
)

_LADDER_FLOOR_CUES = _PRACTICE_REQUEST_CUES

# Ladder ranks used for the conservative fallback: the dimension with the
# LEAST mastery anchors the depth, so the coach never over-teaches a weak
# dimension while another is strong.
_SKILL_RANKS: dict[str, int] = {
    "needs_review": 0,
    "not_verified": 1,
    "assisted": 2,
    "independent": 3,
    "repeat_verified": 4,
}

_SCENARIO_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("debug", "debugging"),
    ("debugging", "debugging"),
    ("implementation", "implementation"),
    ("idea", "implementation"),
    ("project_adaptation", "implementation"),
    ("concept", "comprehension"),
    ("principle", "comprehension"),
    ("planning", "comprehension"),
    ("reading", "comprehension"),
    ("transfer", "transfer"),
)


def resolve_teaching_depth_skill_state(
    *,
    skill_projection: object | None,
    scenario: str | None = None,
) -> SkillState:
    """Pick the skill-projection state this turn's depth should anchor on.

    The scenario's dimension wins when the projection tracks it; otherwise
    the weakest tracked dimension anchors the depth (§九: never over-teach
    a weak dimension while another is strong).
    """

    if not isinstance(skill_projection, dict):
        return None
    dimensions = skill_projection.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        return None

    def _state(name: str) -> str | None:
        record = dimensions.get(name)
        if not isinstance(record, dict):
            return None
        state = str(record.get("state") or "").strip().lower()
        return state or None

    normalized_scenario = str(scenario or "").strip().lower()
    for cue, dimension in _SCENARIO_DIMENSIONS:
        if cue in normalized_scenario:
            preferred = _state(dimension)
            if preferred:
                return preferred
            break

    ranked = [
        (_SKILL_RANKS.get(state, 1), name, state)
        for name, state in ((name, _state(name)) for name in dimensions)
        if state
    ]
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][2]


def _matches(message: str, cues: tuple[str, ...]) -> str | None:
    lowered = message.lower()
    for cue in cues:
        if cue in lowered:
            return cue
    return None


def resolve_teaching_depth(
    *,
    message: str,
    skill_state: SkillState = None,
    affect_urgency: str | None = None,
    needs_rescue: bool = False,
) -> TeachingDepthDecision:
    """Resolve the §八 depth level with §九 suppression rules applied."""

    normalized_message = " ".join(str(message or "").split())
    evidence: list[str] = []

    direct_cue = _matches(normalized_message, _DIRECT_ANSWER_CUES)
    if direct_cue:
        evidence.append(f"direct_answer_request:{direct_cue}")
        return TeachingDepthDecision(
            level=0,
            label=_LEVEL_LABELS[0],
            rationale="The learner explicitly asked for the direct answer; quiz-free reply.",
            direct_answer_override=True,
            offer_light_practice=False,
            evidence=evidence,
        )

    urgent_cue = _matches(normalized_message, _URGENT_RESCUE_CUES)
    urgent_affect = (affect_urgency or "").strip().lower() == "high"
    if urgent_cue or urgent_affect or needs_rescue:
        if urgent_cue:
            evidence.append(f"urgent_rescue:{urgent_cue}")
        if urgent_affect:
            evidence.append("urgent_rescue:affect_high_urgency")
        if needs_rescue:
            evidence.append("urgent_rescue:learner_state_needs_rescue")
        evidence.append(f"skill_state:{skill_state or 'unknown'}")
        return TeachingDepthDecision(
            level=0,
            label=_LEVEL_LABELS[0],
            rationale=(
                "Fix-first rescue: unblock the learner now; "
                "optionally offer one short practice afterwards."
            ),
            direct_answer_override=False,
            offer_light_practice=True,
            evidence=evidence,
        )

    ladder_state = (skill_state or "").strip().lower()
    level = _SKILL_LADDER.get(ladder_state, 1)
    if ladder_state:
        evidence.append(f"skill_state:{ladder_state}")
    else:
        evidence.append("skill_state:unknown")

    floor_cue = _matches(normalized_message, _LADDER_FLOOR_CUES)
    if floor_cue and level < 4:
        evidence.append(f"practice_request:{floor_cue}")
        level = 4

    definition_cue = _matches(normalized_message, _DEFINITION_CUES)
    if definition_cue:
        evidence.append(f"definition_question:{definition_cue}")
        if level > 1:
            level = 1

    return TeachingDepthDecision(
        level=level,
        label=_LEVEL_LABELS[level],
        rationale=f"Skill ladder position for {ladder_state or 'unknown'} evidence.",
        direct_answer_override=False,
        offer_light_practice=False,
        evidence=evidence,
    )
