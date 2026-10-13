# 教学旅程 28 案例报告（2026-10-13）

- harness：`scripts/maturity/real_teaching_journeys_minimax.py`（28 组双回合，7 类 × 4）
- 矩阵规格：`docs/maturity/teaching-case-matrix.md`；台账与对账规则见该文件 §2（M1–M5）
- 运行模式：`skipped_no_credentials`
- 夹具校验（本地执行，无模型）：28/28 通过（pre-fix exit≠0 且 post-fix exit=0）
- 回合分类统计：{'skipped_no_credentials': 56}

## 诚实声明

本环境未设置 `TRAINER_MATURITY_API_KEY` / `TRAINER_MATURITY_PROVIDER_BASE_URL`，
**56 个模型回合全部标记 `skipped_no_credentials`：未向任何 provider 发起调用，
本报告不构成、也不得被引用为「真实模型通过」**。夹具骨架为本地真实执行。

> 分类字段说明：`passed`=M1 脊柱（HTTP + body/disk 校验）+M2 教学接地通过（grounded/corrected 且无 requires_confirmation）
> +M5 同源对账一致且无记忆漂移；`failed`=任一客观判据失败（含 downgraded，降级回合永不算 pass）；
> `provider_error`=请求失败；`local_fallback`=本地兜底（fell_back）；`skipped_no_credentials`=无凭证未执行。本 harness 无 mock 通路。

## 逐案例

| 案例 | 类别 | 夹具 pre/post exit | 回合分类 | 对账 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 01-mutable-default | A | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| 02-late-binding | A | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| 03-nested-alias | A | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| A4-dict-mutation | A | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| 04-binary-search-boundary | B | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| B2-import-env-stale | B | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| B3-async-ordering | B | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| B4-sqlite-null | B | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| C1-shared-default-object | C | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| C2-falsy-vs-null | C | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| C3-var-capture | C | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| C4-resource-cleanup | C | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| D1-default-eval-time | D | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| D2-closure-experiment | D | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| D3-copy-semantics | D | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| D4-hash-contract | D | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| E1-argparse-entry | E | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| E2-async-call-site | E | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| E3-unit-test-contract | E | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| E4-package-layout | E | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| F1-semaphore-limit | F | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| F2-this-binding | F | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| F3-quadratic-scan | F | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| F4-injectable-clock | F | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| G1-cross-session-topic | G | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| G2-review-interval | G | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| G3-provider-recovery | G | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |
| G4-return-after-days | G | 1 / 0 | skipped_no_credentials / skipped_no_credentials | - / - |  |

## 复现

```bash
server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
```

真实模型运行需设置环境变量（凭证绝不出现在仓库中）；结果 JSON 落盘在
`TRAINER_MATURITY_WORKSPACE`（默认 `tmp/maturity-ws/`，不入库）。
