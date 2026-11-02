# Real-model teaching journey — 1c82a41 (2026-11-02)

Real sidecar + SQLite on 127.0.0.1:34978, fresh data dir, owner-supplied
OpenAI-compatible relay. Primary model MiniMax-M2.7; switch model
MiniMax-M3.1-Flash. Key supplied only through `PROBE_PROVIDER_API_KEY`.

| step | result |
| --- | --- |
| 01 session start | 200 |
| 02 resource upload | 200, real resource id |
| 02b provider test | 200: streaming/tools/model verified |
| 03 understand turn | 200, 787 visible chars, complete |
| 04 plan generate | 200, real plan id |
| 05 restart restore | sidecar killed/restarted; same session restored |
| 06 continuity turn | 200, 1747 visible chars, complete |
| 07 workspace switch | 200; workspace B clean, no cross-workspace leak |
| 08 model switch | M3.1 tested and used; concise confirmation |
| 09 memory summary | 200 |

This is machine evidence, not a human teaching-quality sign-off. The separate
real VS Code GUI journey is under `../real-vscode-gui-2026-11-02/`.
