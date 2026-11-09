# V4.1 P0-4 — FSRS recall grading and intervention budget

Date: 2026-11-09  
Baseline: `6b5ac9b` + this change  
Status: **implemented at the scheduling/decision layer; real-provider and multi-week retention acceptance remain pending**

## Recall evidence grading

A recall answer is graded from the observed answer and assistance, never from
a generic pass flag:

| Observation | FSRS grade | Capability effect |
| --- | --- | --- |
| incorrect | `again` | delayed failure can mark `needs_review` |
| correct with no help | `good` | may advance `delayed_recall` after a real delay |
| correct with a hint | `hard` | may advance only the assisted rung |
| no answer / `done` / `reviewed` | no grade | **no** FSRS update and **no** recall evidence |

The grade is persisted on the evidence record (`recall_rating`), not only in
the in-memory scheduler. Code verification still schedules its own practice
card, but it cannot create a recall grade or advance `delayed_recall`.

## Intervention budget

`server/app/memory/review_intervention.py` is one pure decision over the
workspace's existing memory dict. It does not create a parallel store.

| Situation | Interrupt? | Visible review items |
| --- | --- | --- |
| explicit refusal (“not now”, “稍后”) | no | 1 curated item |
| busy / debugging / focused message | no | 1 curated item |
| focused thread with a blocker | no | normal ranked head (related review stays available in Learning) |
| same session already received a proactive offer | no | normal list |
| another session within 4 hours of an offer | no | normal list |
| long offline (≥ 7 days) | yes, once | 1 highest-value item, forced to `due` |
| normal due review | yes, one offer | up to 4 ranked items |
| no due reviews | no | none |

Facts persisted in the existing workspace memory:

- `last_active_at` — real turn activity, used for the long-offline window;
- `review_intervention.last_offer_at` / `last_offer_session_id` — one nudge
  per session plus a four-hour cross-session cooldown;
- `review_intervention.refused_until` — a 12-hour refusal cooldown;
- `review_intervention.last_refusal_*` / `last_engaged_at` — audit facts.

Queue actions participate in the same facts: `skip`/`snooze` record a refusal;
`accept`/`reset`/`done` record engagement and clear the refusal. `done` still
does not grade recall because no answer was observed.

The due-review scheduler applies the visible-item budget after the existing
four-item/plan-slot ranking, so a plan checkpoint keeps its reserved slot while
long-offline/refusal users see one item.

## Wiring

- `ReviewScheduler.derive_due_reviews` — applies the visible-item budget.
- `coach_support` — computes the turn budget before `decide_teaching`, records
  a refusal/busy signal, marks activity, and records a proactive offer only
  when the Turn Decision actually allows an interruption.
- `PedagogyService.decide_teaching` — accepts the budget as
  `intervention_allowed` / `intervention_reason` and exposes
  `intervention_blocked:<reason>` in decision evidence.
- `TurnDecision` — already requires due reviews + intervention permission +
  no focused activity; the budget now makes those permissions real.
- `MemoryService` — `record_review_offer`, `record_review_refusal`,
  `record_review_engagement`, `mark_workspace_active`.
- `recall_evidence` — grades again/hard/good and passes the grade to FSRS.

## Evidence

- `server/tests/test_review_intervention.py`: 18 failure-first tests covering
  refusal/busy messages, normal questions not misread as refusal, one offer per
  session, cross-session cooldown, focused/blocked thread, long-offline
  curation, scheduler caps, persistence/engagement, queue skip/accept,
  recall-grade mapping, a real flashcard grade, and Turn Decision blocking.
- Existing review scheduler/memory/FSRS/attempt tests remain green.
- Full server suite: **4016 passed, 28 subtests passed** (10m13s).
- Full Playwright: **441 / 441 passed**.
- Extension tests and `npm run check`: passed.

## Remaining gaps

- Real-provider rerun and installed-VS-Code acceptance are still blocked by the
  gateway and require the final delivery stage.
- The two-to-four-week learner trial is still required to validate actual
  interruption tolerance and retention; simulated-clock tests are not a
  substitute.
