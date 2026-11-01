# Real-model teaching journey — 2026-11-02

Code: HEAD d72e98b (current worktree). Real sidecar + SQLite on port 34978,
fresh data dir, key supplied only through `PROBE_PROVIDER_API_KEY` (not stored).
Primary model: MiniMax-M2.7; switch model: MiniMax-M3.1-Flash, owner-supplied
OpenAI-compatible relay. The endpoint/key are not stored in the repo.

| step | result |
| --- | --- |
| 01 session start | 200 |
| 02 resource upload | 200, real resource id |
| 02b provider test | 200: streaming/tools/model all verified |
| 03 understand turn | 200, 2259 visible chars; explains check-then-act race, code, and a concrete concurrency test |
| 04 plan generate | 200, real plan id |
| 05 restart restore | sidecar killed/restarted; same session restored |
| 06 continuity turn | 200, 229 visible chars; continues the Foundation step with Condition + locking checks |
| 07 workspace switch | 200; workspace B is clean, cross_workspace_leak=false |
| 08 model switch | 200; M3.1 tested and used; concise confirmation |
| 09 memory summary | 200 |

This is real-model evidence, not a human teaching-quality sign-off. T-0028
remains owner-only. See `../journey-real-m3.1-tool-loop-limit-2026-11-02/` for a
residual sample where M3.1 tool-loop continuity exhausted the provider output
limit before a visible answer; the app surfaced a failure/recovery path rather
than pretending success.
