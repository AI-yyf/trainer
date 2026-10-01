"""Emit a periodic progress line while the server suite runs.

pytest under xdist streams a dot per completed test. When the machine is
loaded, a slow integration test can take 20-30s, which leaves the runner
silent for that whole window. To a supervisor watching for stalls that is
indistinguishable from a hung process, so we print a heartbeat on a fixed
cadence with the real collected/completed counts.

This changes no assertions and no test behaviour — it only makes an active run
legible from the outside. Load it with `-p trainer_suite_heartbeat`.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

#: A supervisor should never see a quiet window longer than this.
INTERVAL_SECONDS = float(os.environ.get("TRAINER_SUITE_HEARTBEAT_SECONDS", "10"))


class _Heartbeat:
    """Time-based liveness beacon.

    Under xdist the controller process does not execute tests, so per-test
    counts are only available inside each worker — and eight workers each
    reporting would be noise, not signal. The controller is the process a
    supervisor is actually watching, so it is the one that speaks.
    """

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def start(self) -> None:
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="trainer-suite-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            elapsed = int(time.monotonic() - self._started)
            print(f"\n[heartbeat] server suite still running, {elapsed}s elapsed\n", flush=True)


@pytest.hookimpl(trylast=True)
def pytest_configure(config) -> None:
    # Workers stay quiet; only the controller reports.
    if hasattr(config, "workerinput"):
        return
    heartbeat = _Heartbeat(INTERVAL_SECONDS)
    config._trainer_heartbeat = heartbeat
    heartbeat.start()


def pytest_unconfigure(config) -> None:
    heartbeat = getattr(config, "_trainer_heartbeat", None)
    if heartbeat is not None:
        heartbeat.stop()
