"""Content-addressed cache for external tool checks (ruff / pyright / pytest).

The evaluator shells out to three processes for every "verify this file" turn.
Each of those is dominated by process startup — pyright alone spends 2-4s in
Node before it looks at a line of code — and the checks are run against a
throwaway sandbox whose path changes on every call, so nothing about the *work*
changes when the learner re-verifies an unchanged file.

Two things follow:

* In the product, re-verifying the same unchanged file should be instant. The
  coach asks for verification repeatedly, and paying a fresh pyright cold start
  each time is pure dead time in the learner's flow.
* In the test suite, the same fixture content is evaluated many times, so the
  same startup cost is paid dozens of times for identical answers.

The cache key is the *content* of the materialised target plus the tool
arguments, never the sandbox path. Tool output frequently embeds the path it
ran against, so stored results keep the sandbox path behind a placeholder and
substitute the current one back in on a hit — a cached result is
indistinguishable from a fresh one, including the paths it prints.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

from .models import CheckCommand, CheckResult

#: The sandbox path is random per call; this token stands in for it.
_SANDBOX_TOKEN = "\x00trainer-sandbox\x00"

#: Bounded so a long-lived sidecar cannot grow without limit. The working set is
#: "the handful of files the learner is editing right now", so a small cache
#: captures nearly all the reuse.
_MAX_ENTRIES = 64


class CheckResultCache:
    """LRU cache of external tool results, keyed by content rather than path."""

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._entries: OrderedDict[tuple[object, ...], CheckResult] = OrderedDict()
        self._max_entries = max(1, max_entries)
        # `/evaluate/current-file` and `/evaluate/snippet` are *sync* FastAPI
        # endpoints, so Starlette runs them in its threadpool. Two learners (or
        # one learner in two panels) verifying at once hit this cache from
        # different threads, and the read-modify-evict sequence is not atomic:
        # both could drop the last entry and the second `popitem` raises
        # KeyError, which surfaces as a 500 on a verification the user asked
        # for. The GIL does not help — it does not make the sequence atomic.
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    # -- key ---------------------------------------------------------------
    @staticmethod
    def _digest(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            # Unreadable target: do not cache, so a later read is never stale.
            return ""

    @staticmethod
    def _normalize(text: str, sandbox: str) -> str:
        return text.replace(sandbox, _SANDBOX_TOKEN) if sandbox else text

    @staticmethod
    def _denormalize(text: str, sandbox: str) -> str:
        return text.replace(_SANDBOX_TOKEN, sandbox) if sandbox else text

    @staticmethod
    def _target_of(command: CheckCommand) -> str | None:
        """The file a check runs against.

        Not "the first token that is not a flag": the real command lines are
        `ruff check <file>`, `pyright <file>` and
        `<python> -m pytest <file> -p no:cacheprovider`, so the first positional
        token is `check` or `pytest`, not the file. Getting this wrong meant the
        digest hashed a path that does not exist, the entry was silently
        refused, and the cache never hit for two of the three tools.
        """
        candidates = [token for token in command.argv[1:] if not token.startswith("-")]
        for token in candidates:
            if Path(token).is_file():
                return token
        return candidates[-1] if candidates else None

    def key(
        self, command: CheckCommand, sandbox: str, runner: object | None = None
    ) -> tuple[object, ...] | None:
        """Cache key for ``command``, or ``None`` when it must not be cached.

        The runner is part of the key. Two different runners can legitimately
        disagree about identical content — a live pyright and a fixture, say —
        so a result is only reusable by the thing that produced it. Without
        this, swapping the evaluator's runner (which the recovery journey does,
        and which a host embedding could too) silently returned the previous
        runner's verdict.
        """
        target = self._target_of(command)
        if target is None:
            return None
        digest = self._digest(Path(target))
        if not digest:
            return None
        # Arguments other than the sandbox path, plus the file's own content.
        args = tuple(
            self._normalize(str(token), sandbox)
            for token in command.argv[1:]
            if token != target
        )
        return (command.name, command.argv[0], digest, args, command.cwd is not None, id(runner) if runner is not None else None)

    # -- get / put ---------------------------------------------------------
    def get(
        self, command: CheckCommand, sandbox: str, runner: object | None = None
    ) -> CheckResult | None:
        key = self.key(command, sandbox, runner)
        if key is None:
            return None
        with self._lock:
            cached = self._entries.get(key)
            if cached is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
        return CheckResult(
            name=cached.name,
            status=cached.status,
            command=[self._denormalize(item, sandbox) for item in cached.command],
            stdout=self._denormalize(cached.stdout, sandbox),
            stderr=self._denormalize(cached.stderr, sandbox),
            exit_code=cached.exit_code,
            summary=self._denormalize(cached.summary, sandbox),
        )

    def put(
        self,
        command: CheckCommand,
        sandbox: str,
        result: CheckResult,
        runner: object | None = None,
    ) -> None:
        key = self.key(command, sandbox, runner)
        if key is None:
            return
        stored = CheckResult(
            name=result.name,
            status=result.status,
            command=[self._normalize(item, sandbox) for item in result.command],
            stdout=self._normalize(result.stdout, sandbox),
            stderr=self._normalize(result.stderr, sandbox),
            exit_code=result.exit_code,
            summary=self._normalize(result.summary, sandbox),
        )
        with self._lock:
            self._entries[key] = stored
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


#: One cache per process. A sidecar is long-lived, which is exactly the case
#: where a learner re-verifying an unchanged file should not re-pay startup.
CHECK_RESULT_CACHE = CheckResultCache()


def cacheable_commands(commands: Iterable[CheckCommand]) -> bool:
    """All-or-nothing guard: never serve a partially cached report."""
    return all(CHECK_RESULT_CACHE.key(command, command.cwd or "") is not None for command in commands)
