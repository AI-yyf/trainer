# Architecture Contract (standing constraints)

- Extension host (TS) + webview (React/Zustand) + FastAPI sidecar (Python).
- `WorkbenchSnapshot` is the universal response envelope; provider payloads are snake_case with camelCase aliases.
- Formal plan writes are optimistic-locked (`expected_revision`, 409 on conflict).
- Evidence honesty: `/training/attempt/evidence` records `self_reported`; host-trusted evidence only via `/training/verification/attest`; replay ledger prevents double-record on resend.
- Research models use dataclass(slots); core domain uses Pydantic. Do not mix.
- Browser capture: accepted work must never be silently dropped; queue mutations must be serialized/atomic; every task carries workspace/pairing/operation identity; 401 ≠ healthy; full queue must not silently evict.
- Async results must re-validate full identity (workspace/session/card/attempt/run + generation) before committing state.
- Local verification and Remote-SSH verification must write evidence through the same trusted writer.
