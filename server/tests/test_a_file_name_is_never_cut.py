"""A file name in stored text is never cut.

Seen with a real model on 2026-11-28, all on one learner turn —
``我在 refunds.py 里也碰到类似的超时重试问题，这次我想自己修，只给我一句提示就好。``:

* the stored next step read ``下一步：围绕 `refunds.py`、「里也碰到类似的超时重试问」 ，先在 `refunds.`
  里查看…`` (``先在 `refun` 里查看`` in a run whose temporary folder had a longer name): the open
  file's path was cut to 80 characters *before* its file name was taken, and the Chinese phrase was
  cut at twelve characters;
* the stored focus read ``当前聚焦点：我在 refunds``: the first clause was split at the dot of
  ``refunds.py``.

A file name is one token: neither a length cap nor a sentence end may fall inside it.
"""

from __future__ import annotations

import re

import pytest

from app.api.router_domains.guided_focus import GuidedFocusDomainMixin
from app.llm.coaching_replies import (
    _current_request_anchor_label,
    _relevance_reanchor_next_step,
    _request_relevance_anchor_terms,
)
from app.specs.service import TaskSpecGenerator

THURSDAY_TURN = "我在 refunds.py 里也碰到类似的超时重试问题，这次我想自己修，只给我一句提示就好。"
# The probe's temporary workspace: 82 characters, so an 80-character cut took "py" off the name.
DEEP_WORKSPACE_FILE = "/var/folders/k2/8v88bznj0_v6synd98blpf5m0000gn/T/trainer-rm-fb-we7vnd1k/refunds.py"


def _focus_domain() -> GuidedFocusDomainMixin:
    return object.__new__(GuidedFocusDomainMixin)


# --- the stored next step ---------------------------------------------------------


def test_a_file_deep_in_the_workspace_keeps_its_whole_name() -> None:
    assert len(DEEP_WORKSPACE_FILE) == 82

    next_step = _relevance_reanchor_next_step(
        message=THURSDAY_TURN,
        current_file={"path": DEEP_WORKSPACE_FILE},
        response_language="zh-CN",
    )

    assert "先在 `refunds.py` 里查看" in next_step
    assert "refunds.py" in _request_relevance_anchor_terms(THURSDAY_TURN, current_file={"path": DEEP_WORKSPACE_FILE})
    assert "refunds." not in next_step.replace("refunds.py", "")


@pytest.mark.parametrize("path", ["C:\\Users\\learner\\course\\payments\\week-03\\src\\refunds.py", "refunds.py"])
def test_the_file_name_is_the_last_segment_whatever_the_separator(path: str) -> None:
    next_step = _relevance_reanchor_next_step(
        message=THURSDAY_TURN, current_file={"path": path}, response_language="zh-CN"
    )

    assert "先在 `refunds.py` 里查看" in next_step


def test_an_anchor_phrase_is_never_cut_in_the_middle_of_a_word() -> None:
    """「里也碰到类似的超时重试问」 was the rest of the learner's clause after the file name, cut
    at twelve characters. Past the limit a phrase is cut where the clause is, after its last
    structural particle, and left out when it has none."""
    terms = _request_relevance_anchor_terms(THURSDAY_TURN, current_file={"path": "/repo/refunds.py"})

    assert _current_request_anchor_label(THURSDAY_TURN, current_file={"path": "/repo/refunds.py"}) == (
        "`refunds.py`、「超时重试问题」"
    )
    for term in terms:
        if re.fullmatch(r"[\u3400-\u9fff]+", term):
            assert not re.search(re.escape(term) + r"[\u3400-\u9fff]", THURSDAY_TURN), term


def test_a_long_clause_without_a_particle_is_left_out_instead_of_cut() -> None:
    run = "这个函数同样会超时重试并且重复扣款"
    message = f"我在 refunds.py 里也碰到这个问题，`refund_all` {run}"

    terms = _request_relevance_anchor_terms(message, current_file={"path": "/repo/refunds.py"})

    assert "refund_all" in terms
    assert not any(run.startswith(term) and len(term) < len(run) for term in terms), terms


# --- the stored focus -------------------------------------------------------------


def test_the_focus_hint_keeps_a_file_name_whole() -> None:
    focus = _focus_domain().extract_focus_hint_from_message(THURSDAY_TURN)

    assert focus == "refunds.py 里也碰到类似的超时重试问题"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("帮我看看 app.py", "帮我看看 app.py"),
        ("v3.11 的 match 语法该怎么理解？先给个例子", "v3.11 的 match 语法该怎么理解"),
        ("Fix app.py. Then run the tests", "Fix app.py"),
        ("Add retries to payments.py", "Add retries to payments.py"),
        ("为什么 example.com 解析失败, 我该先看哪里", "为什么 example.com 解析失败"),
        ("这是什么？", "这是什么"),
    ],
)
def test_a_dot_inside_a_word_is_not_the_end_of_the_clause(message: str, expected: str) -> None:
    assert _focus_domain().extract_focus_hint_from_message(message) == expected


def test_a_task_title_keeps_a_file_name_whole() -> None:
    generator = TaskSpecGenerator()

    assert generator._derive_title("Add retries to payments.py") == "Add retries to payments.py"
    assert generator._derive_title("给 payments.py 的 charge 加上超时重试。不要改测试。") == "给 payments.py 的 charge 加上超时重试"
    assert generator._derive_title("Write the handler. Cover the empty input.") == "Write the handler"


def test_a_statement_of_the_learner_s_own_keeps_its_pronoun() -> None:
    """"我想真正搞懂幂等" is the learner's topic. Cutting its pronoun left 「想真正搞懂幂等」."""
    message = "我想真正搞懂幂等。先帮我看看 payments.py 里的 retry() 有没有问题。"

    label = _current_request_anchor_label(message, current_file={"path": "/repo/payments.py"})

    assert label == "`payments.py`、「我想真正搞懂幂等」"


def test_nothing_is_reanchored_when_the_request_names_nothing() -> None:
    assert (
        _relevance_reanchor_next_step(
            message="why does it time out?", current_file={"path": "/repo/payments.py"}, response_language="en-US"
        )
        == ""
    )
