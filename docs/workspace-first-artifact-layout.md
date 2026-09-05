# Managed Artifact Layout

This note records the current Trainer storage behavior after moving Trainer-owned resource
artifacts into the sidecar-managed carrier root while keeping the active workspace path available
for source validation and user-project context.

Current managed slices:

- Search index:
  - sidecar `search-indexes/<workspace-id>/index.sqlite3`
  - no system-temp fallback remains; Trainer search now stays under the managed carrier root
- Optional local semantic/embeddings storage used by resource indexing:
  - sidecar `qdrant/`
- Inline resource materialization:
  - sidecar `inline-resources/<workspace-id>/`
- Sandbox-linked resource library:
  - sidecar `sandboxes/<workspace-id>/`
- Tier B sandbox preview artifacts for extracted document previews:
  - sidecar `previews/<workspace-id>/`
  - structured HTML / CSV / TSV / notebook / spreadsheet previews also materialize here
  - converted archive previews now also materialize here when Trainer can derive a markdown archive index
- Coach message typed parts now reuse requested resource artifacts:
  - indexed resource turns may emit `metadata.parts[].type = file_preview`
  - preview content prefers managed preview artifacts, then indexed fragments, then resource summaries
  - the same grounded resource/reference payload may also emit `metadata.parts[].type = citation`
  - citation parts project resource/background reference truth into the main coach message renderer
- Coach message typed parts now reuse active training routing state:
  - coached turns may emit `metadata.parts[].type = training_card`
  - card content is projected from workspace-local `active_training_card_routing`, not a separate chat-only cache
- Coach message typed parts now project safe coaching truth, not markdown-only summaries:
  - coached/review turns may emit `metadata.parts[].type = reasoning`
  - reasoning parts only contain safe redacted summaries from `decision_reason`, teaching observations, intervention strategy, and the current coach summary
  - coached/review turns may emit `metadata.parts[].type = checklist`
  - checklist parts reuse explicit failing checks, artifact verification items, and active training verification steps
- Coach message typed parts now project recent workspace-bound tool truth:
  - coached turns may emit `metadata.parts[].type = tool_call` and `metadata.parts[].type = tool_result`
  - tool parts currently reuse recent sandbox event ledger facts plus the shared workspace authority summary
  - result payloads keep `activeWorkspaceRoot`, permission level, ledger/checkpoint counts, and the latest authority operation visible inside the coach thread

Important boundaries:

- The explicit `activeWorkspaceRoot` remains the source-validation and user-project context boundary.
- Trainer-owned resource artifacts live under the managed carrier root, not inside the user project by default.
- Provider secrets still do not belong in the workspace.
- Resource sandbox deletion still flows through one checkpointed trash trail for managed artifacts.

Next alignment targets:

- Add migration helpers for legacy workspace-local `.trainer/...` resource artifacts.
- Expand preview artifact coverage beyond the current DOCX/PDF extracted-text path.
- Keep remote workspaces on the same carrier-root contract without mirroring whole trees back locally.
