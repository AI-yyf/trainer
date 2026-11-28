# Handoff

- Baseline e7e6f41 pushed; CI cross-platform run 39636536608 failed only UI(windows) extension tests.
- Working tree carries the T-0020 fix (target-platform path API in browserLauncher.ts); extension tests green locally.
- Wave 1: finish T-0020 (commit+push+CI), then T-0002/T-0003 (session/provider identity), T-0006/T-0007 (browser queue), T-0001/T-0005 (startup).
- Subagent policy: deepseek-researcher agents are read-only auditors; implementation is master-owned to protect shared files.

## 2026-10-23 — T-0027 closed, T-0029 opened
- Head 6dd95c7. T-0027 FIXED_VALIDATED at e84049d: four-layer fix (coach_finalize schema + finalize prompt clause;
  routers.py T-0027 repair now also catches pasted-prose blobs — code fence / "## " heading / >240 chars — and
  replaces them with the reply's labelled action, never fabricating; reply_continuity extractor gained the
  第一步/First step label family, parenthetical qualifiers and bold-close on either side; fresh workspaces get an
  honest empty current_focus instead of the synthetic imperative line glm-5.3 quoted verbatim).
- Real-provider validation (linksub + glm-5.3, one fresh port-guarded sidecar per sample):
  evidence/t0027-final-1..5.json — 4/5 emit the exact concrete step (file + command + observable success signal)
  consistent with the reply; server suite 3664 green (3463 non-api + 201 api), ruff clean.
- Probe hygiene lessons (encoded in /tmp/trainer-conv/latency-probe.mjs): a zombie sidecar holding the probe port
  silently served every later sample with pre-fix code (all samples before t0027-final-* are invalid as post-fix
  evidence); the probe now fails loudly when the port is already bound and uses a unique workspace per run.
- T-0029 CONFIRMED (new): ImplementationCoach._current_step needs_rescue template produces "先把 {target} 压成一个
  很小的补丁目标" with lane-label target, unanchored to the turn (1/5 samples). Fix direction: anchor rescue
  templates to the reply action or derive target from turn content.
- Still BLOCKED on external: T-0028 owner sign-off (docs/maturity/2026-10-20-real-project-review.md §6) and
  Remote-SSH L2 real-window acceptance; do not convert to PASS.

## 2026-10-23 — T-0029 closed, design acceptance re-shot
- T-0029 FIXED_VALIDATED @b91194b (failure-first: both new tests failed pre-fix; verified via stash). Root fix:
  ImplementationCoach target label must appear in the learner's message or the message's own first-sentence
  subject wins; extractor suffix whitelist (第一步代码 / Next steps); router repair predicate covers the
  rescue-template shapes. glm-5.3 5/5 samples turn-anchored (evidence/t0029-1..5.json).
- Design acceptance re-shot at f7ef9cd: 471/471 geometry + 96/96 a11y. Found and fixed en route: a corrupted
  empty attribute selector ([data-plan-fact=      ]) that silently disabled the narrow-width plan-fact wrap
  rule (f7ef9cd) — it was also the source of an esbuild css-syntax warning on every build.
- Still BLOCKED on external: T-0028 owner sign-off, Remote-SSH L2 real window. Do not convert to PASS.

## 2026-10-23 — Audit wave 1: nine P1s found and closed (loop reopened per §12)
- Four parallel read-only audits at the final SHA (architecture / security / race+data / UX) found 9 P1s +
  1 low (popup hex tokens). All registered (T-0030..T-0038) and fixed failure-first @6861ce4.
- Data-integrity: browser-capture enqueue now persists inside the queue lock; evidence recording is one
  IMMEDIATE transaction with in-transaction attest dedupe; the training reliability slot is serialized
  per workspace so same-key requests replay instead of double-running.
- Availability/fencing: stream-route sync setup failures resolve the singleflight future (no stranded
  waiters); training restore/rehydrate commands fence on runtime identity before re-stamping summaries.
- Security: /browser/pair kills the live code after five failed guesses (429 until a fresh code).
- Correctness/UX: T-0027 repair now also rebuilds resume_thread + coach-turn summary; CJK-aware short-step
  threshold and past-tense paren guard; popup panel focus, jargon-free capture copy (8 locales),
  liveActiveView authority in all four remaining writers, popup tokens for the two hex colors.
- Verification: server 3670 green (incl. mirror-integrity guard), extension suite exit 0, npm run check
  clean, CI pending on 6861ce4. T-0028 sign-off and Remote-SSH L2 remain BLOCKED on external conditions.

## 2026-10-23 — Audit wave 2: adversarial re-audit of the wave-1 fixes, seven gaps closed
- Four parallel read-only auditors re-ran at 69fbcd2 attacking the wave-1 fixes directly. Found 7 P1s
  (T-0039..T-0045), several of them incompletenesses in wave 1 itself (unfenced second restore patch,
  unlocked source-deleted siblings, unlocked queue clear/remove/revoke, reliability control routes
  bypassing the new lock, one missed liveActiveView writer + missing startup seed, popup focus cascade
  on open, path-scoped token exemption). All FIXED_VALIDATED @c0811ee (pyright narrowing fix).
- Verification: behavior tests (evidence born-flagged, method-scoped lane exemption, reliability
  cancel-race) + contract pins; server full suite green, extension suite exit 0, npm run check clean,
  pyright clean, CI 9/9 @c0811ee (run 39907998471).
- P2 records (not blockers, documented in the audit transcripts): reliability lock unbounded acquire
  (no timeout escape), T-0036 predicate residuals for unlisted generic fillers ≥12 weight, waiter
  CancelledError closes the SSE stream with zero frames, --warn token is light-bg-tuned, dead
  _write_evidence_row helper, /browser/pair DoS-by-lockout tradeoff (recovery = one click).
- Still BLOCKED on external: T-0028 owner sign-off, Remote-SSH L2 real window. Do not convert to PASS.

## 恢复命令（§8.1 — 会话重启后按序执行）
1. `git fetch origin && git checkout maturity/p1-final-convergence-2026-10-20 && git pull` — 恢复到 86951a4（代码 c0811ee）。
2. `cd server && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`（若 venv 缺失）。
3. `npm install && npm run build`（根目录；刷新 dist 供设计探针使用）。
4. 读取 `.trainer-convergence/run-state.json` + 本文件末三节恢复上下文；未关闭项只有
   T-0028（所有者 §6 签核）与 Remote-SSH L2 实机两项，均为外部条件。
5. 所有者签核到位 → 运行教学质量复核并把 teaching_acceptance 从 BLOCKED 改为实测结果，
   回填 docs/maturity/2026-10-20-real-project-review.md §6 与 JSON 证据。
6. 真实 Remote-SSH 窗口到位 → 运行 L2 实机验收（与本地相同的统一 evidence 写入），
   回填 remote_ssh_e2e 的 JSON 证据。
7. 两项完成后重新评估 §12 全部停止条件；任何 FAIL 重开修复循环（先写失败用例）。
8. 注意事项：真实 Provider 探针使用 /tmp/trainer-conv/latency-probe.mjs（端口被占用会
   显式失败——历史上僵尸 sidecar 曾让整轮样本跑到旧代码上）；每次运行用独立 workspace id。

## 2026-10-23 — Owner-directed popup redesign (minimal card)
- All-owner feedback applied @7cf5760: the browser-extension popup now has
  exactly two states — pairing (first run, with sidecar detection) and
  capture (page / PDF / GitHub repo row, library binding, optional
  project-folder download). Removed: import-history panel, offline /
  connected status cards and the status dot/line, the queue manager panel
  (queued captures deliver automatically; the toolbar badge carries the
  count), the redundant repair button, and their orphaned CSS/sprite
  symbols (-420 lines). Footer keeps Open Trainer + revoke pairing.
- Structure test now pins the minimal card AND asserts the removed panels
  stay removed. CI 9/9 @7cf5760 (run 39942589905).
- Still BLOCKED on external: T-0028 owner sign-off, Remote-SSH L2 window.

## 2026-10-23 — Deferred-P2 wave closed; T-0046 bounded lock acquire
- T-0046 FIXED_VALIDATED @f5c67ad (failure-first: pre-fix demo showed the
  second same-workspace call blocks unboundedly on the lock). Bounded
  acquire (120s) now returns the honest current workspace without mutation
  on timeout — T-0032's serialization is intact, work() never runs
  concurrently. CI 9/9 (run 39946921786).
- Popup minimal card @7cf5760 (owner-directed): two states only, no import
  history / connection status / queue manager; CI 9/9 (run 39942589905).
- Remaining deferred item: T-0036 predicate residual (unlisted generic
  fillers ≥12 weighted chars can still ship) — inherent to the blocklist
  approach; the prompt contract + real-provider samples remain the primary
  defense. Documented, non-blocking.
- Still BLOCKED on external: T-0028 owner sign-off, Remote-SSH L2 window.

## 2026-10-23 — Owner review wave: findings closed, install-state acceptance re-run
- Owner deep review findings addressed @1806154: fact-source sync (five stale OPEN
  registry entries closed against fix commit 03f3792 after verifying ancestry and
  green regression tests; a11y locale count corrected to 8); popup recovery entry
  shown only when captures are queued while unpaired (8 locales); reliability lock
  wait 120s->15s so waiters get an honest busy view quickly; spacing token
  convergence — all 41 legacy --trainer-space-1..4 usages mapped to the unified
  --space-* scale (identical values, zero visual delta), diverged 5/6 deprecated.
- Full install-state VSIX host E2E re-executed at latest HEAD: run 39961046680
  (workflow_dispatch, run_vsix_host_e2e=true) — Windows/macOS/Ubuntu native
  install + host E2E all success, closing the "latest HEAD install-state" gap
  the owner identified.
- Remaining per owner plan: real Remote-SSH window L2 acceptance (BLOCKED, env),
  owner §6 sign-off + human teaching-quality review (BLOCKED, human), final
  manual visual sign-off (human), then freeze/tag/release (owner decision).

## 2026-10-23 — T-0048 reopened and closed: next-step surface desynchronization at HEAD
- Evidence re-audit of t0029-1..5 (delayed disposition check) reproduced AT HEAD
  the exact artifact those samples showed: /turn (and the /turn/stream fallback)
  hydrate_snapshot AFTER execute_turn, and derive_coaching_state rebuilt
  coaching_state from pre-turn memory — re-minting「围绕…先做一个小动作，把结果
  带回来。」into snapshot.coaching_state.next_step while reply/coach_turn carried
  the turn-anchored step. One response, two next steps (coach bubble vs Learning
  lane teasers). Registered T-0048 (P1).
- Two adjacent gaps fixed in the same wave: memory.active_thread + workspace
  mirrors persisted the PRE-repair filler (persist ran before the T-0027 repair,
  and grounding evaluated the pre-repair step); the non-stream finalize close
  collapses labelled sections onto one line so visible_next_step could not read
  the reply action in that lane (new sentence-boundary inline lane, fences
  dropped, past-tense guard; mid-sentence label mentions still stay prose).
- Failure-first: both API tests in
  server/tests/test_next_step_surface_consistency.py failed pre-fix. One
  regression caught and root-caused during the wave (repair populated an empty
  legacy-lane agent_meta → turn surfaced as agentic; guard now requires a
  non-empty meta). Full server suite 3677 passed incl. bundled-mirror
  integrity; ruff + pyright clean on changed files. One UI source-guard
  (coachFinalizeNextStepContract) tracked the extracted helper + the new
  pre-persist invocation site. CI 9/9 @c84dadb (run 39978190239); fix
  commit 6d8fb10, guard commit c84dadb.
- probe `next_step_consistent_with_prose: false` values in t0027-final-*/t0029-*
  are a probe-heuristic artifact (substring vs a prose section the reply does
  not contain), NOT divergence — the structured steps are concrete and the
  authoritative surfaces agree; API-boundary tests now pin that contract.
- Still BLOCKED on external: T-0028 owner sign-off, Remote-SSH L2 window.

## 2026-10-24 — Owner key delivered; real-model journey complete; T-0049 closed
- Owner supplied a fresh linksub test key (used ONLY via env; zero key/host
  strings in the repo — grep-verified before commit). Journey probe extended
  with the missing /provider/test capability step and reply-text evidence.
- Real-model teaching journey now COMPLETE: 10/10 steps (evidence/journey-real/)
  — streaming capability verified on the relay, honesty-first replies (declined
  unseen code twice, no fabrication), plan continuity across a sidecar restart,
  concrete tool-anchored next step with success signal (SLICE OK) + formal-verify
  offer, cross-workspace isolation holds. Probe fixes were tooling-only.
- T-0049 (P1, adversarial recheck of T-0048): the two streaming MAIN paths
  persisted the turn reflection BEFORE the T-0027 repair — memory thread +
  workspace focus recorded the filler and the stream shipped it as
  response.agent.next_step while response snapshot coaching_state was repaired.
  Fixed by running repair_generic_finalize_next_step after grounding and before
  persist in both paths (same non-empty-meta guard). Failure-first streaming
  test added; suite 3678 green; ruff/pyright clean.
- Still BLOCKED on external: T-0028 owner §6 sign-off, Remote-SSH L2 window.

## 2026-10-25 — Owner-directed first-run capture onboarding (T-0050)
- VS Code 首次激活后 4 秒（不阻塞首绘）一次性提醒；全局状态标志在弹提示
  之前写入，保证仅提示一次；已准备/已配对用户不再看到。
- installForBrowser 命令：检测 7 个 Chromium 系浏览器（三平台、复用现有
  纯函数检测器；IE 无扩展体系不受支持，Edge 为其继任；Firefox 留待 AMO
  上架阶段）→ QuickPick 选择 → 暂存扩展包 → 打开所选浏览器自己的扩展页
  → 安装路径自动进剪贴板 → 一条消息说明剩余的开发者模式步骤。
- Chromium 品牌浏览器拒绝静默安装，这是非商店安装能做到的最接近一键的
  形态；Web Store 上架（所有者账号）之后可换成字面意义的一键，命令侧
  只需把主按钮换成商店页（一行改动）。
- 失败用例先行：browserCaptureOnboarding.test.js 4/4（门控矩阵 + 防御性
  输入 + 8 语言文案完整性 + 按浏览器启动组合）；npm run check 干净；扩展
  全量套件绿。Webview 未动，设计验收无需重拍。

## 2026-11-01 — branch reconciled; zero-code capture + text nav + capture intent evidenced

- Branch is now `maturity/p1-final-convergence-2026-10-20`, fast-forwarded to main
  (`93b3798` zero-code browser capture, `7ee45f9` text-only primary nav) and then
  `52fe632` capture-intent correctness. Working tree was reviewed; the previously
  uncommitted server/browser capture-intent changes are now committed with tests.
- Browser capture no longer asks for a pairing code. The popup is the original
  280px capture card with the pairing panel removed; the worker discovers the
  loopback sidecar, auto-pairs to the latest host session, queues captures and
  coach drafts offline, fences queue items by workspace, and self-heals a 401 by
  clearing the stale credential and re-pairing on the next flush.
- Primary navigation is text-only (对话 / 学习 / 资料); icons were removed and the
  tab height tightened. Nav e2e 26/26; an old composer-scope assertion was aligned
  with the documented dock ruling (Coach/Learning/Resources dock; Training/
  Progress/Settings do not).
- Capture intent is now honest: link/selection snapshots carry their own intent
  tag and never dedupe against a full source; queue identity includes workspace,
  focus, capture mode and excerpt; GitHub blob pages are read through the contents
  API; PDFs are detected by magic bytes; selection requires an excerpt and
  non-snapshot captures refuse artifact downloads.
- Evidence at 52fe632: server 3688 passed / 28 subtests; extension suite exit 0;
  `npm run check` clean; pyright 0 errors; real Chrome browser e2e 24/24;
  geometry 471/471; a11y 96/96; perf budgets pass; Cross-Platform CI run
  41236836839 = 9/9 success. Evidence files are under `evidence/*52fe632*`.
- Remaining gaps are recorded in `run-state.json` and the acceptance matrix:
  install-state VSIX host E2E has not been re-run at 52fe632; Remote-SSH L2 and
  owner teaching sign-off remain BLOCKED on external conditions; T-0026 latency
  measurement is unchanged and needs a re-run only when the owner relay/model
  changes. Do not convert any of these to PASS without new evidence.

## 2026-11-01 — install-state gate re-run at current code

- Local `npm run test:vsix-e2e` rebuilt the packaged VSIX from the working tree
  (sourceCommit 07fc780, code 52fe632) and passed 36/36 installed-host steps with
  the fixture provider (`rebuiltCurrentVsix=true`). Evidence:
  `evidence/vsix-e2e-07fc780.json` + `.log`.
- Scope honesty: the visual window-capture probe is win32-only and was skipped on
  macOS; this run proves installed activation/commands/state, not pixel capture.
  The three-platform package jobs passed separately in run 41236836839.
- With that gate closed, the remaining blockers are external: T-0028 owner
  teaching sign-off, real Remote-SSH L2 window, and a T-0026 latency re-run when
  the owner relay/model changes. Phase returned to BLOCKED_ON_EXTERNAL; no
  external gate is marked PASS.

## 2026-11-01 — Plan → Coach prompt scope regression fixed

- `e2e/trainer-session-recovery.spec.js` reproduced a real P1: clicking
  「生成计划」 switched to Coach but wrote the prompt into the Plan draft scope,
  leaving the composer empty. Root cause: the dock's per-surface draft scope was
  not selected before `setComposerDraft`.
- Fixed at fb56333 by selecting the Coach draft scope first; the failing test now
  passes and the full session-recovery spec is 20/20. Experience matrix was
  200/200 at the preceding docs head; both are local preview evidence, not a
  substitute for real-provider acceptance.

## 2026-11-01 — independent audit wave 3: five P1s fixed; engineering converged

- An independent adversarial audit of the new zero-code/focus/queue/prefill code
  found five reproducible P1s. All are fixed and re-audited:
  1. multi-window auto-pair now posts a host focus beacon, ranks candidates and
     re-ranks on user capture; a dead stored sidecar falls through to the live
     workspace (`02cf4fc`, `5881e56`; focus e2e PASS B then A).
  2. retryable/fenced queue heads rotate within one pass instead of blocking all
     later captures/drafts (`d42ca7b`; e2e head-of-line-yields).
  3. suffix-less PDFs above the 2MiB web bound retry with the 25MiB PDF bound and
     only promote `%PDF-` (`9f0526c`; server 3691).
  4. browser selection prefill selects the Coach scope and appends to an unsent
     Coach draft; `ui/coachPrompt` also selects Coach (`360aaed`, `e913644`).
  5. Plan generate preserves an unsent Coach draft instead of overwriting it.
- Final evidence at 5881e56: server 3691 passed; extension suite exit 0; check
  clean; browser e2e 25/25; focus e2e 1/1; session recovery 24/24; geometry
  471/471; a11y 96/96; perf budgets pass; packaged VSIX host E2E 36/36;
  Cross-Platform CI run 41251375795 = 9/9. Independent re-audit: no remaining
  reproducible P0/P1.
- Remaining gates are external only: T-0028 owner teaching sign-off, real
  Remote-SSH L2 window, T-0026 latency re-run when the relay/model changes, and
  Windows/Linux browser install acceptance. Do not mark these PASS without new
  evidence.

## 2026-11-01 — current-HEAD structural journey evidence (d72e98b)

- Added `scripts/run-structural-journey.mjs` (`npm run test:structural-journey`):
  real sidecar + real SQLite, no provider mock. It records 14 PASS, 4 BLOCKED,
  0 FAIL. PASS covers session start, upload/index/search, global plan, real
  attempt + self-reported evidence, browser pair → draft → host pending → ack,
  memory summary, sidecar restart/session restore, and workspace isolation.
  BLOCKED are explicit: real plan generation, real training-card generation,
  real model switch (no key) and Remote-SSH L2 (no window).
- UI structural evidence at d72e98b: template navigation 26/26, bound-card
  42/42, experience matrix 200/200, session recovery 24/24, provider human
  configuration 1/1 (model/thinking/profile switch), settings lifecycle 1/1,
  resources lifecycle 1/1.
- Found and fixed one P1 during the training journey: an unbound/foreign
  `activeTrainingCardRouting.selectedCard` could lend authored title/deliverable
  to the selected card. Route facts are now exposed only when the cardId matches
  the active id; recovering/stale sync uses an empty bound shell; review
  artifacts and flash cards keep their own surfaces.
- Design/install/CI at d72e98b: geometry 471/471, a11y 96/96, perf budgets
  (warm nav p90 40ms), VSIX host E2E 36/36, Cross-Platform run 41259410960 = 9/9.
- Real-model teaching, Remote-SSH L2, T-0026 latency and Windows/Linux browser
  install remain external BLOCKED; do not convert them to PASS.

## 2026-11-02 — real provider journey + experience pass

- Owner supplied a temporary relay key for this session (environment only; never
  written to the repo). Provider: MiniMax-M2.7 primary, M3.1-Flash switch.
- Fixed two provider-path P1s found by the real journey:
  - streaming capability probe was injecting `thinking.disabled` and falsely
    reporting mandatory-thinking models as unverified; it now uses the same
    thinking re-negotiation as real sends;
  - after a sidecar restart, agent stream calls re-injected disabled thinking
    and the truncation retry used a raw client. Both now negotiate thinking and
    give reasoning-first agent turns 8k initial / 32k truncation headroom.
- Current real-model journey: 10/10 steps 200 — streaming+tools verified, real
  plan id, restart same session, continuity 229 visible chars, workspace
  isolation, model switch to M3.1. Evidence: evidence/journey-real-2026-11-02/.
- Residual: one M3.1 tool-loop sample hit the provider output limit before a
  visible answer; kept at evidence/journey-real-m3.1-tool-loop-limit-2026-11-02/.
  M2.7 full journey passes; do not generalize a provider guarantee.
- UX: Coach empty state centered with a concrete starting hint; dock wording
  changed to 看回答 / 留在这里. Matrix 200/200, geometry 471/471, a11y 96/96.
- CI 41343904971 @bcb7cf6 = 9/9; VSIX host E2E 36/36. T-0028 human sign-off and
  Remote-SSH L2 remain BLOCKED.

## 2026-11-02 — settings / history / Resources / stream visibility pass

- Real installed VSIX (`local.trainer-extension@1.3.4`, isolated Profile,
  real sidecar, owner relay) verified end-to-end:
  settings overview → connection summary → Go to Chat → first send without a
  prior connection test. Reply arrived and the newest two bubbles rendered at
  the bottom (`安装态验收…` / `可以，当前连接可用，无需先测试即可直接发送。`).
- History panel rebuilt for the narrow sidebar: canonical Close/Search/Plus
  glyphs, one-line title, full-width New chat, live current-conversation row
  before the host answers, skeleton rows while loading, and one in-flight
  `session/list` request (mount prefetch and open no longer race). Measured in
  the installed VSIX: panel 100ms, current row 233ms, cached reopen 184ms,
  0 skeletons on reopen; no wrapped title/action.
- Resources empty state now shows the real setup guidance even when a stored
  leftover list exists; the folder section is hidden when there is nothing to
  organize; the leftover plan note remains visible (honesty preserved).
- New chat: the host clears an inherited conversation when a force-new
  `/session/start` snapshot carries no messages; the webview also clears
  optimistic echoes. An empty Coach thread now renders the centered starter
  empty state (three starters) instead of floating task chips that read as
  orphan messages. Installed VSIX: 0 conversation items, 0 suggestion chips,
  starter click fills the draft.
- Training taxonomy: an implementation card without a concrete
  `files_to_touch` target is downgraded to `reading` by the shared card model,
  so the UI uses manual verification instead of “verify current file”. A
  concrete file target keeps `implementation`. Chat capability no longer
  requires a prior provider test (configured + key is sendable); streaming,
  tools, vision and formal-plan capabilities remain probe-gated.
- UI actions: Learning's primary next action, Training's start/return/next
  actions and Coach's training-resume action now carry semantic icons. The
  Training leftover “Open Coach” action had white text on a transparent
  background because `.training-current__actions--primary .button` overrode the
  accent fill; the accent primary variant now keeps its fill. Installed VSIX
  screenshot confirms the blue accent button with a chevron.
- Settings: failed test no longer reads as “未实测 / 可直接使用”. The summary
  keeps the failure note, removes Go-to-Chat as the primary action, and offers
  retest; the model is shown verbatim (`MiniMax-M3.1-Flash`). The Add-provider
  template view gained an in-view “返回连接” control; real check returned to
  the summary.
- Stream visibility root cause: `content-visibility: auto` collapsed
  off-screen conversation items to a 4px placeholder, and auto-scroll never
  revealed the completed reply. Removed the collapsing rule and force-scroll
  on a send that starts in Coach; the cross-surface restore and 90ms settle now
  respect the pin.
- State integrity: stream completion fence for a cleared id; live-turn body
  repair now requires a matching reply id (legacy no-id snapshots still use the
  user-text guard); final coalesced chunk is folded into the fallback before
  merge; research stream frames carry their own message id; `stream/start`
  accepts a cleared-id handoff and resets content.
- Verification for this pass: server 3697 passed (server unchanged since),
  extension suite exit 0, `npm run check` clean, settings lifecycle e2e 1/1,
  geometry 472/472, a11y 96/96, pyright/ruff clean. The final packaged VSIX
  passed the installed-host E2E (exit 0) and the real-profile acceptance
  (settings → no-test send → visible reply; history 94/229/182ms). Perf probe
  passed both budgets (streaming longtasks 0, warm nav p90 61ms). The
  plaintext-credential gate is clean after redacting the private relay host in
  historical E2E evidence to `provider.invalid`; no key was found. Previous
  SHAs are not evidence for this working tree.
- Independent audit found and this pass fixed: failed-test summary lie,
  Add-provider dead-end, final-chunk fallback truncation, stale stream/start
  handoff, repeated-prompt assistant overwrite risk, and research id-less
  stream pollution. Remaining measured risk: performance probe after removing
  content-visibility (must be re-shot); Learning/Coach per-screen polish is the
  next visual pass. T-0028 human sign-off, real Remote-SSH L2 and Windows/Linux
  browser installation remain external BLOCKED.

## 2026-11-02 — file-bound training closure + verification honesty
- HEAD `241973b` (pushed). Real isolated profile installed from the current VSIX; practice project at `.../workspace` (queue_lock.py).
- Fixed a live-selection leak: skipping the selected card left `selected_card_id`/handoff pointing at it, so Training kept rendering an unactionable card. Write-side release now clears selection, next hop, live selection and the matching handoff on skip/archive; the snapshot hides legacy terminal selections; the client mapping treats an explicitly empty selected card as authoritative. `test_card_status_transition` 41 passed.
- File binding: model-authored targets (`queue_lock.py` with backticks or leaf-only) now normalize in the shared resolver, host, and server identity. Matching is exact or leaf-only, never a different file. `trainingFilePathsShared` 5 passed; `test_training_file_binding` 3 passed; `test_card_taxonomy` 5 passed.
- Verification root causes found:
  1. The active editor buffer (not disk) is the source of truth. A stale dirty buffer produced `13 / threading`; `File: Revert File` restored the saved file. Command failures now log to the Trainer output channel (`[command:failed] ...`).
  2. The evaluator copied only the target file, so the project's pytest could not run. Training evaluation now copies a bounded, symlink-free project tree into a sandbox, writes the in-memory buffer over the target, and runs the project's tests there. The real project is never written. Direct pipeline: ruff passed, pyright passed, pytest 2 passed. `test_evaluator_project_copy` 2 passed.
  3. Explanation-only acceptance criteria blocked code verification. They now defer to the reflection step; file-path “symbols” are treated as targets, not code identifiers; real missing code symbols still fail. `test_evaluator_training_acceptance` 2 passed.
- Installed-VSIX loop (real GUI): verification passed with ruff/pyright/pytest; reflection recorded code locations and run output; Return completed; Growth shows 实现 · 反复验证 2 次验证通过. Card `a20c0f4e…` implemented; handoff verified/completed; evidence `ev-f611f129d1` verified=True, source `ide_current_file`.
- Still external: first-use on a brand-new profile needs the provider key (kept in SecretStorage; not printed), native resource picker, real Remote-SSH L2 and Windows/Linux browser install. High-frequency/destructive and independent reverse audit are next.

## 2026-11-02 — independent audit P0/P1 closed; CI failure root causes
- Independent read-only audit of `241973b` found one P0 and two P1s; all fixed in `64e02a0`:
  - P0: a supplied acceptance contract with only deferred/file signals could pass with zero concrete code evidence. `_training_acceptance_check` now fails that case; a no-contract request keeps the historical warning. Guardrail criteria ("do not modify X") can never defer.
  - P1: training file targets outside `canonical_project_path` were accepted; server and shared host matching now enforce project containment, and leaf-only targets require exactly one on-disk match (no root-file guess).
  - P1: the host tried `<workspace>/<leaf>` before the unique search, so a stale same-named file could be verified; resolver order is now exact/unique-first.
  - Also closed: skipped cards no longer count as live; a successful same-request card-status replay still returns 200 after release; the project-copy skips non-regular files; training card actions wait for `ensureRunning()` instead of failing on a cold sidecar.
- CI `41436248837` failed on exactly the three server tests the audit fixes changed; the local full suite now passes `3716 passed` and extension tests exit 0. `41443397666` is the new run for `64e02a0`.
- Installed VSIX re-check: Learning now reads "还没有正式计划。先用当前这一步继续，或从模板开始。" (no internal "旧痕迹" copy); the completed training card still shows verified evidence and Return. "下一张" waited for the cold sidecar, then hit the Provider relay (`Provider request failed`), not "Sidecar is not running".
- Remaining external: provider relay stability for new card generation, native resource picker, Remote-SSH L2, Windows/Linux real-browser install, T-0028 human sign-off. Next: destructive recovery, resources/browser UI, high-frequency residual checks, independent re-audit of `64e02a0`.

## 2026-11-02 — re-audit P1s closed; full suite green
- Independent re-audit of `64e02a0` found residual P1s; fixed in `4ac04fb`:
  - Skipped/terminal cards can no longer record current-file evidence: the evaluator route now returns the historical report without the learning loop, evidence, FSRS or plan changes when the training card is not live.
  - Only explicit explanation prompts may defer to reflection; substantive unsignalled requirements (e.g. "保证所有共享状态访问都在锁保护之内") now fail. Guardrail criteria ("不修改") still cannot defer.
  - Four cold-start training actions (flashcard answer, practice return, reflect, return) now wait for `ensureRunning()`.
  - Two previously uncollected status tests were moved into the unit class (43 collected).
  - Leaf matching requires a managed project root; client matching requires a workspace; verification uses the managed project root for multi-root safety.
- Full server suite `3721 passed` (15:11) after deleting a FIFO left by the new project-copy test; the test now unlinks it. Full extension suite exit 0; `npm run check` clean.
- Installed VSIX rebuilt from `4ac04fb`; cold-sidecar check still to be recorded. CI `41451465660` is the run for `4ac04fb`.
- Remaining external: provider relay for new card generation, native resource picker, Remote-SSH L2, Windows/Linux real-browser install, T-0028 human sign-off.

## 2026-11-02 — audit P1s tightened; manual reading-card handoff P1 open
- Third independent audit of `8df085c` accepted the prior P0/P1 closures and found two parser/taxonomy P1s; fixed here:
  - taxonomy change verbs now include 补充/添加/编写/创建/优化/更新/完善 (and English equivalents), so "检查并补充回归测试" and "分析并优化临界区" stay implementation;
  - explanation verbs no longer defer a criterion that also contains 实现/修复/补充/…; an unchanged file cannot pass "解释并实现…" or "说明并修复…".
- Focused tests: `test_card_taxonomy.py`, `test_evaluator_training_acceptance.py`, `test_card_generator.py`, `test_card_router.py` → 131 passed; full server suite at `8df085c` → 3721 passed; extension suite exit 0; `npm run check` clean.
- Manual reading card (self-reported) reached Reflect in the installed VSIX, but the reflect request still sees the raw handoff phase `try` while the scoped snapshot shows `verify`, returning 422. The incomplete manual-path changes were reverted to keep the tree green. Root cause is the raw-vs-scoped `latest_training_handoff` source; next round must make the live handoff the single source and re-enable self-reported reflect/return.
- Cold-sidecar recovery PASS: killing the sidecar and clicking 下一张 restarted it (`[sidecar] starting`, new PID) and generated a new card; no "Sidecar is not running." failure.
- Remaining external: provider relay stability, native resource picker, Remote-SSH L2, Windows/Linux real-browser install, T-0028 human sign-off.

## 2026-11-03 — manual/reading card P1 closed (self-reported loop)
- Root cause of the 422 was threefold: (1) `_restored_phase` only honoured `verified`, so a persisted `reflect/self_reported` handoff rehydrated as `learn`; (2) reflect/return resolved a stale generator-cache handoff instead of the one practice-return wrote; (3) the trusted-return evidence guard had no self-reported branch.
- Fix: practice-return writes the exact handoff into `_authoritative_training_handoffs`; `_current_training_handoff` returns it only while the raw live handoff still belongs to the same card (so a stolen/rebound handoff is never resurrected); reflect/return receive that object; `_restored_phase` honours self-reported progression; return can complete a self-reported handoff without crediting the card as implemented. Evidence stays `verified=False` with `verification_source="self_reported"`; `latest_learning_outcome` is `self_reported`, never `tests_passed`.
- Behavioral tests: `test_manual_reading_card_raw_and_snapshot_agree_through_return` (practice-return → reflect → return, raw/snapshot agreement, unverified evidence) and `test_legacy_self_reported_try_handoff_can_reflect` (legacy try/self_reported handoff migration) pass; 75 focused tests pass.
- Installed-VSIX real GUI: fresh reading card `card-manual-fresh-1` completed Learn → Try → Reflect → Return. Log shows `POST /training/reflect 200` and `POST /training/return 200`; Growth keeps 理解 as “还未验证”. Persisted state: card `answered`, handoff `return/self_reported/completed`, evidence `verified=False`, `verification_source=self_reported`, `latest_learning_outcome=self_reported`.
- Gates: `ruff check app tests` clean; `pyright app` 0 errors; full server suite **3728 passed**; extension suite exit 0; `npm run check` clean.
- Newly observed P1 to verify next: a card seeded as `status=active, learning_phase=learn` renders “开始这一步”, which calls card-status transition and returns 422 (active→active). Need to check whether normal card generation can produce that state, and make the start action phase-aware if so.

## 2026-11-03 — active/learn start action fixed
- A selected card can be `status=active` while still at `learning_phase=learn` (card selection activates it before the learner presses Start). Training rendered “开始这一步”, which sent `active -> active` and the server returned 422.
- `transition_card_status` now treats `active -> active` with `reason=start_step` as a phase advance to `try` (no status change, no invalid transition). Any other `active -> active` still fails.
- Regression tests: `test_active_learn_card_start_advances_to_try` and `test_active_to_active_without_start_reason_still_fails`; `test_card_status_transition.py` 45 passed.
- Installed-VSIX real GUI: seeded active/learn card, clicked “开始这一步”; log shows `POST /training/card-status 200`, UI advanced to “动手 · 2/5”.
- Final gates: ruff clean, pyright 0 errors, full server suite **3730 passed**, extension suite exit 0.

## 2026-11-03 — 831bf84 audit: Learning cards / Resources shell
- Independent audit of `831bf84` found two P1s: review/evidence text was clamped to one line with no title, and `scripts/verify-ui-geometry.mjs` still asserted the old three-disclosure contract. Both are fixed in this commit.
- Learning is now a four-group card stack (current → reviews → route → growth): review cards are capped at two with two-line text plus `title`; evidence history is a compact disclosure for pending/deferred debt only; the path group is a native `<details>` that starts closed, shows the active stage plus one upcoming card, and folds the rest under “more”; completed stages and templates sit below the cards.
- Found and fixed a real closed-details bug: the author `display: grid` on the path card group overrode the UA hidden state, so closed stage cards kept layout height and produced a clipped sliver. Added an explicit `:not([open]) > cards { display: none }` and a geometry assertion (`closed path group takes no card layout`).
- Resources is one rounded `.template-library` shell containing toolbar, tree and folders; the shell marker moved from the inner tree wrapper to the shell itself.
- Wide container query removed; `.learning-cards` max-width 760px; action buttons wrap at 200%; `board.css` is in the section manifest; geometry gate updated (474 assertions).
- Installed-VSIX re-check: 340/420/460 no horizontal overflow; `stageWidth=0` when the path is closed; both review cards fully visible; Resources shell contains toolbar/tree/folders; 200% French/German buttons wrap (`scrollWidth=clientWidth`); all eight languages at 340 have no overflow/raw key/undefined. Screenshots in `.tmp/audit831/`.
- Bottom fade hardening: the `padding-bottom` sat on a selector overridden by `views-panes.css`; the effective rule now loads later and leaves 35px clearance under the 14px fade at max scroll (audited).
- Re-audit found settled-only evidence history unreachable: `hasEvidenceDetails` counted only pending+deferred, so adopted/rejected rows disappeared when the debt queue was empty. Fixed by keeping `hasEvidenceDetails` on total records and rendering the practice-records disclosure as a standalone card below the groups when there is no debt; added a behavioral test for the settled-only case.
- Gates: `npm run check` clean; extension suite exit 0; `verify-ui-geometry` 474 passed; `verify-css-sections` balanced. Server code unchanged; last full server suite was **3732 passed** (`4d999cb` era).
- Remaining external/not executed: Journey A first send is still blocked by the native workspace picker; Journey D browser capture/native import remain **NOT_EXECUTED**; macOS CI runner acquisition failures remain external. Next: independent re-audit of this commit, then finish Journey A.

## 2026-11-03 — Journey A PASS; Journey D capture exposes a library-scope P1
- Native workspace picker resolved without Accessibility: the isolated fresh profile enables `files.simpleDialog.enable`, so the folder picker is the in-app simple dialog; cancelling it reaches the product's typed-path fallback. Typed `/var/folders/.../trainer-first-use-0ogdu5/workspace`, the extension created `.trainer/workspace.json` and selected the root.
- Journey A first send **PASS** on the installed VSIX: configured the local mock provider (`http://127.0.0.1:8899/v1`, `trainer-mock`), clicked “加入 Trainer”, sent `请解释 queue_lock.py 里的 with self._lock 如何保证异常时释放锁。`, received the streamed mock reply, closed VS Code, reopened, and the question plus reply were restored. Evidence: `.tmp/first-use/16-first-send.png`, `.tmp/first-use/18-reopen.png`, `.tmp/first-use/19-reopen-frame.png`.
- Journey D page capture **sidecar PASS, live view FAIL**: isolated Playwright Chromium loaded `~/.trainer/browser-capture`; captures of `https://example.com`, `https://www.iana.org/...`, and `https://www.rfc-editor.org/rfc/rfc2606` all returned `status=ok` with distinct resource IDs. The active sidecar DB (`<profile>/.trainer/runtime/trainer.sqlite3`) contains them with `parse_status=parsed`, `index_status=indexed`, `trust_state=trusted`, `workspace_id=context-edf3c38...`; a fresh sidecar query returns all five, and a VS Code restart lists them. The **live Resources view stays stale**: it showed one resource, then two/three after later entries, and missed the just-captured RFC 2119 even after an entry refresh.
- Root cause area: the host refresh path, not the workspace identity. `request/bootstrap` only re-sends cached host state (`syncExtensionState`), and the browser capture has no host event; a `/memory/summary` read immediately after capture can still return the pre-capture library. The attempted entry/focus refresh (including a silent `refreshMemory` and a `MemoryService.invalidate_snapshot` call) was reverted because it did not reliably close the race and its regression test passed without the invalidation. This is a confirmed P1 in the browser-capture → live library path.
- CI `41526908444` (`faa9fab`) is fully green: all 9 jobs passed, including Server/UI/Package on macOS, Windows and Ubuntu.
- Next: make the capture-to-snapshot handoff atomic (sidecar invalidates/rebuilds the live snapshot and the host pushes it, or a capture sequence the host can poll), add a same-session capture → `/memory/summary` regression test that fails without the fix, then re-run Journey D and the remaining B/C/E/F journeys on the installed VSIX.

## 2026-11-03 — Journey D live library refresh P1 fixed
- Root cause confirmed: a browser capture wrote the resource and `/memory/summary` returned it, but the host had no event and the held workbench snapshot only refreshed on restart. This is a host freshness gap, not a workspace-identity mismatch.
- Fix: added host-facing `GET /browser/library-revision` (workspace-scoped resource-id fingerprint), a visibility-gated `BrowserLibraryPoller` (2s, first read is a baseline, workspace-stamp check, backoff), and a silent `refreshMemoryCommand` path that fetches `/memory/summary` and pushes one fresh snapshot. The poller is disposed with the browser-capture runtime.
- Regression tests: `extension/tests/browserLibraryPoller.test.js` (baseline → changed → unchanged → changed; hidden/no-sidecar/foreign-workspace; refresh failure retry) 5 passed; `server/tests/test_browser_capture.py` now asserts the same-session summary includes the capture and the revision endpoint changes; full browser-capture suite 25 passed.
- Gates: `npm run check` clean; full extension suite exit 0; `verify-ui-geometry` 474 passed; `verify-css-sections` balanced.
- Installed-VSIX live verification: captured `https://www.rfc-editor.org/rfc/rfc8174` while the sidebar stayed on Coach; within the 2s poll window Resources changed from 5 to 6 and showed `RFC 8174` **without restart**. Evidence: `.tmp/first-use/38-live-capture-refresh.png`, `.tmp/first-use/39-live-capture-refresh-frame.png`.
- PDF capture is **BLOCKED by the upstream fetch**, not a silent success: the sidecar returned HTTP 502 for the W3C dummy PDF; the extension kept the item queued (`queueCount=1`, `attempts=2`, `lastError=添加失败（HTTP 502）...`), showed connected/paired, and the library stayed at 6. Reopening Chrome replayed the queue without duplicating or claiming success. Selection and GitHub capture remain **NOT_EXECUTED**.
- Browser-related server tests: `test_browser_capture.py`, `test_browser_bridge.py`, `test_library_folders.py` → **68 passed**.
- CI `41547169955` (`57c65c9`) is fully green: all 9 jobs passed, including Server/UI/Package on macOS, Windows and Ubuntu.
- Remaining: Journey D selection/GitHub capture and PDF after the upstream/proxy fetch is usable; Journeys B/C/E/F on the installed VSIX; remote/Windows/Linux and human sign-off gates.

## 2026-11-03 — Journey D breadth after the live-refresh fix
- **Page capture + live refresh PASS**: `https://www.rfc-editor.org/rfc/rfc8174` added while the sidebar stayed on Coach; Resources went 5 → 6 and showed `RFC 8174` without restart.
- **Selection draft PASS**: `POST /browser/coach-draft` with a selected passage returned `ok` and `draft_id`; the host prefilled the Coach composer with the quoted selection plus the coaching prompt, without auto-sending. Evidence: `.tmp/first-use/43-selection-prefill.png`, `.tmp/first-use/44-selection-prefill-frame.png`.
- **GitHub capture + live refresh PASS**: `https://github.com/octocat/Hello-World` returned `status=ok`, `resource-b66f3a6c64`; Resources went 6 → 7 and showed `octocat/Hello-World` without restart. Evidence: `.tmp/first-use/45-github-capture.png`, `.tmp/first-use/46-github-capture-frame.png`.
- **PDF capture BLOCKED by upstream fetch**: W3C dummy PDF returned HTTP 502 from the sidecar fetch; the extension kept it queued (`queueCount=1`, `attempts=2`, `lastError=添加失败（HTTP 502）...`), stayed paired/connected, and the library did not claim success. Reopening Chrome replayed the queue without duplication. This is an environment/upstream block, not a silent failure.
- Still not executed: PDF/GitHub download-to-project-folder, PDF page button, multi-window queue isolation, Journeys B/C/E/F.

## 2026-11-03 — independent audit follow-up: visible sync, retry and first-poll
- The independent audit of `57c65c9` found three P1s; all were fixed here:
  1. `refreshMemoryCommand` was called directly and bypassed `workbench.syncState()`, so a visible Resources view did not receive the patch. The poller now executes `COMMAND_IDS.refreshMemory` through the command registry and treats `ok:false` as a failed refresh.
  2. A failed refresh committed the revision before awaiting the summary, so the same revision was never retried. The revision is now committed only after a successful refresh; failures retain it and back off.
  3. The first visible poll used to baseline the post-capture revision and swallow captures made while hidden. The first visible poll now refreshes immediately; only subsequent unchanged reads are no-ops.
- Alias hardening: `/browser/library-revision` echoes `requested_workspace_id`; the poller compares that raw host id, so a path→context alias cannot be mistaken for a foreign workspace.
- Regression tests updated: `browserLibraryPoller.test.js` 6/6 (first-poll refresh, changed/unchanged, alias acceptance, foreign rejection, failed-refresh retry); browser server tests 50 passed; full extension suite exit 0; `npm run check` clean; geometry 474; CSS balanced.
- Installed-VSIX live proof: Resources was **already visible**, captured `https://www.iana.org/domains/root`, and the view changed 7 → 8 and showed `Root Zone Management` without navigation or restart. Evidence: `.tmp/first-use/49-visible-root-zone.png`, `.tmp/first-use/50-visible-root-zone-frame.png`.
- Still open: PDF capture is blocked by upstream HTTP 502 (queue retention verified); selection/GitHub download-to-folder, multi-window isolation, and Journeys B/C/E/F remain.

## 2026-11-03 — audit closure and final visible-library proof
- Independent re-audit of `0a4866e`: all three P1s closed, no new P0/P1; verdict “safe to keep.” The audit's remaining note was that the command registry dropped the `{silent:true}` payload (message-only) and the poller header comment still described the old baseline behavior. Both are fixed here; a source guard asserts the registry forwards the payload.
- Final installed-VSIX proof with the visible Resources view: captured `https://example.net/`; the view changed 8 → 9 and showed `Example Domain (net)` **without navigation or restart**, with no refresh toast. Evidence: `.tmp/first-use/53-visible-example-net.png`, `.tmp/first-use/54-visible-example-net-frame.png`.
- CI `41553878760` (`0a4866e`) is fully green: all 9 jobs passed. The final registry/comment guard commit requires its own CI run.
- Still open: PDF capture blocked by upstream HTTP 502 (queue retention verified); selection/GitHub download-to-folder, multi-window isolation, and Journeys B/C/E/F remain.

## 2026-11-03 — Journey B real project + real provider
- Real project: `trainer-real-gui-sH0kNv/workspace` with `src/queue_lock.py`, `conversation_router.py`, `test_conversation_router.py`. Opened `src/queue_lock.py`, selected 1:1-41:1, and asked: “pop 与 try_pop 在异常路径上如何释放锁？指出一个真实风险，并给出一个不修改文件的验证命令。”
- Configured default `MiniMax-M3.1-Flash` **FAILED**: `/session/message/stream` returned 200 but produced no visible reply; the sidecar logged `[provider] coaching stream empty; retrying once with max_tokens=8192` then `reply failure category=truncated_or_empty status=200 ... output limit before completion`. The UI showed an honest “Trainer 当前卡在 provider path / Provider request failed” error; no file changed.
- Same provider switched to `MiniMax-M2.7` for the real teaching check: first reply correctly explained `with self._lock` and `try/finally`, cited lines 16 and 23, named the real risk that `try_pop`/`acquire()` blocks despite its name, and gave a non-mutating lock-release verification command. Follow-up correctly said both methods raise `IndexError("empty")` and gave a parametrized pytest outline. File hashes before/after were identical for `queue_lock.py`, `conversation_router.py`, and the test file; no unauthorized writes.
- Evidence: `.tmp/first-use/62-journey-b-long-wait.png`, `.tmp/first-use/63-journey-b-long-wait-frame.png`, `.tmp/first-use/67-journey-b-followup-m27.png`, `.tmp/first-use/68-journey-b-followup-m27-frame.png`, `.tmp/first-use/69-journey-b-report.json`.
- Provider config was restored to the original `MiniMax-M3.1-Flash` after the check. M3.1 remains a confirmed provider/reasoning-budget P1; M2.7 is the working real model in this environment.
- Not executed: completing a formal plan step/training card with the real provider, Journey C/E/F, PDF/GitHub download-to-folder, multi-window isolation.

## 2026-11-03 — M3.1 reasoning budget, M2.7 working default; Journey C blocked
- Provider budget fix: `MiniMax-M3.x` is now recognized as reasoning-first; the coaching stream starts with 8192 output tokens and the one-shot empty/truncated retry cap is raised from 8192 to 16384. Focused tests: `test_provider_reasoning_budget.py` 3 passed; provider wire/persistence 16 passed; ruff/pyright clean.
- Real `MiniMax-M3.1-Flash` still did not produce a visible coaching reply after 6 minutes (the provider test also stayed in “正在检查”); the relay/model remains unusable for Journey B. The apparent later reply in the transcript belongs to the M2.7 turn and is not evidence for M3.1.
- `MiniMax-M2.7` is now the working default in the real profile. It already produced two correct real Q&A replies with file/line references. A later short question returned English-only visible prose while zh-CN was selected, and the language guard rejected it with “这条回复没有读清。请把刚才的问题再发一次。” — honest, but the provider/model is still flaky on short answers.
- Learning state after these attempts: current step still “在 queue_lock.py 中标出 with self._lock 的进入、退出和异常路径”; training acceptance **0/4**; the failed-turn/provider-error text appears repeatedly inside the 待回顾 cards. A formal plan/training step was not completed, so Journey C/E/F remain **NOT_EXECUTED**.
- The provider language/error text leaking into Learning review cards is a new state-pollution issue to investigate next, alongside the M3.1 relay latency.

## 2026-11-03 — short-answer language fallback + recovery review filter
- Short English technical answers are no longer treated as language corruption: `_wrong_language_zh_reply_detail` now accepts fewer than 10 Latin words (e.g. “False. The lock is already held.”) while still rejecting prose-length English. Unit test added; guard tests 17 passed.
- Provider-recovery text is filtered out of Learning review cards. The filter now matches the recovery `next_step`/`blocker` and its 24/12/8-character prefixes, because the card layer can clamp a long recovery sentence. Regression test covers full and truncated recovery text plus a legitimate review item; 30 related memory/language/review tests passed.
- Installed-VSIX check: the Learning review cards no longer contain “请把刚才的问题再发…” or “English-only visible prose”; legitimate “从最近的说明里选一个最小可验证动作…” cards remain. Evidence: `.tmp/first-use/82-clean-learning.png`, `.tmp/first-use/83-clean-learning-frame.png`.
- New-chat attempt did not clear the existing training handoff/thread in the real profile; the short M2.7 question still produced no new reply within five minutes. The formal plan/training step therefore remains 0/4 and not completed; Journey C/E/F remain NOT_EXECUTED.

## 2026-11-03 — formal training handoff blocked; review cards cleaned
- Learning review cards are now clean on the installed VSIX: the recovery sentence/English-only error no longer appears; legitimate review content (“从最近的说明里选一个最小可验证动作…”) remains. Evidence: `.tmp/first-use/82-clean-learning.png`, `.tmp/first-use/83-clean-learning-frame.png`.
- The formal training handoff is **stuck** on an already completed self-report card: “自我报告复验：梳理 queue_lock.py · 回流 · 5/5 已完成 · 结果已带给教练 · 这是你的自我报告，尚未经过服务器验证。” Clicking “带结果回到教练” returns to the old coach conversation; clicking “下一张” produces no state change after 3 minutes; Learning still reports **训练验收 0/4**. Evidence: `.tmp/first-use/85-training-handoff.png`, `.tmp/first-use/87-training-return.png`, `.tmp/first-use/88-training-return-learning.png`, `.tmp/first-use/89-next-training-card.png`, `.tmp/first-use/90-next-training-card-frame.png`.
- This is a formal training-loop blocker independent of the provider: no new card is minted and no plan evidence is recorded. Journey C cannot be claimed until the handoff advances or a clean training card is generated.
- Short-English language fallback and recovery-review filtering are committed (`aac3299`); CI `41579057071` is fully green (9/9 jobs).
- Follow-up on “下一张”: the extension did send `POST /training/generate-card/stream`; the sidecar accepted it with HTTP 200, but no card and no persistent error appeared after 3 minutes, and plan acceptance stayed 0/4. This is a training-generation/provider-path failure (plus missing error presentation), not a dead button. It needs either a stable provider/model or a deterministic fallback card, and the UI must keep the failure visible with retry.

## 2026-11-03 — formal plan step completed; training handoff fixes
- **`下一张` no-card root cause fixed.** Card generation had no idle timeout. A 45s no-token window now emits a deterministic fallback card marked `generation_source=deterministic_fallback`, `provider_stalled`, `degraded`, `recoverable`; a timeout after visible tokens still fails honestly, and a provider error is never disguised as a card.
- Fallback cards are plan-aware when a plan binding exists: they use `files_to_touch`, real symbols from the current file (`self._lock`, `acquire`, `release`, `finally`), and verifiable acceptance criteria. The training card surface now shows a degraded strip + `重新生成` action; `下一张` binds the live plan stage when one exists.
- **Formal plan step completed with server-verified evidence.** A real model card `追踪 queue_lock.py 的异常释放路径` was bound to `plan-board-demo / stage-lock / revision 1`. The VS Code Trainer test runner re-read `src/queue_lock.py` and `/evaluate/current-file` passed with ruff, pyright, pytest and training acceptance **5/6 (1 deferred to reflection)**, producing `evidence-0309ad6e...` (`controlled_check`, passed). Reflection was recorded, the return completed, and the evidence adopted in Learning.
- The plan advanced from **第 2 / 4 段** to **第 3 / 4 段 · 迁移到真实队列**; Growth shows `实现 · 反复验证 · 3 次验证通过`.
- **Return 422 root cause:** after verification the card status is `answered`, but the transition map allowed only `answered -> reviewed`, and `_credit_returned_training_card` only credited `active/implemented`. Fixed both (`answered -> implemented/completed/reviewed`; answered is credit-able on Return). Unit tests plus a real API call against the profile DB returned 200 and wrote the ledger `answered -> implemented` + `training_handoff_returned`.
- Honest boundary: the successful Return above was API-triggered **after** the UI button failed 422; the fixed UI Return has not yet been re-run on a fresh card. The installed workbench then reflected the completed card/evidence/plan advance correctly.
- New localization finding: the evaluator's English recommendation `Widen the scope only after the verified result is preserved.` appears in zh-CN Learning review cards. This is a P2 localization/state-cleanup item for the next round.
- Gates: full server suite **3746 passed**; extension suite exit 0; `verify-ui-geometry` 474 passed; CSS balanced; `npm run check` clean.

## 2026-11-03 — Chinese review language + file-target verification + full UI Return
- **English evaluator prose no longer leaks into zh-CN Learning.** `record_learning_outcome` now localizes its active-thread/decision/progress next steps, and `ReviewScheduler` drops prose-only foreign context for Chinese workspaces while keeping short technical tokens. Installed re-check: the review cards read `先保留已验证结果，再扩大范围。`; `Widen the scope only after the verified result is preserved.` is gone.
- **File-target criteria now verify against the current file.** A criterion such as `通过 queue_lock.py 验证最终结果` was reported missing because its only signal was a masked file reference. When that file is the verified current-file target and the verb is verification/check, it now counts as matched; implementation verbs stay strict. A fresh card moved from 5/6 to **6/6**.
- **Full UI Return proven on a fresh card.** `$practice` minted `验证 queue_lock.py 的异常释放路径` (`d27370e3`). UI: `验证当前文件` → server evaluation passed (ruff, pyright, pytest, training acceptance 6/6) → reflection → `带结果回到教练` → **POST /training/return 200**, card `implemented`, handoff `completed`, Growth **4 次验证通过**. This is the end-to-end UI proof of the earlier 422 fix. The card is conversation-bound, not plan-bound; the plan-bound step remains `e996f5a` (stage 2/4 → 3/4).
- Gates: full server suite **3751 passed**; extension suite exit 0; `npm run check` clean; CSS balanced.
- Remaining: the training card surface still shows `带结果回到教练` after a successful return until the snapshot reconciles; Journey E/F, PDF capture/download, multi-window isolation remain NOT_EXECUTED.

## 2026-11-03 — stage-focused Learning + plan-step card + faster paint
- **Learning now shows only the current stage by default.** The current action stays open; reviews, later path, growth, completed stages, templates and practice records live inside one closed `更多` disclosure (with the review debt count in its summary). This removes the wall of review/evidence/growth cards while keeping every destination one click away.
- **Left-edge accent removed.** Review/evidence/active-stage cards no longer use `border-inline-start`; active stage uses a full border + tint instead. Geometry gate asserts no 2px+ left edge.
- **Plan-step card entry.** Learning's current card now has `用训练卡练这一步` in addition to the discussion action. It mints a card with `source=formal_plan_step` and the live plan binding. Real run: card `把 queue_lock 接入真实队列` (`stage-review`, revision 3) → UI verify **7/7** → reflection → Return **POST 200** → implemented → evidence adopted → plan advanced to **4/4**, Growth **5 次验证通过**. The exercise was completed with a minimal `RealQueueAdapter` (`create_real_queue_adapter`, `Queue.get`, `Queue.task_done`) in the isolated test project; py_compile and pytest passed.
- **Stale post-return action fixed.** Status transitions now sync `active_training_card_routing.selected_card`, and snapshots reconcile a stale routing copy from the canonical card map. A returned card no longer keeps showing `带结果回到教练`.
- **Plan generic next step localized.** `Review the result and decide whether to widen scope.` → `复核结果，再决定是否扩大范围。` at read time for Chinese workspaces (plan + runtime overlay).
- **Fast first paint.** The webview initializes `syncStatus` as current when the injected cached bootstrap already carries a plan; the Learning resolver paints the cached step disabled with `恢复中…` instead of replacing the card with a full restoring state. Installed measurement: first action **1.7s**, `SAW_RESTORING=false`; click `在编辑器中打开` opens the Trainer editor tab.
- **Icon/position polish.** The surface control is now a quiet borderless external-link glyph, aligned on the stage line instead of floating below the header; the collapse glyph mirrors it. Both remain keyboard-labeled and 26px.
- Gates: full server suite **3754 passed**; extension suite exit 0; `verify-ui-geometry` **476 passed**; CSS balanced; `npm run check` clean.
- Remaining: Journey E editor-panel/long-code/stream-interrupt; Journey F provider timeout/wrong key/port conflict; PDF capture/download and multi-window isolation; M3.1 unusable.

## 2026-11-04 — ZCode 信息流研究 + Coach 密度收敛（真实安装态）
- **Source studied**: `zai-org/ZCode` @ `a9fe401e` (v3.17.2), shallow-cloned to `/private/var/folders/.../T/opencode/zcode-src`. Key files read: `packages/ui/src/v4/ConversationTimeline.tsx`, `ConversationTurnGroup.tsx` (turn/history grouping, `AssistantHistoryStatus`), `ConversationAgentToolCallRow.tsx`, `ToolCallBlocks/ToolSummaryRow.tsx`, `components/ai-elements/chat-loading.tsx`, `ConversationUserInputBubble.tsx`, `conversationTurnFlowItems.ts`, `conversationTurnWorkSegments.ts`, `ConversationDraftEmptyState.tsx`.
- **What ZCode does differently, and what landed in Trainer**:
  1. **One working line with elapsed time** (`ChatLoading`: working label + tabular duration, timer isolated in its own component). Trainer now renders `CoachWorkingIndicator` with the sheen label plus `1 秒 / 2s`; the timer lives in the leaf, so the thread does not re-render each second.
  2. **Work history is a collapsed one-line summary** (`AssistantHistoryStatus`: “已工作 12 秒” + chevron, expanded to compact tool rows; default open only while running). Trainer now renders `.coach-work-trail` from the existing tool parts: one muted line (`已核对 N 项上下文`) that expands to one row per tool with a safe status hint. Tool calls stay hidden from the reply body.
  3. **User input is a compact bubble with no provenance chips** (`ConversationUserInputBubble`: text + attachments only). Trainer removed the `意图/方式/策略/选区/文件` attachment chips from the thread; metadata remains in the raw payload for sharing/diagnostics.
  4. **No canned pre-reply sentence**; the first content is the working line. Removed both `正在梳理你的问题…` and `正在整理当前步骤…` strings and their tests; e2e now asserts the working label instead.
  5. **Narrow content measure** (ZCode uses container-query widths). Trainer Coach now has `--coach-gutter: clamp(16px, 4vw, 28px)` and `--coach-content-max: 660px`, applied to the thread/empty state and the composer; the assistant left hairline and duplicated composer busy hint were removed.
  6. **Compact suggestion chips**: the three starter prompts are now wrapping pills instead of three full-width bars (the user's “铺得太满” screenshot).
- **Evidence (installed VSIX `1.3.4`, isolated real profile)**:
  - Empty state narrow (393px content): content x=16, width 346; starter chips 96/70/109px; no overflow. `.tmp/first-use/166-empty-narrow.png`.
  - Wide preview column: at a 1000px host, thread width **660px** (cap), composer **604px** (660 − 2×28). `.tmp/first-use/182-preview-wide-1000.png`.
  - Real working line: label `工作中`, elapsed `1 秒`; final answer rendered correctly; `hasMeta=false`, `hasCanned=false`, `innerW=docScrollW=411`. `.tmp/first-use/180-real-coach-working.png`, `.tmp/first-use/181-real-coach-settled.png`.
  - E2E `keeps stream progress in the Coach thread…` PASS (asserts `工作中`, no canned sentence). Extension suite exit 0; geometry **476 passed**; CSS balanced; `npm run check` clean.
- **Honest boundaries**:
  - The collapsed work trail is implemented but **not yet exercised by a real tool-using turn** (`hasTrail=false` on the short Q&A above). Needs a Coach turn that actually calls read/search tools.
  - Real sidebar widening via the sash only reached 411px; the 660px cap is proven in the preview harness, not in a real 800px sidebar.
  - Journey E (long code, session/model switching) and F (bad key, timeout, offline, port conflict) remain **NOT_EXECUTED**; PDF capture still blocked upstream; multi-window isolation not executed.
- Next: real tool-using Coach turn for the trail, then Journey E/F; keep the ZCode study in this file as the design reference.

## 2026-11-04 — 目标模式、技能列表与中性选中态
- **Goal mode（让人动手）**: a one-goal active-learning contract. The composer toggle sends `goalMode` → host `goal_mode` → `SessionMessageRequest.goal_mode` → `coach_context.goal_mode`; the prompt requires one tiny action first, waits for the attempt, corrects one misconception, and ends with a 3-minute review. No plan/card/evidence is minted by the flag itself.
- **In-progress goal bar**: `CoachGoalBar` shows `进行中的目标`, the goal text, elapsed time, pause/resume, end, and expandable details. Store-backed (`goalText`, `goalStartedAt`, `goalPaused`, `goalPausedAt`) so a pane remount does not drop it. Evidence: `.tmp/first-use/201-goal-bar.png`, `202-goal-paused.png`, `203-goal-expanded.png`.
- **Skill list**: `$` palette now has the `技能` section, cube icon per row, one-line description, optional `个人` tag for custom skills, compact 38px rows, and a neutral selected row. The blue inset/underline selected treatment is gone from the palette, nav tabs, plan current/active rows, resources tree/rows/folder toggles, session history, and selected dots. A CSS scan reports **0** remaining accent short-edge selection selectors.
- **Evidence**: `206-palette-compact.png` (38px rows, `activeBg rgb(42,45,46)`, `boxShadow none`, 13px title, 12px detail); `207-noaccent-coach.png` (nav underline neutral `rgba(204,204,204,.3)`, not `#0078d4`); `208-noaccent-history.png` (active session neutral background, no inset); `210-noaccent-resources.png` (selected row neutral `rgb(42,45,46)`, `border-left: transparent`, no shadow). `innerW=docScrollW=411` on all.
- **Tests**: extension suite exit 0; `npm run check` clean; CSS balanced; `verify-ui-geometry` **476 passed**; server goal-mode prompt test 2 passed. VSIX rebuilt/reinstalled after the palette/neutral changes.
- **Honest boundaries**:
  - Goal-mode **model behavior is UNVERIFIED**: the clean-workspace run hit a disabled send, and the real profile has an active training handoff that can intercept the turn. The prompt contract and UI are tested; a real model following the do-first loop is not yet proven.
  - The `设为目标` action is implemented on the latest assistant message, but a history-session probe found 0 action buttons; it needs a clean session with a latest assistant.
  - Learning’s plan is 4/4 complete, so no `.coach-plan-view__stage-row.is-active`/`.is-current` row existed for a visual check; the CSS was neutralized and the scan is clean, but the active Learning state still needs a live plan.
  - Full accent **borders/washes** on some settings options remain (not short-edge; the request covered short-edge selection).
  - Journey E/F, PDF/GitHub download, multi-window isolation remain **NOT_EXECUTED**.

## 2026-11-04 — audit P1 fixes (training stream + short-thread anchor)
- Restored the `training_*` guard in the live Coach bubble (`CoachConversationView`): raw card-generation chunks can no longer render as assistant prose. The source test now asserts the guard.
- Removing the resume banner reopened a short-thread dead zone; the first active message now takes the slack (`.coach-conversation-view__list--active > :first-child { margin-top: auto; }`), resolving to 0 once the thread overflows. Geometry is **476 passed** (the earlier handoff claim is now true for this tree; the audit’s red run was the interim state).

## 2026-11-04 — top-down thread flow, reply-level goal entry, final evidence
- **Thread flow**: removed the short-thread bottom anchor. Messages now fill from the top and append downward (ZCode timeline order); the empty room belongs below the last turn, not above the first. Geometry gate flipped to assert `firstOffsetTop <= 24` and `bottomGap >= 0`; **477 assertions pass**. Real session probe: `items=3, assistants=1, firstOffsetTop=4`; evidence `215-flow-top-final.png`.
- **Goal entry**: removed the separate goal icon from the composer toolbar (user request). Goal mode is entered from a reply’s `设为目标` action; the bar is the only goal UI. The action is present on a real session (`quickActions` includes `set-goal`) and the bar title now uses the **learner’s preceding turn** (not the assistant’s error text): `读一下 src/conversation_router.py…`; `goalIcon=false`; evidence `216-goal-title-from-user.png`.
- **Selected-state accent removal**: all accent short-edge selected indicators are gone (nav underline neutral, plan current/active neutral, resources tree/rows/folder neutral, history active neutral, palette active neutral, selected dots neutral). CSS scan reports 0 remaining accent short-edge selection selectors. Evidence `207-noaccent-coach.png`, `208-noaccent-history.png`, `210-noaccent-resources.png`, `211-palette-final.png`.
- **Palette**: compact 38px rows, 6 rows fit (`clientHeight=256`, `lastBottom=255`), active `rgb(42,45,46)`, `boxShadow=none`, no overflow at 411px.
- **Tests**: extension suite exit 0; `npm run check` clean; CSS balanced; geometry **477 passed**. VSIX rebuilt/reinstalled after these changes.
- **Still open**: goal-mode **model behavior** (do-first reply) is unverified; the clean-workspace send was blocked, and the real profile can be intercepted by training handoff. Journey E/F, PDF/GitHub download, multi-window isolation remain NOT_EXECUTED. Full accent borders/washes on some settings options remain by design (not short-edge).

## 2026-11-04 — goal mode is for mastery; clean-workspace real journey
- **Mastery contract**: goal mode now requires more than a correct action. The prompt asks the learner to explain the reasoning in their own words and handle one small variation; it only ends when they can do it unaided, explain why, and transfer. The goal bar’s expanded details now show `完成标准：做对 → 讲清为什么 → 迁移到一个小变化` in eight languages. Server goal-prompt test 2 passed.
- **Fresh-session entry**: the composer toolbar goal icon stays removed (user request). A quiet `设为目标` text action now lives in the Coach empty state, outside the input; it opens the goal bar with `等待你说出目标`. The reply-level `设为目标` action remains.
- **Clean-workspace real journey (installed VSIX, real profile, clean workspace)**:
  - Admission panel: `发现项目 / 加入 Trainer / 选择项目文件夹 / 仅浏览 / 忽略项目`; composer disabled at first.
  - Clicked `加入 Trainer`; composer enabled, empty state showed `设为目标`.
  - Goal entry opened the bar (`等待你说出目标 0 秒`) and the placeholder `想快速学会什么？例如：用 with 正确加锁`; expanded details showed the mastery criterion.
  - Goal sent: `我想学会用 with 正确加锁，并判断异常时锁会不会释放。`
  - First real reply (290 chars): one tiny code observation + `请回答：print(lock.locked()) 输出 True 还是 False，以及原因` — do-first, no lecture. Evidence `220-goal-clean-first.png`.
  - Learner attempt about `with` + exception; second real reply (354 chars): corrected the `with` exit behavior, named two boundaries (`acquire()` failure before `with`, `__exit__` swallowing), and gave one next validation (`块内主动抛异常验证 release()`). Evidence `221-goal-clean-second.png`.
  - This proves the loop is active-learning, but the **mastery closure** (teach-back + transfer) is not yet reached; a third turn is needed.
- **Admission anomaly (not fixed)**: the command log shows `trainer.workspace.ignoreProject` followed by `trainer.workspace.adoptProject`; the UI operation text said `The current project will be ignored by Trainer.` even though the project directory/session was created under `learning/Projects/project-dd8eb78c...` and the sidecar started the session. The final message is contradictory/stale; P1/P2 for the next first-use round. Log: `user-data/logs/20261104T105558/window1/exthost/output_logging_20261104T105600/1-Trainer.log`.
- **State persistence gap**: `goalMode`/goal text are UI-only and not restored after a VS Code restart; a real “进行中的目标” should survive reload. Not fixed.
- Tests: server goal prompt 2 passed; extension suite exit 0; CSS balanced; geometry 477; VSIX rebuilt/installed after the mastery/entry changes.
- **Resumed-session turn 3**: after relaunch the goal bar was gone (`goalBar=false`) because goal state is UI-only; using `设为目标` on the last assistant set the bar title to the learner’s **attempt**, not the original goal. The third model reply corrected the inside/outside-`with` boundary and asked the learner to confirm where `print(lock.locked())` runs; it did **not** accept a bare answer or claim mastery. Evidence `222-goal-mastery-turn3.png`. Mastery closure (teach-back + transfer) still needs a further correct turn, and goal persistence is the next state fix.

## 2026-11-04 — rich reply rendering: syntax highlight, math, mindmap, table
- **Why code blocks had no syntax highlighting**: Shiki’s default `codeToHtml` uses the Oniguruma **WebAssembly** engine, which the VS Code webview CSP blocks; the rejection was swallowed and every block fell back to plain `<pre><code>`. The model-HTML sanitizer would also strip Shiki’s inline `style` token colors.
- **Fix**: Shiki now uses `createJavaScriptRegexEngine()` + an explicit cached `createHighlighter()` per language/theme (no wasm), and trusted Shiki HTML bypasses the model-HTML sanitizer (the code is escaped by Shiki; the markup/styles are library-owned). Mermaid’s strict SVG now also keeps its library `<style>`/style attributes; `securityLevel: "strict"` remains, and model-provided part renderers still sanitize.
- **Real VS Code format audit (clean workspace, installed VSIX)**: one reply with code + math + mermaid + table produced:
  - `codeBlocks=5, codeSpans=92, codeStyled=63` with real token colors (`#FF7B72`, `#E6EDF3`, etc.).
  - `katex=4, katexDisplay=1`; raw `$...$` no longer leaks.
  - `mermaid=true, mermaidSvg=true, mermaidError=""` for a `mindmap`.
  - `tables=1`.
  - Evidence `223-format-audit.png`.
- Tests: extension suite exit 0; `npm run check` clean; CSS balanced; VSIX rebuilt/installed. An independent security/regression audit of the trusted Shiki/Mermaid bypass is running separately.
- Still not audited in this pass: remote images, external links, task lists/strikethrough in a single real reply; broader Journey E/F; goal-mode mastery persistence/closure; the contradictory admission message noted above.
- **GFM follow-up audit**: a second real reply rendered `h1=1, h2=1, strong=1, em=1, del=1, blockquote=1, ul=2, ol=1, task checkboxes=2, inlineCode=1`; the link rendered with `href=https://example.com` but **no `rel`** (pending hardening). The table in this particular reply stayed plain because the model copied the prompt without the blank line GFM needs after the task list; the previous format-audit reply rendered `tables=1`, so the table renderer itself is proven. Evidence `224-gfm-audit.png`.
- **Link hardening verified**: a real reply with `[Example](https://example.com)` rendered `<a href="https://example.com" target="_blank" rel="noopener noreferrer">`. The link does not replace the Trainer webview. (Remote image rendering still not audited.)

## 2026-11-04 — independent renderer security audit + P2 fixes
- Independent audit: **no P0/P1**. Shiki escapes code text and only emits static bundled-language/theme markup; Mermaid strict mode runs the full SVG through DOMPurify 3.4.1 and cannot be downgraded by `%%{init}%%`. The two sanitizer bypasses are defensible.
- Fixed the audit's P2s:
  - One Shiki highlighter **per theme** (not per language), languages loaded with `loadLanguage()`; failed highlighter promises are deleted; no 242-language/per-language cache.
  - Removed the unused `className` prop from `ShikiCodeBlock` (latent unescaped attribute sink).
  - Added `form-action 'none'` to the webview CSP, closing the Mermaid `foreignObject` form/phishing surface.
  - Tightened source guards for `loadLanguage`, the removed prop, and the CSP.
- Final installed VSIX audit: `codeSpans=92, codeStyled=63`, `katex=4`, `mermaidSvg=1`, `tables=1`, CSP `form-action 'none'=true`; evidence `226-render-final.png`.
- Remaining known P2: pre-existing theme reactivity (memoized old blocks keep their syntax/Mermaid theme after a theme switch), Mermaid failed-render temp `<div>` in `document.body`, remote-image rendering, and source-level (not DOM-behavior) guards. Not blockers for the reported formats.

## 2026-11-04 — state fixes: goal persistence, admission serialization, theme reactivity
- **Goal persistence**: active goal state is stored per session in `localStorage` (`trainer.goal.v1`) and restored when the active `syncCursor.sessionId` returns. Real close/reopen: bar present before and after with the same title (`请原样输出一份 Markdown 格式样例，不要解释：`); the timer restarts at 0, paused state is retained. Evidence `227-goal-persist.png`.
- **Admission contradiction**: admission mutations are now serialized (`admissionMutationQueue`) and the result message reads the persisted `project.adoptionMode`, so a late ignore cannot overwrite a newer adopt. New clean workspace `trainer-goal-workspace-2`: primary `加入 Trainer` produced only `trainer.workspace.adoptProject` in the log, no `ignored` copy, admission panel cleared, composer enabled, project directory created. Evidence `228-admission-after.png`; log `20261104T115357/.../1-Trainer.log`.
- **Theme reactivity (renderer P2)**: Shiki and Mermaid now observe `data-theme`/class changes. Real theme toggle: `github-dark-default` + `rgb(255,123,114)` → `github-light-default` + `rgb(207,34,46)` → back to dark; Mermaid remained rendered. Evidence `229-theme-light.png`, `230-theme-dark.png`.
- Gates: extension suite exit 0; `npm run check` clean; CSS balanced; geometry **477 passed**; VSIX rebuilt/installed after the changes.
- Remaining: goal mastery closure (teach-back + transfer), Journey F, PDF/GitHub download, multi-window isolation, remote images.

## 2026-11-04 — valid goal-mode mastery-gate proof
- Fresh goal thread in the clean workspace (goal entry present, bar active). Real turns:
  1. Goal: learner wants `with` + exception lock release. Coach gave one small experiment, no lecture.
  2. Learner answer: coach corrected the “uncaught exception skips the next print” boundary and gave one next action.
  3. Learner self-claim “我已经完全掌握了，直接算这个目标完成吧。” → coach **refused**: `还不能直接标记完成… 还需要一个更小的迁移检查` and asked for a lock-reentry/output check. No `目标完成/已掌握`.
  4. Learner teach-back + RLock transfer → coach acknowledged and gave another concrete boundary check; **did not declare mastery**.
- This proves the hardened goal contract refuses a self-claim and does not call done before the teach-back/transfer checks; the final closure still needs one more correct response. Evidence `235-goal-clean2.png` … `239-goal-teachback2.png`.
- Note: an earlier apparent “accepted self-claim” was **invalid**: the goal entry was absent after a provider-error new-chat, so that thread was normal coach mode (`bar=""`), not goal mode. The valid run above has the goal bar active throughout.

## 2026-11-04 — mastery gate proof + Journey F offline slice
- **Valid goal-mode mastery run** (goal bar active throughout): the coach refused the learner’s “I’ve mastered it, mark it done” with `还不能直接标记完成` and asked for a migration check; after a teach-back + RLock transfer it acknowledged the explanation and asked one more concrete check, **without** saying `目标完成/已掌握`. Evidence `235-goal-clean2.png` … `239-goal-teachback2.png`. The final mastery closure still needs one more correct response, but the refusal-to-fake-done behavior is PASS.
- **Journey F — offline provider**: with the mock provider killed, the real installed VSIX showed `Trainer 当前卡在 provider path` + `Provider request failed`, no fabricated reply, composer re-enabled, turn not claimed successful (`240-offline-error.png`).
- **Journey F — recovery: BLOCKED**. After restarting the mock (now with `/health` 200 and `/v1/models` 200), resend still failed with the same `Provider test failed: Provider request failed` (`241-offline-recovered.png`, `242-offline-recovered-health.png`). Sidecar log: `[provider] reply failure category=unknown status=None retryable=False detail=Provider test failed: Provider request failed.` The mock received a normal chat POST. This is either a stale provider-test/connection state or a mock-provider mismatch; not yet root-caused. Wrong-key, timeout, and port-conflict paths remain NOT_EXECUTED.

## 2026-11-20 — Unified Learning Waves 1–4 Complete (Ready for T-0028 Owner Sign-Off)
- **Branch & archived reliability reference**: work landed cleanly on `codex/trainer-unified-learning`; selective verification-branch fixes were ported and the old verification branch is archived at tag `archive/trainer-convergence-verification-2026-11-20` -> `1512c070`.
- **Key Waves 1–4 commits**:
  - Wave 1 (Strategy & Unified `<LibraryRoot>`): `40ac5f77` (`docs/STRATEGY.md`), `434f3903` (single `<LibraryRoot>` runtime/resources/memory + `GET /workspace/storage-truth` + zero code-repo pollution).
  - Wave 2 (Calm UX & Copy Vocabulary): `d9aecc1c` (plain progress sentence + drawer declutter), `b214497c` (3-button calm message action bar), `aba4c2de` (`verify:copy-vocabulary` + expanded `verify:ui-geometry`), `edb7c6dc` (browser sidepanel localization & settled practice card).
  - Wave 3 (Selective Reliability Ports, Latency & Productivity Convergence): `ba3f6d87` (sidecar port-race retry), `52faf066` (atomic SQLite evidence + ledger transaction), `f973bd7e` (`PROJECT_WRITE_TOOL_NAMES` denylist, `MINIMAL_COACHING_SYSTEM_TEMPLATE`, shared transport language-integrity store, `pedagogy/productivity.py`), `589c3daf` (branch archive + 2-destination `verify:local-latency`).
  - Wave 4 (Budgeted Proactivity & Idempotency Story): `58c02e0b` (`proactive_budget.py`, `POST /proactive/evaluate`, `learner_actively_typing` guard + `CodingGapTracker`, weakness-diagnostic `## Weakness Recall Cue`), followed by `server/tests/test_idempotency_story_acceptance.py`, `scripts/run-idempotency-story.mjs`, and convergence matrix updates.
- **Bundled server & native binary note**: `extension/bundled/server/` is kept synchronized with `server/` via `node extension/scripts/sync-bundled-server.mjs`. Note that standalone native binaries under `extension/bundled/bin/` (e.g. `extension/bundled/bin/darwin-arm64/trainer-sidecar`) are rebuilt in CI PyInstaller packaging rather than inside local JS/Python test commits.
- **Live external provider validation & `T-0028` sign-off (still BLOCKED — human-only)**:
  - No live provider keys are stored in the repository (`verify:credentials` scanned 4,889 files, 0 findings), and `scripts/run-idempotency-story.mjs` fails closed with exit code `2` when `PROBE_PROVIDER_BASE_URL` / `PROBE_PROVIDER_API_KEY` are unset.
  - Owner sign-off command (supply live credentials):
    ```bash
    PROBE_PROVIDER_BASE_URL="https://api.example.com/v1" \
    PROBE_PROVIDER_API_KEY="sk-..." \
    PROBE_PROVIDER_MODEL="MiniMax-M3.1-Flash" \
    node scripts/run-idempotency-story.mjs
    ```
    Then record human owner review in `.trainer-convergence/acceptance-matrix.json` for `T-0028` (`teaching_acceptance`).

## 2026-11-20 — 1.5.0-rc 工程收口、UI/资料库收敛与真模型直连实测
- **核心修复提交**：
  - `5d77ae3`：修复 Journey F 断网恢复后重发滞留旧 `Provider test failed` 状态与兼容接口 M3.1 SSE 尾包未关闭兜底（`POST_FINISH_DRAIN_TIMEOUT_SECONDS`），补齐行为测试并同步 `extension/bundled/server/`。
  - `2e26c44`：将 `ProviderAgentBinding` 局部代理绕过收口到 `_async_http_client()`，仅对 loopback 地址传 `trust_env=False`，保持测试替身兼容与非环回请求签名不变。
  - `5911cbf` & `0dd62f1`：将 `LearningDrawer` 底部能力展示收敛为**单一统一 4 段能力条**（8 语言正式化术语与文案），隐藏 `Resources` 冗余上下文恢复提示条、增加工具栏搜索框 `data-resource-search-input`，并默认对导入/同步资源仅输出 `.md` + 配套提取图片（`assets/<id>/*.png`）。
  - `d2d6460`：修复含内联页脚卡片（`FocusedPractice` + `InlineProgressCard`）时 `App.tsx` 自动滚动把最新助手回复推离视口的问题，并对齐 4 个 Playwright spec。
  - `b4c9e12`：在 `verify-vsix-e2e.mjs` 跨工作区重开真相校验前对生成候选卡执行 `save + start`，并重编最新 macOS PyInstaller `trainer-sidecar` 二进制（`bundle:sidecar:binary` + `verify:sidecar-runtime` 通过）。
- **真模型多轮验证（已去除干扰性本机代理环境变量；仓库与报告不含密钥及私有地址）**：
  - `MiniMax-M2.7`（`output/idempotency-story-m2.7.json`）：`turn0` 首字 `1183ms`（≤ 2000ms 达标，总耗时 `1283ms`），`turn1` `36619ms`（2 attempts，1775 字），`turn2` `17335ms`（960 字）；全部 `completed=true`、`providerFallback=false`。
  - `MiniMax-M3.1-Flash`（`output/idempotency-story-m3.1-flash.json`）：`turn0` 首字 `3419ms`（略高于 2000ms 目标，总耗时 `3655ms`），`turn1` `17380ms`（1760 字），`turn2` `16638ms`（822 字）；全部 `completed=true`、`providerFallback=false`，验证了 M3.1 SSE 正常关闭。
  - 两轮均验证 `all_under_library_root=true`、`outside_library_root=[]`、代码仓零污染（仅原始 `payments.py`）。
- **全量门禁结果（截至 `d2d6460`）**：
  - `ruff check server/app server/tests`：0 错误；`verify:server-pyright`：0 错误。
  - `pytest server/tests -n 4 -q`：4185 passed，28 subtests passed（注：`-n auto` 高并发下 `test_turn_stream_overhead_under_budget_without_extra_preflight` 偶发争抢 728.9ms > 500ms，standalone 0.94s 与 `-n 4` 全量通过）。
  - `npm run check && npm run build`、`npm run test:extension`、`npm run verify:version`、`npm run verify:credentials`（4998 files, 0 findings）、`npm run verify:copy-vocabulary`（59 files, 0 violations）、`npm run verify:ui-geometry`（288 passed）、`npm run verify:local-latency`（5 actions <= 1000ms）、Playwright 9 核心 spec（171 passed）。
- **试用指南与诚实 BLOCKED 边界**：
  - 新增 15 分钟本机试用与 `T-0028` 签收清单：[docs/TRIAL-1.5.0-RC.md](../docs/TRIAL-1.5.0-RC.md)。
  - `T-0028`（`teaching_acceptance`）与 `remote_ssh_e2e` 保持诚实 `BLOCKED`；最终 VSIX 打包与 `verify-vsix-install` / `test:vsix-e2e` 在干净源码提交后执行并以 `chore(release)` 清单记录。

## 2026-11-21 — 体验极简收敛、唯一输入框主权、RethinkFun 状态流教学内核与四层反自欺验收
- **产品契约锁定 v2.1 与原子提交**：
  - `33570c0`：锁定 `.trainer-convergence/product-contract.md`（v2.1）、`docs/STRATEGY.md`、`AGENTS.md`；统一 `prompts.py`、`skills/builtin.py`、`pedagogy/principle_explainer.py` 的 RethinkFun 状态流内核与禁词纪律；新增只读工具 `inspect_learning_truth` 与显式资料库落盘工具 `save_lecture_note`（严格写入 `<LibraryRoot>/Trainer Library/`，零代码仓污染）；新增 `ProviderConfig.ignoreSystemProxy` 直连绕过与环境代理冲突人话提示。
  - `bb44434`：修复英文系统提示词混入 CJK 字符的问题（将中文禁词表严格限定在 `zh-*` 语境注入），并同步 `test_provider_service.py` 拒绝工具清单。
  - `7acebbe`：落地唯一输入框主权与界面减法——消除 `InlinePracticeAnswer` 第二 `<textarea>` 并移除对话流内 `TrainingCardLibrary` CRUD 面板，给内联练习卡增加 `收起练习 / 展开练习` 折叠条；统一 `Goal mode` 至服务端目标真相并取消 webview `localStorage` 双份目标态；实现 `project-found` 冷启动零拦截（先通过唯一输入框对话，首次持久化温和绑定 `<LibraryRoot>`）；彻底分离资料页顶部 `筛选资料` 与底部 `围绕资料提问或生成讲稿`，点击 `.md` 默认调用 VS Code `markdown.showPreview` 图文预览（次要保留“打开源文件”与行内快捷提问）；Settings → 连接详情补齐 8 语言“网络代理 / 忽略系统代理（直连）”开关并修通 `browserSidecar.ts` 与 `App.tsx` 自动滚动竞态；清零 8 语言内部系统词泄漏（`训练卡库` / `确认入库` / `后续和回看` / `UI proxy` / `事件账本`）。
  - `0b0e13f`：基于真实模型实测揪出并根治 3 个 P1 真问题——为 RethinkFun 深度讲稿（4096 / 推理型模型 8192）和推理型模型工具回合（4096）放宽输出 token 预算；修正 `prompts.py` 与 `tools.py` 中 `coach_finalize` 过期误导提示，确保深度讲稿、代码诊断与真相汇报直接输出完整纯文本；扩展 `note_request.py` 自然中文匹配并在 `App.tsx` / `router_support.py` 中对单输入框真相查询与讲稿落盘自动开启 `useAgentLoop`；要求 `inspect_learning_truth` 回复将内部字段名转译为自然中文。
- **四层反自欺验收结果（截至干净代码头 `0b0e13f`）**：
  1. **工程门禁全绿**：`ruff check` 0 错误、`verify:server-pyright` 0 错误、`pytest server/tests` 全量 4190 passed / 28 subtests passed（注：并发期间 `test_workspace_classifier.py` 1 处 tmp-path 偶发抖动已独立复跑 59/59 0.12s 通过）、`npm run check && npm run build`、`npm run test:extension` 全绿、`verify:version`（1.4.4）、`verify:credentials`（5020 文件 0 泄露）、`verify:copy-vocabulary`（66 文件 0 违规）、`verify:ui-geometry`（360/360 含 `textareas <= 1` 唯一输入框断言）、`verify:local-latency`（5 动作 ≤ 1000ms）、Playwright 12 核心 spec（203/203 passed）。
  2. **真实视觉像素审查**：逐张核查 340px/420px × 深色/浅色 × 中/英 真实渲染截图（对话展开/收起练习、资料页、学习抽屉、设置页连接详情含网络代理开关），修正了审查中发现的资料行标题居中与列对齐缺陷，确认同屏绝无双输入框、无冗余页脚堆叠、零溢出裁切。
  3. **安装态实机验证**：基于干净 `0b0e13f` 重编独立 `darwin-arm64` PyInstaller 侧车二进制（237 文件 `sha256: 88057b06...`）并通过 `verify:sidecar-runtime`，重新打包干净源码态 VSIX（`sourceDirty: false`），通过 `verify-vsix-install`（`metadataJunkCount=0`）与 `test:vsix-e2e`（36/36 installed-host steps PASS）。
  4. **真模型 4 场景实测（`MiniMax-M2.7`，本机存在系统代理环境变量且启用 `ignoreSystemProxy: true` 直连通过，仓库与报告不含任何密钥与私有地址）**：
     - Case 1（短问答）：首字 `3521ms`（本轮中转高于 2s 目标，如实记录），`0` 垫词 / `0` 术语，3 句直指缺口 + 反问。
     - Case 2（RethinkFun 深度讲透 Attention `1/√d_k` + 落盘笔记）：**14/14 项门槛全达标**，`0` 垫词 / `0` 术语，成功调用 `save_lecture_note` 将规范 `.md` 落盘至 `Trainer Library/.trainer-resources/markdown/resource-e5431af414.md`。
     - Case 3（`payments.py` 真实代码引导）：真实读完 7 行代码且**零修改用户代码仓**（`paymentsCodeUntouched=true`），给出 3 方案对比、2 个静默边界 bug、3 行接口契约与 3 条可复现本地 pytest 标准。
     - Case 4（唯一输入框 `inspect_learning_truth` + 推理型复习）：准确报出 3 个阶段与 0 条验证证据（不编造），基于刚存讲稿出 4 问闭卷推导复习题；单次复述工具字段词 `handoff` 已在 `0b0e13f` 补齐自然语言转译指令。
     - 存储真相：`all_under_library_root=true`、`outside_library_root=[]`、代码仓仅保留原始 `payments.py`。
- **诚实 BLOCKED 边界**：`T-0028`（`teaching_acceptance` 人工最终教学签收）与 `remote_ssh_e2e`（真实 Remote-SSH L2 窗口）继续保持 `BLOCKED`，待本人按 [docs/TRIAL-1.5.0-RC.md](../docs/TRIAL-1.5.0-RC.md) 完成 15 分钟安装态试用后签核。

## 2026-11-21 — 全窗口工作区接入、唯一本机 `<LibraryRoot>` 加固、8 语言补全与真实 Remote-SSH L2 实测通过
- **核心修复提交**：
  - `eec0e98`（工作区接入 + Remote Companion URI 修复 + 单 `<LibraryRoot>` 守卫）：
    - 修复真实 Remote-SSH 下 UI 宿主传入 `vscode-remote://<remoteName>+...` URI 与远端工作区扩展 `file://` 根目录 scheme 不匹配导致全部操作被 `WorkspaceScopeError` 拒绝的致命缺陷（`remote-extension/src/extension.ts` 新增 `normalizeIncomingUriForFolder` 并支持多根 `environment(uri)` 严格校验）；
    - 空窗口、多根无活动编辑器窗口下 `WorkspaceAdmissionPanel` 主动作收敛为「选择项目文件夹」，`chooseWorkspaceProjectCommand` 多根时弹出已打开文件夹 QuickPick + 「浏览其他文件夹…」，保留 `vscode-remote://` URI 并通过 `WorkspaceTrustGuard.setPreferredWorkspaceProject` 持久化本窗口选中态；
    - 冷启动首次在输入框发送时自动关联项目并在进入 `managed` 后**自动发送排队首条消息**（失败/取消时清空队列并保留草稿）；
    - 严守唯一本机 `<LibraryRoot>`：`chooseTrainerWorkspaceRootCommand` 拒绝非 `file://` 远端目录作为根目录，打开 `<LibraryRoot>` 本身作为项目时明确报错，彻底移除静默把 `<LibraryRoot>` 上移到父目录的 `relocateWorkspaceRootForProject`；`root-missing` 下选择项目无缝先引导选根目录再绑定项目；补齐 8 语言宿主接入文案；新增 `extension/tests/remoteExtensionResolveUri.test.js`、`e2e/trainer-workspace-admission.spec.js` 及 5 项宿主行为测试。
  - `67a9418`（8 语言完整性 + 硬门禁 + 8 语言单输入框工具触发）：
    - 补齐 `appUiCopy.ts` 全部 8 处缺失键并修正 2 处 `ja-JP` 混入韩文字符的缺陷；补齐 `settingsText.ts` 全部 91 处缺失 8 语言词条（`de-DE`/`fr-FR`/`es-ES`/`pt-BR`/`ja-JP`/`ko-KR` 零英文回退）；`formatReviewDueLabel` 改用当前 locale；
    - 扩展单输入框真相查询（`inspect_learning_truth`）与讲稿落盘（`save_lecture_note`）自动触发至全部 8 语言（`App.tsx`、`router_support.py`、`note_request.py`，同步至 `extension/bundled/server/`，新增 8 语言 pytest）；
    - 新增硬回归门禁 `scripts/verify-i18n-completeness.mjs`（`npm run verify:i18n`），并实际渲染及像素审查 340px 下 `de-DE`/`fr-FR`/`es-ES`/`pt-BR`/`ja-JP`/`ko-KR` 的设置页与学习抽屉截图（0 溢出、0 英文/中文泄漏）。
  - `f6dfb98`（安全卫生）：清除追踪文件 `docs/maturity/2026-10-28-deep-audit.md` 与 `scripts/live-long-horizon-provider-probe.py` 中遗留的私有中转地址，后者改为强制要求环境变量 `TRAINER_LIVE_PROBE_BASE_URL`。
  - `c31e5f6`（单 `<LibraryRoot>` `trainer.sqlite3` 迁移修复）：真实 Remote-SSH 实测中发现 `migrateGlobalStorageToLibraryRootIfNeeded` 与 `workspaceAdmissionCommands.ts` 仅检查 `trainer.db`、漏掉了实际生成的 `trainer.sqlite3`；现已同时兼容 `trainer.sqlite3` 与 `trainer.db` 并补齐行为单测。
- **真实 Remote-SSH Layer-2 实测通过（`remote_ssh_e2e: PASS`）**：
  - 使用最新独立打包的本机 macOS UI 宿主 `trainer-extension@1.4.4`（`extensionKind=1`）+ 远端 Linux x86_64 宿主 `trainer-workspace-companion@1.0.0`（protocol v2），通过真实 VS Code `1.145.2`（`c4453f8e`）`ms-vscode-remote.remote-ssh` 连接实机 Linux 服务器，**19/19 步全绿通过**：
    - `remote_window_attached`（`ssh-remote`）、`local_trainer_activated`、`companion_capabilities_v2`（9/9 能力全开）；
    - 使用 UI 宿主 `vscode-remote://` URI 完整通过 `stat`、`read_file`、`list_directory`、`find_files`、`search_text`、`hash_artifact`（SHA-256 字节一致）、`diagnostics`、`environment`（`os=linux, arch=x64`）；
    - 安全边界实测：读取 `/etc/passwd` 被 Companion fail-closed 拦截（`outside the active workspace`）；
    - 远端真实执行：`python3 -B -m unittest` 通过（`exit_code=0`）与故意失败脚本（`exit_code=1`）均诚实回报；
    - 宿主接入与存储核验：`trainer.workspace.adoptProject` 将远端项目绑定至本机唯一 `<LibraryRoot>`，`trainer.remote.companionState=ready`，`trainer.remote.verify` 通过，`trainer.memory.refresh` 正常，本机 `<LibraryRoot>/.trainer/workspace.json` 与 `<LibraryRoot>/.trainer/runtime/trainer.sqlite3` 均落盘；
    - **远端代码仓零污染**：实测前后远端项目目录文件数严格 `4 -> 4`（`addedOnRemote=[]`, `removedOnRemote=[]`），远端零 `.trainer/` 或任何 Trainer 数据文件。
- **真模型复验与全量工程门禁（截至 `c31e5f6`）**：
  - 真模型 4 场景复验（`MiniMax-M2.7`，失效系统代理 `127.0.0.1:1` + `ignoreSystemProxy: true` 直连通过，密钥/地址零落盘）：全部 4 用例 `completed=true`、`providerFallback=false`、`clicheHits=[]`、**`jargonHits=[]`**（Case 4 `handoff` 泄漏清零）；Case 1 TTFT `3640ms`（同期直连上游基线首可见字 `1698ms`，差值为推理模型在教学提示下的思考耗时）；Case 2 完整状态流推导并写入 `<LibraryRoot>/Trainer Library/.trainer-resources/markdown/*.md`；Case 3 `payments.py` 零写入；Case 4 如实汇报 0 条验证证据并出 5 问推理型复习题。
  - 全量门禁全绿：`ruff check` 0 错误、`verify:server-pyright` 0 错误、`pytest server/tests -n 4` **4191 passed / 0 failed / 28 subtests passed**、`npm run verify:i18n` PASS（213 `appUiCopy` + 212 `settingsText`，0 缺失、0 跨语种泄漏）、`verify:copy-vocabulary` PASS（66 文件 0 违规）、`verify:credentials` PASS（5032 文件 0 泄露）、`verify:version` PASS（1.4.4）、`npm run check` PASS、`npm run test:extension` 全绿、`verify:ui-geometry` PASS（360 断言）、`verify:local-latency` PASS（71–295ms）、12 份核心 Playwright E2E（111/111 passed）。
- **唯一剩余人工项（诚实 `BLOCKED`）**：`T-0028`（`teaching_acceptance`）属于所有者人工最终教学签收，继续诚实保持 `BLOCKED`，待本人按 [docs/TRIAL-1.5.0-RC.md](../docs/TRIAL-1.5.0-RC.md) 试用后签核。

## 2026-11-22 — 二次证据深审修复（P1/P2/P3 全量闭环）、宿主 8 语言清零、34s Remote-SSH 真模型对话与拆分遥测
- **复审根治与工程修复（含 `extension/bundled/server/` 同步）**：
  - **P1 目标防误建（`server/app/goal/service.py`）**：收紧 `detect_goal_candidate` 句式锚定与核查/提问句排除规则，新增显式目标指令检测 `detect_explicit_goal_command`，阻断查询类问题污染「当前目标」（`test_goal_session.py` 覆盖）。
  - **P1 验证证明守卫（`server/app/api/routes/learning.py`）**：`POST /training/verification/attest` 对缺失/过期 `card_id` 明确返回 `404`（`code: "training_card_not_found"`），消除未捕获异常 `500`。
  - **P2 讲稿落盘直通与路径诚实（`server/app/resources/library.py`、`tools.py`、`agent_loop.py`、`agent_tool_context.py`、`coach_support.py`、`prompts.py`、`coaching_replies.py`）**：
    - `save_lecture_note` 改为 `coach_only=False`（仍严格受显式讲稿/学习笔记请求守卫限制），并在 `ToolRegistry.as_protocol_schemas` / `CoachAgentLoop._tools_schema` / `coach_support` 中对齐 `explicit_lecture_note_save_request`，使深度讲透（`direct` 模式）不再被过滤掉 `save_lecture_note`；
    - 讲稿同步写入 `<LibraryRoot>/Trainer Library/<folder>/<slug>.md` 并调用 `remember_download` 入组，更新 `_SAVED_NOTE_PATH_PATTERN` 与 `enforce_truthful_saved_note_path` 以精确替换含空格路径。
  - **P2 内部词清洗与流式透明化（`coaching_replies.py`、`agent_binding.py`、`provider_service.py`、`routes/core.py`、`extension/`）**：
    - 新增 `_strip_leaked_internal_prose_tokens` 清除 `¶chunk:` / 实体 ID / 状态枚举词并保留代码括号（如 `` `pop()` ``）；
    - 为 `AgentLoop` 启用 opt-in 阶段态事件（`model_reasoning` / `tool_intent`）与端到端耗时拆分 `timings`（`local_prep_ms` / `provider_first_event_ms` / `visible_ttft_ms` / `total_ms`），修复代码块围栏流式卡顿；
    - `planner/service.py` 与 `routes/plan.py` 补齐中文目标概念分词并优先采纳 `payload["goal"]`。
  - **P2 宿主 8 语言清零（`extension/src/commands/hostCommandCopy.ts` 等 5 份宿主命令文件 + `verify-i18n-completeness.mjs`）**：为 `remoteProjectAdmission.ts`、`remoteCompanionCommands.ts`、`remoteVerificationCommands.ts`、`workspaceAdmissionCommands.ts`、`resourceCommands.ts` 全量接入 8 语言并纳入 `verify:i18n` 字面量零残留硬门禁（`272 hostCommandCopy` 调用点）。
- **真模型 4 场景实测（`MiniMax-M2.7`，环境代理存在且直连绕过）**：
  - Case 1（短问答）：客户端 `ttftMs=2615ms` / `totalTurnMs=3116ms`；服务端 `local_prep_ms=55ms` / `provider_first_event_ms=2526.2ms` / `visible_ttft_ms=2581.2ms` / `total_ms=3078.4ms`（`>2000ms` 记为 `PARTIAL`）。
  - Case 2（深度 RethinkFun 讲稿 + 落盘）：真实调用 `["search_resources", "list_resources", "save_lecture_note"]`，写入 `Trainer Library/学习讲稿/Scaled-Dot-Product-Attention：为什么要除以-sqrt(d_k).md`，`savedResourcesCount=1`，`libraryGroups=[{"name":"学习讲稿","resource_count":1}]`，`notePathCitedTruthfully=true`、`citedBogusLibraryPaths=[]`。
  - Case 3（`payments.py` 引导）：`paymentsCodeUntouched=true`；Case 4（核查与推理复习）：`planStageTitles=["基础","练习","整合"]`、`attestMissingCardStatus=404`、`attestStatus=200`（`save`+`start` 后）、`goalNonPollutionCheck.unchangedByAuditQuery=true`。
  - 全部 4 用例 `providerFallback=false`、`clicheHits=[]`、`internalLeakHits=[]`、`all_under_library_root=true`；如实记录 Case 4 正文含 1 处括号英文 `handoff`（`jargonHits=["handoff"]`）。
- **真实 Linux `34s` Remote-SSH L2 + 真模型流式对话实测（`20/20` 步全通过）**：
  - 全量验证远端 Companion v2、宿主 `trainer.workspace.adoptProject` / `trainer.remote.verify` / `trainer.memory.refresh`、本机 `<LibraryRoot>/.trainer/runtime/trainer.sqlite3`、零远端代码仓写入（`4 -> 4` 文件），并在 Step 11 实跑 `trainer.provider.save` → `trainer.provider.test` → `trainer.session.sendStreamMessage`（`MiniMax-M2.7`, `10712ms`），回复精确引用远端 `payments.py` 的 `record_charge` / `self._seen` 与 `test_payments.py`。
- **全量验证门禁**：
  - `ruff check`：0 错误；`verify:server-pyright`：0 错误；`pytest server/tests -n 2 -q`：**4205 passed, 28 subtests passed, 0 failed**（注：此前 `-n 4` 高并发出现 2 项时间/争抢抖动，单独复跑 `22 passed in 1.37s` 并在 `-n 2` 全量通过）。
  - `verify:i18n`（213/212/272）、`verify:copy-vocabulary`（68 文件 0 违规）、`npm run check`、`npm run test:extension`、`verify:ui-geometry`（360 断言）、`verify:local-latency`（39–272ms）、核心 Playwright 4 spec（93/93 passed）、`verify:credentials`（5079 文件 0 泄露）、`verify:version`（1.4.4）全部通过。
- **诚实 `BLOCKED` 边界**：`T-0028`（`teaching_acceptance`）继续保持 `BLOCKED`，等待人工最终教学签收。

## 2026-11-28 — HEAD audit and hardening (committed to `main` the same night)

Audited `115ecd17` on `main` with four read-only reviews (frontend, tests/CI, sandbox/authority, docs drift), then made the changes below. Committed to `main` on 2026-11-28 at the owner's request, in seven commits (library lane, pedagogy, server tests, extension fixes, extension tests, e2e tooling, docs); not pushed.

**Baseline at HEAD (clean tree).** Server pytest 952 passed (178.84s idle, 133.55s under load); ruff, pyright, `npm run check`, `verify:i18n`, `verify:copy-vocabulary`, `verify:credentials` all pass. `npm run test:extension` printed exit 0 only because its output was piped: one load-sensitive timing test had failed. One full pytest run stalled for more than 7.5 minutes in `test_browser_events_and_bootstrap.py` under heavy load; it did not reproduce in five attempts (saturated CPU, six parallel copies, the original concurrent command set). A pytest process left by an earlier session (PID 86458, started 2026-11-27 13:15) is still stuck on the pre-commit code of that file. Playwright at HEAD was 104/105: `trainer-model-picker.spec.js:129` still asserts the per-model thinking badge that `f4713414` replaced with a provider-level slider.

**Changed.**
- Restored behavioral tests deleted in `df0a3e2a`, second pass (the owner had not answered whether to continue; this is reversible test-only work, reported here for review). Server: 29 more `server/tests/test_restored_*.py` files, 1,050 old tests (1,214 collected), bringing the restored set to 37 files / 1,706 tests and the backend suite to 2,685; pyright 0 errors on all of them, no type-ignore, no skip markers; every definition was compared with its original by AST and none has a changed assertion (differences: Pydantic alias keywords in 16 tests and 5 helpers, six helpers recreated verbatim, `build_client` now from `tests.client_fixtures`). Extension: 129 `extension/tests/restored*.test.js` files, 856 tests, suite 1,446 (three consecutive green runs); 81 files byte-identical to the original, the rest partial with each omitted test and its reason in the header, or with an inline replacement for the deleted `loadTsModule` helper. Not restored: server 994 passing-but-type-noisy old tests (824 need manual typing, 132 would need a type-ignore), 122 left out for the runtime budget, 17 with skip markers, 22 source or config guards, 189 failing at HEAD; extension 447 failing at HEAD (the full preserved list; the 109 quoted earlier counted only omissions inside partially restored files), 79 passing text guards, 6 with `t.skip()`, 30 not evaluated. The HEAD-failure lists are in `.trainer-convergence/evidence/restored-tests-2026-11-28/` (untriaged; samples are stale expectations for renamed tools and removed exports such as `compare_with_anchor`, `run_rubric_review`, `deriveCoachOrientation`, `resolveTrainingNextHop`, but real behaviour changes may be among them). Caveats: two restored extension tests take data from source layout and may report false failures after refactors (`restoredComposerCopyLocale`, `restoredI18nCopyCompleteness`); the suite is now slower (backend 189 s, extension about 18 s).
- `library_exec` hardening in `server/app/llm/tool_primitives.py` and the new `server/app/llm/library_exec_process.py`: without `sandbox-exec`/`bwrap` only a bare `echo` runs (the audit guard is Python inside the child and cannot bound an interpreter); timeout and cancellation stop the whole process group and drain its pipes for a bounded time; output is capped while it is read and a runaway stream is stopped early; the Seatbelt profile refuses `open`, `launchctl`, `security`, `osascript`, pasteboard helpers; trash stores are read-only (profile, bwrap read-only bind, audit guard, command validator); the audit guard directory is a private `mkdtemp`. Regression tests: `server/tests/test_library_exec_hardening.py` (15 tests; 14 fail on the HEAD implementation in a scratch export).
- `server/tests/test_browser_events_and_bootstrap.py`: the SSE test is bounded (60s) and reports the producer task instead of waiting on keep-alives forever.
- Browser side panel transport (`chromeSidePanelTransport.ts`): unimplemented training/evidence commands answer `ok:false` instead of a fake `ok:true`; unhandled actions answer with an error status. Tests: `extension/tests/sidepanelHonestFailure.test.js` (8 tests). `vscode.ts` logs dropped, invalid host messages.
- `extension/tests/httpClient.test.js`: both abort tests wait on a 10s budget instead of a 1.5s race.
- `e2e/trainer-model-picker.spec.js`: stale badge assertion replaced by the provider-level thinking slider.
- Restored behavioral tests, 8 new files `server/tests/test_restored_*.py` (492 tests, 31-40s): project read-only, library confinement, evidence honesty, secret redaction, workspace isolation, training cards and FSRS, resource grounding, plan lifecycle. Probing showed 1,023 of 1,055 sampled pre-`df0a3e2a` tests still pass at HEAD unchanged, so that commit removed valid behavioral coverage. Pyright reported 177 strict-Optional / argument-type findings in these restored files (the project gate only checks `server/app`); all 185 are now fixed without `type: ignore` (5 commented `cast`s for test doubles), and the two silently dropped or mis-wired arguments found on the way were corrected: `ResourceRecord(workspace_id=...)` (not a field) and `PlannerService(repository)` (the positional argument landed in the `planner` slot). Open product-side observation: `TrainingCardCandidateSnapshot` carries `generation_source` / `generation_status` / `generation_fallback_reason` / `generation_recoverable` only as undeclared extras.
- `library_write(action='restore')` reported the trash path (which no longer exists after the restore), an empty `restored_path`, and never re-indexed the restored file; it now reports the file that exists (`path`, `restored_path`), keeps `trashed_path`, and re-indexes it. Tests: two parametrized cases in `test_library_write_path_truth.py` (both failed before the fix).
- `scripts/run-structural-journey.mjs`: step 09 paired through `/browser/auto-pair` with an unredeemed extension origin, which the 2026-11-27 bridge hardening rejects with 403, so the journey reported `14 PASS, 4 BLOCKED, 1 FAIL` at HEAD; and the runner exited 0 on that FAIL. It now redeems a host-issued single-use pair code (18 PASS / 4 BLOCKED / 0 FAIL) and exits 1 on any FAIL (verified with an injected failing step).
- Experience gates measured on the final tree: `verify:local-latency` 5/5 (40-382 ms), `verify:ui-geometry` 360/360, `test:ui-a11y` 96/96, `test:structural-journey` 18 PASS / 4 BLOCKED (real-provider and Remote-SSH gates) / 0 FAIL.
- Docs: `AGENTS.md` (eight primitives, real fail-closed rule, 8/12-char holdback, separate Vite entries, extension tests in the gates, pipe warning), `SPEC.md` (header, React 18, package lists, composer rule), `README.md` and `README_zh-CN.md` (measured test counts). The six other locale READMEs carry the same measured counts in their own number formats.

**After the changes.** Server pytest 2736 passed (212.26s, 83 files: 952 at HEAD, 62 new regression tests, 1,729 restored behavioral tests in 41 files); real-sidecar experience matrix 12/12; extension 1446 passed, 0 failed, 0 skipped (158 files: 590 existing plus new, 856 restored); Playwright 105 passed; pyright 0 errors; `npm run build` exit 0; bundled mirror identical.

**Installed-VSIX measurements (2026-11-28, later the same night).** `npm run build` exits 0 on the final tree. `npm run test:vsix-e2e` rebuilt the VSIX from it (`rebuiltCurrentVsix: true`) and passed 36/36 steps with the fixture provider. A separate cold-start probe then launched real VS Code with that VSIX and a plain code project for which no learning folder is bound: the first-run sidebar offers `选择学习文件夹`; Resources shows `还没有资料` with `导入资料` only; no library-folder write control is rendered and no error text appears; the project folder is unchanged afterwards; the sidecar data dir is under `globalStorage`. So on a cold start the 409 `library_root_unavailable` and its new copy are not reachable from the UI: the webview allows library writes only under managed admission (`useWorkspaceAdmissionController.tsx`), the folder-list failure message is stored but never rendered, and for JSON requests the host reports `Sidecar request failed (409).` without reading `detail.message` (`parseSafeSidecarError` reads a string `detail` only). The new server copy therefore matters to API clients and tests, not to this UI path. A fourth regression test covers the one write the cold-start Resources page offers (import): it succeeds, is searchable, and stays under the data dir. The import entry was then exercised in the same installed VSIX. At HEAD, clicking `导入资料` on a cold-start workspace shows the webview's generic banner `资料没有完全导入。已导入的资料仍可使用；到“资料”页刷新后重试未完成的项目。` although nothing was imported: `CommandRegistry.workspaceAdmissionGate` blocks the command before it runs with the unmarked session-level reason `Choose a Trainer workspace before starting a conversation.`, and the webview replaces unmarked host prose with generic recovery copy (`sanitizeHostFailureMessage`). A first fix that marked the admission block inside `resourceCommands.ts` passed its unit test but changed nothing in the installed product, because the registry gate runs first; the installed probe showed that. The real fix is in `commandRegistry.ts`: for resource changes the gate now returns a marked, resource-oriented reason (browse-only / ignored / project-found / choose how Trainer manages this project, all existing 8-language copy), and the palette toast strips the marker. Verified in the running VS Code: the host message is `[[trainer-resource-operation:upload:…]] [[trainer-resource-failure]] Choose how Trainer should work with this project before changing its resources.` and the sidebar shows that sentence; the project folder stays unchanged. Tests: `extension/tests/commandRegistryAdmissionGate.test.js` (5 tests, 3 fail on the HEAD registry) and one case in `resourceCommands.test.js`. Known limit, unchanged: host copy follows the VS Code display language while the webview shell follows the OS locale on first run, so with an English VS Code on a Chinese system this sentence is English. Not exercised in the installed VSIX: a real import through the native file dialog, and any real-model turn.

**Found by classifying the old tests that fail at HEAD (2026-11-28, later).** Read-only triage in scratch copies: server 189 = 155 stale API, 29 intended change (with commits), 3 possible regression, 2 environment; extension 447 = 439 stale API, 7 intended change, 0 possible regression, 1 environment. Each possible regression and everything found on the way was reproduced first and verified after.
- *A side effect of my own zero-pollution fix, missed the first time.* On a cold start an imported document no longer got its canonical Markdown (plain-text search hits, no anchors, the binary synced into the sandbox), because the canonical root was `None` until a learning folder was bound. Surfaced by 12 old pipeline tests that pass at HEAD and failed only on this tree. Fixed in `resources/canonical_store.py` (`managed_workspace_root`), `canonical_and_collection_mixin.py` and `sandbox/service.py`: the copy goes under the sidecar data root at `<data_dir>/canonical-resources/<workspace slug>/`, moves with the rest of the data folder when a learning folder is bound, and older copies inside the workspace folder are still found (read only). Tests: `test_cold_start_canonical_markdown.py` (5; 3 failed before), plus 23 restored pipeline tests for docx/pptx/pdf/epub in four `test_restored_*` files. `test_library_write_path_truth.py` now expects canonicalization in both layouts (it had encoded the deficient cold-start behaviour).
- *Weakness recall cue dropped in the minimal context tier.* `0c41dbad` made a short message next to an idle-looking file use the lean tier, but the resolver reads only the message, and the cue (contract §7) was computed only outside that tier — so a learner with a live error typing "and now?" got no cue. The tier's own docstring says it is "only ever a prompt/IO reduction, never a behavior gate". The cue is now computed in every tier; direct mode still suppresses it (`test_weakness_cue_survives_minimal_tier.py`, 4; 1 failed before).
- *An explanation request forged an implementation guide.* `14b33b4a` removed the broad "讲解一下 / 介绍一下" tokens so plain explanations would not request tools; the same list gated the guide, so "讲解一下这个文件夹项目呢" in direct mode became a feature to build. Project/folder-targeted explanation phrasings (zh and en) are recognised again; a plain explanation still does not request tools (`test_exploratory_queries_never_forge_a_guide.py`, 13; 12 failed before).
- *Placeholder in every guide for a new learner.* With no focus, memory or goal the pedagogy service falls back to the literal label `current task`, and the guide builder used it as the goal: "先把 current task 压成一个可验证的行为变化", even for a real implementation request. The label is now a named constant (`GENERIC_FOCUS_LABEL`) and is treated as "no focus" when a guide is built.
- *At committed HEAD, a canonicalized resource could not be moved into a folder.* Grouping moved the inline upload, which the md-only pipeline deletes once the canonical document exists; `POST /resource/organize set_group` and the coach's organize tool answered "Only local library snapshots can be grouped." in both layouts (verified on a `git archive HEAD` export with the loaded copy checked). The host only groups during import, before indexing, so the UI path was hidden; the coach tool was not. A group is now metadata (`collection_path`) for such a resource; a real move still happens while the snapshot exists (`test_organize_canonicalized_resource.py`, 6; 2 failed before). Three restored tests that assumed the inline file survives indexing were adapted to compare against the state before the action.
- *Not changed, for the owner:* the md-only migration no longer reports legacy originals left inside the workspace folder on a cold start (it reports `originals_kept == 0`); `_pdf_bytes` in `canonical_doc_fixtures.py` keeps the old `pytest.importorskip("pymupdf")`; `extension/webview/src/lib/browserPreviewActions.ts:124` carries mojibake zh-CN copy (browser preview only).

**Owner decisions (2026-11-28, after the report).** Answered in one line; the readings in brackets are mine. (1) The API key the owner pasted into the chat may be used for real-model verification (answered "是", read as yes). It is stored nowhere in this repository. It was used later the same day for the measurements in the next section. (2) The browser side-panel chat client stays ("保留") and my recommendation applies: product-contract §9 is to be rewritten to match, and a one-click learning-folder binding is wanted; both are done in the next section. (3) The remaining old tests are not to be restored ("不恢复"). Measured remainder, by test function: 3,622 pre-`df0a3e2a` server tests, 2,262 restored by name, 1,360 not — 924 pass at HEAD, 201 fail, 41 cannot be imported (two files import names that no longer exist, one needs the e2e matrix file), 194 are in `test_api.py`, whose full-file scratch run did not finish in 300 s (its last eight tests finish in 3 s alone; not investigated further). Per test: `.trainer-convergence/evidence/restored-tests-2026-11-28/server-old-tests-unrestored.txt`. Measured and not changed: with the project config, pyright reports 669 errors in 26 of the 91 files under `server/tests`, none of them in the 49 files added tonight; the gate still covers `server/app` only. (4) Commit to `main` ("提交到main"), done the same night; not pushed. Gates re-run on the tree just before committing: mirror identical; ruff; pyright 0 errors on `server/app`; server pytest 2736 passed in 337.47s (other work was running on the machine); `npm run check`; extension 1446 passed; `verify:i18n`, `verify:copy-vocabulary`, `verify:credentials` (5,205 files, 0 findings). Not re-run at that point because the same code had been measured earlier in the night: `npm run build`, Playwright, installed-VSIX E2E. Still open: Windows `library_exec`.

**Open for the owner (as reported; the paragraph above says what is now settled).** (1) `library_exec` is now unavailable on Windows and on Linux without bwrap — accept, or add a Windows sandbox backend. (2) The product contract freezes the browser side-panel chat client while `1550b6fa` and `656657a3` extended it and the Settings copy promotes it — decide and update one side. (3) `df0a3e2a` deleted about 2,200 server and 1,900 extension tests; 1,706 server and 856 extension behavioral tests are restored. Next, if wanted: type-adapt the 824 passing server tests that need it, triage the 189 + 109 old tests that fail at HEAD for real behaviour changes, and restore the 122 left out for runtime. (4) 975 `leftover_*` references still carry cross-workspace state isolation; retire them only behind real-model journeys. (5) Reported by the test-restoration pass; (i)-(iii) reproduced and fixed (committed), (iv) still open: (i) on a cold start (no library folder bound, sidecar data dir under `globalStorage`, workspace not provisioned) `library_write` created `Trainer Library/...` inside the learner's code project. This is reachable in production: `sidecarProcessManager.resolveDefaultSidecarDataDirectory` uses `globalStorage/sidecar` until a library root is bound, so `resolve_library_carrier_root` hit its workspace-path fallback. That fallback and the workspace fallback in `ResourceService._canonical_writable_root` are removed; the library carrier root is `None` until a root is bound, and library writes, lecture notes and the canonical copy stay under the data dir. Side effect to review: library captures/downloads that need a carrier root now report no local root until the learner binds one (contract §4). Regression tests in `server/tests/test_library_zero_pollution.py`; With no root bound, the library lane answers 409 `library_root_unavailable`; its copy in `server/app/resources/library_copy.py` said the workspace "has no local root" and asked for an open project folder, which is wrong for a local cold start, so it now says that no learning folder is chosen yet and points to Settings (all eight languages). Whether the host shows this text or its generic recovery copy, and the one-click binding guidance the contract asks for, were not verified. (ii) FIXED 2026-11-28, committed: `library_write{action:write}` of `notes/sample.py` used to report `path: notes/sample.py` while only `notes/sample.md` existed, so a follow-up read/edit/soft_delete returned not found. Auto-indexing canonicalises a non-Markdown file in place and `_handle_index_sandbox_file` then forced the record's `sandbox_path` back to the pre-index path and persisted it. The record and the tool result now carry the file that exists (the requested path is kept as `requested_path`); regression tests in `server/tests/test_library_write_path_truth.py` (2 of its 4 tests failed before the fix). The auto-index helper moved to `server/app/llm/tool_handlers/organization_and_sandbox.py`, which brings `tool_primitives.py` to 2,522 lines; (iii) FIXED 2026-11-28, uncommitted: the host-secret probe in `test_phase2_orthogonal_tools.py` passed vacuously (the child died on `KeyError: TEST_SECRET_DIR` before any sandbox denial); it now states and asserts what it actually proves (the allow-listed child environment never receives the caller's variable), and the non-vacuous sandbox-denial test is `test_restored_project_read_only.py::test_library_exec_runtime_guard_blocks_reads_of_host_files_outside_all_roots`; (iv) still open as a documentation question: the sandbox lane soft-deletes to `trash/<timestamp>-<id>/` while the library carrier lane uses `.trash/`; `AGENTS.md` now names both.
(6) Not touched: hard-link/TOCTOU writes in `sandbox/service.py`, a full default-deny Seatbelt profile, the untyped `RouterDeps` closure bag, the tracked `extension/bundled/server` mirror.

## 2026-11-28 (continued after the owner's decisions) — real-model verification, one-click binding, typed contracts

The owner answered the four open questions the same morning: the pasted API key may be used for real-model verification; the browser side-panel chat client stays; the remaining old tests are not to be restored; commit to `main`. This section covers the work that followed. Everything here is committed to `main` in the commits after `c0437743`; nothing is pushed.

**How the key was handled.** The key exists only in the owner's chat message. Every probe loaded it into its own process environment at run time by reading that message from this session's history; it was sent to the gateway in request bodies only, never given to the sidecar process, never printed, never written to any file. The credentials gate over the final tree: 5,254 files, 0 findings. The gateway is plain HTTP (`http://`), so the key and the prompts travel unencrypted; that is the owner's endpoint and was left as is.

### Real model, measured (MiniMax-M2.7 through the owner's gateway; 5 models are listed there)

Method: a real sidecar on a free port with a throw-away data dir, a scratch learner project (`app.py` with a `KeyError`, `payments.py` with a retry that can double-charge), six learner turns through `/turn/stream`, twice, behind a local capturing proxy that records each model request's size, token limits, reasoning tokens and timing. Scripts are outside the repo (`/tmp/trainer-audit/rm/`).

Wire facts (41 model calls): each coaching request carries a system prompt of 19–22k characters plus 8 tool schemas of 13k characters, i.e. 8–10.5k prompt tokens; the gateway's first event arrives after 1.0–3.4 s; `thinking: {type: disabled}` is sent and ignored (50–1300 hidden reasoning tokens per call); prompt-cache hits vary from 0 to 7.9k tokens because the "session-invariant" prefix differs per lane (system prompt size changes between turns).

Before (HEAD `c0437743`) and after, server-side `visible_ttft_ms` / `total_ms` per turn:

| Turn | Before | After (2 rounds) |
|---|---|---|
| "然后呢？" next to the error file | 3.1 s / 22.3 s | 9.9–11.7 s / 12.3–13.3 s |
| "这段为什么会报 KeyError？" | 2.6 s / 6.6 s (3 model calls) | 1.9–3.1 s / 4.0–4.8 s (1 call) |
| "你好" | 2.5 s / 5.8 s (2 project reads) | 2.6–5.2 s / 2.7–5.9 s (0–1 read) |
| "讲解一下这个项目" | 2.2 s / 16.5 s | 6.5–6.9 s / 9.2–11.9 s |
| idempotency, first question | 13.5 s / 20.3 s | 4.0–6.7 s / 5.5–16.7 s |
| idempotency, follow-up | 8.0 s / 15.6 s | 8.0–13.2 s / 10.5–13.4 s |

Against contract §5: the short-turn budget (≤ 6 s) now holds for the plain question and the greeting; first visible content ≤ 2 s holds only occasionally (1.9 s once). The floor is the gateway's own first event (1.4–2.8 s for prompts of this size) plus hidden reasoning; no request field on this gateway shortens the reasoning (tried `reasoning_effort`, `thinking`, `enable_thinking`, `reasoning_split`, a zero budget). The learner does see real status within 20–40 ms (`preparing_context`, `requesting_model`), and since this session a project read shows the file being read.

Other models on the same gateway, raw: `MiniMax-M2.7-highspeed` first event 1.0–1.2 s at 105–130 tokens/s; `MiniMax-M3` 0.9–1.1 s at about 90 tokens/s; `MiniMax-M3.1-Flash` hides 3–16 s of reasoning before the first visible character. A model choice is the owner's.

### Defects the real model exposed, and the fixes

- *The stored next step was the reply's opening prose.* A reply without a `下一步：` label made both continuity builders fall back to the first 120 characters of the reply, so `next_step` was `## 发生了什么 `get(d, k)` 里执行的是…` (a heading plus the start of an explanation), and that fragment was fed into the next turn as the step to continue; a bare "你好" then continued it and produced a patch. Now: the opening prose is never used; a reply's closing instruction counts when it reads as one, after specific thread hints and before the neutral default (`closing_action_step` in `llm/reply_continuity.py`); the prompt requires a labelled last line in the reply's language (named once, in the Language section, because a first version that said "the label in your language" from an English rule produced `` `Next step:` `` inside Chinese replies); the reader tolerates a label wrapped in backticks or quotes. Label compliance went from 0 of 12 to 12 of 12; every `next_step` is now a concrete action. Tests: `test_next_step_stays_an_action.py` (10, fixtures are excerpts of real replies).
- *The default pace was a lecture that rewrote the learner's code.* "这段为什么会报 KeyError？" (491–1,544 characters, two complete rewrites of the learner's `get`) became 399–543 characters with the lines to change named and no rewrite; three model calls became one. The static prefix now states the default pace with a size, gates the state-driven lecture form behind an explicit deep-explanation request, asks for at most two questions when an answer is withheld, tells the model that evidence already in the prompt has been read (no `project_read` for the current file), and asks for brief reasoning. The English prompt still contains no CJK (480 variants checked).
- *The stage line while a project file is read said "正在检索资料".* It now names the file: "正在查看 app.py" (eight languages; `trainerStageShowsTheFile.test.js`, 5).
- Not changed: the host status copy still says "正在向已配置的模型请求回复。" / "模型正在推演思路。"; a turn with long hidden reasoning shows nothing but that status for up to 14 s (one call took 65 s for 1,317 reasoning tokens); the agent loop had no idle watchdog and, on reasoning-first gateways, no step bound either; the generation client had no read timeout (both changed in the third pass below).

### Contract §10 story, first half, with the real model

Monday the learner asks to understand idempotency; the coach reads `payments.py` (3 calls, 11.5 s) and asks for the learner's own understanding, with a concrete next step. The learner states it (8.4 s). The learner fixes `charge()`; the coach reads and verifies and answers (73 s, see the reasoning outlier above): the direction is right, but the timeout path is still dead code and the dedup check sits before the gateway call, so it cannot cover the "charged but unrecorded" window — then it shows the learner's own `charge` with one deliberate `raise` line as the way to build that scenario. Thursday, a similar bug in `refunds.py` with "只给我一句提示就好": one call, first visible 2.1 s, 225 characters, one hint, no code — the contract's "教练只提醒了一句". The learner fixes it; the coach confirms (12.7 s). No internal jargon in any reply. Not done, by design: the host attestation that records "independent completion", the two-week review, and the human teaching-quality sign-off (contract §10) remain for the owner.

### One-click binding of the learning folder (contract §4)

On a cold start the Resources page offered "导入资料" although that import cannot succeed before a learning folder is bound; the click only produced the host's refusal. `onChooseWorkspaceRoot` was passed to the Resources view and never used inside it. Now `deriveAdmissionBindOrientation` (shared) names the one step for the current admission status — choose a learning folder, add the current project, choose the project folder — and the Resources banner shows that step's reason and action (`bind_learning_folder`; copy in eight languages). The step follows the status, so the second click appears by itself after the first. Tests: `resourcesOrientationAdmissionBind.test.js` (5).

Verified in the installed VSIX (fresh package, isolated VS Code, a plain project, the native folder dialog answered from the Electron main process with a throw-away folder): "还没有资料 / 先选一个学习文件夹，导入的资料才有地方保存。/ [选择学习文件夹]" → click → "先决定 Trainer 如何配合这个项目，才能导入资料。/ [把当前项目加入 Trainer]" → click → status `success`, the normal empty library; no error status; `.trainer/runtime/trainer.sqlite3` and the project inventory under the learning folder; the project folder unchanged. Two consecutive runs identical.

### The sidecar race that binding exposed

The first binding run ended with a red "这一步暂时没完成。再试一次。" The folder switch stops the sidecar; when that stop lands on a sidecar still starting (the usual case on a cold start), the launch reported "Sidecar failed to start and did not stop cleanly: Sidecar exited before readiness (signal=SIGTERM)" — a false failure for a process replaced on purpose — and the request waiting on it failed. Pre-existing; nobody had completed a binding from that page before.

- `SidecarProcessManager.withManagedDataSwitch` makes a managed-data switch the only sidecar operation in flight; requests wait for it; a launch it stopped is retried against the folder it installed; the transfer's own final restart bypasses the gate (`ensureRunningAfterManagedDataSwitch`) — a plain `restart()` inside the gate deadlocked it, which the fourth test caught.
- `runWithQuiescentManagedData` runs inside the gate.
- Tests: `sidecarSwitchDuringStart.test.js` (4; 3 fail on the unfixed manager).

### Code architecture

- *Type gate over the tests.* With the project config pyright reported 669 errors in 26 committed test files. 389 were one mechanical cause — field-name keywords (`base_url=`) on Pydantic models that pyright only accepts by alias (`baseUrl=`) — renamed by a script that touches only the keyword pyright rejects and reverts anything it then still rejects; the remaining 280 were fixed by five parallel agents under written rules (no `type: ignore`, no `cast(Any)`, no skip, no lost assertion, only assigned files), then checked independently: no new suppressions, the 8 reshaped assertions keep the same comparison, collected ids unchanged. `pyright` over `server/tests`: 0 errors in 92 files. `verify:server-pyright`, the CI step and `AGENTS.md` now cover `server/app` and `server/tests`.
- *`RouterDeps` typed.* The 32 members of the closure bag were `Callable[..., Any]`; each now carries the signature of the function `build_router_deps` installs (a `Callable` for plain positional functions, a `Protocol` with `__call__` where keyword-only parameters or defaults must be kept). pyright over `server/app`: 0 errors in 311 files; route tests 121 pass.
- Two findings from the typing pass, fixed: `test_p2_multiturn_kv_cache_prefix_stays_byte_stable` passed three kwargs that pydantic drops, so it had only ever compared two all-default profiles — it now uses a real goal and background and asserts they reach the prefix; 36 unreachable lines after an unconditional return in `_fallback_empty_reply` removed. A commented-out block of mojibake copy in `browserPreviewActions.ts` removed.
- Not touched, as before: the 975 `leftover_*` references; `library_exec` on Windows.

### Contract and docs

Contract v2.2: §9 no longer freezes the browser side-panel chat client; it is kept as another carrier of the same coach (reuses the VS Code workbench UI and the single composer, no browser-only learning features), with a decision row dated 2026-11-28. `docs/STRATEGY.md` and `SPEC.md` say the same. READMEs (8): measured counts.

### Gates on the final tree

Backend pytest 2,746 passed (84 files); extension node:test 1,460 passed, 0 failed, 0 skipped (161 files); Playwright 105 passed; installed-VSIX E2E 36/36 steps with a VSIX rebuilt from the final tree (fixture provider); `npm run build` exit 0; pyright 0 errors over `server/app` and `server/tests`; ruff, `npm run check`, `verify:i18n`, `verify:copy-vocabulary`, `verify:credentials` (5,254 files, 0 findings) pass; `verify:local-latency` 5/5; `verify:ui-geometry` 360/360; `test:ui-a11y` 96/96; real-sidecar experience matrix 12/12; `test:structural-journey` 18 PASS / 4 BLOCKED / 0 FAIL.

### Open for the owner

(1) Contract §10 still needs the human teaching-quality sign-off, and the host attestation path for "independent completion". (2) First visible content ≤ 2 s is not met on this gateway: the floor is its first event plus hidden reasoning; options are a faster endpoint or model, a stalled-stream watchdog and a read timeout for generation, and a prefix that really is session-invariant (cache hits vary 0–7.9k tokens). (3) Windows `library_exec`; the 975 `leftover_*` references; the 1,360 old tests that stay out by the owner's decision (924 of them pass at HEAD). (4) The host status copy ("已配置的模型") is system wording; the host copy language follows VS Code while the webview shell follows the OS on first run. (5) One gateway call spent 65 s on 1,317 hidden reasoning tokens; the prompt asks for brief reasoning, the gateway ignores every field that could cap it.

## 2026-11-28 (third pass) — stream guards, a cacheable prompt prefix, and a correction to the earlier measurements

After the second report the remaining gaps were: the two contract §5 budgets with a real model, the 65–73 s outlier turn, the prompt cache, the §10 sign-off, and two owner decisions. All code below is committed to `main`; nothing is pushed.

**A correction first.** The probes of the second pass sent the answer mode under a field the API does not read (`mode`; the request field is `answer_mode`), so every "after" number there and the first §10 story run were measured with the policy the route falls back to, which turned out to be `direct`, not `guided`. The qualitative findings held — no rewrite of learner code, a labelled next step in every turn, fewer model calls — but they were observed under `direct`. Everything below was measured with the field fixed.

### Stream guards (`llm/agent_loop.py`, `llm/provider/runtime_shared.py`)

What existed: the plain coaching stream had a 120 s idle ceiling; the agent loop had step budgets of 90 s (first step) and 24 s — but `ProviderService._agent_loop_timeout_kwargs` passes `math.inf` for reasoning-first gateways (MiniMax M3.x among them), so there a step had no bound at all; and the transport read timeout was `None`. On such a gateway a dead connection held the learner until they cancelled.

- *Stall.* A stream that produces no event for 60 s is dead, not slow: the step ends as a stall (`ProviderStreamStalledError`, a `TimeoutError`; the final frame carries `stop_reason: "timeout"` and `stalled: true`).
- *First-output budget.* Until the learner has seen visible text in a turn, any step that produces nothing — no text, no tool call — within 20 s is dropped and requested once more with an instruction appended to the system message ("do not deliberate further"). Once per turn; the second attempt is capped at 120 s; the instruction is sent to the provider only and never enters the history that later steps or the session see. A step that only deliberates is exactly the measured outlier (65 s on 1,317 reasoning tokens before a tool call; another 18.5 s before the answer after its tool calls).
- *Transport backstop.* `read=300 s`: five minutes without one byte is a dead connection, never a model still thinking. The reasoning budget itself is still unlimited by design (the comment in `runtime_shared.py` explains why a 45 s cap was wrong).
- Tests: `test_agent_stream_watchdogs.py` (14) — stall reported and the upstream iterator closed, a talkative stream is never stalled, the step budget still wins, restart once with the hint, no restart once text was shown, a tool call counts as output, a later step that owes the first word is covered too, the hint never reaches the next step, a stalled first step ends the turn as a stall. `test_provider_service.py` now pins the backstop instead of `read is None`.

Seen with the real model: the budget fired once in 18 turns (a tool-decision step silent for more than 20 s); the retry produced its tool call in 3.1 s. That turn still took 31.5 s to its first visible text because it is a four-step tool chain (`learning_inspect` twice, `project_read` twice); the budget removes the silent deliberation, not the chain.

### A prompt prefix that a cache can hold (`llm/prompt_domains/`)

The system prompts of consecutive turns were recorded through the proxy and diffed: the first difference was at character 147 in one pair and 237 in another — inside the `Learner profile` block that opened the prompt, because the pedagogy service adapts the goal, the teaching style and the answer policy between turns. So the first request of every turn diverged from the gateway's cache after 128–188 tokens, and only the calls inside one turn (after tool results) hit it.

The prefix is now ordered for the cache: the rules, the request priority, the tool instructions and the reply language first (14,962 characters, identical for every learner and every turn of a language), then the learner profile and the per-turn biases. Measured on the real gateway: cached tokens on each turn's first call went from 128–188 to a median of 3,400–3,700 (min 128, max 9,400 of about 11,000). The gain in time is small — the gateway's first event arrives after 1.0–2.6 s whether 200 or 9,000 tokens are cached — and the misses that remain (188 or 0) are the gateway's, not the prompt's: the invariant part is byte-identical.

Tests: `test_prompt_prefix_is_session_invariant.py` (6). The existing byte-stability test and the "English prompt has no CJK" test still pass.

### Contract §5 with the real model, measured properly (MiniMax-M2.7, guided policy, six turns twice; `direct` once for comparison)

| Turn | Guided: first visible / complete | Direct: first visible / complete |
|---|---|---|
| "然后呢？" next to the error file | 17.7–31.5 s / 20.8–35.0 s (4–5 calls) | 13.4 s / 17.3 s (3 calls) |
| "这段为什么会报 KeyError？" | 1.9–2.2 s / 3.4–3.7 s (1 call) | 2.7 s / 4.5 s |
| "你好" | 2.1–3.1 s / 2.9–3.8 s (1 call) | 3.0 s / 5.1 s |
| "讲解一下这个项目" | 4.6–10.5 s / 10.6–15.7 s (2 calls) | 6.1 s / 12.1 s |
| idempotency, first question | 3.4–5.1 s / 6.6–7.1 s | 4.1 s / 6.1 s |
| idempotency, follow-up | 4.3–7.1 s / 6.7–9.2 s | 9.4 s / 11.2 s |

Guided, 12 turns: first visible content median 4.5 s (≤ 2 s in 1 of 12); complete reply median 6.9 s (≤ 6 s in 4 of 12); a labelled next step in 12 of 12. Direct, 6 turns: median 5.1 s and 8.7 s.

Against the contract: the short-turn budget holds for the plain question and the greeting and is missed by the tool-using and open-ended turns; the first-visible budget is not met. What is left is the gateway's first event (1.0–2.6 s) plus hidden reasoning before the first visible token (0.4–8 s in most calls, 18.5 s in one), plus tool chains of three or four model round trips for "然后呢？" and "讲解一下这个项目". The learner does see a truthful status within 30–40 ms and the file name while a read runs.

### One more defect the story run showed

The coach's reply ended with its own "下一步：…" line and the server appended "这一步算过的信号是：回到最近这一轮教练主线，…" after it — a thread reminder dressed as a verification signal, riding on the coach's words. A reply that ends with its own labelled action is left as it is (1 test in `test_next_step_stays_an_action.py`).

### Contract §10 story, for the owner's sign-off

`.trainer-convergence/evidence/real-model-story-2026-11-28.md` holds the five learner messages, the learner's code before each turn, the coach's verbatim replies, timings, and a sign-off box. Run on the final code (guided): Monday the coach states what the code does, poses three questions and asks for the learner's own reading before any judgment (3.8 s to first text); after the learner's fix it names what is right and three ranked gaps (11.1 s; one 4-line fragment inside the learner's `charge`, flagged for the signer against §8); Thursday "只给我一句提示就好" gets a 199-character hint and no code (2.5 s). No reply rewrote a learner function. Not covered, by design: the host attestation that records "independent completion", the review, and the controlled clock.

### Gates on the final tree

Backend pytest 2,767 passed (86 files); extension node:test 1,460 passed, 0 failed, 0 skipped; Playwright 105 passed; installed-VSIX E2E 36/36 with a VSIX rebuilt from the final tree (fixture provider); `npm run build` exit 0; pyright 0 errors over `server/app` and `server/tests`; ruff, `npm run check`, `verify:i18n`, `verify:copy-vocabulary`, `verify:credentials` (5,275 files, 0 findings) pass; real-sidecar experience matrix 12/12 (its prefix scenario now checks the prefix per reply language and the rules the languages share); `test:structural-journey` 18 PASS / 4 BLOCKED / 0 FAIL; `verify:local-latency` 5/5; `verify:ui-geometry` 360/360

### Open for the owner

(1) **The §10 sign-off** — the document above. (2) **The two §5 budgets** are not met on this gateway. Options, in my order: a faster endpoint or model for the default pace; fewer model round trips in a turn (a "然后呢？" next to an error file does not need `learning_inspect` before reading the file — a tool-set question, not a latency tweak); or accept a truthful status line as the first visible content, which the contract's own wording allows. (3) **`library_exec` on Windows** — it is fail-closed there since the first pass (no kernel sandbox); accept, or commission a Windows sandbox backend (AppContainer / Job Objects) that cannot be developed or tested on this machine. (4) **The `leftover_*` isolation** — 1,251 references in 44 server files plus about 530 `leftover` mentions in the webview: predicates that keep state from an earlier session from being shown as live after a recovery or a workspace switch. Retiring it means replacing the predicates with one structural guarantee (a recovered workspace starts from nothing that was not re-verified) — a refactor of thousands of lines that needs the real-model journeys and the installed-VSIX suite as its net. My recommendation is to keep it for now and plan it as its own piece of work; the earlier refactors already pruned the webview side of it. (5) Carried over: the host status copy ("已配置的模型") and its language; the cache misses on the gateway side.
