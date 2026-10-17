"""Local usage insights router (P1 #12, §6.1).

A read-only consumer for the local event ledger: no write endpoint exists in
this router by construction, so the dashboard can never become a side channel
into the audit trail.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...core.usage_insights import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS, build_local_usage_insights
from ..runtime import TrainerRuntime


def build_insights_router(runtime: TrainerRuntime) -> APIRouter:
    router = APIRouter(tags=["insights"])

    @router.get("/insights/local-usage")
    def local_usage(
        window_days: int = Query(default=DEFAULT_WINDOW_DAYS, ge=1, le=MAX_WINDOW_DAYS),
    ) -> dict[str, object]:
        """Local-only usage facts aggregated from this machine's event ledger.

        Coarse counts only — no identifiers, no content, no network. The
        aggregation reads the ledger it is given and never appends to it.
        """
        ledger = getattr(runtime, "event_ledger", None)
        entries = ledger.all_entries() if ledger is not None else []
        return build_local_usage_insights(entries, window_days=window_days)

    return router
