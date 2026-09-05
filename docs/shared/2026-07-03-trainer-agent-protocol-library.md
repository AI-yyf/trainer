# Trainer Agent Protocol Library

Updated: 2026-07-03

Purpose: this is the first curated protocol packet for Trainer's Resources sandbox. It is not a raw link dump. It is the normalized material that the coach, the provider adapter, and future library-cleanup jobs can use directly.

## Library Curation Contract

Every protocol packet that enters the Trainer library should be normalized into the same shape:

1. Source of truth:
   Official doc URL, captured date, protocol family.
2. Execution surface:
   Endpoint shape, request style, tool payload style, result loop style.
3. Tool behavior:
   Default tool policy, forcing options, schema guarantees, parallel-call behavior.
4. Trainer adapter note:
   What Trainer should infer by default, what must be explicit, and what should be blocked from hallucination.
5. Verification recipe:
   The smallest live probe that proves the protocol still works.
6. Cleanup rule:
   Keep the distilled packet, drop redundant scraps, note freshness, and keep one canonical summary instead of many near-duplicates.

That means the Resources view should gradually become a governed working library:

- raw source -> distilled packet
- distilled packet -> runnable adapter note
- runnable adapter note -> verified smoke script / scenario
- obsolete fragments -> trash / replace

## Official Source Map

- OpenAI Function Calling:
  [developers.openai.com/api/docs/guides/function-calling](https://developers.openai.com/api/docs/guides/function-calling)
- Anthropic Tool Use Overview:
  [platform.claude.com/docs/en/agents-and-tools/tool-use/overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- Gemini Function Calling:
  [ai.google.dev/gemini-api/docs/function-calling](https://ai.google.dev/gemini-api/docs/function-calling)

## Protocol Cards

### 1. OpenAI / OpenAI-compatible Chat + Responses

What matters:

- `tool_choice` can be `auto`, `required`, a specific function, or an allowed subset.
- `parallel_tool_calls: false` is the simplest way to keep a single-tool teaching loop stable.
- `strict: true` is the recommended schema mode.
- Responses attempts to normalize tool schemas into strict mode when possible; Chat Completions stays non-strict by default unless you opt in.
- Streaming function calls is supported.

Trainer adapter note:

- Treat OpenAI-compatible gateways as protocol family first, not by marketing name.
- Default capability posture for this family should be `chat/tools/streaming=true`.
- For teaching turns that need one grounded lookup, prefer a single-tool loop over parallel tool fan-out.
- When the learner explicitly asks for resource lookup, force or strongly constrain the tool set around `search_resources`.

Verification recipe:

- `/models` probe or provider test route.
- Single-turn tool call with one narrow resource search.
- Streaming probe only after the single-turn path is stable.

### 2. Anthropic Messages

What matters:

- Tool use can stay in `auto`, but Anthropic explicitly documents that the boundary is steerable by system prompt wording.
- Anthropic also documents that a stronger instruction like "Always call a tool first before responding." increases tool use.
- If prompting is not enough, `tool_choice` should be used to require a tool call.
- `strict: true` is supported for exact schema conformance.
- Claude's client-tool loop is: model returns `tool_use`, application executes, application returns `tool_result`.

Trainer adapter note:

- `api=anthropic` or `protocol=anthropic_messages` must resolve to the Anthropic Messages path even when the gateway hostname is not `anthropic.com`.
- Default capability posture for this family should be `chat/tools/streaming=true`.
- A teaching coach should not rely only on soft prompt hints when a grounded lookup is required; it should carry a strong turn-level search directive and, when possible, preload the most likely library fragments.
- The Messages-family loop is well-suited for Trainer's Coach because it cleanly separates teach -> tool -> teach.

Verification recipe:

- Raw `/v1/messages` probe with `x-api-key` and `anthropic-version`.
- One live Coach turn that uploads a unique library note, asks about that exact note, and verifies that `search_resources` ran before the reply.

### 3. Gemini Function Calling

What matters:

- Gemini supports tool-choice control through `generation_config.tool_choice.allowed_tools`.
- `mode: "any"` can constrain the model to a specific callable set.
- Gemini supports multi-tool use and can circulate built-in tool context with `previous_interaction_id`.

Trainer adapter note:

- Gemini should be treated as a first-class agent family, not only as "another OpenAI-compatible gateway".
- The single-card teaching loop still benefits from constraining the callable set to one or two tools.
- Stateful continuation should preserve the prior interaction/thread handle when the provider surface supports it.

Verification recipe:

- Minimal function-calling probe.
- Then a constrained library lookup turn with only the resource-search tool available.

## Trainer Policy: Library-first Coaching

Trainer should behave like a coach with a memory, not like a stateless chatbot:

- If the workspace library contains likely material for the current teaching question, Trainer should look there first.
- If the learner explicitly asks to search the library, Trainer must search before answering.
- If the learner names a coined term or project-specific phrase that is not grounded in the current thread, Trainer should prefer a library lookup over freehand explanation.
- The final reply should synthesize the best fragment, not dump the raw hit list.

## Trainer Policy: Library Cleanup

The Resources sandbox is allowed to be fully agent-managed, but it must stay clean:

- keep one canonical distilled note per protocol topic
- merge duplicates into the canonical note
- preserve provenance links
- move stale, low-trust, or conflicting fragments toward review/trash instead of silently mixing them into teaching
- keep short verification notes attached to the material so the next turn can reuse them

## Current Working Baseline in This Repo

This round established the baseline Trainer should build on:

- protocol hints can now come from `protocol`, `api`, or provider-key style fields instead of only a provider display name
- protocol families now carry default tool-capable capability flags instead of silently falling back to `tools=false`
- Coach turns now support stronger resource-search requirements
- Coach can preload likely resource hits into the turn context so the library is consulted more like a real coach's working memory

## Next Protocol Packets To Add

- OpenAI Responses native turn-state notes
- Gemini native adapter packet
- OpenAI-compatible gateway quirks packet
- Multi-provider model-switch packet for the composer/runtime handoff
