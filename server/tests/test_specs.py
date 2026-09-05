from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import TaskSpecifyRequest
from app.specs import TaskSpecGenerator, TaskSpecificationRequest
from app.specs.service import SpecService


class TaskSpecTests(unittest.TestCase):
    def test_generator_extracts_constraint_signals(self) -> None:
        generator = TaskSpecGenerator()
        result = generator.generate(
            TaskSpecificationRequest(
                prompt=(
                    "Build a parser.\n"
                    "- Input: accept a markdown string.\n"
                    "- Output: return headings.\n"
                    "- Must ignore empty lines.\n"
                    "- Raise an error on invalid indentation."
                )
            )
        )
        self.assertEqual(result.spec.inputs[0], "Input: accept a markdown string.")
        self.assertTrue(any("Must ignore empty lines." == item for item in result.spec.constraints))
        self.assertTrue(any("Raise an error on invalid indentation." == item for item in result.spec.failure_conditions))

    def test_generator_extracts_chinese_verifiable_requirement_signals(self) -> None:
        generator = TaskSpecGenerator()
        result = generator.generate(
            TaskSpecificationRequest(
                prompt=(
                    "实现一个用户注册校验器。输入：用户名、邮箱和密码；输出：校验结果和提示信息；"
                    "必须拒绝空值；验收标准：有效邮箱可以通过；错误时返回明确错误信息。"
                )
            )
        )

        self.assertEqual(result.spec.title, "实现一个用户注册校验器")
        self.assertEqual(result.spec.inputs, ["输入：用户名、邮箱和密码；"])
        self.assertEqual(result.spec.outputs[0], "输出：校验结果和提示信息；")
        self.assertIn("必须拒绝空值；", result.spec.constraints)
        self.assertIn("验收标准：有效邮箱可以通过；", result.spec.constraints)
        self.assertIn("必须拒绝空值；", result.spec.edge_cases)
        self.assertIn("错误时返回明确错误信息。", result.spec.failure_conditions)

    def test_spec_service_exposes_chinese_task_requirements(self) -> None:
        task = SpecService().specify(
            TaskSpecifyRequest(
                natural_language_goal=(
                    "写一个折扣计算函数，输入是商品价格和会员等级，输出最终价格，"
                    "必须拒绝空值，验收标准是会员折扣计算正确，错误时返回可读提示。"
                )
            )
        )

        self.assertTrue(any(item.startswith("输入是") for item in task.inputs))
        self.assertTrue(any(item.startswith("输出最终价格") for item in task.outputs))
        self.assertTrue(any(item.startswith("必须拒绝空值") for item in task.constraints))
        self.assertTrue(any(item.startswith("验收标准") for item in task.constraints))
        self.assertTrue(any(item.startswith("必须拒绝空值") for item in task.edge_cases))
        self.assertTrue(any(item.startswith("错误时") for item in task.failure_conditions))


if __name__ == "__main__":
    unittest.main()
