# Trainer 8-Capability Audit & Progress Report
**Date**: 2025-06-15  
**Reference**: `docs/open-source-fit-and-provider-strategy.md`

## Executive Summary

Trainer has strong foundations across all 8 capability areas. The core architecture already implements the strategy's requirements. This report assesses current state, identifies gaps, and prioritizes next actions.

---

## 1. Provider / 模型层 (Provider v2)

### Current State ✅ STRONG
- Provider v2 schema with profile registry already implemented
- Protocol enum: `openai_responses`, `openai_chat_completions`, `anthropic_messages`, `openai_chat_completions_compatible`
- Multi-profile support with `.current` marker
- Model aliases and task bindings
- Provider diagnostics and test results
- API key management via VS Code secrets

### Strategy Alignment ✅
- `cc-switch` style profile management: **IMPLEMENTED**
- Pydantic AI style abstraction: **PARTIAL** (using own types)
- Direct API adapters: **IMPLEMENTED**
- Protocol-aware capability gating: **IMPLEMENTED**

### Gaps
- Gemini protocol (`gemini_generate_content`) not yet in enum
- Model capability matrix UI could show more detail
- Task binding UI could be more interactive

### Next Actions
- [ ] Add `gemini_generate_content` to protocol enum
- [ ] Enhance model capability matrix display in Settings

---

## 2. Resources / Workspace / Sandbox

### Current State ✅ STRONG
- Active workspace root concept implemented
- 6-level permission system: `inspect`, `annotate`, `reorganize`, `generate`, `apply`, `destructive`
- Path normalization with root boundary validation
- Trash/ledger for destructive operations
- Checkpoint support

### Strategy Alignment ✅
- Claude Code workspace-first: **IMPLEMENTED**
- Pi project-local settings: **PARTIAL**
- Folder sovereignty model: **IMPLEMENTED**

### Gaps
- Mounted sources manifest not yet surfaced in UI
- Operation ledger UI could show pending changes
- Checkpoint diff viewer could be enhanced

### Next Actions
- [ ] Surface mounted sources in Resources view
- [ ] Add operation ledger summary to workspace authority panel
- [ ] Enhance checkpoint diff viewer

---

## 3. File Preview 三层能力梯

### Current State ✅ STRONG
- Tier badges already implemented (Tier A/B/C)
- Text/code preview with CodeMirror + Shiki
- PDF preview with react-pdf + PDF.js
- CSV preview with structured table
- DOCX preview with docx-preview
- PPTX/XLSX preview in progress
- Audio preview with wavesurfer.js

### Strategy Alignment ✅
- All recommended libraries already integrated or planned
- Tier classification working
- VS Code native editor fallback available

### Gaps
- MarkItDown not yet integrated for universal conversion
- Video preview not yet implemented
- Some preview types need error state improvements

### Next Actions
- [ ] Integrate MarkItDown for universal Tier B conversion
- [ ] Add video quick preview
- [ ] Improve preview error states with retry options

---

## 4. Search 与资料利用

### Current State ✅ STRONG
- SQLite FTS5 lexical search
- Metadata filtering (trust, project, freshness)
- Path/title/symbol recall
- Citation system with IDs

### Strategy Alignment ✅
- Lexical-first: **IMPLEMENTED**
- Semantic-optional: **ARCHITECTURE IN PLACE**
- Teaching-oriented result packaging: **PARTIAL**

### Gaps
- Search results could show more teaching signals
- "Inject to training card" toggle not prominent
- Result trust/project indicators need visual polish

### Next Actions
- [ ] Add teaching signals to search results (skill level, last practiced)
- [ ] Make "inject to training card" more visible
- [ ] Add recency weighting visualization

---

## 5. 会话渲染 (Typed Parts Registry)

### Current State ✅ STRONG
- PartsRenderer with type switch
- Markdown, code, diff, table, citation, tool_call, tool_result
- Reasoning, training_card, plan_update, test_result
- File_preview, checklist, alert
- Mermaid, math rendering

### Strategy Alignment ✅
- `assistant-ui` style taxonomy: **IMPLEMENTED**
- `Vercel AI Elements` taxonomy reference: **FOLLOWED**

### Gaps
- Some parts could use better animations
- Tool call streaming state could be more visual
- Long outputs need better collapse/expand UX

### Next Actions
- [ ] Add streaming animation for tool calls
- [ ] Improve collapse/expand for long outputs
- [ ] Add result caching visualization

---

## 6. Training 核心

### Current State ✅ STRONG
- FSRS scheduler already implemented in Python sidecar
- Single-card state machine: idle → queued → present_card → learner_attempt → evidence_submit → coach_feedback → rating
- Card types: Recall, Explain, Predict, Drill, Debug, Transfer, Review
- Hint ladder with tier disclosure
- Evidence submission and feedback

### Strategy Alignment ✅
- `ts-fsrs` / `py-fsrs`: **IMPLEMENTED**
- Retrieval practice principles: **IMPLEMENTED**
- Worked-example fading: **ARCHITECTURE READY**

### Gaps
- Hint ladder UI could be more visual with numbered tiers
- Training progress visualization could be enhanced
- Evidence submission UX could be smoother

### Next Actions
- [ ] Enhance hint ladder with tier indicators (CSS already added)
- [ ] Add training progress bar
- [ ] Improve evidence submission flow

---

## 7. Memory 分层体系

### Current State ✅ STRONG
- Master plan memory
- Project memory (per-project plans, goals)
- Session memory
- Resource memory (provenance, trust, chunks)
- Review memory (FSRS card state)
- Preference memory
- Provider diagnostics memory

### Strategy Alignment ✅
- Claude Code memory organization: **FOLLOWED**
- Layer separation: **IMPLEMENTED**
- Retrieval hierarchy: **IMPLEMENTED**

### Gaps
- Memory layer visual indicators in UI could be enhanced
- Layered memory summary in conversation could be more informative
- Memory update policies could be more visible

### Next Actions
- [ ] Add memory layer indicators (CSS already added)
- [ ] Enhance memory layer summary component
- [ ] Surface memory update policies in Settings

---

## 8. Remote 访问

### Current State ✅ STRONG
- VS Code Remote SSH / Tunnels / Dev Containers复用
- `workspace.fs`, `findFiles`, `FileSystemWatcher` integration
- Remote-aware provider diagnostics
- sidecar runs on extension host side

### Strategy Alignment ✅
- VS Code Remote as first-class citizen: **IMPLEMENTED**
- Sidecar near workspace: **IMPLEMENTED**
- No remote sync layer: **COMPLIANT**

### Gaps
- `credentialMode` UI (`workspace_secret` vs `ui_proxy`) not surfaced
- Remote connection status could be more visible in header
- Remote workspace trust indicators could be enhanced

### Next Actions
- [ ] Add credential mode selection in Settings
- [ ] Enhance remote status in header
- [ ] Add remote trust indicators

---

## UX Improvements Added (2025-06-15)

### Completed
1. **Quick Actions Labels**: More action-oriented labels ("看代码", "解释原理", etc.)
2. **Composer Placeholder**: More guiding placeholder text
3. **CSS Animations**: FadeIn, pulse, slideInUp, hover effects
4. **Hint Ladder**: Tier indicators with numbered badges
5. **Training Card**: Hover effects, active states, progress bar
6. **Shortcut Hints**: Keyboard shortcut display on send button hover
7. **Focus Management**: Better focus states for accessibility

### Files Modified
- `extension/webview/src/app/AppRecovered.tsx`
- `extension/webview/src/components/composer/CoachComposer.tsx`
- `extension/webview/src/styles.css` (~250 lines added)

---

## Open Source Reuse Summary

| Component | Library | License | Status |
|-----------|---------|---------|--------|
| Code preview | CodeMirror 6 | MIT | ✅ Integrated |
| Code highlighting | Shiki | MIT | ✅ Integrated |
| PDF preview | react-pdf + PDF.js | MIT + Apache-2 | ✅ Integrated |
| DOCX preview | docx-preview + Mammoth | Apache + BSD-2 | ✅ Integrated |
| CSV/Table preview | TanStack Table | MIT | ✅ Integrated |
| Audio preview | wavesurfer.js | BSD-3 | ✅ Integrated |
| File tree | react-arborist | MIT | 🔲 Not yet integrated |
| Universal conversion | MarkItDown | MIT | 🔲 Next phase |
| FSRS scheduler | py-fsrs | MIT | ✅ Implemented |
| Provider abstraction | Pydantic AI | MIT | 🔲 Design reference |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Preview library bloat | Use tree-shaking, lazy load heavy libraries |
| Memory growth with FTS5 | Implement chunk limits, cleanup policies |
| Remote performance | Index on workspace side, not local |
| Training UX complexity | Keep card UI minimal, progressive disclosure |

---

## Next Phase Recommendations

### Phase 1: Polish (Low Effort, High Impact)
- [ ] Add missing Chinese translations
- [ ] Enhance memory layer indicators
- [ ] Improve preview error states

### Phase 2: Completeness (Medium Effort)
- [ ] Integrate MarkItDown for universal conversion
- [ ] Add video quick preview
- [ ] Surface operation ledger in workspace authority

### Phase 3: Advanced Features (Higher Effort)
- [ ] react-arborist for file tree
- [ ] Semantic search enhancement
- [ ] Remote credential mode UI

---

## Conclusion

Trainer is already strongly aligned with the strategy document. The core architecture for all 8 capabilities is in place. The focus should now be on:
1. Polish and UX improvements
2. Filling in missing preview formats
3. Enhancing teaching-oriented features

**Estimated completion**: 60% toward full strategy vision
**Priority**: UX polish and missing preview formats