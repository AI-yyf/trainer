# 教学旅程案例报告（全矩阵 32 案例 · 本次 32 案例）

- harness：`scripts/maturity/real_teaching_journeys_minimax.py`（32 组双回合：28 代码案例 A–G×4 + 4 文学案例 L）
- 矩阵规格：`docs/maturity/teaching-case-matrix.md`；台账与对账规则见该文件 §2（M1–M5）
- 运行模式：`real`
- 夹具校验（本地执行，无模型）：32/32 通过（pre-fix exit≠0 且 post-fix exit=0）
- 回合分类统计：{'passed': 59, 'failed': 2, 'local_fallback': 3}

- 文学案例（category L）：夹具=交付物校验器（¶ 锚点、引文与原文逐字互查、栏目完整性），材料正文跨回合不变，回合 1→2 之间写完交付物；判据全部是客观结构判据，不含审美判断。

## 诚实声明

分类逐回合记录；`local_fallback` / `provider_error` 回合不计入模型教学质量；
内容质量栏由独立评审 agent 填写并标注「待 owner 确认」，不记为人工审阅。

> 分类字段说明：`passed`=M1 脊柱（HTTP + body/disk 校验）+M2 教学接地通过（grounded/corrected 且无 requires_confirmation）
> +M5 同源对账一致且无记忆漂移；`failed`=任一客观判据失败（含 downgraded，降级回合永不算 pass）；
> `provider_error`=请求失败；`local_fallback`=本地兜底（fell_back）；`skipped_no_credentials`=无凭证未执行。本 harness 无 mock 通路。

## 逐案例

| 案例 | 类别 | 夹具 pre/post exit | 回合分类 | 对账 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 01-mutable-default | A | 1 / 0 | passed / passed | ok / ok |  |
| 02-late-binding | A | 1 / 0 | passed / passed | ok / ok |  |
| 03-nested-alias | A | 1 / 0 | failed / passed | server sent no grounding stamp for an ungrounded step / ok |  |
| A4-dict-mutation | A | 1 / 0 | passed / passed | ok / ok |  |
| 04-binary-search-boundary | B | 1 / 0 | passed / passed | ok / ok |  |
| B2-import-env-stale | B | 1 / 0 | passed / local_fallback | ok / - |  |
| B3-async-ordering | B | 1 / 0 | passed / local_fallback | ok / - |  |
| B4-sqlite-null | B | 1 / 0 | passed / passed | ok / ok |  |
| C1-shared-default-object | C | 1 / 0 | passed / passed | ok / ok |  |
| C2-falsy-vs-null | C | 1 / 0 | passed / passed | ok / ok |  |
| C3-var-capture | C | 1 / 0 | passed / passed | ok / ok |  |
| C4-resource-cleanup | C | 1 / 0 | passed / passed | ok / ok |  |
| D1-default-eval-time | D | 1 / 0 | passed / passed | ok / ok |  |
| D2-closure-experiment | D | 1 / 0 | passed / passed | ok / ok |  |
| D3-copy-semantics | D | 1 / 0 | passed / passed | ok / ok |  |
| D4-hash-contract | D | 1 / 0 | passed / passed | ok / ok |  |
| E1-argparse-entry | E | 1 / 0 | passed / passed | ok / ok |  |
| E2-async-call-site | E | 1 / 0 | passed / passed | ok / ok |  |
| E3-unit-test-contract | E | 1 / 0 | passed / passed | ok / ok |  |
| E4-package-layout | E | 1 / 0 | passed / failed | ok / server sent no grounding stamp for an ungrounded step |  |
| F1-semaphore-limit | F | 1 / 0 | passed / passed | ok / ok |  |
| F2-this-binding | F | 1 / 0 | passed / passed | ok / ok |  |
| F3-quadratic-scan | F | 1 / 0 | passed / passed | ok / ok |  |
| F4-injectable-clock | F | 1 / 0 | passed / passed | ok / ok |  |
| G1-cross-session-topic | G | 1 / 0 | passed / passed | ok / ok |  |
| G2-review-interval | G | 1 / 0 | passed / passed | ok / ok |  |
| G3-provider-recovery | G | 1 / 0 | passed / passed | ok / ok |  |
| G4-return-after-days | G | 1 / 0 | passed / passed | ok / ok |  |
| L1-close-read-annotate | L | 1 / 0 | passed / passed | ok / ok |  |
| L2-imitation-transfer | L | 1 / 0 | local_fallback / passed | - / ok |  |
| L3-theory-concept-card | L | 1 / 0 | passed / passed | ok / ok |  |
| L4-compare-two-pieces | L | 1 / 0 | passed / passed | ok / ok |  |

## 解释质量汇总（非门控观察维度）

- 已评估回合：61（provider_error / local_fallback / skipped_no_credentials 回合不产出解释质量）
- solution_dump_suspected 回合：6/61

| 维度 | ok | weak | unclear |
| --- | --- | --- | --- |
| addresses_learner | 56 | 5 | 0 |
| language_alignment | 55 | 5 | 1 |
| anchored_symbols | 0 | 18 | 43 |
| no_solution_dump | 47 | 6 | 8 |
| explains_reasoning | 23 | 16 | 22 |

> 解释质量是结构化上报维度（`app/llm/explanation_quality.py`），不参与 classification 判定；`unclear` 表示该回合输入不足以判定。

## 复现

```bash
server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
```

真实模型运行需设置环境变量（凭证绝不出现在仓库中）；结果 JSON 落盘在
`TRAINER_MATURITY_WORKSPACE`（默认 `tmp/maturity-ws/`，不入库）。
