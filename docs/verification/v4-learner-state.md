# V4.1 P0-2 — Unified Learner State projection

Date: 2026-11-09  
Baseline: `6951abb` + this change  
Status: **implemented as a workspace-scoped read projection; real-provider rerun pending gateway recovery**

## Contract

`server/app/learner_state.py` is the one read projection for a learner in one
workspace. It is not a new store and never writes:

| Fact | Owner (write) | Projection read |
| --- | --- | --- |
| Profile | `MemoryService.record_profile` / `TrainerRepository` | `TrainerRepository.get_profile` |
| Goal | `GoalService` | `GoalService.current` |
| Memory | `MemoryService` | `MemoryService.snapshot` |
| Mastery | `AttemptStore` + UnifiedEvidence projection | `training_skill_projection` dimensions |
| Evidence | attempt / handoff / memory evidence queue | `collect_unified_evidence` |
| Review | `ReviewScheduler` + FSRS training state | due count and due items |

Every fact is a `FactEnvelope` carrying `source`, `confidence`, `updated_at`
and workspace `scope`. `confidence` is `known`, `unknown` or
`insufficient_evidence`; missing facts are never fabricated. The snapshot is
explicitly read-only and the payload lists that limitation.

`GET /learner/state?workspace_id=...` returns this projection. It accepts a
session id as well, resolves through the same workspace resolver as the rest
of the API, and returns 503 instead of silently inventing a learner if the
service is unavailable.

## Wiring

- **Coach** (`api/coach_support.py`): builds one projection per turn and uses
  its profile, goal presence, memory snapshot and mastery dimensions for
  `infer_learner_state`, `AffectService` and `decide_teaching`. It no longer
  re-derives those facts from separate snapshots inside the turn.
- **Plan** (`api/routes/plan.py`): memory and profile reads go through
  `learner_memory_snapshot` / `learner_profile`. Profile is the projection's
  profile fact, not a parallel cache, so a corrected preference is visible on
  the next plan read.
- **Training** (`api/routers.py`, `api/router_support.py`): card preparation and
  training controls read memory/mastery from `learner_memory_snapshot`; the
  skill projection is the same object Review and Coach see.
- **Review** (`api/routes/memory.py`): `/memory/reviews` reads due reviews from
  the projection; `/evidence/records` uses the same `collect_unified_evidence`
  function the projection uses.
- **Runtime** (`api/runtime.py`): `TrainerRuntime` owns one
  `LearnerStateService`; the service wraps the existing repository, memory,
  goal and attempt services rather than creating parallel state.

Workspace scope is enforced in the service (`workspace_id_required`) and each
fact is read with that exact workspace id. A projection for workspace A cannot
contain B's profile, goal, memory, evidence or reviews.

## Evidence

- `server/tests/test_learner_state.py`: 8 focused tests covering the six facts,
  ownership map, workspace isolation/no leakage, unknown and
  `insufficient_evidence` semantics, preference correction visibility, the
  shared evidence collector, the projection-owned profile read, and the HTTP
  endpoint.
- Existing P0 regressions still pass: `test_turn_decision.py` (12),
  `test_affect.py`, `test_teaching_quality.py`,
  `test_training_skill_evidence.py`.
- Ruff passes on all changed Python modules.
- Full server suite: **3981 passed, 28 subtests passed** (8m05s).
- Bundled sidecar mirrored from `server/` with
  `npm run sync:server --prefix extension`; source/bundled parity checks pass.

## Boundaries

- This projection is a read contract, not a router-level gate. Formal task/plan
  endpoints still gate on the request's explicit intent; the Turn Decision is
  the teaching-decision authority.
- No real-provider or installed-GUI PASS is claimed for this change. The
  gateway was returning SSL/503 on 2026-11-09; prior real-provider evidence
  remains at commit `4e41e0c`.
- Five-dimension mastery, FSRS recall grading/intervention budget, resources
  and project teaching, and the long-term trial remain pending.
