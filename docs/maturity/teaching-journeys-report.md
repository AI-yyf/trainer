# 教学旅程案例报告（最新事实来源）

> **本文件是教学旅程验收的唯一最新事实来源（canonical）。** 带日期的同名文件是单次运行的历史归档快照，由 harness 直接生成；本文件正文始终对应最近一次有效运行。harness 现在同时刷新本文件与当天的归档文件，历史快照不再被覆盖。
> 机器可读的事实摘要（提交 SHA / 运行时间 / 模型 / 分类计数模板）见 [`ACCEPTANCE_FACTS.md`](ACCEPTANCE_FACTS.md)；两处数值必须一致。
>
> **2026-10-19 全矩阵运行（最新）**：32 案例（28 代码 A–G×4 + 4 文学 L）/ 64 回合，逐回合 `{'passed': 64}`，0 failed / 0 fallback / 0 provider_error。矩阵已包含文学案例的真实模型轮次。原始产物 `tmp/maturity-ws/report.json` 早于 harness 元数据插桩，未记录 SHA/时间/模型/平台；记录提交为 `38969f5`（详见归档文件与 ACCEPTANCE_FACTS）。自本次插桩起，新运行的 `report.json` 会在 `run` 字段中记录 commit、dirty、model、provider host、platform、时间和分类计数。
>
> **2026-10-17 矩阵扩容说明（P2 #17）**：harness 矩阵从 28 案例扩到 32 案例（28 代码 A–G×4 + 4 文学 L）。历史 55/1 与 56/56 事实只覆盖 28 个代码案例，已归档在 `2026-10-13-teaching-journeys-report.md`；文学夹具骨架见 `2026-10-17-literature-journeys-report.md`。

## 本次运行（2026-10-19 全矩阵，提交 38969f5 记录）

- harness：`scripts/maturity/real_teaching_journeys_minimax.py`（32 组双回合：28 代码案例 A–G×4 + 4 文学案例 L）
- 矩阵规格：`docs/maturity/teaching-case-matrix.md`；台账与对账规则见该文件 §2（M1–M5）
- 运行模式：`real`
- 夹具校验（本地执行，无模型）：32/32 通过（pre-fix exit≠0 且 post-fix exit=0）
- 回合分类统计：{'passed': 64}

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
| 03-nested-alias | A | 1 / 0 | passed / passed | ok / ok |  |
| A4-dict-mutation | A | 1 / 0 | passed / passed | ok / ok |  |
| 04-binary-search-boundary | B | 1 / 0 | passed / passed | ok / ok |  |
| B2-import-env-stale | B | 1 / 0 | passed / passed | ok / ok |  |
| B3-async-ordering | B | 1 / 0 | passed / passed | ok / ok |  |
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
| E4-package-layout | E | 1 / 0 | passed / passed | ok / ok |  |
| F1-semaphore-limit | F | 1 / 0 | passed / passed | ok / ok |  |
| F2-this-binding | F | 1 / 0 | passed / passed | ok / ok |  |
| F3-quadratic-scan | F | 1 / 0 | passed / passed | ok / ok |  |
| F4-injectable-clock | F | 1 / 0 | passed / passed | ok / ok |  |
| G1-cross-session-topic | G | 1 / 0 | passed / passed | ok / ok |  |
| G2-review-interval | G | 1 / 0 | passed / passed | ok / ok |  |
| G3-provider-recovery | G | 1 / 0 | passed / passed | ok / ok |  |
| G4-return-after-days | G | 1 / 0 | passed / passed | ok / ok |  |
| L1-close-read-annotate | L | 1 / 0 | passed / passed | ok / ok |  |
| L2-imitation-transfer | L | 1 / 0 | passed / passed | ok / ok |  |
| L3-theory-concept-card | L | 1 / 0 | passed / passed | ok / ok |  |
| L4-compare-two-pieces | L | 1 / 0 | passed / passed | ok / ok |  |

## 解释质量汇总（非门控观察维度）

- 已评估回合：64（provider_error / local_fallback / skipped_no_credentials 回合不产出解释质量）
- solution_dump_suspected 回合：3/64

| 维度 | ok | weak | unclear |
| --- | --- | --- | --- |
| addresses_learner | 56 | 8 | 0 |
| language_alignment | 57 | 6 | 1 |
| anchored_symbols | 0 | 9 | 55 |
| no_solution_dump | 53 | 3 | 8 |
| explains_reasoning | 24 | 11 | 29 |

> 解释质量是结构化上报维度（`app/llm/explanation_quality.py`），不参与 classification 判定；`unclear` 表示该回合输入不足以判定。

## 复现

```bash
server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
```

真实模型运行需设置环境变量（凭证绝不出现在仓库中）；结果 JSON 落盘在
`TRAINER_MATURITY_WORKSPACE`（默认 `tmp/maturity-ws/`，不入库）。

---

## 归档

| 日期 | 文件 | 说明 |
| --- | --- | --- |
| 2026-10-13 | [`2026-10-13-teaching-journeys-report.md`](2026-10-13-teaching-journeys-report.md) | 28 代码案例双回合，`{'passed': 55, 'local_fallback': 1}`（真实模型，历史） |
| 2026-10-17 | [`2026-10-17-literature-journeys-report.md`](2026-10-17-literature-journeys-report.md) | 4 个文学案例的本地夹具事实（无凭证，0 个真实模型回合） |
| 2026-10-19 | [`2026-10-19-teaching-journeys-report.md`](2026-10-19-teaching-journeys-report.md) | 32 案例 / 64 回合全矩阵，`{'passed': 64}`（真实模型） |
| 2026-10-19 | [`2026-10-19-teaching-journeys-report-subset-02-A4-E2-E3-G2-5.md`](2026-10-19-teaching-journeys-report-subset-02-A4-E2-E3-G2-5.md) | 5 案例子集冒烟，10/10 passed |
| 2026-10-19 | [`2026-10-19-teaching-journeys-report-subset-03-C2-C3-D1-4.md`](2026-10-19-teaching-journeys-report-subset-03-C2-C3-D1-4.md) | 4 案例子集冒烟，8/8 passed |
| 2026-10-19 | [`2026-10-19-teaching-journeys-report-subset-03-E4-2.md`](2026-10-19-teaching-journeys-report-subset-03-E4-2.md) | 2 案例子集冒烟，4/4 passed |
| 2026-10-19 | [`2026-10-19-teaching-journeys-report-subset-E4-1.md`](2026-10-19-teaching-journeys-report-subset-E4-1.md) | 1 案例子集冒烟，2/2 passed |
