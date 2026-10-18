# R2 — reasoning-first provider truncation (deepseek-v4.1-flash)

## Symptom (real model, real sidecar, 32-case harness)

First run against `deepseek-v4.1-flash` (linksub OpenAI-compatible gateway):

```
fixtures 32/32 passed
turn classification: {local_fallback: 60, passed: 4}
```

64 turns, 60 of them fell back to local degraded replies. The user-facing copy
was `Provider request failed; upstream response body redacted.` and the sidecar
log (after adding failure logging) showed:

```
[provider] reply failure category=truncated_or_empty status=200 retryable=True
detail=Provider response ended before Trainer received a complete visible
coaching reply. Provider response reached its output limit before completion.
```

## Root cause

`deepseek-v4.1-flash` is reasoning-first: it spends output tokens on
`reasoning_content` before any visible text. The coaching lanes request a
1024-token output budget, which the hidden reasoning can consume entirely
(`finish_reason=length`, empty visible content). Trainer classified that as a
provider failure and fell back — even though the model and gateway work
(chat, streaming, and tool calls all probed `200`).

The truncation path had a retry only for the Anthropic-native lane; the
OpenAI-compatible lanes (the majority of gateways) had no budget escalation.

## Fix

One adaptive escalation: when a reply is explicitly truncated/empty, retry
**once** with a reasoned headroom (8192 tokens, bounded; never for models that
answered within the normal budget). Applied at every live chokepoint:

| Lane | Code |
| --- | --- |
| Non-stream coaching (`/turn`) | `ProviderService._llm_reply` |
| Streaming coaching (`/turn/stream`) | `_provider_service_coaching_reply_stream` (the live implementation assigned over the base method) |
| Plain completion / stream | `ProviderService.chat_completion`, `chat_completion_stream` |
| Agent binding (tool loop) | `ProviderAgentBinding._openai_truncated_budget_retry` |
| Reasoning-first detection | `capability.py` pattern now covers `deepseek[-_. ]?v\d` |

Also added: every provider turn failure now logs one redacted
`[provider] reply failure category=… status=… detail=…` line — the sidecar was
previously silent about provider failures, which is why this class of bug had
no diagnostic trail.

## Evidence

| Run | Result |
| --- | --- |
| Before the fix | 4 passed / 60 local_fallback (64 turns) |
| After the first escalation (4096) | **54 passed / 1 failed / 9 local_fallback** |
| After tuning to 8192, previously failing subset (`03-nested-alias`, C2, C3, D1) | **8/8 passed**, 0 fallback |
| Final full 32-case rerun (8192) | **59 passed / 2 failed / 3 local_fallback** (64 turns) |

The final rerun's residual, with the real provider log:

| Turns | Classification | Cause |
| --- | --- | --- |
| 2 | `failed` | `server sent no grounding stamp for an ungrounded step` — a grounding-honesty gap (R5), not provider usability |
| 1 | `local_fallback` | `language_corruption` — the gateway returned mojibake; Trainer honestly refused to treat it as a clean turn |
| 2 | `local_fallback` | `Provider test failed` — the connection-test probe path still exceeds its small probe budget on this gateway (follow-up) |

57 budget escalations fired across the run; only these 5 turns did not end in
a model-produced, trustworthy reply, and each is classified honestly rather
than counted as a pass.

Regression tests added:
`test_openai_chat_call_escalates_the_budget_after_a_truncated_reply`,
`test_empty_stream_escalates_the_budget_once_and_recovers`.

## Residual

Any fallback that survives the single escalation is reported honestly as
`local_fallback` (never counted as a model-quality pass). The harness copy for
those turns still says the provider path is blocked, which is accurate — the
gateway/model really did not return a usable coaching reply for that turn.
