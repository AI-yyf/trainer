# MiniMax-M3.1 stream-close trace — 2026-11-02

The historical GUI sample showed correct visible text but no stream close for
240 s. Current-HEAD attempts did not reproduce it; this directory keeps the
full traces rather than claiming a fix.

| probe | result |
| --- | --- |
| upstream `/chat/completions` stream | 17.9 s, `finish_reason=stop`, `[DONE]`, 45 visible chars, 426 reasoning chars |
| sidecar `/session/message/stream` (non-agent, saved session) | 4.3 s, `event: complete`, 47 visible chars |
| sidecar `/session/message/stream` (agent loop + workspace snapshot) | 25.9 s, `event: complete`, tool calls, 208 visible chars |
| real installed VS Code GUI (M3.1, mouse/keyboard) | 9 s and 6 s in two runs; no streaming dots/cursor at the end |
| host trace | `[stream] ... complete bytes=12945`, `loop-ended complete=true response=true` |

The assistant reply is persisted in the session database and renders after a
reload (`gui-restored.png`). No current provider, sidecar, or host completion
defect was found in these runs. The historical 240 s PARTIAL remains as a
residual risk, most likely a transient relay/stream condition; it is not
claimed as fixed.
