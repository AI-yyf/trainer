from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPOSITORY_ROOT / "server"
PROVIDER_SOURCES = (
    SERVER_ROOT / "app" / "llm" / "provider_service.py",
    REPOSITORY_ROOT / "extension" / "bundled" / "server" / "app" / "llm" / "provider_service.py",
)
SOURCE_PAIRS = (
    (
        SERVER_ROOT / "app" / "api" / "routers.py",
        REPOSITORY_ROOT / "extension" / "bundled" / "server" / "app" / "api" / "routers.py",
    ),
    PROVIDER_SOURCES,
    (
        SERVER_ROOT / "app" / "llm" / "prompts.py",
        REPOSITORY_ROOT / "extension" / "bundled" / "server" / "app" / "llm" / "prompts.py",
    ),
    (
        SERVER_ROOT / "app" / "workspace" / "adoption_index.py",
        REPOSITORY_ROOT
        / "extension"
        / "bundled"
        / "server"
        / "app"
        / "workspace"
        / "adoption_index.py",
    ),
    (
        SERVER_ROOT / "app" / "pedagogy" / "implementation_coach.py",
        REPOSITORY_ROOT
        / "extension"
        / "bundled"
        / "server"
        / "app"
        / "pedagogy"
        / "implementation_coach.py",
    ),
    (
        SERVER_ROOT / "app" / "pedagogy" / "service.py",
        REPOSITORY_ROOT / "extension" / "bundled" / "server" / "app" / "pedagogy" / "service.py",
    ),
    (
        SERVER_ROOT / "app" / "memory" / "review_scheduler.py",
        REPOSITORY_ROOT
        / "extension"
        / "bundled"
        / "server"
        / "app"
        / "memory"
        / "review_scheduler.py",
    ),
)
MOJIBAKE_SOURCE_MARKERS = (
    "\u6d93\u5b29\u7af4\u9352\u20ac",
    "\u93c8\u20ac\u704f\u5fd3\u5f72\u6960\u5c83\u7609\u9354\u3124\u7d94",
    "MVP 杈圭晫",
)
UNFRIENDLY_VISIBLE_COPY_MARKERS = (
    "下一刀",
    "第一刀",
    "这一刀",
    "一刀很薄",
    "最薄的一刀",
)
MALFORMED_VISIBLE_COPY_MARKERS = (
    "建议起点?",
    "教学提醒?",
    "尽量接住最近的进步?",
    "别断复盘节奏?",
    "做稳，再用这条验证它?",
)


def _load_provider_from_raw_source(source_path: Path) -> dict[str, object]:
    if str(SERVER_ROOT) not in sys.path:
        sys.path.insert(0, str(SERVER_ROOT))

    namespace: dict[str, object] = {
        "__name__": f"app.llm.provider_service_source_integrity_{source_path.parent.parent.parent.name}",
        "__package__": "app.llm",
        "__file__": str(source_path),
    }
    exec(compile(source_path.read_bytes(), str(source_path), "exec"), namespace)
    return namespace


def _assert_clean_chinese_reply(reply: object) -> None:
    text = str(reply)

    assert 0 < len(text) <= 480
    assert any("\u4e00" <= character <= "\u9fff" for character in text)
    assert "\ufffd" not in text
    assert not any("\ue000" <= character <= "\uf8ff" for character in text)


def _looks_like_gbk_mojibake_literal(value: str) -> bool:
    def cjk_count(text: str) -> int:
        return sum("\u3400" <= character <= "\u9fff" for character in text)

    if cjk_count(value) < 3:
        return False

    try:
        repaired = value.encode("gbk").decode("utf-8")
    except UnicodeError:
        repaired = value.encode("gbk", errors="replace").decode("utf-8", errors="replace")

    compact_length = max(1, len(repaired.replace(" ", "").replace("\n", "")))
    return (
        repaired != value
        and cjk_count(repaired) >= 3
        and cjk_count(repaired) / compact_length >= 0.35
        and repaired.count("\ufffd") / compact_length <= 0.25
    )


@pytest.mark.parametrize("source_path", PROVIDER_SOURCES, ids=("server", "bundled"))
def test_raw_provider_source_keeps_zh_cn_fallbacks_compact_and_clean(source_path: Path) -> None:
    module = _load_provider_from_raw_source(source_path)
    service = module["ProviderService"](api_key="sk-test-key")

    summary, next_step = module["_agentic_fallback_continuity"](
        "继续修这个 provider",
        current_file=None,
        coach_context=None,
        response_language="zh-CN",
    )
    override = module["_build_empty_reply_override"](
        "继续修这个 provider",
        current_file=None,
        coach_context=None,
        response_language="zh-CN",
    )

    replies = (
        service._onboarding_reply("zh-CN"),
        service._error_reply(RuntimeError("timeout"), "zh-CN"),
        service._missing_api_key_reply("zh-CN"),
        service.provider_failure_reply("network", "timeout", "zh-CN"),
        service._fallback_empty_reply(
            message="继续修这个 provider",
            current_file={"path": "server/app/llm/provider_service.py"},
            response_language="zh-CN",
        ),
        summary,
        next_step,
        override["summary"],
        override["next_step"],
        override["teaching_note"],
        override["resume_thread"],
    )

    for reply in replies:
        _assert_clean_chinese_reply(reply)


def test_bundled_provider_source_matches_server_semantics() -> None:
    server_tree = ast.parse(PROVIDER_SOURCES[0].read_text(encoding="utf-8"))
    bundled_tree = ast.parse(PROVIDER_SOURCES[1].read_text(encoding="utf-8"))

    assert ast.dump(server_tree, include_attributes=False) == ast.dump(
        bundled_tree,
        include_attributes=False,
    )


@pytest.mark.parametrize("server_source,bundled_source", SOURCE_PAIRS)
def test_shipped_coach_sources_are_clean_and_in_sync(
    server_source: Path,
    bundled_source: Path,
) -> None:
    server_text = server_source.read_text(encoding="utf-8")
    bundled_text = bundled_source.read_text(encoding="utf-8")

    for source_path, text in ((server_source, server_text), (bundled_source, bundled_text)):
        assert not any("\ue000" <= character <= "\uf8ff" for character in text), source_path
        assert not any(marker in text for marker in MOJIBAKE_SOURCE_MARKERS), source_path
        assert not any(marker in text for marker in UNFRIENDLY_VISIBLE_COPY_MARKERS), source_path
        assert not any(marker in text for marker in MALFORMED_VISIBLE_COPY_MARKERS), source_path
        source_tree = ast.parse(text, filename=str(source_path))
        malformed_literals = [
            node.lineno
            for node in ast.walk(source_tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _looks_like_gbk_mojibake_literal(node.value)
        ]
        assert not malformed_literals, f"Possible GBK mojibake literals in {source_path}: {malformed_literals}"
        unfriendly_literals = [
            node.lineno
            for node in ast.walk(source_tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and any(marker in node.value for marker in UNFRIENDLY_VISIBLE_COPY_MARKERS)
        ]
        assert not unfriendly_literals, f"Unfriendly coach copy in {source_path}: {unfriendly_literals}"

    assert server_text == bundled_text
