"""Opt-in anonymous telemetry (P2 #18).

Consent first, aggregate second, identifiers never. The module reads only this
machine's own append-only event ledger and the consent record it owns, and the
export it builds contains coarse counts — no content, no paths, no provider
material, no account identity — and only when consent is on. A consent-off
machine exports an empty payload by construction: opt-out is fail-closed.
"""

from .service import TelemetryService, telemetry_export_schema

__all__ = ["TelemetryService", "telemetry_export_schema"]
