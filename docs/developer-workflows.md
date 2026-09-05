# Trainer Developer Workflows

This repository is under active development with a **five-view React (Vite + Zustand) + FastAPI** architecture.

> Current sidebar IA source of truth: [`docs/ui-contract.md`](./ui-contract.md) with exactly `Coach / Plan / Resources / Training / Settings`.
> Historical three-view planning docs under `docs/plans/` are archival context only. If an older plan conflicts with the UI contract, follow `docs/ui-contract.md`.

## Source Of Truth

| What | Where |
|------|-------|
| Sidebar IA + view responsibilities | `docs/ui-contract.md` |
| UI expectations | `ui设计基准.md` and `ui设计基准.pdf` (repo root) |
| Cross-process contracts | `shared/src/protocol.ts`, `shared/src/models.ts`, `shared/src/tokens.ts` |
| Runtime architecture | `docs/architecture.md` |
| Code map | `AGENTS.md` |
| Verification matrix | `docs/verification.md` |

Coach transport reminder:
- Treat sync send routing as already intent-split: Coach/default turns use `/session/message`, non-Coach structured intents use `/turn`.
- Treat stream routing as intent-split in both preview and desktop paths: Coach/default turns use `/session/message/stream`, while structured Plan, Resources, and Training turns use `/turn/stream`.
- If you change Coach transport, update `extension/src/commands/sessionCommands.ts`, `extension/webview/src/lib/browserSidecar.ts`, server routes, and focused tests together.
- `metadata.parts` is the shared conversation truth surface. Normalize it in `shared/src/protocol.ts`; render current Coach message parts through `extension/webview/src/components/coach/CoachMessageParts.tsx` rather than assuming the older `components/parts/*` path is the live Coach entrypoint.

## Cross-Platform Notes (跨平台)

`.ps1` 脚本仍是 Windows PowerShell 的便利入口。Windows、macOS 和 Linux 均可直接使用下方的 Node 生命周期命令；它们会选择当前平台的 Python 虚拟环境路径。

| Windows 命令 | macOS / Linux 等价命令 |
|-------------|----------------------|
| `scripts/bootstrap.ps1` | `npm run bootstrap` |
| `scripts/dev.ps1` | `npm run dev` |
| `scripts/dev.ps1 -StartSidecar` | `npm run dev:sidecar` |
| `scripts/check.ps1` | `npm run verify` |
| `scripts/smoke.ps1` | `npm run smoke` |
| `server/.venv/Scripts/python.exe` | `server/.venv/bin/python` |

### Shell 差异注意

- 项目中所有代码路径引用（如 `shared/src/protocol.ts`）使用 Unix 风格斜杠 `/`，三平台通用
- Python `.venv` 路径在 Windows 上是 `Scripts/`，在 macOS/Linux 上是 `bin/`
- `npm run *` 命令三平台通用
- `npm test` 三平台通用
- `cd e2e && npx playwright test` 三平台通用

| Command | What it does |
|---------|-------------|
| `scripts/bootstrap.ps1` | Install all dependencies (npm + Python venv) |
| `scripts/dev.ps1` | Build webview + extension (tsc + Vite) |
| `scripts/dev.ps1 -StartSidecar` | Build + start FastAPI sidecar |
| `scripts/check.ps1` | TypeScript + (if venv) Python checks |
| `scripts/check.ps1 -Strict` | Fail on any skipped check |
| `scripts/smoke.ps1` | Probe manifests, builds, venv, ports |
| `scripts/smoke.ps1 -Strict` | Also requires sidecar health |
| `scripts/smoke.ps1 -TrainerTurnSmoke ...` | Run a live Coach-turn smoke against a real sidecar + OpenAI-compatible provider |
| `npm run build` | Root build (webview + extension only) |
| `npm run check` | Root typecheck only (TS, not Python) |
| `npm test` | Extension contract tests plus the full Python test suite |
| `npm run verify` | Portable build, TS checks, extension tests, Ruff, Pyright, and server tests |
| `npm run smoke:provider` | Run the provider echo/language-integrity smoke directly |
| `npm run smoke:trainer-turn` | Run the live Coach-turn continuity + learn-first routing smoke directly, including the zh-CN remote/debug/function-guidance routes |
| `npm run package:vsix` | Package installable VSIX |
| `npm run test:server` | Run all Python tests |
| `cd e2e && npx playwright test` | Run E2E test |

## Bootstrap

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

Notes:
- Installs `extension/` npm dependencies when `extension/package.json` exists
- Installs `extension/webview/` npm dependencies when `extension/webview/package.json` exists
- Creates `server/.venv` with all Python dependencies (Python 3.12+ required)
- Validates Python version is 3.12+ before creating virtualenv
- Supports `-UseUv` flag to use `uv sync --project server --extra dev` instead of pip
- Skips Python virtualenv if `server/app/main.py` does not exist

## Build

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
```

This builds:
1. Webview package (Vite with TypeScript) — outputs to `extension/webview/dist/`
2. Extension host (tsc) — outputs to `extension/dist/`

Use `-StartSidecar` to also start the FastAPI server after build.

### Portable lifecycle

The Node lifecycle commands are the cross-platform equivalent of the PowerShell
helpers. They keep the existing Windows scripts intact while resolving the correct
project virtualenv interpreter for Windows, macOS, or Linux.

```bash
npm run bootstrap
npm run dev
npm run dev:sidecar -- --auto-port
npm run smoke
npm run smoke:strict
```

## Verify

```powershell
# All checks (non-strict: reports SKIP for unready areas)
scripts/check.ps1

# Strict mode — fails on any area that can't run
scripts/check.ps1 -Strict
```

The check script runs:
1. `npm run check --prefix extension/webview` — webview typecheck
2. `npm run check --prefix extension` — extension typecheck
3. (if `server/.venv` exists) `ruff check app/` — Python lint
4. (if `server/.venv` exists) `pyright app/` — Python type analysis
5. `npm run test:server` — Python tests

For Coach streaming or recovery changes, also run:

- `npm run verify:coach-recovery --prefix extension`
- `npm run verify:webview-recovery --prefix extension`
- `node --test extension/tests/webviewBridge.test.js`

This launches the real browser preview, replays preview host messages, and verifies recovered notices, in-progress streaming UI, activity-strip refresh, and full coach-loop completion behavior.
The bridge test covers the extension-host lifecycle side: visible-view rehydration, empty-html recovery, and latest streaming snapshot delivery through `WorkbenchSidebarController`.

## Smoke Test

```powershell
# Basic smoke — checks manifests, builds, venv, probes ports
scripts/smoke.ps1

# Strict — same but requires sidecar health on known port
scripts/smoke.ps1 -Strict

# Probe specific port
scripts/smoke.ps1 -Port 8765

# Real Coach-turn smoke against a running sidecar
scripts/smoke.ps1 -TrainerTurnSmoke -TrainerTurnSmokeSidecarUrl http://127.0.0.1:8765 -TrainerTurnSmokeApiKey <key> -TrainerTurnSmokeBaseUrl <base-url> -TrainerTurnSmokeModel <model>
```

By default probes:
- Port **8765** (default sidecar port)
- Extension-managed range **34891-34911**

The smoke script checks:
- Repository manifests exist (package.json, pyproject.toml, etc.)
- Source readiness (extension.ts, main.py, webview main.tsx)
- Build outputs (webview dist, extension dist)
- Python virtualenv readiness (server/.venv)
- Port accessibility (sidecar health endpoint)

With `-TrainerTurnSmoke`, it also checks:
- `remote_workspace -> debug_loop -> function_guidance` fresh-lane continuity
- visible Coach replies for cross-lane contamination
- learn-first remote requests materializing a `practice` training card route
- zh-CN `remote_workspace`, `debug_loop`, and `function_guidance` replies and training-card copy staying localized during live learn-first routing

## Running Tests

### Python (59 test files, ~60k lines)

```bash
# All tests
npm run test:server

# Single test file
cd server && python -m pytest tests/test_api.py -v

# Single test
cd server && python -m pytest tests/test_api.py::test_something -v

# With coverage
cd server && python -m pytest tests/ -v --cov=app
```

Key test files:
- `test_api.py` (219117 lines) — API endpoint tests (note: extremely large, handle with care)
- `test_memory.py` (54574 lines) — Memory service tests
- `test_pedagogy.py` (61267 lines) — Pedagogy service tests
- `test_provider_service.py` (60407 lines) — Provider service tests
- `test_training_flow_integration.py` (33208 lines) — Training flow tests

### TypeScript (55 test files)

```bash
# Run all JS/TS tests
npm test

# Single test file
cd extension && npx jest tests/sessionCommands.test.js
```

### E2E (Playwright)

```bash
cd e2e && npx playwright test trainer.spec.js
```

The e2e test runs a black-box browser-based test against the Vite dev server. It requires `npm run dev` in `extension/webview/` to be running.

## Common Tasks

### Add a new command

1. Add command ID to `shared/src/commands.ts` (`trainerCommands` object)
2. Add command definition to `extension/package.json` (`contributes.commands`)
3. Create handler in `extension/src/commands/` (or extend existing)
4. Register handler in `extension/src/commands/index.ts`
5. Add to command catalog in `shared/src/commands.ts` (`trainerCommandCatalog`)
6. Wire in `extension/src/core/commandRegistry.ts`

### Add a new API endpoint

1. Add handler in `server/app/api/routers.py` (inside `build_router()`)
2. Wire through `TrainerRuntime` (`server/app/api/runtime.py`)
3. Add request/response types to `shared/src/protocol.ts`
4. Add Pydantic models to `server/app/core/models.py` if needed
5. Add test in `server/tests/`
6. Add webview-side handler in `extension/src/commands/` and `extension/webview/src/lib/`

### Add i18n key

1. Add key to `CopyKey` type in `extension/webview/src/lib/i18n/copy.ts`
2. Add or refine the locale text you want to localize; `en-US` remains the shared fallback for missing keys
3. Use `t()` function in components (from `useTranslation` hook)

## File Size Awareness

The following files are unusually large and should be split when practical:

| File | Lines | Recommendation |
|------|-------|---------------|
| `server/tests/test_api.py` | 219,117 | Split by endpoint domain |
| `server/app/api/routers.py` | 6,027 | Split into domain routers |
| `extension/webview/src/app/App.tsx` | 5,843 | Split main view renderers |
| `server/app/memory/service.py` | 4,468 | Split by sub-domain |
| `server/app/pedagogy/service.py` | 2,068 | Already partially split |
| `server/app/llm/provider_service.py` | 2,200 | Split provider methods |
| `extension/webview/src/styles.css` | 2,822 | Split by component domain |
| `extension/webview/src/components/resources/CoachResourcesView.tsx` | 80,814 | Split into sub-views |
| `extension/webview/src/components/settings/CoachSettingsView.tsx` | 62,537 | Split into tabbed panels |
| `extension/webview/src/components/training/CoachTrainingView.tsx` | 92,435 | Split by sub-mode |
