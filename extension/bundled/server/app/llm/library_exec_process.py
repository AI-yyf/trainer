"""Process lifecycle for ``library_exec``: group termination and capped output collection.

Kept apart from the tool definitions: this is asyncio plumbing with no dependency on the
tool registry, the sandbox profiles or the command validator.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Callable

EXEC_READ_CHUNK_BYTES = 64 * 1024
# A stream is cut off (and its process group stopped) once it overruns the
# capture cap by this factor, instead of spinning until the deadline.
EXEC_OVERFLOW_FACTOR = 8
# How long to wait for a killed group's pipes to close. A child that left the
# group keeps them open, so this wait must be bounded.
EXEC_DRAIN_SECONDS = 2.0


# Host helpers that do their work through system daemons. The Seatbelt network
# deny cannot see that traffic (``open`` hands the URL to LaunchServices, the
# browser makes the request), and Keychain, pasteboard and launchd are no part
# of running a learner's script, so executing them is refused outright.
SEATBELT_BRIDGING_HELPERS: tuple[str, ...] = (
    "/usr/bin/open",
    "/usr/bin/osascript",
    "/bin/launchctl",
    "/usr/bin/launchctl",
    "/usr/bin/security",
    "/usr/bin/pbcopy",
    "/usr/bin/pbpaste",
    "/usr/bin/automator",
    "/usr/bin/shortcuts",
)


def terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    # Signal the group even when the leader already exited: its background
    # children then still own the pgid, which keeps the id reserved and the
    # signal safe. Only a leader that is alive and unreachable through the
    # group needs the direct kill.
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError, AttributeError):
        os.killpg(proc.pid, signal.SIGKILL)
    if proc.pid and proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()


async def abandon_process_group(
    proc: asyncio.subprocess.Process,
    collect_task: asyncio.Task[tuple[bytes, bytes, bool]],
) -> None:
    """Stop the process group and stop depending on its pipes.

    A child that left the group (``setsid``) keeps the pipes open, so the drain
    is bounded: after ``EXEC_DRAIN_SECONDS`` the collector is cancelled rather
    than awaited forever.
    """
    terminate_process_group(proc)
    try:
        if not collect_task.done():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(collect_task), timeout=EXEC_DRAIN_SECONDS)
    finally:
        if not collect_task.done():
            collect_task.cancel()
            # Retrieve the outcome so a late failure never surfaces as an
            # "exception was never retrieved" warning at garbage collection.
            collect_task.add_done_callback(lambda task: task.cancelled() or task.exception())


async def collect_process_output(
    proc: asyncio.subprocess.Process,
    *,
    cap_bytes: int,
    on_overflow: Callable[[], None],
) -> tuple[bytes, bytes, bool]:
    """Read both pipes, retaining at most ``cap_bytes`` per stream.

    ``communicate()`` buffers everything a process writes before the caller can
    truncate it, so an accidental ``while True: print(...)`` grew the sidecar
    without bound until the deadline.  Here each stream keeps only its head; a
    stream that overruns the cap by ``EXEC_OVERFLOW_FACTOR`` stops the process
    group outright.  Returns ``(stdout, stderr, overflowed)`` once the process
    has exited and both pipes are closed.
    """
    overflowed = False

    async def _pump(stream: asyncio.StreamReader | None) -> bytes:
        nonlocal overflowed
        if stream is None:
            return b""
        kept: list[bytes] = []
        kept_bytes = 0
        seen_bytes = 0
        while True:
            chunk = await stream.read(EXEC_READ_CHUNK_BYTES)
            if not chunk:
                return b"".join(kept)
            seen_bytes += len(chunk)
            room = cap_bytes - kept_bytes
            if room > 0:
                kept.append(chunk[:room])
                kept_bytes += min(len(chunk), room)
            elif not overflowed and seen_bytes > cap_bytes * EXEC_OVERFLOW_FACTOR:
                overflowed = True
                on_overflow()

    stdout, stderr, _ = await asyncio.gather(_pump(proc.stdout), _pump(proc.stderr), proc.wait())
    return stdout, stderr, overflowed


def sbpl_deny_process_exec(paths: tuple[str, ...]) -> str:
    return "(deny process-exec {})".format(" ".join(f'(literal "{path}")' for path in paths))
