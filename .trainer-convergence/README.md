# Trainer Convergence Workspace

Persistent working state for the autonomous convergence loop.

- `product-contract.md` — locked product positioning, v2.1 (2026-11-21). Changes only through its decision log (§11).
- `architecture-contract.md` — standing architecture constraints.
- `design-contract.md` — locked design system and UX rules.
- `issue-registry.json` — the single source of truth for open defects.
- `task-dag.json` — dependency graph for the current wave.
- `acceptance-matrix.json` — release gates and their real evidence.
- `run-state.json` — current loop checkpoint (safe to resume from).
- `handoff.md` — what a fresh session must know.

Rules:
- Task IDs are stable and never reused for a different defect.
- Only the master marks tasks DONE after real verification.
- No plaintext secrets, tokens or user content in these files.
