"""Browser capture bridge: pairing, credentials and the coach draft queue.

The Trainer Capture browser extension talks to the sidecar through this lane:
a short-lived 6-digit pairing code registered by the host is exchanged for a
long-lived Bearer credential, and selection drafts queue here until the host
polls them into the Coach composer.
"""

from .service import (
    BrowserBridgeService,
    BrowserCredential,
    BrowserPairingError,
    PairCodeRegistration,
    build_coach_draft_text,
)

__all__ = [
    "BrowserBridgeService",
    "BrowserCredential",
    "BrowserPairingError",
    "PairCodeRegistration",
    "build_coach_draft_text",
]
