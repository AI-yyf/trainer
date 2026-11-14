"""One turn decision: explicit request, learner state and evidence are facts.

The coach has one natural conversation entry. Modules such as send-intent
analysis, goals, memory, affect and teaching depth provide facts; this module
is the single authority that decides what this turn is allowed to do.

Hard constraints:
1. Ordinary chat never mints a formal task, training card or learning plan.
2. An explicit user request outranks a stored teaching preference. "Direct
   answer" means no quiz and no forced practice.
3. Teaching may be proactive, but a formal practice/goal/plan flow starts only
   when the learner asked for it. Review may be proactive when it is due and
   the learner is not in a blocked/focused activity.
4. Unknown is an answer: when intent, affect or mastery cannot be inferred,
   the decision stays conversational and does not invent a state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

TurnMode = Literal["chat", "clarify", "direct_answer", "teach", "practice", "review", "plan"]
TurnSource = Literal[
    "explicit_user",
    "learner_state",
    "goal",
    "evidence",
    "review_due",
    "default",
    "unknown",
]
TurnConfidence = Literal["known", "unknown"]
IntentSource = Literal["explicit", "inferred", "none"]

_DIRECT_ANSWER_PATTERN = re.compile(
    r"(直接(告诉|说|给|回答)|不要反问|别反问|别问我|只要答案|把代码给我|"
    r"just tell me|tell me directly|give me the (direct )?answer|no questions|"
    r"don'?t quiz me|stop asking)",
    re.IGNORECASE,
)
_PRACTICE_PATTERN = re.compile(
    r"(带我练|给我(出|一个)?练习|给我出.{0,4}题|出一个练习|出题|练习一下|"
    r"give me an exercise|give me a practice|let me practice|quiz me on|"
    r"let'?s practice|ponme un ejercicio|donne-moi un exercice|gib mir eine übung|"
    r"練習問題を一問出して|연습 문제를 한 개 내|me dê um exercício)",
    re.IGNORECASE,
)
_REVIEW_PATTERN = re.compile(
    r"(^复习(?:一下|上次|之前)?|(?:帮我|带我|我想|开始|一起|继续|请|来)复习|考考我|帮我回忆|"
    r"review (me|what i learned)|spaced repetition|quiz me for review|"
    r"help me recall)",
    re.IGNORECASE,
)
_ACTION_REFUSALS = {
    "practice": re.compile(
        r"(?:不要|不用|别|先不|不想|不是要).{0,12}(?:练习|出题|训练)|"
        r"\b(?:don['’]t|do not|no|skip)\s+(?:give me (?:an? )?|start )?(?:practice|exercise|quiz)",
        re.IGNORECASE,
    ),
    "review": re.compile(
        r"(?:不要|不用|别|先不|不想|不需要|不是要).{0,12}(?:复习|回忆|考我)|"
        r"\b(?:don['’]t|do not|no|skip|not now for)\s+(?:start |do )?(?:review|recall|spaced repetition)",
        re.IGNORECASE,
    ),
    "plan": re.compile(
        r"(?:不要|不用|别|先不|不想|不需要|不是要).{0,12}(?:学习计划|制定计划|生成计划|做计划)|"
        r"\b(?:don['’]t|do not|no|skip)\s+(?:(?:create|generate|make|build) (?:a )?)?(?:learning )?plan",
        re.IGNORECASE,
    ),
}
_QUOTED_TEXT = re.compile(r'`+[^`]*`+|“[^”]*”|「[^」]*」|"[^"]*"')
_CLAUSE_BOUNDARY = re.compile(
    r"[,，。！？!?；;\n]+|(?:但是|不过|而是|但(?=我|今天|现在|请|可以))|\b(?:but|instead)\b",
    re.IGNORECASE,
)
_HABITUAL_CONTEXT = re.compile(r"平时|通常|一贯|以往|\busually\b|\bnormally\b", re.IGNORECASE)
_REPORTED_CONTEXT = re.compile(
    r"^(?:为什么|为何|什么是|如何|怎么|这[段份篇]|文档|材料|原文|他[说问]|她[说问]|"
    r"why\b|what\b|how\b|the (?:document|article|book)\b|(?:he|she|they) (?:said|wrote)\b)",
    re.IGNORECASE,
)
_TEACH_PATTERN = re.compile(
    r"(\?|？|什么|为什么|怎么|如何|解释|原理|区别|学习|研究|方向|项目|实现|调试|错误|"
    r"论文|概念|定义|举例|帮我看看|看看这个|"
    r"\bwhat\b|\bwhy\b|\bhow\b|\bexplain\b|\bimplement\b|\bdebug\b|"
    r"\bproject\b|\bconcept\b|\blearn\b|\bresearch\b|\bpaper\b|"
    r"\breview this (code|change|file)\b)",
    re.IGNORECASE,
)
_PLAN_PATTERN = re.compile(
    r"(制定.{0,6}(学习)?计划|生成.{0,6}(学习)?计划|重排.{0,6}计划|"
    r"plan my learning|create a learning plan|generate a learning plan|"
    r"build a learning plan)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class TurnFacts:
    """Facts supplied by the other modules. This object makes no decisions."""

    message: str
    requested_intent: str = "coach"
    intent_source: IntentSource = "explicit"
    answer_mode: str | None = None
    needs_rescue: bool = False
    needs_review: bool = False
    due_review_count: int = 0
    has_active_goal: bool = False
    has_trusted_evidence: bool = False
    activity_in_progress: bool = False
    intervention_allowed: bool = True
    intervention_reason: str = ""
    onboarding_needed: bool = False


@dataclass(slots=True)
class TurnDecision:
    mode: TurnMode
    source: TurnSource
    confidence: TurnConfidence
    reason: str
    allow_question: bool = False
    allow_formal_task: bool = False
    allow_formal_plan: bool = False
    allow_review: bool = False
    may_interrupt: bool = False
    evidence: list[str] = field(default_factory=list)
    refused_actions: frozenset[str] = field(default_factory=frozenset)


def _matches(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def _action_cues(message: str) -> tuple[dict[str, str], frozenset[str]]:
    cues: dict[str, str] = {}
    refused: set[str] = set()
    for clause in _CLAUSE_BOUNDARY.split(_QUOTED_TEXT.sub(" ", message)):
        clause = clause.strip()
        if _HABITUAL_CONTEXT.search(clause) or _REPORTED_CONTEXT.match(clause):
            continue
        for action, pattern in (
            ("direct", _DIRECT_ANSWER_PATTERN),
            ("practice", _PRACTICE_PATTERN),
            ("review", _REVIEW_PATTERN),
            ("plan", _PLAN_PATTERN),
        ):
            refusal = _ACTION_REFUSALS.get(action)
            if refusal is not None and refusal.search(clause):
                refused.add(action)
                cues.pop(action, None)
            elif cue := _matches(pattern, clause):
                refused.discard(action)
                cues[action] = cue
    return cues, frozenset(refused)


def decide_turn(facts: TurnFacts) -> TurnDecision:
    """Return the single decision for one turn.

    ``requested_intent`` is only a fact. An inferred intent is never enough to
    enter a formal practice/plan flow; that needs an explicit request.
    """

    message = " ".join(str(facts.message or "").split())
    explicit_intent = facts.intent_source == "explicit"
    cues, refused = _action_cues(message)
    evidence = [f"explicit_{action}_refusal" for action in sorted(refused)]

    direct_cue = cues.get("direct")
    prefers_direct = str(facts.answer_mode or "").strip().lower() == "direct"
    if direct_cue:
        evidence.append(f"direct_answer_request:{direct_cue}")

    practice_cue = cues.get("practice")
    explicit_practice = "practice" not in refused and (bool(practice_cue) or (
        explicit_intent and facts.requested_intent in {"task", "next_task"}
    ))
    if practice_cue:
        evidence.append(f"explicit_practice_request:{practice_cue}")
    elif explicit_practice:
        evidence.append(f"explicit_practice_intent:{facts.requested_intent}")

    review_cue = cues.get("review")
    explicit_review = "review" not in refused and (bool(review_cue) or (
        explicit_intent and facts.requested_intent == "review"
    ))
    if review_cue:
        evidence.append(f"explicit_review_request:{review_cue}")
    elif explicit_review:
        evidence.append("explicit_review_intent:review")

    plan_cue = cues.get("plan")
    explicit_plan = "plan" not in refused and (bool(plan_cue) or (
        explicit_intent and facts.requested_intent == "plan"
    ))
    if plan_cue:
        evidence.append(f"explicit_plan_request:{plan_cue}")
    elif explicit_plan:
        evidence.append("explicit_plan_intent:plan")

    # 1. "Just tell me" is the strongest constraint: answer, no quiz, no task.
    if direct_cue and not (practice_cue or review_cue or plan_cue):
        return TurnDecision(
            mode="direct_answer",
            source="explicit_user",
            confidence="known",
            reason="The learner explicitly asked for a direct answer.",
            allow_question=False,
            allow_formal_task=False,
            allow_formal_plan=False,
            allow_review=False,
            may_interrupt=False,
            evidence=evidence,
            refused_actions=refused,
        )

    # 2. Formal practice starts only from an explicit request (or explicit
    #    task/next-task action), never from an inferred chat phrase.
    if explicit_practice:
        return TurnDecision(
            mode="practice",
            source="explicit_user",
            confidence="known",
            reason="The learner explicitly asked to practice.",
            allow_question=True,
            allow_formal_task=True,
            allow_formal_plan=False,
            allow_review=False,
            may_interrupt=False,
            evidence=evidence,
            refused_actions=refused,
        )

    # 3. Formal review can be explicit; a due review may also be proactive
    #    when the learner is not in a blocked/focused activity.
    if explicit_review:
        return TurnDecision(
            mode="review",
            source="explicit_user",
            confidence="known",
            reason="The learner explicitly asked for review.",
            allow_question=True,
            allow_formal_task=False,
            allow_formal_plan=False,
            allow_review=True,
            may_interrupt=False,
            evidence=evidence,
            refused_actions=refused,
        )

    # 4. Formal learning plans only from an explicit plan request.
    if explicit_plan:
        return TurnDecision(
            mode="plan",
            source="explicit_user",
            confidence="known",
            reason="The learner explicitly asked for a learning plan.",
            allow_question=True,
            allow_formal_task=False,
            allow_formal_plan=True,
            allow_review=False,
            may_interrupt=False,
            evidence=evidence,
            refused_actions=refused,
        )

    # 5. Rescue is fix-first; it never mints a task/plan and does not quiz.
    if facts.needs_rescue or (prefers_direct and not facts.activity_in_progress):
        evidence.append("learner_state:needs_rescue" if facts.needs_rescue else "direct_answer_mode")
        return TurnDecision(
            mode="direct_answer",
            source="learner_state",
            confidence="known",
            reason=(
                "The learner is blocked; fix the immediate issue before teaching."
                if facts.needs_rescue else "The learner prefers a direct answer."
            ),
            allow_question=False,
            allow_formal_task=False,
            allow_formal_plan=False,
            allow_review=False,
            may_interrupt=False,
            evidence=evidence,
            refused_actions=refused,
        )

    teach_cue = _matches(_TEACH_PATTERN, message)
    if facts.due_review_count > 0 and not facts.intervention_allowed:
        evidence.append(
            f"intervention_blocked:{facts.intervention_reason or 'policy'}"
        )

    # 5b. An unbuilt relationship/context needs one intake question before
    #     teaching or review; it must not mint a task or plan.
    if facts.onboarding_needed:
        evidence.append("learner_state:onboarding_needed")
        return TurnDecision(
            mode="clarify",
            source="learner_state",
            confidence="known",
            reason="Build the relationship context with one focused intake question.",
            allow_question=True,
            allow_formal_task=False,
            allow_formal_plan=False,
            allow_review=False,
            may_interrupt=False,
            evidence=evidence,
            refused_actions=refused,
        )

    # 6. Proactive review is allowed only when it is due, the learner has not
    #    just started a focused/debugging activity, affect permits it, and the
    #    turn is not an explicit teaching question. A principle question is
    #    more urgent than a background review.
    if (
        not teach_cue
        and "review" not in refused
        and facts.needs_review
        and facts.due_review_count > 0
        and facts.intervention_allowed
        and not facts.activity_in_progress
    ):
        evidence.extend(
            [
                "learner_state:needs_review",
                f"review_due:{facts.due_review_count}",
            ]
        )
        return TurnDecision(
            mode="review",
            source="review_due",
            confidence="known",
            reason="A due review can be offered without interrupting a blocked activity.",
            allow_question=True,
            allow_formal_task=False,
            allow_formal_plan=False,
            allow_review=True,
            may_interrupt=True,
            evidence=evidence,
            refused_actions=refused,
        )

    # 7. A concrete goal or trusted evidence supports teaching, not a formal
    #    task/plan flow.
    if facts.has_active_goal or facts.has_trusted_evidence:
        source: TurnSource = "goal" if facts.has_active_goal else "evidence"
        evidence.append(f"turn_context:{source}")
        return TurnDecision(
            mode="teach",
            source=source,
            confidence="known",
            reason="There is enough learning context to teach this turn.",
            allow_question=True,
            allow_formal_task=False,
            allow_formal_plan=False,
            allow_review=False,
            may_interrupt=False,
            evidence=evidence,
            refused_actions=refused,
        )

    # 8. A substantive question or discussion is teachable without inventing
    #    mastery, a task or a plan. This keeps natural questions from being
    #    misread as an empty chat or as a formal learning flow.
    if teach_cue:
        evidence.append(f"turn_context:teach:{teach_cue}")
        return TurnDecision(
            mode="teach",
            source="default",
            confidence="known",
            reason="The learner is asking to understand or discuss something.",
            allow_question=True,
            allow_formal_task=False,
            allow_formal_plan=False,
            allow_review=False,
            may_interrupt=False,
            evidence=evidence,
            refused_actions=refused,
        )

    # 9. No usable signal: stay conversational instead of inventing a state.
    evidence.append("turn_context:unknown")
    return TurnDecision(
        mode="chat",
        source="unknown",
        confidence="unknown",
        reason="No explicit learning request, goal or trusted evidence was found.",
        allow_question=False,
        allow_formal_task=False,
        allow_formal_plan=False,
        allow_review=False,
        may_interrupt=False,
        evidence=evidence,
        refused_actions=refused,
    )
