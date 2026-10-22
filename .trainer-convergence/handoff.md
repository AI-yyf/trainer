# Handoff

- Baseline e7e6f41 pushed; CI cross-platform run 39636536608 failed only UI(windows) extension tests.
- Working tree carries the T-0020 fix (target-platform path API in browserLauncher.ts); extension tests green locally.
- Wave 1: finish T-0020 (commit+push+CI), then T-0002/T-0003 (session/provider identity), T-0006/T-0007 (browser queue), T-0001/T-0005 (startup).
- Subagent policy: deepseek-researcher agents are read-only auditors; implementation is master-owned to protect shared files.
