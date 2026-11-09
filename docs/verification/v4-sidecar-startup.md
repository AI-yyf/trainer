# Sidecar preparation time — under 1 second

Date: 2026-11-09

## Root causes

The cold start paid for work that the health screen did not need:

- `MemoryService` opened the Qdrant local client eagerly, including the first
  collection scan, while constructing the app.
- `resources/ingest.py` imported `trafilatura` (and therefore `dateparser` /
  `htmldate`) at module load.
- `ingest/service.py` imported PyMuPDF at module load.
- `app.main` executed `app = create_app()` at import time, so importing the
  module built a complete FastAPI app (runtime + 187 routes), then
  `run_sidecar.py` built a second one.
- The health probe polled every 300ms, adding up to 300ms of detection delay.

## Changes

- Qdrant client is opened lazily on the first semantic operation; the
  in-memory fallback remains unchanged.
- trafilatura and PyMuPDF load only when a URL/PDF source is actually parsed.
- The module-level ASGI `app` is now a lazy proxy for legacy
  `uvicorn app.main:app` / test imports; `run_sidecar.py` still uses the
  explicit `create_app()` factory.
- Sidecar health polling is 100ms.

## Measurements

Measured from process spawn to the first successful `/health` response on the
packaged darwin-arm64 sidecar, local machine:

| Build | Samples | Result |
| --- | --- | --- |
| Before | 1 | 1.871s |
| Intermediate (lazy imports, eager module app) | 5 | 0.839–1.005s |
| Final (lazy imports + lazy module app) | 5 | **0.650–0.790s** |

Source sidecar after the final changes measured 0.746–0.918s. The UI health
poll adds at most 100ms, so the "Trainer 正在准备中" state clears within the
one-second budget once the process is spawned.

## Verification

- Full server suite: **4023 passed, 28 subtests passed** (8m21s).
- Extension tests and `npm run check`: passed.
- `npm run build`, `npm run package:vsix`, `verify-package.mjs`: passed.
- Latest installed-GUI screenshot of Settings no longer shows the preparation
  banner, but the full installed-GUI journey still has an unrelated
  provider-test UI assertion to fix; no full GUI PASS is claimed here.

## Real provider evidence recorded while the gateway was available

The gateway recovered during this check. These runs used
`https://linksub.fun` with `deepseek-v4.1-flash` and the key supplied only via
the process environment (never written to the repo):

- `docs/verification/v4-provider-journeys.json`: journeys 5/6/15/19/20 **PASS**
  (preference adaptation/change, memory revoke, resource version, multi-project
  isolation).
- `docs/verification/v4-review-provider-journeys.json`: journeys 9/11/12
  **PASS** (forgetting days, refusal, long absence).
- `docs/verification/v4-fsrs-delayed-recall.json`: first review, day-scale
  interval and delayed-recall turn **PASS**.
- `docs/verification/v4-real-learning-loop.json`: chat → goal → teaching →
  generated practice card → real pytest verification → LearnerState evidence
  update → restart → delayed review turn **PASS** (8 assertions true).

The multi-week learner trial remains not executed.
