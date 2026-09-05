# Trainer Built-in Skill Intake

Date: 2026-07-10

Purpose:
- identify strong open-source agent tools and skill ecosystems that Trainer can absorb
- separate direct built-in candidates from reference-only projects
- keep every intake honest to Trainer's current five-view product contract

## Intake rules

Trainer should only absorb an external tool as a built-in skill when all of these are true:

1. license is commercially usable
2. the capability fits one of the five existing views
3. the runtime boundary stays truthful
4. the capability lowers learning cost instead of adding another control surface
5. the result can flow back into Coach, Plan, Resources, or Training

If a repo is useful but too heavy, too coupled, or too runtime-specific, Trainer should borrow the pattern rather than vendor the whole stack.

## Direct built-in candidates

### 1. Agent Reach
- Repo: https://github.com/Panniantong/agent-reach
- License: MIT
- Why it fits:
  - retrieval-first reach across web surfaces
  - strong "search first, then rank, then teach" mental model
  - maps directly to Trainer Resources and Coach
- Intake shape inside Trainer:
  - built-in `$reach` skill
  - retrieval-first source sweep
  - top-source ranking by relevance, trust, and next-step fit
- Do not copy:
  - whole CLI shell surface
  - "internet everywhere" assumption when Trainer is offline or policy-blocked

### 2. MarkItDown
- Repo: https://github.com/microsoft/markitdown
- License: MIT
- Why it fits:
  - excellent document-to-markdown ingestion
  - already aligned with Trainer's resource-to-teaching pipeline
  - useful for theory, books, office docs, and mixed-format study
- Intake shape inside Trainer:
  - resource normalization
  - note extraction
  - flash/practice candidate generation from converted content
- Guardrail:
  - keep file-access scope governed by the Trainer sandbox boundary

### 3. OpenSkills
- Repo: https://github.com/numman-ali/openskills
- License: Apache-2.0
- Why it fits:
  - same portable skill-file direction as modern coding agents
  - useful reference for cross-agent skill packaging and loading
- Intake shape inside Trainer:
  - skill packaging compatibility
  - future import path for external skill bundles
  - built-in `$bundle` skill for packaging a reusable skill bundle candidate
- Guardrail:
  - do not make Trainer dependent on an external loader runtime for core UX

### 4. Mem0
- Repo: https://github.com/mem0ai/mem0
- License: Apache-2.0
- Why it fits:
  - strong memory-layer patterns for long-lived agents
  - aligns with Trainer's recovery, repeated blockers, and learning traces
- Intake shape inside Trainer:
  - memory selection strategy
  - recovery-aware recall
  - evidence and weakness carry-forward
- Guardrail:
  - Trainer should keep its own governed learning memory semantics instead of copying a generic assistant memory model

## Reference-only or partial-intake candidates

### 5. RAGFlow
- Repo: https://github.com/infiniflow/ragflow
- License: Apache-2.0
- Use it for:
  - retrieval ranking ideas
  - ingestion, parsing, and context-layer patterns
  - multi-source evidence assembly
- Do not vendor by default:
  - too heavy for Trainer's default desktop-first extension stack
  - risks turning Resources into a backend platform instead of a teaching library

### 6. Agent Skill Index
- Repo: https://github.com/heilcheng/awesome-agent-skills
- License: MIT
- Use it for:
  - discovery
  - external skill sourcing
  - curation patterns
- Do not vendor by default:
  - it is a directory, not a runtime

### 7. Youtu-Agent
- Repo: https://github.com/TencentCloudADP/youtu-agent
- License: MIT
- Use it for:
  - orchestration ideas
  - open-model-friendly agent patterns
- Do not vendor by default:
  - Trainer already has a coach-first runtime and should not grow a second agent shell

## Built-in skill pack to surface now

These are honest to the current Trainer codebase and should be visible now:

1. `$reach`
   - retrieval-first source sweep
   - library first, governed web search second
   - returns top sources for the immediate next step

2. `$map`
   - builds a source map
   - clusters official docs, code examples, failure cases, and tutorials
   - helps the learner pick what to read first

3. `$distill`
   - turns current sources into reusable teaching assets
   - one note
   - one flash candidate
   - one practice-card candidate
   - one plan-evidence candidate

4. `$lecture`
   - deep explanation with theory-plus-code teaching flow
   - already aligned with the existing lecture-style skill direction

5. `$bundle`
   - packages the current topic into a portable skill bundle candidate
   - keeps trigger, scope, inputs, outputs, examples, and guardrails explicit
   - useful for Trainer-owned skill curation and export/import later

## Product truth rules

- `$reach` must not pretend that blocked network search succeeded
- `$map` must keep source provenance visible
- `$distill` must preserve the return path into Plan and Training
- no built-in skill may silently mutate the formal plan
- no skill may write outside the governed resource sandbox

## Next intake moves

1. connect built-in skill surfacing to the shared skill catalog instead of only local UI suggestions
2. add governed external skill import for selected SKILL.md bundles
3. attach license and provenance metadata to imported skills inside Resources
4. let Trainer decide whether a new source becomes:
   - note
   - flash
   - practice
   - evidence
   - or background-only material
