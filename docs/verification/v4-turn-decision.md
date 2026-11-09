# V4.1 P0-1 — Unified Turn Decision

Date: 2026-11-09  
Baseline: `852faa1` + this change  
Status: **implemented at the teaching-decision layer; real-provider rerun pending gateway recovery**

## Contract

`server/app/pedagogy/turn_decision.py` is the single authority for one turn's
lane and permissions. Other modules supply facts:

| Fact source | Fact |
| --- | --- |
| `sendIntelligence.ts` | requested intent + `intentSource` (`explicit` / `inferred` / `none`) |
| Goal / profile | active goal |
| Skill projection / evidence | trusted capability evidence |
| Pedagogy | onboarding needed, scenario/focus |
| Affect | rescue/reassurance/recovery |
| FSRS / memory | due review count and needs-review |

The decision returns `mode` (`chat`, `clarify`, `direct_answer`, `teach`,
`practice`, `review`, `plan`), source, confidence and explicit permissions:
`allow_question`, `allow_formal_task`, `allow_formal_plan`, `allow_review`,
`may_interrupt`.

## Hard constraints

1. Ordinary chat never mints a formal task, training card or learning plan.
2. An explicit direct-answer request wins over stored teaching preferences:
   no quiz, no exercise, no forced plan.
3. Formal practice/plan starts only from an explicit request. A due review may
   be proactive only when it is due, affect permits it, and the learner is not
   in a blocked/focused activity.
4. Unknown intent stays conversational (`chat`, confidence `unknown`); no
   mastery or task is invented.

## Wiring

- `sendIntelligence.ts` now reports `intentSource`; it no longer lets an
  inferred natural-language intent pretend to be an explicit formal action.
- `SessionMessageRequest` carries `intent_source`; the extension host forwards
  it on both stream and non-stream routes.
- `PedagogyService.decide_teaching` builds `TurnFacts`, calls `decide_turn`,
  and exposes the decision on `TeachingDecision` (`turn_mode`, `turn_source`,
  `turn_confidence`, `turn_allow_*`, `turn_may_interrupt`).
- `TeachingDepth` remains a strategy reference; a direct-answer override and
  chat/unknown lanes can no longer leave contradictory question/exercise/plan
  flags.
- `AffectService` only supplies affect; due-review count no longer determines
  frustration (previous increment).

## Evidence

- `server/tests/test_turn_decision.py`: 12 focused tests, including
  direct-answer, inferred-task, explicit practice/review/plan, proactive review
  interruption, onboarding intake, unknown and rescue.
- `server/tests/test_affect.py`: backlog does not change affect; explicit
  direct request does not raise frustration.
- `server/tests/test_teaching_quality.py`: missing assistance is unknown, not
  independent.
- `server/tests/test_training_skill_evidence.py`: missing assistance cannot
  advance the skill ladder.
- Full server suite: **3973 passed**.
- Extension tests: **passed** (including `sendIntelligence` source and host
  forwarding).
- Full Playwright: **441 / 441 passed**.
- VSIX rebuilt.

## Remaining gaps

- Route-level formal task/plan endpoints still use the explicit `intent` field
  as their gate; the turn contract is the teaching-decision authority, not yet
  a single request-router gate.
- Real-provider rerun on 2026-11-09 was blocked by `linksub.fun` SSL/503; no
  real-model PASS is claimed for this change. Prior successful provider
  evidence remains at commit `4e41e0c`.
- The wider V4.1 work (LearnerState projection, five-dimension evidence, FSRS
  recall grading, resources-to-teaching, long-term trial) remains pending.
