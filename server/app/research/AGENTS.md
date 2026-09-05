# Research Module

**Parent:** `server/app/`

## OVERVIEW
Multi-theme deep research orchestration with time-based agent scheduling.

## STRUCTURE
```
research/
├── __init__.py     # Public exports
├── models.py       # All data models (dataclass, slots=True)
├── scheduler.py    # Time-driven checkpoint/advance logic
└── service.py      # ResearchOrchestratorService
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Add research model | `models.py` | Use `dataclass(slots=True)`, never Pydantic |
| Change scheduling logic | `scheduler.py` | All time/progress calculations |
| Add agent role | `service.py` `_advance_theme()` | Role switch in iteration loop |
| Add API endpoint | `api/routes/research.py` | Uses `...research.models` imports (3 levels up) |

## CONVENTIONS
- All models use `dataclass(slots=True)` — NOT Pydantic BaseModel
- `to_dict()` methods on complex models for API serialization
- `create()` classmethods for factory construction
- `utc_now()` helper for consistent timezone handling
- Agent iteration: Researcher(0) → Editor(1) → Critic(2) → Synthesizer(3+)

## ANTI-PATTERNS
- NEVER use Pydantic `BaseModel` in research models — breaks intentional separation
- NEVER import from `app.core.models` in research models — avoid circular deps
- NEVER advance research without checking `should_advance()` first

## UNIQUE STYLES
- `ScheduleSpec.create()` auto-generates `Checkpoint` objects from `duration_weeks` + `cadence`
- `WorkbenchGate` is the human-agent communication portal with approvals + notifications
- `AgentState` tracks iteration + review count separately; reset on synthesis completion
- Approval flow: agent creates Approval → human resolves via gate → triggers theme completion
