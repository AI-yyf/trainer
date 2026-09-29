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
