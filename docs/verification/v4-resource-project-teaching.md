# V4.1 P1 — Resources / project analysis / Skill teaching linkage

Date: 2026-11-09  
Baseline: `102619d` + this change  
Status: **implemented on the existing resource/project/skill stack; real-provider and installed-VS-Code acceptance remain pending**

## Resource → teaching evidence

The resource library already produced canonical Markdown, trusted knowledge
fragments and resource-based training cards. The missing return path was
provenance: a card-bound verification did not cite the resource version it was
built from.

Now `record_executed_training_evidence` resolves the card's `resource_id`
server-side and records the current:

- `resource_version_id`
- `resource_content_hash`
- `resource_location`

If the resource is no longer present, the evidence does not invent a version;
it records an explicit `resource version unavailable` limitation. The
capability projection still requires controlled execution, so a citation alone
never advances mastery.

## Resource change invalidation

On `/resource/index`, the version store's current content hash is compared with
earlier citations:

- evidence pinned to an older hash becomes `source_stale`
  (`resource_version_changed`), with `is_current = false`;
- stale evidence stays visible for audit but is excluded from
  `project_skills`, so an old verification cannot keep a capability "verified";
- a same-hash re-index clears the stale flag;
- new verification against the new version records a new live citation.

`UnifiedEvidence.verified` is false for stale or deleted sources.

## Project knowledge Skill lifecycle

Distilled project skills already carried `source_resource_id`, commit/branch,
workspace scope, version and usage facts. They now also pin
`source_content_hash`.

- A resource content change marks the matching project skill `stale`,
  deactivates it and excludes it from agent selection.
- The old body is retained for audit; status reads `stale`.
- Re-distillation (`/project/distill` / project import) clears staleness,
  restores activation and advances version only when the content/commit
  changed.
- Skill usage remains a usage fact (`usage_count`, `applied_count`,
  last evidence), never learner mastery.

## Existing teaching links preserved

- Resource ingest → canonical Markdown, knowledge fragments, teaching assets,
  workspace understanding and resource-based cards.
- Resource digest → concept cards, practice questions, examples and common
  pitfalls (on demand; content-hash cached).
- Project import → symbol index / overview / call graph / analysis adapters →
  knowledge skill + study-guide teaching asset linked to the library, Coach and
  learning.
- Skill runtime → condition-trigger selection, progressive body load,
  permission-preserving guidance block, usage feedback.

## Evidence

- `server/tests/test_resource_project_teaching.py`: 7 focused tests covering
  card citation of the current resource version, stale evidence exclusion,
  same-hash restore, project-skill stale/reactivate, a real re-index
  integration that stales evidence and skill together, and usage-feedback
  honesty.
- `server/tests/test_project_distill.py`: now asserts the distilled skill pins
  the resource content hash.
- Resource/project/skill/evidence focused suite: **117 passed**.
- Full server suite: **4023 passed, 28 subtests passed** (8m49s).
- Full Playwright: **441 / 441 passed**.
- Extension tests and `npm run check`: passed.

## Remaining gaps

- Real-provider grounded teaching, installed-VS-Code journeys and a multi-week
  learner trial are still pending; no real-model PASS is claimed.
- Large-repository incremental analysis and cross-language symbol binding
  remain the next project-analysis depth items.
