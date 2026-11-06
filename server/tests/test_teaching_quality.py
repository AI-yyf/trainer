"""Phase 3 — 真实教学质量评估验收 (确定性、证据驱动).

覆盖评估要求的五个维度：解释准确性(引用完备率)、提示有效性、难度适配、
独立解题、跨项目迁移。关键约束：
- 样本不足 = insufficient_evidence (score None)，绝不伪装 0/1；
- 只读持久化 attempt/evidence，不接受自报或模型自评；
- 文字表达质量保留人工评审 (limitation 明示)。
"""

from __future__ import annotations

from pathlib import Path

from app.pedagogy.quality import MIN_SAMPLE, evaluate_teaching_quality
from app.training.attempt_store import AttemptStore

HASH = "a" * 64
CITATION = {
    "resource_id": "resource-1",
    "resource_version_id": "version-1",
    "resource_content_hash": HASH,
    "resource_location": {"page": 2, "anchor_id": "¶p2.1@120"},
}


def _seed(
    store: AttemptStore,
    workspace_id: str,
    *,
    card_id: str,
    result: str,
    assistance_level: str = "independent",
    transfer: bool = False,
    citation: bool = False,
) -> str:
    attempt = store.start_attempt(
        workspace_id=workspace_id,
        card_id=card_id,
        file_path="main.py",
        file_hash=HASH,
        assistance_level=assistance_level,
    )
    kwargs = dict(CITATION) if citation else {}
    store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash=attempt.get("file_hash") or HASH,
        result=result,
        trust_level="self_reported",
        transfer_metadata={"source_workspace": "project-a", "target": "project-b"}
        if transfer
        else None,
        **kwargs,
    )
    return attempt["attempt_id"]


def test_empty_workspace_reports_insufficient_never_zero(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "q.db")
    report = evaluate_teaching_quality(store, "ws-empty")
    payload = report.as_payload()
    assert payload["overall"] is None
    assert payload["measured_dimensions"] == 0
    for dimension in payload["dimensions"]:
        assert dimension["score"] is None
        assert dimension["status"] == "insufficient_evidence"


def test_five_dimensions_measured_from_real_evidence(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "q.db")
    workspace = "ws-quality"
    # 4 independent passes with full citations.
    for index in range(4):
        _seed(store, workspace, card_id=f"card-i{index}", result="passed", citation=True)
    # 2 assisted outcomes: one passed, one failed (hint effectiveness 0.5).
    _seed(store, workspace, card_id="card-a1", result="passed", assistance_level="guided", citation=True)
    _seed(store, workspace, card_id="card-a2", result="failed", assistance_level="guided")
    # 3 transfer-marked outcomes: 2 passed, 1 failed (transfer 2/3).
    _seed(store, workspace, card_id="card-t1", result="passed", transfer=True, citation=True)
    _seed(store, workspace, card_id="card-t2", result="passed", transfer=True, citation=True)
    _seed(store, workspace, card_id="card-t3", result="failed", transfer=True)

    report = evaluate_teaching_quality(store, workspace)
    dims = {dimension["key"]: dimension for dimension in report.as_payload()["dimensions"]}

    # 9 attempts; independent = 4+3 transfer(independent default)=7 → 7/9
    assert dims["independent_solving"]["sample_size"] == 9
    assert dims["independent_solving"]["score"] == round(7 / 9, 3)

    # Assisted: 2 samples; one passed → 0.5 (>= MIN_SAMPLE? 2 < 3 → insufficient)
    assert MIN_SAMPLE == 3
    assert dims["hint_effectiveness"]["status"] == "insufficient_evidence"

    # Transfer: 3 samples; 2 passed → 0.667
    assert dims["transfer"]["score"] == round(2 / 3, 3)

    # Citations: passed+cited evidence = 7 cited passed? cited evidence count:
    # 4 independent + 1 assisted + 2 transfer = 7 cited, all passed → 1.0
    assert dims["citation_completeness"]["score"] == 1.0

    # Difficulty: pass rate = passed(7)/current(9) ≈ 0.778 → adapted, high score
    assert dims["difficulty_fit"]["evidence"]["read"] == "adapted"
    assert dims["difficulty_fit"]["score"] == 1.0

    payload = report.as_payload()
    assert payload["measured_dimensions"] >= 4
    assert payload["overall"] is not None
    assert any("human" in line for line in payload["limitations"])


def test_hint_effectiveness_measured_once_sample_is_enough(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "q.db")
    workspace = "ws-hints"
    for index in range(3):
        _seed(store, workspace, card_id=f"card-a{index}", result="passed", assistance_level="guided")
    for index in range(3):
        _seed(store, workspace, card_id=f"card-i{index}", result="passed")
    dims = {
        dimension["key"]: dimension
        for dimension in evaluate_teaching_quality(store, workspace).as_payload()["dimensions"]
    }
    assert dims["hint_effectiveness"]["score"] == 1.0
    assert dims["hint_effectiveness"]["evidence"]["assisted_evidence"] == 3
