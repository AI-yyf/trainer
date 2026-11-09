# V4.1 P0-3 — Five-dimension capability evidence

Date: 2026-11-09  
Baseline: `faff052` + this change  
Status: **implemented at the projection/producer layer; real-provider and long-term retention acceptance remain pending**

## Contract

The skill projection now carries five capability dimensions:

| Dimension | Meaning | Accepted evidence |
| --- | --- | --- |
| `comprehension` | explain the principle and causal chain | controlled comprehension/theory answer |
| `implementation` | produce a working result | controlled file/command evaluation |
| `debugging` | locate, explain and fix a failure | controlled debugging-task evaluation |
| `transfer` | use the capability in a new context | controlled pass on a return card or explicit transfer evidence |
| `delayed_recall` | still recall after a retention interval | answered recall after a real delay |

Literature/language subjects keep their own vocabulary (`expression`,
`appreciation`) and also carry `delayed_recall`.

Ladder: `not_verified → assisted → independent → repeat_verified`, plus
`needs_review` after a qualified failure.

## Qualification rules

1. **Assisted** requires a controlled pass with an explicit hint/guided
   assistance level. A failed result never becomes assisted.
2. **Independent** requires a controlled pass with explicit no-assistance
   evidence (`none` or `independent`). Missing/unknown assistance stays visible
   in the drilldown but cannot advance the ladder.
3. **Repeat verified** requires distinct attempts; re-verifying the same
   attempt never counts twice.
4. **Transfer** requires the record's dimension to be `transfer` and an
   explicit cross-context fact. An implementation card that merely carries a
   scenario string is not transfer. A card whose learning phase is `return`
   is recorded as transfer when its controlled evaluation passes. Repeat
   transfer verification needs two distinct scenario/environment/constraint
   contexts.
5. **Delayed recall** requires:
   - an actual recall answer (`evidence_kind = recall`);
   - a stored FSRS elapsed interval of at least one day;
   - explicit assistance (independent or hinted);
   - a controlled recall result.
   Immediate answers, missing delays, code verification, "done"/"reviewed"
   actions and "I remembered" self-reports are visible evidence but cannot
   advance this dimension. A delayed failure produces `needs_review`.

## Real producers

- Card evaluation records the card's capability dimension
  (`implementation`, `debugging`, `comprehension`, or `transfer` for a return
  card) instead of treating every file check as implementation.
- A returned card maps to `transfer` with
  `transfer_metadata = {"source": "training_return"}`.
- Flashcard answers schedule FSRS and record a controlled recall attempt. The
  first immediate answer has delay `0` and cannot advance delayed recall; a
  later answer uses the scheduler's real `elapsed_days`.
- Theory-drill answers record an immediate `comprehension` check; a delayed
  theory answer uses `delayed_recall`.
- Each recall gets its own attempt id, so two delayed successes count as two
  distinct attempts while an active practice attempt is never resumed or
  closed by a recall.
- `review queue → done` only defers the queue. It no longer calls
  `process_mastery_review(GOOD)` because no recall answer occurred.
- `UnifiedEvidence` preserves `dimension`, `evidence_kind` and
  `recall_delay_days`, so LearnerState/Review readers can explain the same
  judgment.

## Evidence

- `server/tests/test_five_dimension_evidence.py`: 16 focused tests covering
  missing assistance, assisted vs independent, implementation failure not
  claiming debugging, incidental scenario not claiming transfer, distinct
  transfer contexts, immediate/missing-delay/wrong-kind recall, delayed recall
  ladder/failure/assisted, code verification not advancing recall, the real
  flashcard two-day flow, return-card transfer, theory-drill comprehension,
  review "done" not grading FSRS, attempt-store no-hint semantics and
  UnifiedEvidence fields.
- Updated existing tests for the five-dimension registry and profile labels.
- Full server suite: **3997 passed, 28 subtests passed** (8m00s).
- Full Playwright: **441 / 441 passed**; experience matrix **200 / 200 passed**.
- Extension tests: **passed** (120 projection/workbench tests included).
- `npm run check`: passed.

## Remaining gaps

- Real-provider and installed-VS-Code acceptance are not claimed; the gateway
  remained unavailable on 2026-11-09. Prior provider evidence stays at
  `4e41e0c`.
- A real two-to-four-week learner trial is still required for retention
  quality, repeated-error change and interruption tolerance.
- Transfer currently needs a returned card or explicit transfer metadata; a
  dedicated "new scenario" card type/UI is not yet built.
- The review intervention budget is the next P0 after this closure.
