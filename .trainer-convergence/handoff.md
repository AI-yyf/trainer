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
