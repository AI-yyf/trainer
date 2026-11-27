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
    "resources/service.py": 2000,
    "core/models.py": 2000,
    "llm/prompts.py": 2000,
    "llm/agent_binding.py": 2000,
    "db/repository.py": 2000,
    "api/router_domains/training_cards.py": 2000,
    "pedagogy/service.py": 2000,
}

STRICT_2K_MODULES = (
    "resources/service_support.py",
    "resources/canonical_and_collection_mixin.py",
    "resources/search_and_governance_mixin.py",
    "core/model_domains/foundations_and_provider.py",
    "core/model_domains/resources_and_training.py",
    "core/model_domains/memory_and_coach.py",
    "core/model_domains/workspace_and_sandbox.py",
    "llm/prompt_domains/templates_and_system.py",
    "llm/prompt_domains/messages_and_turn_signals.py",
    "llm/prompt_domains/scenario_and_context_blocks.py",
    "llm/agent_binding_helpers.py",
    "llm/agent_binding_protocols_mixin.py",
    "db/repository_assets_and_transfer_mixin.py",
    "api/router_domains/training_cards_activation_mixin.py",
    "pedagogy/goal_and_adaptation_mixin.py",
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

    oversized_2k: list[str] = []
    for rel_path in STRICT_2K_MODULES:
        py_path = SERVER_APP / rel_path
        line_count = len(py_path.read_text(encoding="utf-8").splitlines())
        if line_count >= 2000:
            oversized_2k.append(f"{rel_path} ({line_count} lines)")
    assert oversized_2k == [], f"Extracted backend modules must stay < 2000 lines: {oversized_2k}"

    over_2500 = [
        f"{p.relative_to(SERVER_APP).as_posix()} ({len(p.read_text(encoding='utf-8').splitlines())} lines)"
        for p in sorted(SERVER_APP.rglob("*.py"))
        if len(p.read_text(encoding="utf-8").splitlines()) >= 2500
    ]
    assert over_2500 == [], f"No server/app module may reach 2500 lines: {over_2500}"


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
    import app.llm.agent_binding as ab_mod
    import app.llm.agent_binding_protocols_mixin as ab_mixin
    import app.llm.provider.coaching_reply_mixin as coaching_mixin
    import app.llm.provider.connectivity_and_probes_mixin as conn_mixin
    import app.llm.provider_service as ps_mod

    sentinel_httpx = types.SimpleNamespace(Client="patched_client_sentinel", AsyncClient="patched_async_sentinel")
    monkeypatch.setattr(ps_mod, "httpx", sentinel_httpx)
    monkeypatch.setattr(ps_mod, "build_vision_challenge", lambda *_a, **_kw: "patched_vision")
    monkeypatch.setattr(ps_mod, "build_coaching_messages", lambda *_a, **_kw: ["patched_msg"])
    monkeypatch.setattr(ab_mod, "httpx", sentinel_httpx)

    assert conn_mixin.httpx.Client == "patched_client_sentinel"
    assert conn_mixin.build_vision_challenge() == "patched_vision"
    assert coaching_mixin.build_coaching_messages() == ["patched_msg"]
    assert ab_mixin.httpx.AsyncClient == "patched_async_sentinel"
