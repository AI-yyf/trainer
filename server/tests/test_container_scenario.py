from __future__ import annotations

import pytest

from app.llm.coaching_first_turn import _resolve_first_turn_guided_lane
from app.llm.prompts import infer_coaching_scenario


@pytest.mark.parametrize("message", [
    "解释 Python 容器和容器里的对象：列表可变，元组不能替换元素。",
    "继续当前步骤：新建 list_pairs.py，验证 tuple 内 list 的可变性。为什么现在：先钉住容器和容器里的对象。",
    "用 C++ vector 容器练习迭代和求和。",
])
def test_data_containers_do_not_become_remote_workspace_coaching(message: str) -> None:
    scenario = infer_coaching_scenario(message, default="general")
    assert scenario != "remote_workspace"
    assert _resolve_first_turn_guided_lane(
        scenario=scenario, learner_message=message,
        reply="先验证容器里的对象仍然能修改，然后带回运行结果。",
    ) != "remote_workspace"


@pytest.mark.parametrize("message", [
    "帮我连接开发容器里的 VS Code 工作区",
    "Docker 容器中的路径在哪台主机上？",
    "VS Code Remote SSH 为什么打不开远程文件？",
])
def test_actual_remote_development_requests_keep_remote_lane(message: str) -> None:
    assert infer_coaching_scenario(message, default="general") == "remote_workspace"
