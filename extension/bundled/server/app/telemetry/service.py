"""TelemetryService — opt-in consent + anonymous aggregation over the local ledger.

Design rules (non-negotiable):

- **Consent is stored durably and append-only audited**: every change goes into
  ``telemetry.json`` (capped history) and into the in-process event ledger, so
  the audit trail always answerable "when did telemetry start and stop".
- **The export is the only thing that ever leaves the machine**, and it carries
  coarse counters only: event-type names from the ledger's canonical list, a
  UTC day series, nothing else. ``payload_ref``/``audit_note``/scope values and
  every identifier stay inside the machine.
- **Opt-out is fail-closed**: an opt-out machine exports an empty payload —
  the aggregation skips the ledger entirely, so a bug can never leak counts
  after consent is withdrawn.
- Unknown ledger event types are dropped, not bucketed into ``other``, so the
  export can never mint a new event vocabulary on the wire.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..core.event_ledger import ALL_EVENT_TYPES, EventLedgerService

SCHEMA = "trainer.telemetry.v1"
CONSENT_SCHEMA = "trainer.telemetry-consent.v1"
CONSENT_FILE_NAME = "telemetry.json"
DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 90
CONSENT_HISTORY_CAP = 50

_SOURCE_PATTERN = re.compile(r"^[a-z_]{1,24}$")


def telemetry_export_schema() -> str:
    return SCHEMA


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class TelemetryService:
    """Consent holder + the read-only side of the local event ledger."""

    def __init__(self, event_ledger: EventLedgerService, data_dir: Path) -> None:
        self._ledger = event_ledger
        self._path = Path(data_dir) / CONSENT_FILE_NAME
        self._state: dict[str, Any] = {"opted_in": False, "updated_at": None, "history": []}
        self._load()

    # -- consent ------------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict) or str(raw.get("schema", "")) != CONSENT_SCHEMA:
            return
        self._state = {
            "opted_in": bool(raw.get("opted_in", False)),
            "updated_at": raw.get("updated_at") or None,
            "history": [item for item in raw.get("history", []) if isinstance(item, dict)],
        }

    def _save(self) -> None:
        payload = {"schema": CONSENT_SCHEMA, **self._state}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def _normalize_source(self, source: Any) -> str:
        text = str(source or "").strip().lower()
        if _SOURCE_PATTERN.match(text):
            return text
        return "unspecified"

    def set_opt_in(self, opted_in: bool, *, source: str | None = None) -> dict[str, Any]:
        """Record a consent change (append-only, audited, idempotent).

        A no-op consent call does not extend the history: consent state only
        changes when the answer changes.
        """
        normalized = bool(opted_in)
        token = self._normalize_source(source)
        if normalized == self._state["opted_in"]:
            return self.status()
        at = datetime.now(timezone.utc).isoformat()
        self._state["opted_in"] = normalized
        self._state["updated_at"] = at
        self._state["history"] = (
            [*self._state["history"], {"at": at, "opted_in": normalized, "source": token}]
            [-CONSENT_HISTORY_CAP:]
        )
        self._save()
        self._ledger.record_event(
            "telemetry_consent_changed",
            payload_ref={"opted_in": normalized, "source": token},
        )
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "opt_in": bool(self._state["opted_in"]),
            "consent_updated_at": self._state["updated_at"],
            "consent_changes": len(self._state["history"]),
        }

    # -- aggregation --------------------------------------------------------

    def build_export(self, *, window_days: int = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
        """The exportable anonymous payload (or the empty opt-out payload)."""
        try:
            requested = int(window_days)
        except (TypeError, ValueError):
            requested = DEFAULT_WINDOW_DAYS
        span = max(1, min(requested, MAX_WINDOW_DAYS))
        generated_at = datetime.now(timezone.utc).isoformat()
        empty = {
            "schema": SCHEMA,
            "generated_at": generated_at,
            "opt_in": False,
            "window_days": span,
            "daily": [],
            "by_event": {},
            "unknown_ledger_events_dropped": 0,
            "total_events": 0,
        }
        if not self._state["opted_in"]:
            return empty
        now = _parse_iso(generated_at) or datetime.now(timezone.utc)
        window_start = now - timedelta(days=span)
        day_counts: dict[str, int] = {}
        by_event: dict[str, int] = {}
        dropped = 0
        for entry in self._ledger.all_entries():
            occurred = _parse_iso(getattr(entry, "occurred_at", None))
            if occurred is None or occurred < window_start or occurred > now:
                continue
            event_type = str(getattr(entry, "event_type", "") or "")
            if event_type not in ALL_EVENT_TYPES:
                dropped += 1
                continue
            by_event[event_type] = by_event.get(event_type, 0) + 1
            day = occurred.date().isoformat()
            day_counts[day] = day_counts.get(day, 0) + 1
        daily = []
        for offset in range(span):
            day = (now - timedelta(days=span - 1 - offset)).date().isoformat()
            daily.append({"date": day, "events": day_counts.get(day, 0)})
        return {
            "schema": SCHEMA,
            "generated_at": generated_at,
            "opt_in": True,
            "window_days": span,
            "daily": daily,
            "by_event": by_event,
            "unknown_ledger_events_dropped": dropped,
            "total_events": sum(by_event.values()),
        }
