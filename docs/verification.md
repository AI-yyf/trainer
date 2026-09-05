# Trainer Verification Matrix

## Automated Verification

| Area | Command | Current behavior | Turns green when |
| --- | --- | --- | --- |
| **Webview typecheck** | `npm run check --prefix extension/webview` | Runs the real TypeScript webview check | Webview deps installed, app type-safe |
| **Webview production bundle** | `npm run build --prefix extension/webview` | Builds the Vite bundle for the extension host | Webview manifest, deps, entrypoint aligned |
| **Extension host typecheck** | `npm run check --prefix extension` | Runs tsc for the extension host | Extension source type-safe |
| **Extension build** | `npm run build --prefix extension` | Compiles TS to `dist/` | Extension source compiles without errors |
| **Coach route contract (desktop send)** | `node --test extension/tests/sessionMessageRoute.test.js` | Verifies non-stream extension sends split by intent | `/session/message` and `/turn` usage matches `sessionCommands.ts` |
| **Coach route contract (browser preview)** | `node --test extension/tests/browserSidecar.test.js` | Verifies preview sync/stream route split and adapter behavior | Browser preview transport matches the documented contract |
| **Coach visibility recovery (extension host)** | `node --test extension/tests/webviewBridge.test.js` | Verifies `WorkbenchSidebarController` rehydrates visible views with the latest host truth | Empty-html recovery, healthy visibility re-sync, and recovered streaming snapshots stay aligned with current host state |
| **Coach recovery loop (browser preview)** | `npm run verify:webview-recovery --prefix extension` | Launches the real preview and replays recovered + live host messages | Recovered notices, in-progress streaming bubble, agent activity strip, patch refresh, and loop completion all stay truthful |
| **Coach message parts e2e** | `cd server && python -m pytest tests/test_session_agent_e2e.py -q` | Verifies assistant responses can carry structured `metadata.parts` through the sidecar path | Typed message parts remain available to the UI adapters |
| **i18n copy coverage** | `node --test extension/tests/i18nCopyCompleteness.test.js` | Verifies all 8 UI languages resolve every key through the shared en-US fallback and keep direct values non-empty | Translator coverage stays complete across zh-CN/en-US/es-ES/fr-FR/de-DE/ja-JP/ko-KR/pt-BR |
| **WorkbenchSnapshot contract** | `cd server && python -m pytest tests/test_workbench_snapshot_contract.py -q` | Verifies the shared snapshot surface stays aligned with the server model envelope | Public snapshot fields remain synchronized for cross-language evolution |
| **Root build** | `npm run build` | Webview + extension host | Both TS projects compile |
| **Root check** | `npm run check` | TypeScript typecheck (no Python) | Both TS projects type-safe |
| **Server lint** | `cd server && ruff check app/` | Lint check all Python source | Ruff passes |
| **Server type analysis** | `cd server && run pyright app/` | Static type analysis | Pyright passes |
| **Server tests** | `npm run test:server` | Portable root runner for the full Python suite | It passes in a recorded Windows, macOS, or Linux target job |
| **Portable full verification** | `npm run verify` | Node-driven build, TS checks, extension tests, Ruff, Pyright, and server tests | All required checks pass on the target runner without PowerShell |
| **Portable bootstrap** | `npm run bootstrap` | Installs extension, webview, and server dev dependencies with platform-native Python paths | The target runner completes setup without PowerShell |
| **Portable development build** | `npm run dev` | Builds the webview and extension host without PowerShell | Both desktop packages compile through the Node lifecycle command |
| **Portable smoke readiness** | `npm run smoke` | Reports manifests, build outputs, platform-native venv readiness, and sidecar health | Core readiness is visible without PowerShell |
| **Windows staged check** | `scripts/check.ps1` | TS checks + (if venv ready) Ruff + Pyright + Pytest | All executed areas pass on Windows |
| **Windows strict staged check** | `scripts/check.ps1 -Strict` | Same but fails on any area that can't run | All deps installed + all pass on Windows |
| **Windows smoke readiness** | `scripts/smoke.ps1` | Reports manifests, source, build outputs, venv | All core items report ready on Windows |
| **Windows strict smoke** | `scripts/smoke.ps1 -Strict` | Same + requires sidecar health on known port | Sidecar answers `/health` on Windows |
| **Live Coach-turn smoke** | `node scripts/trainer-turn-smoke.mjs` or Windows-only `scripts/smoke.ps1 -TrainerTurnSmoke ...` | Runs real `remote / debug / function_guidance / learn-first training` checks against a live sidecar + provider, including `zh-CN remote / debug / function_guidance` routes | Fresh-lane continuity stays clean, learn-first routing produces a practice card, and zh-CN training copy stays localized across all first-class lanes |
| **Native VSIX package** | `npm run package:vsix` | Builds a native sidecar for the current runner and verifies its manifest | The current target artifact is valid; missing other target triples remain explicitly unverified |
| **Full delivery** | `npm run verify:delivery` | Portable full verification + native package VSIX | The target runner passes verification and produces a .vsix; this is not proof of all target triples |

## Manual Smoke Test

Run after implementation changes:

1. `npm run bootstrap` - bootstrap all dependencies on the current platform
2. `npm run dev` - build webview + extension
3. (If server changed) `npm run dev:sidecar` or manual uvicorn
4. Launch VS Code against `extension/`
5. Confirm the **Trainer activity bar icon** appears
6. Open the Trainer workbench and confirm **five top-level views** render:
   - Coach
   - Plan
   - Resources
   - Training
   - Settings
7. Confirm truthful blocked states when provider or sidecar is not ready (no black screen)
8. Configure an OpenAI-compatible provider and test the connection
   - Keep the product-facing default endpoint on the official provider template. The provided MiniMax gateway (`http://47.107.101.18:3000/v1`) is test-only and must not be surfaced in the UI.
   - Run `node scripts/provider-smoke.mjs` only when `TRAINER_PROVIDER_SMOKE_API_KEY` already exists in the process environment; provide `TRAINER_PROVIDER_SMOKE_BASE_URL` and `TRAINER_PROVIDER_SMOKE_MODEL` through the existing SecretStorage/environment bridge. The script never prints or persists credentials or provider responses; output is limited to success/failure category, model, protocol, and elapsed milliseconds.
   - After provider smoke passes, run `node scripts/trainer-turn-smoke.mjs` only when `TRAINER_TURN_SMOKE_PROVIDER_API_KEY`, `TRAINER_TURN_SMOKE_PROVIDER_BASE_URL`, and the local sidecar are already available through the existing secure environment/SecretStorage bridge. Its output is likewise limited to category, model, protocol, and elapsed milliseconds; do not pass keys on the command line or write them to files.
   - The smoke now verifies `/models`, exact probe echoing, `<think>` leakage, and language integrity. Use `TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE=zh-CN` for the default coaching language and `TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE=en-US` only when you intentionally check an English fallback.
   - Do not treat the provided MiniMax gateway as zh-CN-ready unless the live smoke passes without `language_corruption`. On July 2, 2026, the same gateway still returned model IDs successfully but corrupted Chinese probe text into question marks.
9. Send a default Coach turn and confirm the reply appears in the Coach message flow
10. If you touched transport or message rendering, verify any structured assistant output stays attached to the message as typed parts instead of drifting into a separate pseudo-console
11. If you touched recovery, streaming, or host-message hydration, run `npm run verify:webview-recovery --prefix extension` and confirm the browser preview replays recovered completion/error notices, in-progress streaming UI, and a full live coach loop truthfully
12. If you touched intent routing, exercise one non-Coach structured intent and confirm both browser preview and desktop streaming use `/turn/stream`
13. Open Training and confirm the five questions are answered on the first viewport
14. Evaluate a file and confirm the result appears
15. Run `npm run smoke:strict` and confirm health

## Multi-Lane Integration Checklist

- **Shared lane**: Keep `shared/src/models.ts` and `shared/src/protocol.ts` backward-compatible
- **Command catalog**: Keep `shared/src/commands.ts` and `extension/package.json` aligned on reachable commands
- **Extension host**: Register commands and views declared in `shared/src/commands.ts` and `extension/package.json`
- **Webview lane**: Keep `extension/webview/package.json` in sync with imports and Vite config
- **Server lane**: Keep `/health`, session APIs, and importable package roots working
- **Verification lane**: Keep scripts and docs aligned to actual skeleton, not intended end-state

## Port Probing

The smoke script probes the following ports by default:

- **8765** — default sidecar port
- **34891-34911** — extension-managed sidecar range

To probe a specific port through the portable lifecycle:

```bash
npm run smoke -- --port 8765
npm run smoke -- --port 8765,34891
```

Windows PowerShell convenience equivalent:

```powershell
scripts/smoke.ps1 -Port 8765
scripts/smoke.ps1 -Port 8765,34891
```

## Known Gaps

- `npm run verify` requires an installed Python 3.12+ environment with the server dev dependencies
- Root `npm run check` does not verify Python; use `npm run verify` for full portable coverage
- Strict smoke cannot pass unless the sidecar is running and answering `/health`
- A native VSIX package verifies its current `platform-arch` binary only. Missing or unverified Linux, Darwin, or Windows target binaries remain coverage gaps until their native runner produces evidence.
- The GitHub Actions matrix is configuration until its target jobs have recorded passing results.
- `test_api.py` (219117 lines) is extremely large — should be split by endpoint domain
- Live provider and Coach-turn smoke require an explicit reachable endpoint plus credentials. They remain intentionally credential-gated and are not implied by mock or browser-preview coverage.
- Browser-preview recovery proves the webview state contract, but release verification still needs a real VS Code host restart or webview-reconstruction check before claiming reconnect behavior is proven in the host.

## Project Ideal State Gaps

The following gaps exist between the current state and the [project ideal state](../README.md#project-ideal-state-项目理想状态):

| Gap | Priority | Notes |
|-----|----------|-------|
| Non-functional smokes may silently pass | P2 | `scripts/check.ps1` SKIP behavior masks missing toolchains |
| Training handoff full loop | P2 | evidence_submit → coaching feedback cycle not complete |
| File size problem | P3 | 5 files over 5000 lines, 3 over 60,000 lines |
