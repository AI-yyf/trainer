"""Emit live telemetry payloads for scripts/verify-telemetry-payload.mjs.

The probe builds a real sidecar app in a throwaway data dir, walks the two
possible consent states, and prints machine-readable records to stdout. It
prints ONLY stdout-JSON records (every other byte goes to stderr), one per
line, prefixed so the Node guard can parse strictly:

    PROBE_EXPORT:{...}      one per scenario (``case`` field set inside)
    PROBE_WHITELIST:{...}   the canonical ledger event-type vocabulary

The guard's assertion contract is that the export never escapes the schema,
never ships identifiers/free text, and never ships counts after opt-out.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.core.event_ledger import (  # noqa: E402
    ALL_EVENT_TYPES,
    EVENT_PLAN_STAGE_ADVANCED,
    EVENT_RESOURCE_UPLOADED,
)
from app.core.settings import AppSettings  # noqa: E402
from app.main import create_app  # noqa: E402


def record(name: str, doc: dict) -> None:
    sys.stdout.write(f"{name}:{json.dumps(doc, ensure_ascii=False)}\n")
    sys.stdout.flush()


def probe() -> int:
    with tempfile.TemporaryDirectory(prefix="trainer-telemetry-probe-") as tmp:
        settings = AppSettings(
            app_name="Trainer Telemetry Probe",
            host="127.0.0.1",
            port=8765,
            data_dir=Path(tmp),
            database_name="trainer-telemetry-probe.db",
            default_session_stage="intake",
            summary_message_limit=6,
            enable_network_fetch=False,
        )
        app = create_app(settings)
        runtime = app.state.runtime
        ledger = runtime.event_ledger

        # Scenario A: a consent-off machine must export nothing.
        opt_out_export = runtime.telemetry_service.build_export(window_days=7)
        ledger.record_event(EVENT_RESOURCE_UPLOADED)
        record("PROBE_EXPORT", {"case": "opt_out", "export": opt_out_export})

        # Scenario B: consent on, seeded activity, one rogue ledger type.
        runtime.telemetry_service.set_opt_in(True, source="probe")
        for _ in range(3):
            ledger.record_event(EVENT_RESOURCE_UPLOADED)
        ledger.record_event(EVENT_PLAN_STAGE_ADVANCED)
        ledger.record_event("rogue_event_type_not_in_whitelist")
        opt_in_export = runtime.telemetry_service.build_export(window_days=7)
        record("PROBE_EXPORT", {"case": "opt_in", "export": opt_in_export})

        record("PROBE_WHITELIST", {"all_event_types": sorted(ALL_EVENT_TYPES)})
    return 0


if __name__ == "__main__":
    raise SystemExit(probe())
