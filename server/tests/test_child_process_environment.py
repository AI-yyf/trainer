"""Child processes the sidecar starts never inherit the sidecar's own secret."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.process_env import SIDECAR_SECRET_ENV_VARS, child_process_environment


def test_child_environment_drops_the_sidecar_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    monkeypatch.setenv("TRAINER learner_KEEP_ME", "kept")
    monkeypatch.setenv("PATH", "/usr/bin")

    environment = child_process_environment()

    assert "TRAINER_SIDECAR_TOKEN" not in environment
    assert environment["PATH"] == "/usr/bin"
    # Nothing else about the learner's environment is hidden from their own tools.
    assert "TRAINER learner_KEEP_ME" in environment
    assert SIDECAR_SECRET_ENV_VARS == ("TRAINER_SIDECAR_TOKEN",)


def test_child_environment_applies_explicit_overrides_last() -> None:
    environment = child_process_environment(
        {"TRAINER_SIDECAR_TOKEN": "secret", "A": "1"},
        {"B": "2", "A": "overridden"},
    )
    assert environment == {"A": "overridden", "B": "2"}


def test_a_real_child_process_cannot_see_the_sidecar_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The property that matters, observed end to end: code the sidecar runs
    as a child cannot read the token out of its own environment."""
    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    script = tmp_path / "print_env.py"
    script.write_text(
        "import os, sys\nsys.stdout.write(os.environ.get('TRAINER_SIDECAR_TOKEN', '<absent>'))\n",
        encoding="utf-8",
    )

    inherited = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=True
    )
    scrubbed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=True,
        env=child_process_environment(),
    )

    assert inherited.stdout == "instance-secret"
    assert scrubbed.stdout == "<absent>"


def test_evaluator_runner_starts_children_without_the_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.evaluator.models import CheckCommand
    from app.evaluator.service import SubprocessCommandRunner

    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    probe = tmp_path / "token_env.py"
    probe.write_text(
        "import os\nprint(os.environ.get('TRAINER_SIDECAR_TOKEN', '<absent>'))\n",
        encoding="utf-8",
    )

    result = SubprocessCommandRunner().run(
        CheckCommand(
            name="python-script", argv=[sys.executable, "-B", str(probe)], cwd=str(tmp_path)
        )
    )

    assert result.stdout is not None
    assert "instance-secret" not in result.stdout
    assert "<absent>" in result.stdout


def test_mcp_server_process_starts_without_the_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.llm.mcp_client import McpServerConfig, McpStdioClient

    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    probe = tmp_path / "mcp_env_probe.py"
    probe.write_text(
        "import os, sys\n"
        "sys.stdout.write('TOKEN=' + os.environ.get('TRAINER_SIDECAR_TOKEN', '<absent>') + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdin.readline()\n",
        encoding="utf-8",
    )

    async def run() -> str:
        config = McpServerConfig(
            name="probe", command=sys.executable, args=(str(probe),), env={"PROBE": "1"}
        )
        client = McpStdioClient(config)
        await client.start()
        try:
            assert client._process is not None
            line = await asyncio.wait_for(client._process.stdout.readline(), timeout=10)  # noqa: SLF001 - test probe
            return line.decode("utf-8")
        finally:
            await client.close()

    output = asyncio.run(run())
    assert "TOKEN=<absent>" in output
    assert "instance-secret" not in output


def test_the_language_server_starts_without_the_token_and_off_the_repo_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`python -m pylsp` runs inside the learner's repository.

    `-m` puts that repository first on `sys.path`, so a checked-in `pylsp.py`
    would run with the language server's privileges and, through the
    environment, the sidecar token.
    """
    import subprocess as subprocess_module

    from app.project.analysis_adapter import _LspSession

    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    captured: dict[str, object] = {}

    class _Stopped(Exception):
        pass

    def fake_popen(*args: object, **kwargs: object) -> None:
        captured["argv"] = args[0]
        captured["kwargs"] = kwargs
        raise _Stopped()

    monkeypatch.setattr(subprocess_module, "Popen", fake_popen)
    with pytest.raises(_Stopped):
        _LspSession(tmp_path / "repo")

    argv = captured["argv"]
    kwargs = captured["kwargs"]
    assert list(argv[1:3]) == ["-m", "pylsp"]
    environment = kwargs["env"]  # type: ignore[index]
    assert "TRAINER_SIDECAR_TOKEN" not in environment
    assert environment["PYTHONSAFEPATH"] == "1"


def test_every_spawned_process_gets_a_scrubbed_environment() -> None:
    """A call site that forgets the scrub hands the sidecar token to a learner tool.

    This is a source guard on purpose: the calls are spread over many modules
    and most need tools (git, tesseract, pylsp, docker) that CI does not have.
    It resolves subprocess aliases and also covers ``asyncio`` subprocesses and
    ``os.system``/``os.exec*``/``os.spawn*``, which inherit the environment and
    take no ``env=`` argument at all.
    """
    import ast

    spawn_names = {"run", "Popen", "check_output", "check_call", "call"}
    asyncio_spawn_names = {"create_subprocess_exec", "create_subprocess_shell"}
    os_inherit_names = {
        "system",
        "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
        "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe",
    }
    helper_names = {"child_process_environment", "_skill_runtime_environment"}
    app_root = Path(__file__).resolve().parents[1] / "app"
    violations: list[str] = []

    for path in sorted(app_root.rglob("*.py")):
        if path.name == "process_env.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        subprocess_modules = {"subprocess"}
        asyncio_modules = {"asyncio"}
        os_modules = {"os"}
        imported_spawn_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if alias.name == "subprocess":
                        subprocess_modules.add(bound)
                    elif alias.name == "asyncio":
                        asyncio_modules.add(bound)
                    elif alias.name == "os":
                        os_modules.add(bound)
            elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                for alias in node.names:
                    if alias.name in spawn_names:
                        imported_spawn_names.add(alias.asname or alias.name)

        def is_spawn_call(
            func: ast.expr,
            imported: set[str] = imported_spawn_names,
            subprocess_mods: set[str] = subprocess_modules,
            asyncio_mods: set[str] = asyncio_modules,
        ) -> bool:
            if isinstance(func, ast.Name):
                return func.id in imported
            if not isinstance(func, ast.Attribute):
                return False
            if func.attr in spawn_names and isinstance(func.value, ast.Name):
                return func.value.id in subprocess_mods
            if func.attr in asyncio_spawn_names and isinstance(func.value, ast.Name):
                return func.value.id in asyncio_mods
            return False

        def is_inherited_os_call(
            func: ast.expr,
            os_mods: set[str] = os_modules,
        ) -> bool:
            return (
                isinstance(func, ast.Attribute)
                and func.attr in os_inherit_names
                and isinstance(func.value, ast.Name)
                and func.value.id in os_mods
            )

        def calls_helper(enclosing: ast.AST) -> bool:
            for candidate in ast.walk(enclosing):
                if not isinstance(candidate, ast.Call):
                    continue
                target = candidate.func
                if isinstance(target, ast.Name) and target.id in helper_names:
                    return True
                if isinstance(target, ast.Attribute) and target.attr in helper_names:
                    return True
            return False

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if is_inherited_os_call(func):
                violations.append(
                    f"{path.relative_to(app_root)}:{node.lineno} "
                    "uses an os call that inherits os.environ"
                )
                continue
            if not is_spawn_call(func):
                continue
            env_keyword = next(
                (keyword for keyword in node.keywords if keyword.arg == "env"), None
            )
            if env_keyword is None:
                violations.append(f"{path.relative_to(app_root)}:{node.lineno} inherits os.environ")
                continue
            value = env_keyword.value
            if isinstance(value, ast.Call) and (
                (isinstance(value.func, ast.Name) and value.func.id in helper_names)
                or (isinstance(value.func, ast.Attribute) and value.func.attr in helper_names)
            ):
                continue
            if isinstance(value, ast.Name):
                # A locally built environment is fine when the enclosing
                # function builds it from the scrubbed one, or from the skill
                # runtime's allowlist (which refuses the token by name).
                enclosing = max(
                    (fn for fn in functions if fn.lineno <= node.lineno <= fn.end_lineno),
                    key=lambda fn: fn.lineno,
                    default=None,
                )
                if enclosing is not None and calls_helper(enclosing):
                    continue
            violations.append(
                f"{path.relative_to(app_root)}:{node.lineno} passes an unscrubbed environment"
            )

    assert violations == []
