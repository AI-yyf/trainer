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
