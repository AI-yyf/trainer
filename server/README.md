# Trainer Sidecar (`server/`)

Local FastAPI Python 3.12 sidecar powering Trainer's coaching loop, pedagogy kernel, memory engine, FSRS scheduler, library ingestion, and host-attested verification.

## Package Layout

- `app/main.py` / `app/api/` — FastAPI app factory, `TrainerRuntime` wiring, and domain routers (`workspace`, `memory`, `learning`, `resources`, `provider`, `sandbox`, `research`, `training_handoff`, `mcp`, `browser`)
- `app/llm/` — ReAct coach agent loop (`agent_loop.py`), 5-protocol provider abstraction (`provider_service.py`), system-proxy bypass support, streaming reasoning/tool stage events, tool registry (`save_lecture_note`, `inspect_learning_truth`, `read_file`, etc.), and grounded reply recovery guards
- `app/pedagogy/` — RethinkFun state-flow pedagogy kernel (`service.py`, `principle_explainer.py`, `implementation_coach.py`, `project_idea_miner.py`, `project_adaptation_coach.py`)
- `app/training/` — FSRS spaced-repetition scheduler, card generator/router, and 5-phase handoff (`LEARN → TRY → VERIFY → REFLECT → RETURN`)
- `app/memory/` & `app/db/` — SQLite (`<LibraryRoot>/.trainer/runtime/trainer.sqlite3`) + Qdrant vector memory + per-project fail-closed isolation
- `app/resources/` & `app/ingest/` — Unified `<LibraryRoot>/Trainer Library/` management, PyMuPDF/Trafilatura/MarkItDown ingestion, normalized Markdown + visual assets
- `app/workspace/` — Workspace classifier and fail-closed `WorkspaceAuthority` gate

## Local Development & Verification

```bash
cd server
uv sync --frozen --extra dev --python 3.12

# Run backend test suite (295 test files, 4,205 collected pytest tests)
.venv/bin/pytest tests

# Static lint and type gates (must both exit 0)
.venv/bin/python -m ruff check app tests
.venv/bin/python -m pyright app
```

From the repository root, you can also run `npm run test:server` and `npm run verify:server-pyright`.
