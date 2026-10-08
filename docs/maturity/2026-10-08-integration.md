# Main integration acceptance — 2026-10-08

This integration includes the five unpublished `product-final-polish` commits
through `83e30ff71bec7c802a1b2bfeb1426cd3093177d7` and the maturity changes below.
The user explicitly authorized remote main integration. The remote baseline
was `978ceddd67c914b71220fd53316bdf2c1c9feb47`; no product version bump or formal
Release is part of this integration.

## Resulting behavior

- Coach, Learning and Resources are the three primary destinations. History
  and Settings remain header utilities; all six internal routes retain their
  commands, deep links and restore paths. Coach owns the full composer;
  focused practice owns its response input. Secondary facts use disclosure.
- Learning derives its title, primary label, enabled state and click target
  from one scoped action descriptor. Ongoing practice remains resumable;
  optional evidence cannot replace an available learning step. Provider
  recovery opens the Settings destination named by its button.
- Host synchronization advances its baseline only after an applied ACK.
  Generation, revision and workspace/session fences reject stale deliveries;
  a single in-flight update, latest-update coalescing and bounded full-snapshot
  recovery keep delivery queues bounded. Operation notifications carry scope
  and operation identity; uncertain verification delivery stays unconfirmed.
- Hidden surfaces avoid per-chunk React work while retaining drafts and
  scroll position. Scroll restoration temporarily disables browser anchoring
  during the scoped restore. Page exit flushes the latest composer draft.
- Shared image staging enforces count, signature, byte and decoded-dimension
  limits before transport. Encoding/resizing runs in a bounded, cancellable
  worker and completion is fenced to the original draft scope. Server image
  validation independently checks transport and actual decoded content.
  Vision capability requires an exact answer to fresh image-only numbers;
  legacy fixed-marker results no longer establish vision support.
- Packaging builds and verifies source, frozen native Sidecar, manifest and
  Companion in dependency order. Versions and provenance are checked before
  packaging; actual CLI import-cycle and dependency-directory leakage faults
  are fixed. CI, cross-platform, nightly and release workflows use the same
  fail-closed artifact inputs. Source mirrors include the new image and vision
  modules plus the frozen Python lock.

## Local verification

| Command or check | Observed result |
| --- | --- |
| `npm run check` | Webview and extension TypeScript checks; CSS balance passed |
| `npm run test:extension:verbose` | 1,847 passed; 1 existing skip; 0 failed |
| `cd server && .venv/bin/python -m pytest tests -q -n 4` | 3,201 passed; 28 subtests passed; 29 dependency warnings |
| Frozen Pyright and Ruff | 0 Pyright errors; Ruff passed |
| Actual TypeScript language-service diagnostics for changed UI/runtime files | 0 diagnostics; no callable LSP tool was available |
| `TRAINER_E2E_PORT=4195 TRAINER_E2E_REUSE_EXISTING_SERVER=1 npx playwright test --workers=4 --reporter=line` | 360 passed on the final immutable preview |
| Packaging/capability regression subset | 44 passed, including the actual subprocess CLI failure contract |
| Four changed workflows with actionlint 1.7.12 | Passed |
| Golden screenshots | All 12 regenerated; Coach and Learning inspected; Learning image changed |
| Fresh native packaging and isolated Code install | Passed on macOS arm64 / Code 1.127.0 |

The full browser run covers the existing eight-language, theme, narrow-width,
keyboard, settings, provider, resources, recovery and governance scenarios.
Fixtures were updated to declare their intended practice/provider state;
evidence identity, trust and dispatch assertions remain enforced. The scroll
and immediate-draft-reload failures required production fixes. Browser
fixtures establish layout and interaction behavior, not real teaching evidence.

Logs and local artifacts are in the ignored `output/maturity/` directory:
`extension-native-final.log`, `server-integrated.log`, `browser-delivery.log`,
`types-delivery.log`, `pyright-integrated.log`, `ruff-integrated.log`,
`native-package.log`, `native-install.log` and `native-artifact-inspection.json`.

## Measured performance

`docs/verification/perf-probe-baseline.json` is refreshed from the final preview
using `TRAINER_PERF_URL=http://127.0.0.1:4195 node scripts/perf-probe.mjs`.
Across 300 synthetic stream chunks, both Coach-only and previously visited
surfaces observed zero tasks above the observer's 50 ms floor. The worst warm
navigation p90 was 49 ms against the 100 ms budget; navigation during streaming
was 8 ms. These are one-machine samples, not provider latency measurements.

`surface-before.json` and `surface-after.json` record actual React Profiler
callbacks from the opt-in profiling build. Before the retention fix, visited
hidden surfaces committed for every stream chunk. Afterward, hidden Learning,
Resources, Growth and Settings produced no commits during the burst; Training
had one transition commit. The probe includes all six routes, dirty Settings
and a large resource reader. Missing metric entries mean no callback was
observed. Timing variations under concurrent builds do not support a general
speedup percentage. Reproduce with `scripts/surface-profile-probe.mjs` and a
preview built using `TRAINER_WEBVIEW_PROFILE=1`.

## Native artifact provenance

The verified local artifact is `trainer-1.3.4-darwin-arm64.vsix`, 114,883,774
bytes, SHA-256
`df1d1f5745cf8ee963ba0911f260fda2952ef5c88702a686aacc01b9929c4ee1`.
Its matching `.vsix.build.json` truthfully records pre-commit HEAD `83e30ff…`
and `sourceDirty=true`. It is a local acceptance artifact, not a clean final
commit release artifact. The native build used Python 3.12.2, PyInstaller
6.22.2, Pillow 12.3.0, VSCE 4.0.0 and Node 26.8.2.

The isolated installation listed `local.trainer-extension@1.3.4`, verified
installed source/lock manifests and started the installed frozen Sidecar for
an actual `/health` response. The archive contained 1,590 entries, all seven
required package entries, and zero foreign runtimes, dependency directories
or Apple metadata files. Temporary profiles were removed.

## Remaining acceptance

The broader maturity goal remains open. This local integration does not
establish 20–30 real-provider teaching journeys, credential-gated visual
understanding, native Remote-SSH disconnect/reconnect and evidence isolation,
or actual Windows/Linux installation and basic use. Those require their own
recorded results. The updated cloud workflows will run after the main push;
their result is separate from the successful local checks above. Native
installation/Sidecar health does not establish complete native UI acceptance.
