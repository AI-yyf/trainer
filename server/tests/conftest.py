"""Shared test-process configuration (§五).

Windows CI measured the server suite at 57m42s serial while Linux/macOS
finish in ~15m — the difference is SQLite fsync journaling on NTFS across
the thousands of throwaway per-test connections. Every database in this
tree lives in a tmp_path that is deleted after the test, so durability
there is irrelevant. Process-wide pragmas (this conftest only exists
under tests/) trade that durability for wall time; production defaults
are untouched.
"""

from __future__ import annotations

import sqlite3

_original_connect = sqlite3.connect


def _fast_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
    connection = _original_connect(*args, **kwargs)
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute("PRAGMA journal_mode = MEMORY")
    return connection


sqlite3.connect = _fast_connect  # type: ignore[assignment]
