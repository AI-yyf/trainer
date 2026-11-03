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
