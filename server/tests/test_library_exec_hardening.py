"""library_exec hardening: fail-closed without a kernel sandbox, bounded cleanup, capped output.

Restores and extends behavioral coverage of the ``library_exec`` guarantees. None of these
had a test at HEAD (the timeout path, the no-sandbox lane, output flooding and trash
integrity were all untested):

- a host without sandbox-exec / bwrap refuses to run an interpreter: the audit guard is
  ordinary Python inside the child's own process and cannot bound it;
- a plain timeout returns the timeout payload instead of leaking ``CancelledError``;
- a leader that exits while a background child holds the pipes is still cleaned up at the
  deadline, and the child does not outlive the call;
- a runaway stream is cut off early instead of being buffered until the deadline;
- helpers that act through system daemons (``open``, ``launchctl``, ``security`` ...) are
  refused by the Seatbelt profile;
- recoverable storage (trash) is readable but never writable inside the sandbox.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.llm.tool_primitives import (
    _MAX_RAW_CAPTURE_BYTES,
    _PYTHON_AUDIT_SITECUSTOMIZE,
    _build_macos_seatbelt_profile,
    _build_sandboxed_exec_argv,
    _collect_process_output,
    _ensure_python_audit_guard_dir,
    _lexical_norm_path,
    _linux_bwrap_bin,
    _macos_sandbox_exec_usable,
    _terminate_process_group,
    _validate_library_exec_command,
)
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app

PRIMITIVE_MODULE = "app.llm.tool_primitives"


def _kernel_sandbox_available() -> bool:
    return bool(_macos_sandbox_exec_usable()) or bool(_linux_bwrap_bin())


requires_kernel_sandbox = pytest.mark.skipif(
    not _kernel_sandbox_available(),
    reason="no OS kernel sandbox (sandbox-exec / bwrap) on this host",
)
macos_only = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")


def _setup_ctx(tmp_path: Path) -> tuple[Any, ToolContext, Path, Path]:
    project_root = tmp_path / "learner_project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    app = create_app(Settings(data_dir=tmp_path / "trainer_data"))
    runtime = app.state.runtime
    workspace_id = "ws-exec-hardening"
    runtime.register_workspace_path(workspace_id, str(project_root))
    library_root = Path(runtime.sandbox_service.ensure_operation_root(workspace_id)).resolve()
    ctx = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="sess-exec-hardening",
        response_language="zh-CN",
        extra={},
    )
    return runtime, ctx, project_root, library_root


def _process_is_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


# ---------------------------------------------------------------- no kernel sandbox


def test_without_kernel_sandbox_an_interpreter_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library_root = tmp_path / "lib"
    project_root = tmp_path / "proj"
    library_root.mkdir()
    project_root.mkdir()
    monkeypatch.setattr(f"{PRIMITIVE_MODULE}._macos_sandbox_exec_usable", lambda: False)
    monkeypatch.setattr(f"{PRIMITIVE_MODULE}._linux_bwrap_bin", lambda: None)

    for interpreter_command in (
        'python3 -c "print(1)"',
        'env python3 -B -c "import os"',
        'python -u -c "print(1)"',
        "/usr/bin/python3 -c 'print(1)'",
    ):
        argv, backend = _build_sandboxed_exec_argv(
            interpreter_command,
            library_root=library_root,
            project_root=project_root,
        )
        assert argv is None, f"{interpreter_command!r} must not run without a kernel sandbox"
        assert backend == "unavailable"


@pytest.mark.asyncio
async def test_without_kernel_sandbox_the_tool_fails_closed_with_an_honest_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runtime, ctx, project_root, _library_root = _setup_ctx(tmp_path)
    monkeypatch.setattr(f"{PRIMITIVE_MODULE}._macos_sandbox_exec_usable", lambda: False)
    monkeypatch.setattr(f"{PRIMITIVE_MODULE}._linux_bwrap_bin", lambda: None)
    registry = build_default_tool_registry()

    result = await registry.invoke(ctx, "library_exec", {"command": 'python3 -c "print(1)"'})

    assert result["ok"] is False
    assert result["error"] == "sandbox_unavailable"
    assert result["sandbox_backend"] == "unavailable"
    assert "kernel sandbox" in result["detail"]
    assert list(project_root.iterdir()) == [project_root / "app.py"]


@pytest.mark.skipif(not os.path.exists("/bin/echo"), reason="/bin/echo is POSIX-only")
def test_without_kernel_sandbox_only_a_bare_echo_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library_root = tmp_path / "lib"
    library_root.mkdir()
    monkeypatch.setattr(f"{PRIMITIVE_MODULE}._macos_sandbox_exec_usable", lambda: False)
    monkeypatch.setattr(f"{PRIMITIVE_MODULE}._linux_bwrap_bin", lambda: None)

    argv, backend = _build_sandboxed_exec_argv("echo hello", library_root=library_root, project_root=None)
    assert argv == ["/bin/echo", "hello"]
    assert backend == "direct_echo_no_shell"

    # Anything a shell would interpret is refused: no redirects, no expansion.
    for not_bare in ("echo a > out.txt", "echo $HOME", "echo `id`", "echo a; echo b"):
        argv, backend = _build_sandboxed_exec_argv(not_bare, library_root=library_root, project_root=None)
        assert argv is None, not_bare
        assert backend == "unavailable"


# ---------------------------------------------------------------- timeout and cleanup


@pytest.mark.asyncio
@requires_kernel_sandbox
async def test_plain_timeout_returns_the_timeout_payload(tmp_path: Path) -> None:
    _runtime, ctx, _project_root, _library_root = _setup_ctx(tmp_path)
    registry = build_default_tool_registry()

    started = time.monotonic()
    result = await registry.invoke(
        ctx,
        "library_exec",
        {"command": 'python3 -c "import time; time.sleep(20)"', "timeout_seconds": 1},
    )
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert result["error"] == "timeout"
    assert "timed out after 1.0s" in result["detail"]
    assert elapsed < 8.0, f"timeout handling took {elapsed:.1f}s"


@pytest.mark.asyncio
@requires_kernel_sandbox
async def test_background_child_does_not_outlive_the_deadline(tmp_path: Path) -> None:
    _runtime, ctx, _project_root, library_root = _setup_ctx(tmp_path)
    registry = build_default_tool_registry()
    pid_file = library_root / "bg.pid"
    child_pid: int | None = None

    try:
        started = time.monotonic()
        result = await asyncio.wait_for(
            registry.invoke(
                ctx,
                "library_exec",
                {
                    # The shell exits at once; the background sleeper keeps both pipes open.
                    "command": "sleep 300 & echo $! > bg.pid; echo started",
                    "timeout_seconds": 1,
                },
            ),
            timeout=15.0,
        )
        elapsed = time.monotonic() - started

        assert result["ok"] is False
        assert result["error"] == "timeout"
        assert elapsed < 8.0, f"the call lasted {elapsed:.1f}s for a 1s deadline"
        child_pid = int(pid_file.read_text(encoding="utf-8").strip())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not _process_is_gone(child_pid):
            await asyncio.sleep(0.1)
        assert _process_is_gone(child_pid), f"background child {child_pid} survived library_exec"
    finally:
        if child_pid is not None and not _process_is_gone(child_pid):
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)


def test_group_is_signalled_even_after_the_leader_exited(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[tuple[int, int]] = []

    class _ExitedLeader:
        returncode = 0
        pid = 4242

        def kill(self) -> None:
            signals.append((0, 0))

    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    _terminate_process_group(_ExitedLeader())  # type: ignore[arg-type]

    assert signals == [(4242, signal.SIGKILL)]


# ---------------------------------------------------------------- output cap


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _FakeProc:
    def __init__(self, stdout: _FakeStream, stderr: _FakeStream) -> None:
        self.stdout = stdout
        self.stderr = stderr

    async def wait(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_collector_keeps_only_the_head_of_each_stream() -> None:
    chunk = b"x" * 64 * 1024
    stops: list[str] = []
    proc = _FakeProc(_FakeStream([chunk] * 6), _FakeStream([b"e" * 10]))

    stdout, stderr, overflowed = await _collect_process_output(
        proc,  # type: ignore[arg-type]
        cap_bytes=_MAX_RAW_CAPTURE_BYTES,
        on_overflow=lambda: stops.append("stopped"),
    )

    assert len(stdout) == _MAX_RAW_CAPTURE_BYTES
    assert stdout.startswith(b"x")
    assert stderr == b"e" * 10
    assert overflowed is False
    assert stops == []


@pytest.mark.asyncio
async def test_collector_stops_a_runaway_stream_once_it_overruns_the_cap() -> None:
    chunk = b"y" * 64 * 1024
    stops: list[str] = []
    # 64 x 64 KiB = 4 MiB on stdout, far past cap x 8; the stream never ends by itself.
    proc = _FakeProc(_FakeStream([chunk] * 64), _FakeStream([]))

    stdout, _stderr, overflowed = await _collect_process_output(
        proc,  # type: ignore[arg-type]
        cap_bytes=_MAX_RAW_CAPTURE_BYTES,
        on_overflow=lambda: stops.append("stopped"),
    )

    assert overflowed is True
    assert stops == ["stopped"]
    assert len(stdout) == _MAX_RAW_CAPTURE_BYTES


@pytest.mark.asyncio
@requires_kernel_sandbox
async def test_runaway_output_is_cut_off_long_before_the_deadline(tmp_path: Path) -> None:
    _runtime, ctx, _library_root = _setup_ctx(tmp_path)[:3]
    registry = build_default_tool_registry()

    started = time.monotonic()
    result = await asyncio.wait_for(
        registry.invoke(
            ctx,
            "library_exec",
            {"command": "python3 -c \"while True: print('x' * 4096)\"", "timeout_seconds": 30},
        ),
        timeout=20.0,
    )
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert result["error"] == "output_limit_exceeded"
    assert result["truncated"] is True
    assert len(result["stdout"]) <= 30_000
    assert elapsed < 15.0, f"a runaway stream took {elapsed:.1f}s to stop"


# ---------------------------------------------------------------- Seatbelt profile


def test_seatbelt_profile_refuses_daemon_helpers_and_keeps_trash_read_only(tmp_path: Path) -> None:
    library_root = tmp_path / "lib"
    project_root = tmp_path / "proj"
    library_root.mkdir()
    project_root.mkdir()

    profile = _build_macos_seatbelt_profile(library_root, project_root)

    for helper in ("/usr/bin/open", "/bin/launchctl", "/usr/bin/security", "/usr/bin/osascript"):
        assert f'(deny process-exec (literal "{helper}")' in profile or (
            f'(literal "{helper}")' in profile and "(deny process-exec" in profile
        ), helper
    assert "(deny network*)" in profile

    library_allow = f'(allow file-write* (subpath "{library_root.resolve()}")'
    assert library_allow in profile
    for trash_name in (".trash", "trash", ".trainer-trash"):
        trash_deny = f'(subpath "{library_root.resolve() / trash_name}")'
        assert trash_deny in profile, trash_name
    # SBPL is last-rule-wins, so the trash deny must come after the library allow.
    assert profile.rindex("(deny file-write*") > profile.index(library_allow)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="bwrap lane is POSIX-only")
def test_bwrap_lane_mounts_existing_trash_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library_root = tmp_path / "lib"
    project_root = tmp_path / "proj"
    (library_root / "trash").mkdir(parents=True)
    project_root.mkdir()
    monkeypatch.setattr(f"{PRIMITIVE_MODULE}._macos_sandbox_exec_usable", lambda: False)
    monkeypatch.setattr(f"{PRIMITIVE_MODULE}._linux_bwrap_bin", lambda: "/usr/bin/bwrap")

    argv, backend = _build_sandboxed_exec_argv(
        "ls", library_root=library_root, project_root=project_root
    )

    assert backend == "linux_bwrap"
    assert argv is not None
    trash = str(_lexical_norm_path(library_root.resolve() / "trash"))
    ro_binds = [argv[i + 1 : i + 3] for i, token in enumerate(argv) if token == "--ro-bind"]
    assert [trash, trash] in ro_binds


@pytest.mark.asyncio
@macos_only
@requires_kernel_sandbox
async def test_library_exec_cannot_hand_work_to_system_daemons(tmp_path: Path) -> None:
    _runtime, ctx, _project_root, _library_root = _setup_ctx(tmp_path)
    registry = build_default_tool_registry()

    # Judge by the sandbox's own refusal text, not by the exit code: ``open -h``
    # prints its usage and exits 1 even when it is allowed to run.
    for helper_command in ("open -h", "/bin/sh -c 'open -h'", "launchctl list"):
        result = await registry.invoke(ctx, "library_exec", {"command": helper_command})

        assert result["ok"] is False, helper_command
        assert result["sandbox_backend"] == "macos_seatbelt"
        assert "Operation not permitted" in result["stderr"], (helper_command, result["stderr"])


# ---------------------------------------------------------------- trash is read-only


def test_validator_refuses_trash_references_up_front(tmp_path: Path) -> None:
    library_root = tmp_path / "lib"
    project_root = tmp_path / "proj"
    library_root.mkdir()
    project_root.mkdir()

    for command in (
        "cat .trash/kept.md",
        "ls trash/",
        "echo x > .trainer-trash/notes.md",
        "echo x > Trash/notes.md",
    ):
        reason = _validate_library_exec_command(command, library_root=library_root, project_root=project_root)
        assert reason is not None, command
        assert "restore" in reason

    # A folder that merely ends in "trash", or the plain word, is ordinary learner content.
    for allowed in (
        "cat notes.md",
        "cat mytrash/notes.md",
        "cat trash-metal/notes.md",
        "python3 -c \"print('trash')\"",
    ):
        assert (
            _validate_library_exec_command(allowed, library_root=library_root, project_root=project_root)
            is None
        ), allowed


@pytest.mark.asyncio
@requires_kernel_sandbox
async def test_trash_is_readable_but_never_writable_inside_the_sandbox(tmp_path: Path) -> None:
    _runtime, ctx, _project_root, library_root = _setup_ctx(tmp_path)
    trash_dir = library_root / ".trash"
    trash_dir.mkdir()
    (trash_dir / "kept.md").write_text("recoverable\n", encoding="utf-8")
    registry = build_default_tool_registry()

    read_result = await registry.invoke(
        ctx,
        "library_exec",
        {
            # The name is assembled at runtime so this exercises the runtime guards,
            # not the static command validator.
            "command": "python3 -c \"from pathlib import Path; "
            "print((Path('.') / ('.' + 'tr' + 'ash') / 'kept.md').read_text())\""
        },
    )
    assert read_result["ok"] is True, read_result
    assert "recoverable" in read_result["stdout"]

    for write_command in (
        "python3 -c \"from pathlib import Path; "
        "(Path('.') / ('.' + 'tr' + 'ash') / 'forged.md').write_text('forged')\"",
        "python3 -c \"from pathlib import Path; "
        "(Path('.') / ('.' + 'tr' + 'ash') / 'kept.md').write_text('rewritten')\"",
    ):
        result = await registry.invoke(ctx, "library_exec", {"command": write_command})

        assert result["ok"] is False, write_command
    assert not (trash_dir / "forged.md").exists()
    assert (trash_dir / "kept.md").read_text(encoding="utf-8") == "recoverable\n"


# ---------------------------------------------------------------- audit guard placement


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permission bits")
def test_audit_guard_dir_is_private_and_not_predictable(tmp_path: Path) -> None:
    library_root = tmp_path / "lib"
    library_root.mkdir()

    guard_dir = _ensure_python_audit_guard_dir(library_root)

    assert _ensure_python_audit_guard_dir(library_root) == guard_dir
    assert guard_dir.name.startswith("trainer-exec-guard-")
    legacy_name = f"trainer-exec-guard-{os.getuid()}"
    assert guard_dir != Path(tempfile.gettempdir()).resolve() / legacy_name
    assert guard_dir.stat().st_mode & 0o777 == 0o555
    site_file = guard_dir / "sitecustomize.py"
    assert site_file.stat().st_mode & 0o777 == 0o444
    assert site_file.read_text(encoding="utf-8") == _PYTHON_AUDIT_SITECUSTOMIZE
