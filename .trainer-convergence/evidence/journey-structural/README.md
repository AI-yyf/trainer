# Teaching journey probe — structural validation (2026-10-23)

Probe: journey-probe.mjs (this directory). Real sidecar (temp data dir, port
guard), real API contracts, real interruptions. Provider key INVALID by
necessity — the original linksub key was lost with a rotated session log, and
no valid key exists in this session.

## Validated (provider-independent)
- 01 session start: 200
- 02 resource upload: 200, resource-917abefc1f (real library record)
- 05 sidecar SIGTERM + restart + /session/start: same_session=true
  (session restore across process restart)
- 07 workspace switch: workspace B gets its own session, ZERO cross-workspace
  content leak (asserted on the streamed reply text)
- 09 memory summary: 200
- Fail-closed honesty: /turn/stream 409 "需要通过真实流式探测的 Provider" and
  /plan/generate 400 "当前连接还不能用" when the provider is not live —
  Trainer refuses to fabricate teaching content with a dead connection.

## Requires a valid provider key (owner must supply; old key unrecoverable)
- Real-model turns (03/06/08) — request path executed, provider auth refused.
- /plan/generate 200 — gated on live provider by design.

Human teaching-quality judgment ("是否真正有帮助") remains a separate,
owner-gated acceptance regardless of key validity.
