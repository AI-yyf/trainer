from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_APP = REPO_ROOT / "server" / "app"
BUNDLED_APP = REPO_ROOT / "extension" / "bundled" / "server" / "app"

FORMER_MONOLITH_CEILINGS = {
    "memory/service.py": 2000,
    "memory/workspace_recovery.py": 800,
    "api/coach_support.py": 350,
    "llm/provider_service.py": 2250,
    "sandbox/service.py": 2200,
    "llm/tools.py": 900,
    "training/card_generator.py": 2000,
}

EXTRACTED_DOMAIN_DIRS = (
    "memory",
    "memory/workspace_recovery_domains",
    "api/coach_support_domains",
    "llm/provider",
    "sandbox",
    "llm/tool_handlers",
    "training/card_generator_domains",
)


def _is_broad_exception_type(exc_type: ast.expr | None) -> bool:
    if exc_type is None:
        return True
    if isinstance(exc_type, ast.Name):
        return exc_type.id in {"Exception", "BaseException"}
    if isinstance(exc_type, ast.Tuple):
        return any(_is_broad_exception_type(elt) for elt in exc_type.elts)
    return False


def _is_silent_noop_body(body: list[ast.stmt]) -> bool:
    return len(body) == 1 and (
        isinstance(body[0], ast.Pass)
        or (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and body[0].value.value is Ellipsis
        )
    )


def test_zero_silent_broad_exception_pass_in_server_app() -> None:
    offenders: list[str] = []
    for py_path in sorted(SERVER_APP.rglob("*.py")):
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
        rel = py_path.relative_to(SERVER_APP).as_posix()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ExceptHandler)
                and _is_broad_exception_type(node.type)
                and _is_silent_noop_body(node.body)
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], f"Silent broad exception handlers found: {offenders}"


def test_phase4_backend_module_line_ceilings() -> None:
    for rel_path, ceiling in FORMER_MONOLITH_CEILINGS.items():
        target = SERVER_APP / rel_path
        line_count = len(target.read_text(encoding="utf-8").splitlines())
        assert line_count < ceiling, f"{rel_path} has {line_count} lines (ceiling < {ceiling})"

    oversized: list[str] = []
    for rel_dir in EXTRACTED_DOMAIN_DIRS:
        for py_path in sorted((SERVER_APP / rel_dir).glob("*.py")):
            line_count = len(py_path.read_text(encoding="utf-8").splitlines())
            if line_count >= 2500:
                oversized.append(f"{py_path.relative_to(SERVER_APP).as_posix()} ({line_count} lines)")
    assert oversized == [], f"Extracted backend modules must stay < 2500 lines: {oversized}"

    over_5k = [
        f"{p.relative_to(SERVER_APP).as_posix()} ({len(p.read_text(encoding='utf-8').splitlines())} lines)"
        for p in sorted(SERVER_APP.rglob("*.py"))
        if len(p.read_text(encoding="utf-8").splitlines()) >= 5000
    ]
    assert over_5k == [], f"No server/app module may exceed 5000 lines: {over_5k}"


def test_bundled_server_app_python_mirror_parity() -> None:
    server_files = {p.relative_to(SERVER_APP).as_posix() for p in SERVER_APP.rglob("*.py")}
    bundled_files = {p.relative_to(BUNDLED_APP).as_posix() for p in BUNDLED_APP.rglob("*.py")}
    assert server_files == bundled_files

    mismatched = [
        rel
        for rel in sorted(server_files)
        if (SERVER_APP / rel).read_bytes() != (BUNDLED_APP / rel).read_bytes()
    ]
    assert mismatched == [], f"Out-of-sync bundled server Python files: {mismatched}"


def test_provider_service_monkeypatch_hooks_propagate_to_mixins(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.llm.provider.coaching_reply_mixin as coaching_mixin
    import app.llm.provider.connectivity_and_probes_mixin as conn_mixin
    import app.llm.provider_service as ps_mod

    sentinel_httpx = types.SimpleNamespace(Client="patched_client_sentinel")
    monkeypatch.setattr(ps_mod, "httpx", sentinel_httpx)
    monkeypatch.setattr(ps_mod, "build_vision_challenge", lambda *_a, **_kw: "patched_vision")
    monkeypatch.setattr(ps_mod, "build_coaching_messages", lambda *_a, **_kw: ["patched_msg"])

    assert conn_mixin.httpx.Client == "patched_client_sentinel"
    assert conn_mixin.build_vision_challenge() == "patched_vision"
    assert coaching_mixin.build_coaching_messages() == ["patched_msg"]
