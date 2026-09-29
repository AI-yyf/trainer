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
