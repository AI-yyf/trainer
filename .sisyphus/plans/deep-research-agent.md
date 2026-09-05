# Deep Research Agent System Plan

**Created**: 2026-04-22
**Status**: Planning Complete, Ready for Implementation

---

## Overview

Build a deep research agent system that:
- Supports **multi-theme** parallel research (user can select multiple topics)
- Time-based orchestration: each stage **1 week to 1 year** (default 1 month, adjustable)
- Agent automatically performs **multi-round task orchestration** during research period
- Provides **multiple perspectives**, **rigorous thinking**, and **task scaffolding**
- Works like a **real editor/researcher**: deep, long-term, continuous, iterative research
- **Workbench** is the open portal for human-agent communication

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Workbench UI                        │
│  ┌─────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ Research │ │   Research   │ │  Agent Gate      │  │
│  │ Themes   │ │   Timeline   │ │  (Communication) │  │
│  └─────────┘ └──────────────┘ └──────────────────┘  │
├─────────────────────────────────────────────────────┤
│               API Layer (FastAPI)                    │
│  POST /research/create, /research/theme, /advance   │
├─────────────────────────────────────────────────────┤
│            Research Orchestrator                     │
│  ┌───────────────────────────────────────────────┐  │
│  │  Scheduler (time-driven, cadence-based)        │  │
│  │  Role Dispatcher (Researcher/Editor/Critic/)   │  │
│  │  Thinking Scaffold (Socratic, Devil's Adv.)    │  │
│  │  Iteration Loop (research→draft→review→final)  │  │
│  └───────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│         Existing Services (Reuse)                    │
│  Memory | Semantic Search | Provider | Evaluator    │
└─────────────────────────────────────────────────────┘
```

---

## Data Models

### ResearchProject
- id, title, description
- themes: ResearchTheme[] (multi-theme parallel)
- agent_state: AgentState
- workbench_gate: WorkbenchGate
- created_at, updated_at

### ResearchTheme
- id, title, description
- duration: timedelta (1 week ~ 1 year, default 1 month)
- status: planning | active | paused | completed
- threads: ResearchThread[] (angles: analysis, comparison, critique...)
- schedule: ScheduleSpec (start_date, end_date, cadence, checkpoints)
- artifacts: Artifact[]

### AgentState
- current_role: researcher | editor | critic | synthesizer
- thinking_log: ThinkingEntry[]
- pending_questions: string[]
- self_review_count: int

### WorkbenchGate
- human_messages: Message[]
- agent_reports: Report[]
- approval_queue: Approval[]
- notifications: Notification[]

---

## Implementation Phases

### Phase 1: Research Data Models + API (1 week)
**Files to create:**
- `server/app/research/__init__.py`
- `server/app/research/models.py` - All data models
- `server/app/research/service.py` - ResearchOrchestratorService
- `server/app/research/scheduler.py` - Time-based scheduler
- `server/app/api/routes/research.py` - API endpoints

**API Endpoints:**
- `POST /research/create` - Create research project
- `POST /research/theme` - Add theme
- `GET /research/state` - Get current state
- `POST /research/advance` - Advance one round
- `POST /research/checkpoint` - Set checkpoint
- `POST /research/approve` - Human approval
- `GET /research/report` - Get agent report

### Phase 2: Agent Orchestration Engine (2 weeks)
**Files to create:**
- `server/app/research/role_dispatcher.py` - 4 roles with prompts
- `server/app/research/thinking_scaffold.py` - Socratic, Devil's Advocate, Evidence Chain
- `server/app/research/iteration_loop.py` - Research→Draft→Review→Final

**Role Prompts:**
- **Researcher**: Deep search, read, summarize
- **Editor**: Organize, integrate, polish
- **Critic**: Review, question, find gaps
- **Synthesizer**: Cross-theme synthesis, insights

### Phase 3: Workbench Frontend (2 weeks)
**Files to modify:**
- `shared/src/models.ts` - Add research types
- `extension/webview/src/lib/types.ts` - Frontend types

**Components to create:**
- `ResearchThemesPanel.tsx` - Left sidebar extension
- `ResearchTimeline.tsx` - Main timeline view
- `AgentGatePanel.tsx` - Enhanced conversation
- `FindingCard.tsx` - Research finding display
- `ArtifactViewer.tsx` - Output viewer

### Phase 4: Integration + Testing (1 week)
- End-to-end tests
- Performance optimization
- UX polish

---

## Frontend Improvements (Parallel)

| Issue | Fix | Priority |
|-------|-----|----------|
| No theme toggle UI | Add in Topbar or CommandPalette | High |
| Sidebar flat only | Expand Plan stages, Resources list | Medium |
| Conversation simple | Add streaming, code highlight | High |
| No search/quick open | Add Ctrl+P content search | Medium |
| Evaluation non-interactive | Add check interaction | Low |
| Right panel stacked | Make collapsible accordion | Medium |
| Hero no progress | Add plan progress bar | Low |
| No drag reordering | Future enhancement | Low |

---

## Key Design Decisions

1. **Time granularity**: Day/Week/Month, default month
2. **Agent trigger**: Manual + automatic (cadence-based)
3. **Multi-theme**: Independent with periodic cross-theme synthesis
4. **Thinking scaffold**: Prompt templates + structured JSON output
5. **Workbench gate**: Extend ConversationPanel → AgentGatePanel
6. **Iteration rounds**: Configurable, default 3

---

## Dependencies on Existing Code

- `MemoryService` - Store research memory
- `SemanticMemory` - Vector search for resources
- `ProviderService` - LLM calls
- `EvaluatorService` - Quality checks
- `ResourceService` - Resource management
- `TrainerRuntime` - Service orchestration

---

## Success Metrics

1. User can create multi-theme research project with custom durations
2. Agent automatically advances research rounds based on schedule
3. Agent produces structured outputs with thinking logs
4. Human can review, approve, and guide through workbench
5. Research findings and artifacts are persistable and exportable
