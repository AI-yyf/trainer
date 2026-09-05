# Unified Coach Master Plan

Date: 2026-06-29
Status: active planning source for the unified-coach program
Scope: product direction, scenario coverage, reuse strategy, acceptance bar

This document turns the current Trainer codebase into one clear product program:
Trainer should become a low-understanding-cost, strong-teaching, recoverable,
verifiable, long-evolving unified coach.

When documents disagree:

1. `docs/ui-contract.md` remains the source of truth for shipped IA and view ownership.
2. `docs/verification.md` remains the source of truth for verification commands.
3. This file is the source of truth for what the next major product state must become.

## 1. North Star

Trainer is not a chat skin and not an auto-coder.
Trainer is a conversation-first learning coach inside VS Code that can:

- understand the current workspace and the learner's goal,
- turn that understanding into a governed plan,
- ingest and curate learning resources,
- generate and run teaching cards grounded in real files,
- recover truthfully from blocked states,
- prove what was learned and what still is not learned,
- keep improving its teaching materials over time without reinventing the stack.

The product promise is simple:

- the user starts in `Coach`,
- every serious action can flow into `Plan`, `Resources`, `Training`, or `Settings`,
- every result can flow back into the next teaching decision,
- nothing important becomes invisible, unverifiable, or unrecoverable.

## 2. Non-Negotiables

The unified coach must preserve all of these rules at once:

- Exactly five top-level views: `Coach`, `Plan`, `Resources`, `Training`, `Settings`.
- `Coach` is the super-entry for natural language, slash/skill commands, and recovery.
- `Training` stays `single-card-first`.
- Provider, sidecar, and workspace states must be honest; no fake readiness.
- Sandbox and workspace boundaries must stay explicit and auditable.
- `Plan` is governed truth, not a silently mutated chat summary.
- `Resources` are a governed knowledge library, not a general file manager.
- Eight-language i18n must keep deterministic fallback behavior.
- Windows, macOS, and Linux must keep the same product semantics.
- Prefer open, commercial-friendly reuse over custom infrastructure.

## 3. What Already Exists in the Repo

Trainer is not starting from zero. The current repo already has important anchors:

| Area | Existing anchor | Why it matters |
| --- | --- | --- |
| Five-view IA | `docs/ui-contract.md` | Prevents IA drift and dashboard sprawl |
| Typed message parts | `shared/src/protocol.ts`, `CoachMessageParts.tsx` path documented in `docs/ui-contract.md` | Makes Coach capable of tool/result/plan/card rendering without a fake job console |
| Skill deck | `shared/src/skillCatalog.ts` | Coach can already act like a command-and-skill super-entry |
| Provider protocols | `shared/src/providerProtocols.ts` | The product already understands OpenAI, Anthropic, Gemini, and compatible endpoints |
| Workspace authority | `server/app/workspace/authority.py`, `shared/src/remoteWorkspace.ts` | There is already a boundary model for remote/local workspace truth |
| Training routing | `shared/src/trainingCardRouting.ts`, `server/app/training/*` | The repo already has a real card-selection model instead of pure chat-only drills |
| Resource carrier root | `docs/workspace-first-artifact-layout.md` | Trainer-owned artifacts already live outside user project code by default |
| Verification skeleton | `docs/verification.md`, `scripts/check.ps1`, `scripts/smoke.ps1` | There is already a path to proving behavior instead of only describing it |
| Browser preview scenarios | `extension/webview/src/lib/browserPreviewHarness.ts` | We can test narrow-sidebar UX and scenario cards without full VS Code boot |

Implication: the correct strategy is not "rebuild Trainer."
The correct strategy is "tighten and connect the existing pieces into one coherent coach."

## 4. Required Scenario Coverage

Trainer must cover all of these scenarios without creating extra top-level views.

| Scenario | Coach responsibility | Plan responsibility | Resources responsibility | Training responsibility | Verification |
| --- | --- | --- | --- | --- | --- |
| Pure Q&A | answer, clarify, suggest next move | optional follow-up task | cite relevant resource if present | offer flash/practice only when helpful | answer quality, grounded references |
| Existing project learning | inspect file, explain current code, propose smallest next move | create or refresh project subplan | surface code/resource evidence | generate project-grounded practice | learner can act in real files |
| Empty folder bootstrapping | help define goal and first scaffold task | create first milestone | suggest starter references | issue first minimal practice card | first working artifact appears |
| Remote workspace onboarding | explain boundary before deeper coaching | record remote mode and constraints | keep managed artifacts outside project by default | generate remote-boundary practice/flash cards | learner can explain host/path/credential boundary |
| Debugging | shrink problem to one trustworthy loop | record blocker and verification target | attach logs, traces, or docs | generate minimal debug-loop practice/flash cards | one reproduced issue, one proved bad state |
| Function hints and unfamiliar APIs | explain what hover/signature/definition prove | link gap to plan stage | attach docs or local call sites | generate function-contract recovery cards | learner can state one real contract safely |
| Resource ingestion | explain what imported material is good for | connect resource to plan evidence or backlog | import, index, preview, score trust | derive flash/practice candidates | provenance and next-use path stay visible |
| Dependency/API study | compare library role and project fit | place the dependency into the plan | curate official docs and trusted references | issue usage and transfer cards | learner can use the dependency in code |
| Provider setup and failure recovery | explain what failed and what is still possible | avoid mutating plan from transport failure | none unless docs are needed | allow theory/resource work while blocked | auth, endpoint, model, and protocol states stay truthful |
| Cross-session resume | summarize what was active | restore stage, blocker, due review, next step | restore relevant artifacts | reopen the active or due card | no silent loss of context |

Three scenario families are especially important because the user explicitly asked for them:

1. Remote workspace coaching: SSH, tunnels, dev containers, WSL, local.
2. Debug coaching: reproduction, breakpoint placement, state verification, explanation.
3. Function guidance coaching: hover, signature help, definition, call site, safe next edit.

## 5. Coach Interaction Model

Trainer should feel closer to a strong coach-agent product, but stay a teaching tool.

The interaction model should be:

- message-first,
- command-oriented,
- typed-part-grounded,
- recoverable,
- explicit about next action.

### 5.1 Inputs

Coach must accept three first-class inputs:

- natural-language messages,
- slash/skill commands,
- context-aware action pills.

The command families should remain visible and predictable:

- explain and review,
- plan and next-task,
- resource import and indexing,
- sandbox and workspace boundary,
- provider and model diagnostics,
- training card generation and resume.

### 5.2 Outputs

Each serious coach reply should be able to contain:

- a direct teaching answer,
- typed parts for tools/results/reasoning/plan/card evidence,
- the current smallest next move,
- an optional structured handoff into `Plan`, `Resources`, or `Training`.

### 5.3 Rules

Coach must never:

- silently rewrite the formal plan,
- pretend a provider is usable because HTTP responded once,
- claim practice success without verification,
- hide the workspace boundary,
- bury the next action under decorative UI noise.

## 6. View-by-View Product Contract

### 6.1 Coach

First viewport promise:
the learner can immediately see what Trainer understood, what it is doing, and what to do next.

Must provide:

- conversation truth,
- typed parts,
- slash/skill entry,
- context chips,
- agent activity,
- recovery messages,
- route into all other views.

Must not become:

- a second dashboard,
- a hidden plan editor,
- a fake terminal log.

### 6.2 Plan

First viewport promise:
the learner can see the current line of work, why it matters now, and how it will be verified.

Must provide:

- master plan and project subplans,
- explicit stage status,
- blockers,
- evidence queue,
- review queue,
- freeze/replan controls.

Must not become:

- a chat transcript,
- a task dump with no hierarchy,
- an auto-mutating artifact.

### 6.3 Resources

First viewport promise:
the learner can find, trust, preview, and convert resources without losing provenance.

Must provide:

- governed carrier-root storage,
- import from file/folder/URL,
- search and preview,
- trust/freshness/provenance metadata,
- transform path into cards, plan evidence, or knowledge atoms.

Must not become:

- a CMS,
- a raw filesystem browser,
- a place that writes into user project code by surprise.

### 6.4 Training

First viewport promise:
the learner knows the current card, why it is now, what to deliver, how to verify it, and where the result returns.

Must provide:

- one dominant current card,
- flash, practice, review, scenario, and transfer flows,
- clear recovery,
- clear completion backflow,
- due-review and weakness continuity.

Must not become:

- a card dashboard,
- a mixed feed of many equal-priority tasks,
- a hidden grading system with no visible proof.

### 6.5 Settings

First viewport promise:
the learner knows whether Trainer is truly usable right now and what remains to be configured.

Must provide:

- provider profiles,
- protocol selection,
- model refresh,
- connection testing,
- language and teaching defaults,
- remote credential mode guidance,
- workspace context policy.

Must not become:

- a business-content view,
- a fake green status panel,
- a place that hides auth, model, or sidecar failures.

## 7. Training Card System

Trainer needs a stable card grammar, not ad hoc prompts.

Every serious card should carry these fields:

- `whyNow`
- `targetSkill`
- `problemStatement`
- `learnerDeliverable`
- `verificationSteps`
- `returnWith`
- `fallbackAction`
- `nextAfterCompletion`

### 7.1 Card families

| Family | Purpose | Typical source |
| --- | --- | --- |
| Flash | compress recall | resource atom, repeated weakness, dependency/API fact |
| Practice | perform one real action | current workspace, current blocker, plan gap |
| Review | reflect on failure or success | finished or failed practice |
| Scenario | transfer into context | remote/debug/function/dependency/project situations |
| Transfer | apply known skill in a new folder/project | repeated cross-project weakness or growth edge |

### 7.2 Required scenario packs

The first scenario packs should be:

1. Remote boundary pack
   - practice: identify workspace type, host ownership, safe credential mode, and one concrete path fact
   - flash: restate the local-vs-remote credential rule in one sentence
2. Minimal debug-loop pack
   - practice: reproduce once, stop once, prove one bad state
   - flash: restate the smallest trustworthy debug loop before editing
3. Function-contract recovery pack
   - practice: recover one contract from hover, signature help, definition, and one call site
   - flash: state what each editor signal proves and does not prove
4. Resource-to-knowledge pack
   - practice: turn one imported document or URL into one trusted knowledge atom and one next card
   - flash: recall the provenance and the one key concept extracted
5. Dependency/API mastery pack
   - practice: use one real dependency/API in context with one verified output
   - flash: recall one core capability, one sharp edge, and one safe usage rule

### 7.3 Example card specs

These examples are the quality bar for real cards. They are not mock copy only; they define the shape that live card generation should satisfy.

Example: remote-boundary practice card

```yaml
type: practice
scenarioPack: remote_boundary
title: Verify the remote workspace boundary
whyNow: Deeper remote coaching is unsafe until host ownership and credential flow are explicit.
targetSkill: Explain workspace host ownership and safe credential placement.
problemStatement: Prove which machine owns the workspace files, which credential mode is safe, and which path fact confirms that judgment.
learnerDeliverable:
  - one sentence naming the workspace type
  - one concrete path or URI fact
  - one credential-mode decision with reason
verificationSteps:
  - identify remote type: local, SSH, tunnels, dev container, or WSL
  - confirm one real path or mount point
  - state whether credentials should stay local or remote
returnWith: workspace type, path fact, credential decision
fallbackAction: if the path story is unclear, prove only host ownership first
nextAfterCompletion: continue remote task with the boundary now fixed
```

Example: debug-loop flash card

```yaml
type: flash
scenarioPack: minimal_debug_loop
title: State the smallest trustworthy debug loop
whyNow: Blind edits are more likely than grounded debugging at this point.
targetSkill: Recall the minimum loop before editing code.
question: What is the smallest trustworthy debug loop before you change code?
expectedAnswerShape:
  - one reproduction step
  - one pause point
  - one bad-state observation
verificationSteps:
  - learner answer fits the three-part shape
  - learner does not skip directly to code changes
returnWith: one-sentence debug rule
fallbackAction: re-open the failing path and find the first state transition
nextAfterCompletion: launch the matching practice card in the real file
```

Example: function-contract practice card

```yaml
type: practice
scenarioPack: function_contract_recovery
title: Recover one function contract from editor signals
whyNow: A safe edit depends on proving what one function expects and returns.
targetSkill: Use hover, signature help, definition, and one call site as separate evidence sources.
problemStatement: Recover one function contract and name one safe next edit that respects it.
learnerDeliverable:
  - function name
  - expected inputs
  - expected output
  - one confirming call site
  - one safe next edit
verificationSteps:
  - hover or signature help checked
  - definition checked
  - one real call site checked
  - safe next edit does not contradict the recovered contract
returnWith: contract summary plus one grounded next edit
fallbackAction: reduce scope to one function and one call site
nextAfterCompletion: implement or review the next edit with the contract visible
```

## 8. Self-Evolution Without Wheel Reinvention

The self-evolution system should not mean "Trainer writes itself."
It should mean Trainer gets better at choosing, ingesting, and operationalizing good material.

The pipeline should be:

1. Discover candidate sources:
   - official docs,
   - permissively licensed repos,
   - user-provided resources,
   - trusted tutorials or reference projects.
2. Filter:
   - license,
   - maintenance activity,
   - scenario fit,
   - implementation quality,
   - ingestion cost.
3. Ingest:
   - import into managed resource storage,
   - preserve provenance,
   - extract knowledge atoms.
4. Operationalize:
   - generate cards,
   - generate plan evidence candidates,
   - generate scenario packs.
5. Learn from outcomes:
   - which cards actually helped,
   - which resources were stale or confusing,
   - which scenario packs improved transfer.

This system must never:

- auto-install heavy infrastructure as a hidden dependency,
- import incompatible licenses into core product code,
- blur resource storage with user project storage,
- turn Trainer into an unconstrained agent runtime.

## 9. Open-Source Reuse Strategy

The stack should reuse proven pieces with clear licenses and narrow adaptation layers.

| Component | Use mode | Why | Source |
| --- | --- | --- | --- |
| `cc-switch` | adapt directly | provider profiles, active profile marker, history/template patterns | <https://github.com/farion1231/cc-switch> |
| `Pydantic AI` | adapt directly | provider/model abstraction, typed agent contracts, fallbacks | <https://github.com/pydantic/pydantic-ai> |
| `MarkItDown` | adapt directly | multi-format conversion into searchable teaching material | <https://github.com/microsoft/markitdown> |
| `ts-fsrs` and `py-fsrs` | adapt directly | shared spaced-repetition logic in TS and Python | <https://github.com/open-spaced-repetition/ts-fsrs>, <https://github.com/open-spaced-repetition/py-fsrs> |
| `assistant-ui` | borrow interaction and typed-part ideas | message/tool/artifact primitives without copying product IA | <https://github.com/assistant-ui/assistant-ui> |
| VS Code Remote platform | rely on official platform behavior | remote SSH, tunnels, dev containers, and WSL should stay native | <https://code.visualstudio.com/docs/remote/ssh>, <https://code.visualstudio.com/docs/remote/tunnels>, <https://code.visualstudio.com/docs/devcontainers/containers>, <https://code.visualstudio.com/docs/remote/wsl> |
| VS Code editor platform | rely on official platform behavior | debugging and IntelliSense should stay native teaching surfaces | <https://code.visualstudio.com/docs/editor/debugging>, <https://code.visualstudio.com/docs/editor/intellisense> |
| `Pi` | reference only | project-local policy, permission, and remote abstraction ideas | <https://github.com/earendil-works/pi> |
| `OpenClaw` | reference only | workspace-first and memory-layout ideas, but not its heavier gateway/skill runtime as our default stack | <https://github.com/openclaw/openclaw> |

Do not make these part of the default required stack:

- external LLM gateway,
- external vector database,
- heavy office-online server,
- Docker-only sandbox,
- general-purpose agent runtime with its own infra expectations.

## 10. Runtime Truth Observations

These are current facts that the program must design around.

- The browser preview already supports explicit remote/debug/function training scenarios through `extension/webview/src/lib/browserPreviewHarness.ts`.
- Desktop and browser-preview stream routing now split by intent: Coach/default turns use `/session/message/stream`; structured views use `/turn/stream`.
- `shared/src/remoteWorkspace.ts` and `server/app/workspace/authority.py` already model remote types and workspace boundaries, but they still need product-level teaching flows around them.
- `shared/src/trainingCardRouting.ts` already gives Trainer a real scoring and routing model for cards; this should be expanded, not replaced.
- On 2026-06-29, a real smoke against the user-supplied MiniMax-compatible endpoint returned `401 authentication_failed` with a token-unavailable message for both `/models` and `/chat/completions`. This must be treated as an honest provider-failure path, not as proof of product readiness or a Trainer bug.

## 11. Definition of Done

Trainer reaches the next major bar only when all of these are true:

- Five-view IA remains fixed.
- Coach genuinely works as the super-entry.
- Slash/skill logic is visible and predictable.
- Plan, Resources, Training, and Settings each close their own loop.
- Remote/debug/function teaching flows are first-class, not demo-only.
- Cards can be resumed, verified, and flowed back into plan and memory.
- Provider and sidecar failures stay honest everywhere.
- Eight-language fallback remains intact.
- Windows, macOS, and Linux preserve the same behavioral semantics.
- Open-source reuse lowers complexity instead of creating hidden infra debt.

## 12. Immediate Next Slice

After this plan, the highest-value implementation order is:

1. Provider truth and recovery end-to-end
   - Settings, Coach, and resume states must agree on auth/protocol/model truth.
2. Live scenario packs
   - remote/debug/function cards must be generated from real workspace context, not preview-only data.
3. Plan/resource/training backflow
   - card completion must explicitly update evidence and next-step logic.
4. Cross-platform hardening
   - non-PowerShell verification path and CI matrix for Windows/macOS/Linux.
5. Self-evolution loop
   - trusted-source intake, license filtering, knowledge extraction, card scoring, and outcome feedback.
