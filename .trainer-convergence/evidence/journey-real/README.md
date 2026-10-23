# Real-model teaching journey — linksub relay + glm-5.3 (2026-10-24)

Owner supplied a fresh test key for the linksub relay (used ONLY via the
PROBE_PROVIDER_API_KEY environment variable; the key never appears in this
repository — verified by grep over every archived file before commit).

Probe: /tmp/trainer-conv/journey-probe.mjs (port-guarded sidecar on
127.0.0.1:34978, fresh TRAINER_DATA_DIR per run, 9-step journey + capability
step 02b). Run captured at HEAD 1ecbd8b code.

| step | result |
| --- | --- |
| 01 session start | 200 |
| 02 resource upload | 200, real resource id |
| 02b provider /provider/test | ok, streaming_ready=true, model_supported=true, tools_ready=true (real relay passes the fail-closed streaming gate) |
| 03 understand turn | 200, 327 chars, complete. Coach honestly declines to analyze the unseen code snapshot and asks for it — no fabricated analysis; no structured next_step in stream |
| 04 plan generate | 200, real plan id (needs inline provider override; probe now passes it) |
| 05 restart + restore | sidecar killed and restarted mid-journey; same session restored |
| 06 continuity turn | 200, 1415 chars, complete. Structured next step: 「把上面的 thread_slice.py 放入工作区并运行，成功信号是终端输出 `SLICE OK`；之后我可以用 verify_practice_current_file 对照实际文件做正式核对。」 — concrete, verifiable, tool-anchored, references the plan's current step after restore |
| 07 workspace switch | workspace B got its own session; cross_workspace_leak=false |
| 08 model switch (same relay, re-declared model) | 200, honest one-line confirmation 「我在，请继续。」 |
| 09 memory summary | present |

Teaching read: honesty-first (twice declined unseen code), plan continuity
across a sidecar restart, executable next step with success signal and a
formal-verification offer. This completes the real-model journey evidence for
the release gate's journey item; the human teaching sign-off (T-0028) remains
a separate owner-only gate.
