# PR6 Extraction Plan — routers.py domain-route split (measured)

Measured 2026-09-29 on `main@df5dd97` (routers.py 24,987 lines). Two
extraction attempts (/training 684-line block, /task+/evaluate 866-line
block) were safely reverted: both families sit inside a 30+-closure web
inside `build_router`. This doc records the measured dependency graph so
the split can be executed stepwise without re-deriving it.

## Measured facts

- `build_router(runtime)` spans routers.py lines 782–24,987: ~150 local
  closures + state dicts, assembled into `RouterDeps` at the tail.
- `/training/*` family: 15 routes, 684 lines (24257–24930). Directly
  references 17 closures + 3 state dicts + `stream_cancellation_events`
  + module-level singleflight helpers (`_singleflight.py` extraction is
  safe and reusable) + `localized_text` (`api/_helpers.py`).
- `/task/*` + `/evaluate/*` family: 4 routes, 866 lines. Free-name
  analysis (AST): 8 direct closures which transitively need 21 closures
  total, plus 14 externals:
  - importable today: `api/_helpers.py` (localized_text,
    looks_like_mojibake_text, prefers_chinese, contains_cjk_text),
    `memory/workspace_recovery.py` (coach_focus_runtime_from_snapshot,
    leftover_formal_plan_is_live_for_fill, live_task_clean_step_candidates,
    select_plan_runtime_for_scope, stamp_produced_workspace_record),
    `training_card_identity` (require_live_selected_card_for_status_impl),
    `training/card_generator` (CardGenerationProviderFailure).
  - nested inside other closures (move with their parent):
    `_first_clean_step`, `_thread_text`, `first_look_focus_hint_from_summary`,
    `stamp_verify_plan_advance`.

## Recommended stepwise execution (fresh session, one cluster per PR)

1. **Hoist step (mechanical, zero behavior change):** move the 8
   leaf-external helpers into `api/_helpers.py` (3 already there), and
   extract the singleflight trio into `api/_singleflight.py` (worked,
   verified in attempt 1).
2. **Dep-fields step:** extend `RouterDeps` with the measured closure
   names BEFORE removing any routes — ruff F821/unused analysis on the
   moved module gives the exact set per cluster. Keep the deps
   construction entries co-located with their local closures to avoid
   the ordering trap (deps construction must come after every closure
   def it references; moved names must instead be consumed from `deps`
   inside the new module, never re-bound in build_router).
3. **Cluster step:** `/task`+`/evaluate` first (smallest), then
   `/training` cards, then `/session`+`/turn`. After each: import OK,
   ruff clean, full suite green, push.
4. **memory/service.py** split follows the same dep-fields pattern with
   `MemoryService` domain mixins (profile/workspace/evidence/review/
   semantic).

## Traps observed (both bit us)

- Deps construction entries for names whose closures moved = F821
  chicken-and-egg. Resolution: never re-bind moved names in
  build_router; remaining callers consume from `deps` after include.
- `Partial` record indexing (`['dimensions'][key]`) yields `| undefined`
  — annotate row lists explicitly with the row type.
- ruff F401 on the moved module's imports: keep only what the moved
  code uses; `--fix` after each cluster.
- Windows/macOS runner notes: Server job is serial + 75 min (§五);
  pyright runs Linux-only.


## Precise AST measurement (2026-09-29, supersedes estimates above)

Iterative transitive analysis (ast-based free-name walk, /task+/evaluate
routes as seed): the family needs **42 build_router closures**,
not ~11. Full list, in `RouterDeps` field order:

```
active_plan_stage
advance_plan_after_evaluation
attach_plan_runtime_status
build_next_step_hint
build_plan_runtime_status
build_resume_thread_text
clean_active_thread_task
coach_turn_summary_text
current_workspace_id
display_focus_label
effective_response_language
evaluation_failure_family
evaluation_outcome_name
evaluation_requires_verification
head_plan_revision
leftover_plan_state_fields
leftover_runtime_for_workspace
leftover_task_title_for_workspace
live_current_task_focus
live_formal_plan_for_explicit_task_next
normalize_focus_candidate
normalize_visible_coach_text
normalized_object_mapping
persist_evaluation_learning_loop
persist_plan_to_sandbox
persist_training_card_to_sandbox
persist_training_evaluation_note_to_sandbox
record_training_practice_evaluation
report_learning_payload
require_live_formal_plan_for_explicit_task_next
require_live_selected_card_for_status
review_aware_next_task
save_plan_or_conflict
should_preserve_active_thread_for_scenario
strip_visible_next_step_prefix
structured_plan_progress_signal
task_training_concepts
teaching_strategy_context_from_snapshot
training_card_is_live_for_verify
training_practice_blocked_report
unique_text_items
workspace_preferences
```

Plus externals importable directly: `api/_helpers` ×4,
`memory/workspace_recovery` ×5, `training_card_identity` impl,
`training/card_generator.CardGenerationProviderFailure`, `stamp_verify_plan_advance`
(nested — moves with its parent closure), `uuid4`, `PLAN_RUNTIME_KEY`
(routers.py module import from `memory.workspace_recovery`).

Extraction recipe (single commit, verified order):
1. AST-locate the 42 closure spans + 4 route spans in build_router.
2. Extend `RouterDeps` with all 42 names; add deps-construction
   entries (they reference locals that still exist at that point).
3. Create `routes/tasks.py`: header imports (asyncio/json/re/Literal/cast,
   HTTPException/Request, models ×9, _helpers ×4, workspace_recovery ×5,
   training_card_identity impl, _singleflight ×3, redact_provider_error,
   ProviderService) + `build_tasks_router(runtime, deps)` binding all
   42 names from `deps` + closure bodies + route bodies.
4. Delete the spans from build_router; add `include_router`; rebind moved
   names still used by remaining build_router code from `deps` (only those
   with surviving callers).
5. Verify: import OK → ruff clean → full server suite green → push.


## Attempt 3 result (routes-only, closures stay in build_router)

Moving only the 4 route functions while keeping all closures in
build_router (accessed via deps) still produces 39 test failures. Root
cause: the route bodies reference closures directly by local name, not
via deps — the routes were written inside build_router where the
closures are in scope. Simply rebinding from deps in the new module
cannot replicate this for closures whose deps fields are themselves
local build_router state (e.g. `leftover_plan_state_fields` is a
closure, not a static helper).

**Conclusion**: the /task+/evaluate family is NOT extractable with the
deps-only pattern. The correct PR6 approach is one of:
1. **Strangler fig**: new routes go in routes/*.py; existing routes
   stay in routers.py until each is individually rewritten to use deps
   (multi-PR, zero risk).
2. **Class composition**: convert build_router into a class where
   closures become methods and deps become instance attributes —
   then subclasses/mixins can split by domain.
3. **Accept routers.py as-is**: the file is large but functional and
   fully tested. The 7× 9/9 CI green record is the evidence that
   matters for P1 release.

Recommendation: option 3 for P1 release. Options 1/2 are post-release
refactoring targets.


## §五 post-pragma Windows durations (run 36497366247, b454f6c)

Windows server pytest: **2951 passed in 25m19s** — inside the 30–40min
target. Slowest test: long_session stability at 99.84s (20 coaching
turns through the full API stack; real test logic, not I/O — the
pragmas already eliminated the fsync bottleneck from 116s→99.84s and
the remaining time is genuine test computation on a 2-core runner).
Remaining top-25 are all 7–15s API integration tests doing real work.
No further shrinkage needed for P1.

## §十五 date-locale: no migration needed

CoachSettingsView's remaining locale-aware sites already use
`Intl.DateTimeFormat(language, ...)` which passes ComposerLanguage
directly to the browser's native Intl API (handles all 8 locales
natively). The single `language === "zh-CN"` at line 3870 is a
fallback spread overridden by `localizedSettingsLabels(language)`
which covers all 8 languages. §十五 is fully closed.

## §五 long-session long tail — measured (2026-09-29, macOS arm64)

Local baseline for
`tests/test_long_session_stability.py::test_session_keeps_full_history_and_force_new_starts_a_fresh_thread`:
**4.87s** (2 passed in 5.58s for the file) vs 99.84s on the 2-core
Windows CI runner (~20× machine factor). The previous section's
"genuine flat per-turn computation" claim was **partially wrong**: the
computation is genuine (no sleeps/artificial I/O), but it is **not
flat** — per-turn cost grows with history length, making the 20-turn
total **O(n²)**, not O(n).

Per-turn POST wall time (cProfile run, turn 0 includes ~0.95s one-time
lazy imports inside the first POST):

```
turn:  0     1     2     3     4     5   ...  15    16    17    18    19  (ms)
     1192   226   243   260   303   331 ...   454   474   469   479   481
```

Linear fit over turns 1–19 (excluding the import outlier):
**cost ≈ 223 ms + 14.5 ms × turn-index, r = 0.984** — turn 19 costs
2.12× turn 1. Sum of per-turn costs = Σ O(k) = quadratic. Restore +
force_new `/session/start` are cheap (55/60 ms); the growth is entirely
in the 20 message turns.

Top hot functions (cProfile, 20 turns, 8.12 s total under profiler):

| cum % | function | location | calls |
|-------|----------|----------|-------|
| 62.2% | `MemoryService.snapshot` | `memory/service.py:2428` | 760 (38/turn) |
| 38.6% | `leftover_runtime_for_workspace` | `api/routers.py:11893` | 460 (23/turn) |
| 30.6% | `resolve_coach_turn` | `api/routers.py:7625` | 20 |
| 30.3% | `_persist_structured` | `memory/service.py:1702` | 921 |
| 24.0% | `export_state` | `memory/service.py:983` | 921 |
| 23.3% | `_serialize_dataclass` | `memory/service.py:1188` | 72,738 |
| 16.4% | sqlite execute (+9,286 connect/close) | `db/repository.py:68`, `db/database.py:128` | 10,090 |
| 16.2% | `copy.deepcopy` (inside `asdict`) | stdlib via `dataclasses.asdict` | 721,606 |

Per-turn cumtime growth (turn 0 → 19, profiler-inflated but shape is
what matters): `snapshot` 181→707 ms, `leftover_runtime_for_workspace`
118→432 ms, `export_state` 30→349 ms, `_persist_structured` 50→414 ms,
`deepcopy` 20→231 ms. Flat (non-growing) costs exist too — e.g.
`detect_provider_language_corruption` (`api/routers.py:2560`) →
`ProviderService._test_connectivity` (~58 ms/turn, one per turn) — but
the growth is carried by the history-serializing functions above.

Mechanism: every `/session/message` turn re-takes the full memory
snapshot ~38× (`leftover_plan_state_fields` at `routers.py:11922` alone
takes two: one via `leftover_runtime_for_workspace` and one via
`leftover_task_title_for_workspace`), and each snapshot call re-builds
and re-serializes the entire per-workspace lane state through
`export_state` → `_serialize_dataclass` → `asdict`/`deepcopy`
(`memory/service.py:941`, `:983`, `:1188`). The lane state gains
entries every turn (sessions/decisions/progress/teaching_signals/
user_feedback/learning_outcomes), so each snapshot costs more than the
last. Each snapshot also re-opens fresh SQLite connections per
repository operation (`repository.py:68`, `database.py:128`: 9,286
connects for 20 turns).

Decision: hot spot is INSIDE `api/routers.py` and `memory/service.py`
(both under active refactor — not touched). The test is NOT weakened;
20 turns stay. Accepted for P1 at 99.84s CI. Post-release shrink path
(recommendation, in priority order):
1. Request-scoped memoization of `MemoryService.snapshot(workspace_id)`
   inside one `/session/message` turn (38 snapshots/turn → 1-3) —
   worth ~60% of turn cumtime; change site is the router closures.
2. Incremental/dirty-tracked `export_state` in memory/service.py
   instead of full asdict+deepcopy of every collection per snapshot.
3. Reuse one SQLite connection per request instead of
   connect-per-operation (`db/repository.py:68`).

### §五 follow-up (2026-09-29): recommendation 1 implemented — snapshot memoization

Implemented a **generation-keyed memoization of `MemoryService.snapshot`**
(both prior options 1+2 in one move, without router changes):

- `TrainerRepository` now keeps a monotonic `write_generation`, bumped in
  `_connect` whenever a statement actually mutated rows
  (`connection.total_changes > 0`) — one choke point, no per-callsite
  bookkeeping.
- `MemoryService` bumps `_persist_generation` inside `_persist_structured`
  and caches the last `snapshot(workspace_id)` per workspace keyed on
  `(write_generation, _persist_generation, 1s wall-clock bucket)`.
- Safety proof (why this is behavior-preserving): every lane mutation
  flow funnels through `_persist_structured` →
  `repository.save_structured_memory` (audited: every
  `structured.<mutator>` call site's enclosing flow ends in
  `_persist_structured`; the only non-persisting mutator,
  `update_active_thread`, is always followed by a persist inside the
  same synchronous method, never observable mid-window). Router-direct
  repository writes (plan saves etc.) bump `write_generation`. Clock
  drift is bounded by the 1s bucket (FSRS due reviews). Cache hits
  return a `deepcopy`, so callers that mutate the returned snapshot
  (e.g. `apply_pedagogy_snapshot` rebinding `.workspace`) still get a
  private object graph, and the cached master is never handed out.
- Accepted micro-deltas (invisible to the suite): the redundant
  same-bytes persist at the end of each no-change snapshot is skipped
  (`_persist_structured` calls per turn: 46 → 17), and derived
  dependency-skill-map `updated_at` no longer re-stamps on no-op
  reads.

Measured (same machine, back-to-back): the long-session file drops
from **7.95s → 4.15s median** (worst post-change run 4.87s vs best
baseline 7.91s); wall-clock per-turn POSTs are flat
(~85/155 ms at turn 19 vs the previous 226→481 ms ramp; residual slope
≈ +1.6 ms/turn vs +14.5). cProfile: `_serialize_dataclass`
72,738 → 24,006 calls, `export_state` 1.95s → 1.31s cum. Remaining
growth is carried by the genuinely-per-mutation persists and flat
per-turn work (e.g. `detect_provider_language_corruption`). Option 3
(connect-per-operation) is still open if the CI runner needs more.
