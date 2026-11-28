# The stored next step keeps the file name — before and after, on the real sidecar

Date: 2026-11-28. Commits: `ca08c00a` (before) → `2b75773c` (after). Tool: `/tmp/trainer-audit/rm/stub_fallback_probe.py` (outside the repository).

## Why a scripted model

The template fallback of the stored next step appears only when the model's reply carries no action of its own. With the live gateway that happened once in twenty turns (`evidence/real-model-story-2026-11-28.md` runs), so rolling the gateway again would not reproduce it on demand. The probe runs the real sidecar process, the real `/session/start`, `/provider/test` and `/turn/stream` routes and the real agent loop, and replaces only the model with a local OpenAI-compatible stub that replies with the words recorded from the live model. The sidecar verifies the stub's capabilities itself (chat, streaming, a forced no-op tool call).

## Input

The contract's story (`story_probe.STORY`), first four turns, guided, `zh-CN`, agent loop on. The first three replies end with a labelled action; the fourth — the Thursday turn — is the recorded reply that had none:

> 提示：退款和扣款的关键差别是**同一个 order_id 允许合法退多次**（部分退款、多次退款），所以幂等键不能用 order_id，得用这笔退款请求自己的标识。

Learner message: `我在 refunds.py 里也碰到类似的超时重试问题，这次我想自己修，只给我一句提示就好。`
Open file: `…/T/trainer-rm-stub-replay-<id>/refunds.py`, 91 characters.

## Result

| Tree | Stored next step of the Thursday turn (`response.agent.next_step`) |
|---|---|
| before `ca08c00a` | 下一步：围绕 `refunds.py`、「里也碰到类似的超时重试问」 ，先在 `trainer-rm-stub-replay-uods5c82` 里查看与这个问题直接相连的输入、分支或调用，带回第一条实际输出或报错。 |
| after `2b75773c` | 下一步：围绕 `refunds.py`、「超时重试问题」，先在 `refunds.py` 里查看与这个问题直接相连的输入、分支或调用，带回第一条实际输出或报错。 |

Before: the 80-character cap fell inside the path, so the "先在 `…` 里" slot held the tail of the temporary folder's name and no file name at all (with the live run's shorter folder it held `refunds.` / `refun`); the Chinese anchor was cut inside the word 「问题」.
After: the whole file name, the anchor cut at the clause's particle, no stray space before the comma.

In both runs the first three turns stored the labelled action of their own reply, and every turn's outcome was `success` with one model call.

## Limits

- The model's words are replayed, not generated: this shows what the pipeline stores for that reply, not how often the live model writes one.
- The same replay was not run against the live gateway after the fix.
