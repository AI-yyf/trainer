# 验收事实摘要（ACCEPTANCE FACTS）

> **自动生成风格的事实清单**：数值只来自验收产物，不由人工改写；产物里没有的字段显式写「未记录」，不猜。
> 本文件是模板：字段与填写规则固定，新一次验收后按同样字段刷新数值。
> 事实来源：`tmp/maturity-ws/report.json`（raw 产物，未入库）与最新报告 [`teaching-journeys-report.md`](teaching-journeys-report.md)（canonical，入库）。
> 两处数值必须一致；不一致时以 raw 产物为准并修复 canonical 报告。
>
> **2026-10-19 刷新**：本文件此前停留在 28 案例 / 56 回合的 55+1 快照。当前 raw 产物已经是
> **32 案例 / 64 回合、64 passed**；下表的分类计数从该产物逐回合重新统计，旧数值不再保留。

## 1. 运行标识

| 字段 | 值 | 来源 |
| --- | --- | --- |
| 验收类型 | 真实模型教学旅程验收（32 案例双回合 = 64 回合；含 4 个文学案例；非门控解释质量维度同场采集） | `report.json` `mode=real`、`cases` |
| harness | `scripts/maturity/real_teaching_journeys_minimax.py` | 报告头 / 脚本 |
| 矩阵规格 | `docs/maturity/teaching-case-matrix.md` §0 红线、§2（M1–M5） | 规格文件 |
| 原始产物 | `tmp/maturity-ws/report.json`（未入库） | 文件存在 |
| 提交 SHA | **未记录在产物内**（`report.json` 早于 harness 元数据插桩，无 SHA 字段）。记录该次运行的提交为 `38969f5`（commit message 明示 32 案例 / 64 回合 → 64 passed）；核对时仓库 HEAD 为 `7e440de614a5224c4d75ac7153c394a2ea1d4f84` | `git log` / `report.json` |
| 运行时间 | **未记录在产物内**（无时间戳字段）。近似：`tmp/maturity-ws/report.json` 落盘 2026-10-19 05:43 +0800；记录提交时间 05:44 +0800 | 文件 mtime |
| 模型 | **未记录**（`report.json` 未落盘实际取值）。harness 默认值为 `MiniMax-M2.7`；若运行时设置过 `TRAINER_MATURITY_MODEL` 则以环境变量为准，本文件不代猜 | 脚本默认值；产物无字段 |
| 运行模式 | `real`（本 harness 无 mock 通路） | `report.json` |
| 时长/节奏 | 时长**未记录**；默认单并发、回合间隔 12s（32×2=64 回合，仅间隔约 12.6 分钟，不含模型耗时） | `teaching-case-matrix.md` §4；脚本默认值 |
| 元数据插桩 | 自本次刷新起，新运行的 `report.json` 增加 `run` 字段：`git_commit` / `git_dirty` / `model` / `provider_host` / `platform` / `machine` / `python` / `started_at` / `finished_at` / `case_count` / `turn_count` / `classification_counts` / `fixture_ok`。2026-10-19 产物不含该字段，不得事后补写 | `scripts/maturity/real_teaching_journeys_minimax.py` |

## 2. 案例与回合分类

| 字段 | 值 | 来源 |
| --- | --- | --- |
| 案例数 | 32（28 代码 A–G×4 + 4 文学 L） | `report.json` `cases` |
| 回合数 | 64（每案例 2 回合） | `report.json` 逐案例 `turns` |
| 夹具校验 | 32/32 通过（pre-fix exit≠0 ×32；post-fix exit=0 ×32） | `report.json` 逐案例 `fixture` |
| `passed`（通过） | 64 | 逐回合分类计数 |
| `failed`（失败） | 0 | 逐回合分类计数 |
| `local_fallback`（诚实回退） | 0 | 逐回合分类计数 |
| `provider_error` | 0 | 逐回合分类计数 |
| `skipped_no_credentials` | 0 | 逐回合分类计数 |

**结论行（与 canonical 报告一致）：64 通过 / 64 回合；0 failed / 0 local_fallback / 0 provider_error。**

## 3. 解释质量（非门控观察维度）

| 字段 | 值 |
| --- | --- |
| 已评估回合 | 64 |
| `solution_dump_suspected` 回合 | 3 / 64 |

| 维度 | ok | weak | unclear |
| --- | --- | --- | --- |
| addresses_learner | 56 | 8 | 0 |
| language_alignment | 57 | 6 | 1 |
| anchored_symbols | 0 | 9 | 55 |
| no_solution_dump | 53 | 3 | 8 |
| explains_reasoning | 24 | 11 | 29 |

> `unclear` = 输入不足以判定（诚实缺省，不猜）；解释质量不参与教学 pass/fail 判定（`app/llm/explanation_quality.py` 为非门控上报层）。

## 4. 平台状态

| 字段 | 值 | 来源 |
| --- | --- | --- |
| 运行载体 | 本地 sidecar（uvicorn `http://127.0.0.1:34900`，loopback；凭证 env-only、非明文外发） | `tmp/maturity-ws/maturity_sidecar.log` |
| 运行平台（OS/架构） | **未记录在产物内**（`report.json` 无平台字段）。刷新核对环境：darwin-arm64 | 系统环境 |
| 三平台发布验收（win32 / darwin / linux） | **不在本文件范围**——本摘要只覆盖教学旅程真实模型验收；发布/打包验收由 `npm run verify` 矩阵负责 | 分工说明 |

## 5. 生成与刷新（机械步骤）

```bash
# 1) 跑验收（需 env-only 凭证；产物落在 TRAINER_MATURITY_WORKSPACE，默认 tmp/maturity-ws/）
#    完整真实运行会同时刷新 canonical 报告与当天归档；冒烟子集只写自己的 dated 文件。
server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py

# 2) 从 raw 产物取分类计数（本文件 §2）
python3 - <<'PY'
import collections, json
d = json.load(open('tmp/maturity-ws/report.json'))
print(collections.Counter(t['classification'] for c in d['cases'] for t in c['turns']))
print(d['explanation_quality_summary'])
print(d.get('run', 'run metadata not recorded'))
PY

# 3) 确认 canonical 报告与 raw 产物数值一致；缺字段保持「未记录」
```

## 6. 诚实声明

- 分类逐回合记录；`local_fallback` / `provider_error` 回合不计入模型教学质量。
- 本文件不是「通过证明」；任何通过结论以 `report.json` 逐回合分类 + canonical 报告为准。
- 2026-10-19 产物早于元数据插桩，SHA / 时间 / 模型 / 平台字段保持「未记录」，不得事后补写；记录提交仅用于定位。
- 历史 28 案例 55/1 快照已恢复到 [`2026-10-13-teaching-journeys-report.md`](2026-10-13-teaching-journeys-report.md)，不再被后续运行覆盖。
