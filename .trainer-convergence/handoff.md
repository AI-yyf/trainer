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
