# 教学旅程案例报告（全矩阵 32 案例 · 本次 1 案例）

- harness：`scripts/maturity/real_teaching_journeys_minimax.py`（32 组双回合：28 代码案例 A–G×4 + 4 文学案例 L）
- 矩阵规格：`docs/maturity/teaching-case-matrix.md`；台账与对账规则见该文件 §2（M1–M5）
- 运行模式：`real`
- 夹具校验（本地执行，无模型）：1/1 通过（pre-fix exit≠0 且 post-fix exit=0）
- 回合分类统计：{'passed': 2}

## 诚实声明

分类逐回合记录；`local_fallback` / `provider_error` 回合不计入模型教学质量；
内容质量栏由独立评审 agent 填写并标注「待 owner 确认」，不记为人工审阅。

> 分类字段说明：`passed`=M1 脊柱（HTTP + body/disk 校验）+M2 教学接地通过（grounded/corrected 且无 requires_confirmation）
> +M5 同源对账一致且无记忆漂移；`failed`=任一客观判据失败（含 downgraded，降级回合永不算 pass）；
> `provider_error`=请求失败；`local_fallback`=本地兜底（fell_back）；`skipped_no_credentials`=无凭证未执行。本 harness 无 mock 通路。

## 逐案例

| 案例 | 类别 | 夹具 pre/post exit | 回合分类 | 对账 | 备注 |
| --- | --- | --- | --- | --- | --- |
| E4-package-layout | E | 1 / 0 | passed / passed | ok / ok |  |

## 解释质量汇总（非门控观察维度）

- 已评估回合：2（provider_error / local_fallback / skipped_no_credentials 回合不产出解释质量）
- solution_dump_suspected 回合：0/2

| 维度 | ok | weak | unclear |
| --- | --- | --- | --- |
| addresses_learner | 2 | 0 | 0 |
| language_alignment | 2 | 0 | 0 |
| anchored_symbols | 0 | 0 | 2 |
| no_solution_dump | 2 | 0 | 0 |
| explains_reasoning | 1 | 1 | 0 |

> 解释质量是结构化上报维度（`app/llm/explanation_quality.py`），不参与 classification 判定；`unclear` 表示该回合输入不足以判定。

## 复现

```bash
server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
```

真实模型运行需设置环境变量（凭证绝不出现在仓库中）；结果 JSON 落盘在
`TRAINER_MATURITY_WORKSPACE`（默认 `tmp/maturity-ws/`，不入库）。
