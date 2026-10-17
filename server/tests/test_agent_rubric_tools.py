"""P2 #15: read_resource_excerpt / compare_with_anchor / run_rubric_review.

Contract under test:
- All three tools register in the default registry and are READ-ONLY.
- ``read_resource_excerpt`` serves real indexed chunk text (never fabricated),
  resolves anchors (chunk id / synthetic ¶chunk anchor / real paragraph anchor
  via fragment location), and carries citation ids when fragments exist.
- ``compare_with_anchor`` produces deterministic signals only and always
  reports ``evidence_bearing: False``.
- ``run_rubric_review`` is host-gated (``rubric_review_allowed``), refuses
  model-authored rubrics (fail-closed ``host_rubric_missing``), and never
  claims to be evidence.
- The agent tool-context stamps ``rubric_review_allowed`` only on an explicit
  learner request WITH a host card rubric present.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.llm.agent_tool_context import _build_agent_tool_context_extra
from app.llm.tools import (
    ToolContext,
    ToolRegistry,
    build_default_tool_registry,
)
from app.resources.models import ResourceChunk, ResourceKind
from app.resources.models import ResourceRecord as RegistryResourceRecord
from app.training.card_request import message_requests_rubric_review


class _RegistryStub:
    def __init__(self, resources: dict[str, RegistryResourceRecord], chunks: dict[str, list[ResourceChunk]]):
        self._resources = resources
        self._chunks = chunks

    def get(self, resource_id: str) -> RegistryResourceRecord | None:
        return self._resources.get(resource_id)

    def list_chunks(self, resource_id: str) -> list[ResourceChunk]:
        return list(self._chunks.get(resource_id, []))


class _ResourceServiceStub:
    def __init__(self, registry: _RegistryStub):
        self.registry = registry


class _RuntimeStub:
    def __init__(self, resource_service: _ResourceServiceStub | None):
        self.resource_service = resource_service


def _context(runtime: Any, **extra: Any) -> ToolContext:
    return ToolContext(
        runtime=runtime,
        workspace_id="workspace-rubric",
        session_id="session-rubric",
        extra=dict(extra),
    )


def _registry() -> ToolRegistry:
    return build_default_tool_registry()


def _literature_library() -> _RuntimeStub:
    resource = RegistryResourceRecord.create(
        kind=ResourceKind.EPUB,
        source_uri="/tmp/kongyiji.epub",
        title="《孔乙己》精读",
        metadata={
            "content_language": "zh-CN",
            "knowledge_fragments": [
                {
                    "paragraph_anchor": "¶spine:ch1:/body/p[3]",
                    "citation_id": "cite-res-1@v1",
                    "location": {"chunk_id": "chunk_aaa", "paragraph_anchor": "¶spine:ch1:/body/p[3]"},
                }
            ],
        },
    )
    chunks = [
        ResourceChunk(
            resource_id=resource.id,
            chunk_id="chunk_aaa",
            text="孔乙己是站着喝酒而穿长衫的唯一的人。他身材很高大；青白脸色，皱纹间时常夹些伤痕。",
            order=0,
            start_line=1,
            end_line=3,
        ),
        ResourceChunk(
            resource_id=resource.id,
            chunk_id="chunk_bbb",
            text="店内外充满了快活的空气。",
            order=1,
            start_line=4,
            end_line=4,
        ),
    ]
    return _RuntimeStub(
        _ResourceServiceStub(_RegistryStub({resource.id: resource}, {resource.id: chunks}))
    )


# ---------------------------------------------------------------------------
# registration + read-only marking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["read_resource_excerpt", "compare_with_anchor", "run_rubric_review"],
)
def test_tools_register_with_read_only_handlers(name: str) -> None:
    raw_tools = _registry()._tools
    definition = raw_tools.get(name) if isinstance(raw_tools, dict) else None
    assert definition is not None, f"{name} missing from default registry"
    assert definition.handler is not None
    assert definition.parameters.get("type") == "object"


# ---------------------------------------------------------------------------
# read_resource_excerpt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_excerpt_serves_real_chunk_text_with_synthetic_anchor() -> None:
    runtime = _literature_library()
    result = await _registry().invoke(
        _context(runtime), "read_resource_excerpt", {"resource_id": _first_resource_id(runtime)}
    )
    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["resource"]["name"] == "《孔乙己》精读"
    assert result["resource"]["content_language"] == "zh-CN"
    first = result["excerpts"][0]
    assert "孔乙己是站着喝酒而穿长衫的唯一的人" in first["text"]
    assert first["anchor_id"] == "¶chunk:0@1"
    # No citation for the synthetic anchor (fragment pins the spine anchor).
    assert first["citation_id"] is None


@pytest.mark.asyncio
async def test_read_excerpt_resolves_real_paragraph_anchor_with_citation() -> None:
    runtime = _literature_library()
    result = await _registry().invoke(
        _context(runtime),
        "read_resource_excerpt",
        {"resource_id": _first_resource_id(runtime), "anchor_id": "¶spine:ch1:/body/p[3]"},
    )
    assert result["ok"] is True
    first = result["excerpts"][0]
    assert first["text"].startswith("孔乙己是站着喝酒")
    assert first["citation_id"] == "cite-res-1@v1"


@pytest.mark.asyncio
async def test_read_excerpt_fails_closed_without_index() -> None:
    resource = RegistryResourceRecord.create(kind=ResourceKind.TEXT, source_uri="/tmp/notes.txt", title="笔记")
    runtime = _RuntimeStub(_ResourceServiceStub(_RegistryStub({resource.id: resource}, {})))
    result = await _registry().invoke(
        _context(runtime), "read_resource_excerpt", {"resource_id": resource.id}
    )
    assert result["ok"] is False
    assert result["error"] == "index_missing"


@pytest.mark.asyncio
async def test_read_excerpt_unknown_anchor_lists_available_anchors() -> None:
    runtime = _literature_library()
    result = await _registry().invoke(
        _context(runtime),
        "read_resource_excerpt",
        {"resource_id": _first_resource_id(runtime), "anchor_id": "¶chunk:9@99"},
    )
    assert result["ok"] is False
    assert result["error"] == "anchor_not_found"
    assert "¶chunk:0@1" in result["available_anchors"]


def _first_resource_id(runtime: _RuntimeStub) -> str:
    return next(iter(runtime.resource_service.registry._resources))


# ---------------------------------------------------------------------------
# compare_with_anchor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_reports_deterministic_signals_and_never_verifies() -> None:
    runtime = _literature_library()
    result = await _registry().invoke(
        _context(runtime),
        "compare_with_anchor",
        {
            "submission": "他坐着喝酒，而别人都站着。他穿着短衣。",
            "anchor_text": "孔乙己是站着喝酒而穿长衫的唯一的人。他身材很高大。",
        },
    )
    assert result["ok"] is True
    assert result["read_only"] is True
    signals = result["signals"]
    assert signals["lane"] == "deterministic"
    assert signals["evidence_bearing"] is False
    assert signals["anchor"]["sentence_count"] == 2
    assert signals["submission"]["sentence_count"] == 2
    assert 0.0 <= signals["rhythm_similarity"] <= 1.0
    assert "never verifies" in result["evidence_note"]


@pytest.mark.asyncio
async def test_compare_identical_text_yields_zero_delta() -> None:
    text = "孔乙己是站着喝酒而穿长衫的唯一的人。他身材很高大。"
    runtime = _literature_library()
    result = await _registry().invoke(
        _context(runtime), "compare_with_anchor", {"submission": text, "anchor_text": text}
    )
    assert result["signals"]["mean_sentence_length_delta"] == 0.0
    assert result["signals"]["rhythm_similarity"] == 1.0


@pytest.mark.asyncio
async def test_compare_requires_submission_and_anchor() -> None:
    runtime = _literature_library()
    missing_submission = await _registry().invoke(
        _context(runtime), "compare_with_anchor", {"anchor_text": "锚文本。"}
    )
    assert missing_submission["error"] == "missing_submission"
    missing_anchor = await _registry().invoke(
        _context(runtime), "compare_with_anchor", {"submission": "练习文本。"}
    )
    assert missing_anchor["error"] == "missing_anchor"


@pytest.mark.asyncio
async def test_compare_loads_library_anchor_and_citation() -> None:
    runtime = _literature_library()
    result = await _registry().invoke(
        _context(runtime),
        "compare_with_anchor",
        {
            "submission": "小伙计也有了自己的位置。",
            "resource_id": _first_resource_id(runtime),
            "anchor_id": "¶spine:ch1:/body/p[3]",
        },
    )
    assert result["ok"] is True
    assert result["anchor"]["citation_id"] == "cite-res-1@v1"
    assert result["anchor"]["resource"]["name"] == "《孔乙己》精读"
    assert result["anchor"]["chars"] > 0


# ---------------------------------------------------------------------------
# run_rubric_review — host gate + host rubric only
# ---------------------------------------------------------------------------


_RUBRIC_ITEMS = [
    {"statement": "点明叙述视角是小伙计", "anchor": "孔乙己是站着喝酒而穿长衫的唯一的人", "criteria": ["提到小伙计视角"]},
    {"statement": "说明短衣帮与长衫客的分界", "anchor": "短衣帮", "criteria": []},
]


def _gated_context(**extra: Any) -> ToolContext:
    base: dict[str, Any] = {
        "rubric_review_allowed": True,
        "current_file": {
            "path": "card://text_payload",
            "content": "",
            "rubric_items": _RUBRIC_ITEMS,
            "anchor_text": "孔乙己是站着喝酒而穿长衫的唯一的人。",
        },
    }
    base.update(extra)
    return _context(_literature_library(), **base)


@pytest.mark.asyncio
async def test_run_rubric_review_requires_the_host_gate() -> None:
    runtime = _literature_library()
    result = await _registry().invoke(
        _context(runtime), "run_rubric_review", {"submission": "一些文本。"}
    )
    assert result["ok"] is False
    assert result["error"] == "rubric_review_not_allowed"


@pytest.mark.asyncio
async def test_run_rubric_review_reports_item_results_without_evidence() -> None:
    from app.evaluator.models import CheckStatus

    result = await _registry().invoke(
        _gated_context(),
        "run_rubric_review",
        {"submission": "叙述视角来自小伙计，短衣帮与长衫客的分界是明确的。"},
    )
    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["rubric_source"] == "host_card"
    assert result["reviewer_lane"] == "local_rubric"
    assert result["item_count"] == 2
    assert result["evidence_bearing"] is False
    assert "not evidence" in result["note"]
    # Item 1's anchor arrives via spec.anchor_text (matched); item 2's anchor
    # ("短衣帮") appears in the submission corpus too — both matched.
    assert result["status"] == CheckStatus.PASSED.value
    assert result["missing"] == []


@pytest.mark.asyncio
async def test_run_rubric_review_refuses_when_no_host_rubric_exists() -> None:
    result = await _registry().invoke(
        _gated_context(current_file={"path": "card://text_payload", "content": ""}),
        "run_rubric_review",
        {"submission": "文本。", "rubric": _RUBRIC_ITEMS},
    )
    assert result["ok"] is False
    assert result["error"] == "host_rubric_missing"


@pytest.mark.asyncio
async def test_run_rubric_review_falls_back_to_text_submission_carrier() -> None:
    context = _gated_context(
        current_file=None,
        text_submission={
            "path": "card://text_payload",
            "content": "提交文本",
            "rubric_items": _RUBRIC_ITEMS,
            "anchor_text": "孔乙己是站着喝酒而穿长衫的唯一的人。",
        },
    )
    result = await _registry().invoke(context, "run_rubric_review", {"submission": "提交文本"})
    assert result["ok"] is True
    assert result["item_count"] == 2


@pytest.mark.asyncio
async def test_run_rubric_review_requires_submission() -> None:
    result = await _registry().invoke(_gated_context(), "run_rubric_review", {})
    assert result["ok"] is False
    assert result["error"] == "missing_submission"


# ---------------------------------------------------------------------------
# tool-context auto-stamp: explicit request + host rubric
# ---------------------------------------------------------------------------


def _extra(message: str | None, current_file: Any) -> dict[str, Any]:
    return _build_agent_tool_context_extra(
        coach_context=None,
        attachment_delivery={},
        answer_mode="guided",
        current_file=current_file,
        learner_message=message,
    )


def test_stamp_arms_on_explicit_request_with_host_rubric() -> None:
    extra = _extra(
        "帮我按评分标准评审我的仿写",
        {"path": "card://text_payload", "rubric_items": _RUBRIC_ITEMS},
    )
    assert extra["rubric_review_allowed"] is True
    assert "run_rubric_review" not in extra["denied_tool_names"]


def test_stamp_fails_closed_without_host_rubric() -> None:
    extra = _extra("帮我按评分标准评审我的仿写", {"path": "card://text_payload", "content": ""})
    assert extra["rubric_review_allowed"] is False
    assert "run_rubric_review" in extra["denied_tool_names"]


def test_stamp_fails_closed_without_explicit_request() -> None:
    extra = _extra("随便聊聊今天读的内容", {"path": "card://text_payload", "rubric_items": _RUBRIC_ITEMS})
    assert extra["rubric_review_allowed"] is False
    assert "run_rubric_review" in extra["denied_tool_names"]


def test_stamp_respects_explicit_rejection_language() -> None:
    assert message_requests_rubric_review("不要用评分标准评审，直接聊感受") is False
    assert message_requests_rubric_review("帮我按评分标准评审我的仿写") is True
    assert message_requests_rubric_review("run the rubric on my submission") is True
    assert message_requests_rubric_review("") is False
