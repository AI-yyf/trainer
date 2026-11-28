# AGENTS.md — Trainer Engineering & Architecture Guide

Trainer is a VS Code learning coach built on a **Pi-inspired minimal runtime spine** paired with **Trainer-native pedagogical primitives**:

1. **Asymmetric Dual-Space Authority**:
   - `<ProjectRoot>` (learner's codebase): **strictly read-only** (`project_read`, `project_verify`). The learner authors project edits; Trainer inspects, diagnoses, and verifies.
   - `<LibraryRoot>` (managed study sandbox): **full autonomous read/write/edit/exec** (`library_read`, `library_write`, `library_exec`) with soft-delete recovery (`trash/<timestamp>-<id>/` in the sandbox lane, `.trash/` in the library carrier lane) and automatic SQLite FTS5 indexing.
   - Outside both spaces the coach gets only `web_fetch` (network) and `learning_inspect` / `learning_action` (learning state). These 8 names are the complete tool surface; each takes an `action` argument.
   - `library_exec` runs **only under an OS kernel sandbox** (macOS `sandbox-exec` Seatbelt / Linux `bwrap`) and fails closed when neither exists — a bare `echo` is the sole exception, because the PEP 578 `sys.addaudithook` guard is ordinary Python inside the child's own process and cannot bound an interpreter. The kernel profile also refuses helpers that act through system daemons (`open`, `launchctl`, `security`, …) and keeps trash read-only; treat both the hook and the static command validator as defense-in-depth, never as the boundary.
   - Timeout and cancellation stop the whole process group (`os.killpg`, even after the leader exited) and drain its pipes for a bounded time; output is capped while it is read, and a stream that overruns the cap stops the process early.
2. **Pi-Style Harness & Prompt Discipline**:
   - The session-invariant prefix (`build_static_coaching_prefix`, defined in `server/app/llm/prompt_domains/messages_and_turn_signals.py` and re-exported by `llm/prompts.py`) sits at byte 0 of `messages[0]` so LLM Prompt KV Caches stay warm across turns and skill activations.
   - `server/app/llm/harness.py` & `server/app/llm/agent_loop.py` split tool outputs into `{ llm_content, ui_details }`, apply 65%/35% Head+Tail truncation, feed real 4-protocol `ProviderUsage` (`OpenAI`, `Responses`, `Anthropic`, `Gemini`) into compaction, and support mid-batch `steering` interruption.
   - Streaming paths hold back only an 8/12-character tail (`_stream_holdback_chars` in `llm/coaching_replies.py`: 8 for Chinese, 12 otherwise) so truncation retries stay invisible while deltas stream live; tail checks are O(1) across `auto`, `guided`, `balanced`, and `direct` modes.
3. **Lean Frontend & Bundled Sidecar Parity**:
   - `extension/webview/tsconfig.json` compiles the full `src/` tree (`"include": ["src"]`).
   - Browser-only preview mocks (`browserSidecar.ts` / `browserPreviewHarness.ts`) are reachable only through separate Vite entries (`vscode-preview.html`, the side panel, the test entry), never from the VS Code webview entry; `.vscodeignore` keeps their chunks out of the VSIX.
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
npm run verify:server-pyright  # pyright over server/app and server/tests: zero errors, no type: ignore
server/.venv/bin/pytest server/tests -q

# 3. Full TypeScript check (Webview + Extension), extension host tests, i18n, copy vocabulary, and production build
npm run check
npm run test:extension
npm run verify:i18n
npm run verify:copy-vocabulary
npm run build
```

Run each gate un-piped (or check `$pipestatus`): a trailing `| tail` hides a non-zero exit, and a piped `npm run test:extension` reported success while one test had failed.
