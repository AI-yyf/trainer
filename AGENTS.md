# AGENTS.md — Trainer Engineering & Architecture Guide

Trainer is a VS Code learning coach built on a **Pi-inspired minimal runtime spine** paired with **Trainer-native pedagogical primitives**:

1. **Asymmetric Dual-Space Authority**:
   - `<ProjectRoot>` (learner's codebase): **strictly read-only** (`project_read`, `project_verify`). The learner authors project edits; Trainer inspects, diagnoses, and verifies.
   - `<LibraryRoot>` (managed study sandbox): **full autonomous read/write/edit/exec** (`library_read`, `library_write`, `library_exec`) with `.trash/` soft-delete recovery and automatic SQLite FTS5 indexing.
   - `library_exec` enforces OS-level sandboxing (macOS `sandbox-exec` Seatbelt / Linux `bwrap`) plus an in-process C-level PEP 578 `sys.addaudithook` guard and process-group cancellation (`os.killpg`).
2. **Pi-Style Harness & Prompt Discipline**:
   - `server/app/llm/prompts.py` places the session-invariant prefix (`build_static_coaching_prefix`) at byte 0 of `messages[0]` so LLM Prompt KV Caches stay warm across turns and skill activations.
   - `server/app/llm/harness.py` & `server/app/llm/agent_loop.py` split tool outputs into `{ llm_content, ui_details }`, apply 65%/35% Head+Tail truncation, feed real 4-protocol `ProviderUsage` (`OpenAI`, `Responses`, `Anthropic`, `Gemini`) into compaction, and support mid-batch `steering` interruption.
   - Streaming paths run with **zero holdback (`_stream_holdback_chars == 0`)** and O(1) tail checks so first-token latency stays minimal across `auto`, `guided`, `balanced`, and `direct` modes.
3. **Lean Frontend & Bundled Sidecar Parity**:
   - `extension/webview/tsconfig.json` compiles the full `src/` tree (`"include": ["src"]`).
   - Browser-only preview mocks (`browserSidecar.ts` / `browserPreviewHarness.ts`) are dynamically imported only outside VS Code so production Webview bundles stay lean.
   - Whenever files under `server/` change, mirror them into `extension/bundled/server/` via `npm run sync:server --prefix extension`.

## Repository Layout

- `server/app/` — FastAPI sidecar (`llm/`, `evaluator/`, `training/`, `memory/`, `resources/`, `sandbox/`, `skills/`).
- `extension/src/` — VS Code Extension Host lifecycle, commands, and sidecar process manager.
- `extension/webview/src/` — React Webview UI (Chat, Resources, Training/Plan drawer, Settings).
- `shared/src/` — Shared TypeScript types and cross-surface contracts.
- `remote-extension/` — Lightweight Remote-SSH workspace companion.

## Standard Verification Gates

```bash
# 1. Mirror server sources into extension/bundled/server
npm run sync:server --prefix extension

# 2. Python lint, static types, and backend unit/integration suite
server/.venv/bin/ruff check server/app server/tests
npm run verify:server-pyright
server/.venv/bin/pytest server/tests -q

# 3. Full TypeScript check (Webview + Extension), i18n, copy vocabulary, and production build
npm run check
npm run verify:i18n
npm run verify:copy-vocabulary
npm run build
```
