# 2026-10-21 UX convergence — startup, icons, browser capture

Scope: the post-1.3.4 UX pass requested after installing the `14f42ee` build.
This note records what changed, how it was verified, and what remains
human-owned. It does not replace the signed release acceptance record.

## 1. Startup no longer waits for the sidecar

### Defects fixed

1. **The stale-while-revalidate cache never persisted.** `schedulePersist()`
   cleared and re-armed its 1.5 s timer on every state patch. Streaming and
   tool traffic can arrive faster than 1.5 s for minutes, so the write was
   starved indefinitely and no `trainer.bootstrapSnapshot.v1.*` key existed.
   The timer is now armed once per burst; later calls only replace the pending
   payload. `flush()` persists the newest payload on `deactivate()`.
2. **The cache was seeded after the view provider was registered**, leaving a
   window where the first bootstrap could render empty. Seeding now happens
   before registration, so even the first resolve carries the restored thread.
3. **A stale stored session id caused a failing `/session/activate` on every
   launch.** A 404 now clears the stored id, so later launches go straight to
   `/session/start`. A real restore is a 200 and no fallback.
4. **The sidecar only started after the first render.** Activation now
   requests `ensureRunning()` immediately after the managed data root is
   applied; the later rehydration joins the same promise.
5. **Oversized caches could exceed the memento budget.** The writer halves the
   tail until the envelope fits and skips the write if a single message still
   exceeds 2 MB.

### Evidence

Real default-profile launch, installed `1.3.4` build (2026-10-21):

```
[sidecar] prewarm requested during activation
[activation] seeded cached bootstrap (stale-while-revalidate)
[activation] Trainer extension host activated
[webview] resolve start
[webview] html ready
[webview] bootstrap posted          <- cached thread is already on screen
...
[sidecar] prewarm ready             <- engine becomes ready later
...
POST /session/activate 200 OK
[session] restored stored session session-e198e3ef4a
```

The persisted workspace memento contains
`trainer.bootstrapSnapshot.v1.context-992e4643223d4b769f61b3fa741fe863`
(1 conversation message at the time of inspection). The installed-host VSIX
E2E added a `bootstrap-snapshot-cached` step: it passed with 2 cached messages
after 1,520 ms — the first write at the end of the debounce window.

## 2. Icon system

- One five-step optical scale is enforced everywhere:
  `12 (micro) / 14 (inline) / 16 (control) / 18 (header) / 20 (nav)`.
  Off-scale sizes 11, 13 and 15 were removed from all 115 call sites.
- Header history/settings icons are 18 px on the 20-box canvas; settings
  category icons are 18 px; primary navigation now uses dedicated 20-box
  Coach / Learning / Resources glyphs at 18 px with selective fill.
- `TrainerIconBase` keeps a 1.4 stroked 16/20-box and uses 1.9 on the 24-box so
  the rendered hairline matches its neighbours.
- `.trainer-icon` now owns `inline-block`, `flex: none`, `overflow: visible`
  and baseline alignment; header utilities have hover, pressed, selected,
  disabled and focus states.
- New source-contract test (`extension/tests/iconSystemContract.test.js`)
  rejects off-scale sizes and ad-hoc raw SVG icons.

### Evidence

- 96/96 accessibility pages (8 languages × 6 views × normal/200% font) pass.
- 471/471 UI geometry assertions pass at 340/420/460 widths in dark/light and
  Chinese/English.
- Normal and 200% screenshots show the three destinations with aligned icons;
  the 200% nav stacks icon above label instead of wrapping the icon away from
  its label.

## 3. Browser capture installation

- Settings → Preferences now has a **Browser capture** card with three
  actions: install, open the browser's extensions page, show the pairing code.
- `trainer.browserCapture.install` copies the bundled MV3 extension to
  `~/.trainer/browser-capture`, opens the folder and shows a four-step guide
  naming `chrome://`, `edge://`, `brave://`, `opera://`, `vivaldi://` and
  `arc://` extensions pages.
- `trainer.browserCapture.openExtensionsPage` detects installed Chromium
  browsers (Chrome, Edge, Brave, Arc, Opera, Vivaldi, Chromium) on macOS,
  Windows and Linux and opens the matching native extensions page.
- Multi-window correctness: discovery now returns **every** reachable sidecar,
  pairing tries each until the instance that owns the code accepts it, and
  port-recovery only switches credentials to an instance that validates them.
  Previously a second VS Code window could capture the pairing attempt or turn
  an offline queue into a false "credential invalid" failure.
- Popup panel swapping: `.panel { display:flex }` overrode the browser's
  `[hidden]` rule, so the pairing and "Trainer not running" cards stayed on
  screen after a successful pair. Added an explicit `.panel[hidden]` opt-out.
- Popup library count: a successful capture refreshed local history but not the
  sidecar status cache, so the count lagged one item. Captures/downloads now
  call `trainer:refresh` before rendering.
- No Web Store publication and no silent install: branded Chromium browsers do
  not allow programmatic unpacked installs. The flow removes the URL typing,
  browser choice and folder hunting while leaving the browser's own
  "Load unpacked" confirmation to the user.

### Evidence

- Browser-capture E2E: 23/23 checks, including a run with a competing Trainer
  sidecar on `127.0.0.1:8765`; pairing still reached the correct `34892`
  instance, offline queuing still worked, and all downloads/revocation checks
  passed.
- Real branded Chrome 155 (separate profile, remote-debugged): Developer mode
  enabled, **Load unpacked** clicked in `chrome://extensions`, folder
  `~/.trainer/browser-capture` selected, Trainer Capture 0.3.0 appeared as an
  enabled extension. Paired with code `899950`, captured `example.com` and
  `example.org`; the popup showed "已加入资料库", workspace `trainer`, library
  count 2, and two successful history rows. Sidecar `/browser/status` returned
  `library_count: 2`.
- Installed bundle copy: 21 files, `Trainer Capture 0.3.0`, all six extension
  URLs present in the localized guide.
- 65 shared/browser-extension tests, including the multi-instance discovery
  assertion and the popup panel/count regression guards.

## 4. Commands run

```
npm run check
npm run test:extension            # pass
npm run test:browser-capture-e2e  # 23/23 (also with a competing sidecar)
npm run test:experience-matrix    # 200/200
node scripts/verify-ui-geometry.mjs  # 471/471
node scripts/capture-ui-accessibility-matrix.mjs  # 96/96
npm run test:vsix-e2e             # ok, incl. bootstrap-snapshot-cached
npm run test:server               # 3644 passed
npm run verify:package            # darwin-arm64 package passed
npm run verify:credentials        # 11,411 files, 0 findings
```

## 5. Remaining human-owned items

- Owner sign-off in `docs/maturity/2026-10-20-real-project-review.md` §6 is
  still blank. An Agent review is not a human review.
- Remote-SSH Layer 2 human window acceptance remains Not Executed.
- Chrome 155 "Load unpacked" is verified above on a physical browser. The
  Edge/Brave/Arc/Opera/Vivaldi branded shells still need their own one-time
  click-through on a machine where they are installed; the automated Chromium
  run covers the extension runtime, not each branded shell.
- No tag, publish or release action is authorized by this note.
