# 教学旅程案例报告（全矩阵 32 案例 · 本次 4 案例）

- harness：`scripts/maturity/real_teaching_journeys_minimax.py`（32 组双回合：28 代码案例 A–G×4 + 4 文学案例 L）
- 矩阵规格：`docs/maturity/teaching-case-matrix.md`；台账与对账规则见该文件 §2（M1–M5）
- 运行模式：`skipped_no_credentials`
- 夹具校验（本地执行，无模型）：4/4 通过（pre-fix exit≠0 且 post-fix exit=0）
- 回合分类统计：{'skipped_no_credentials': 8}

- 文学案例（category L）：夹具=交付物校验器（¶ 锚点、引文与原文逐字互查、栏目完整性），材料正文跨回合不变，回合 1→2 之间写完交付物；判据全部是客观结构判据，不含审美判断。

## 诚实声明

本环境未设置 `TRAINER_MATURITY_API_KEY` / `TRAINER_MATURITY_PROVIDER_BASE_URL`，
**8 个模型回合全部标记 `skipped_no_credentials`：未向任何 provider 发起调用，
本报告不构成、也不得被引用为「真实模型通过」**。夹具骨架为本地真实执行。

> 分类字段说明：`passed`=M1 脊柱（HTTP + body/disk 校验）+M2 教学接地通过（grounded/corrected 且无 requires_confirmation）
> +M5 同源对账一致且无记忆漂移；`failed`=任一客观判据失败（含 downgraded，降级回合永不算 pass）；
> `provider_error`=请求失败；`local_fallback`=本地兜底（fell_back）；`skipped_no_credentials`=无凭证未执行。本 harness 无 mock 通路。

## 逐案例

| 案例 | 类别 | 夹具 pre/post exit | 回合分类 | 对账 | 备注 |
| --- | --- | --- | --- | --- | --- |
| L1-close-read-annotate | L | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| L2-imitation-transfer | L | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| L3-theory-concept-card | L | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| L4-compare-two-pieces | L | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |

## 解释质量汇总（非门控观察维度）

- 已评估回合：0（provider_error / local_fallback / skipped_no_credentials 回合不产出解释质量）
- solution_dump_suspected 回合：0/0

| 维度 | ok | weak | unclear |
| --- | --- | --- | --- |
| addresses_learner | 0 | 0 | 0 |
| language_alignment | 0 | 0 | 0 |
| anchored_symbols | 0 | 0 | 0 |
| no_solution_dump | 0 | 0 | 0 |
| explains_reasoning | 0 | 0 | 0 |

> 解释质量是结构化上报维度（`app/llm/explanation_quality.py`），不参与 classification 判定；`unclear` 表示该回合输入不足以判定。

## 复现

```bash
server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
```

真实模型运行需设置环境变量（凭证绝不出现在仓库中）；结果 JSON 落盘在
`TRAINER_MATURITY_WORKSPACE`（默认 `tmp/maturity-ws/`，不入库）。
