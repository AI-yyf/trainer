# 验收事实摘要（ACCEPTANCE FACTS）

> **自动生成风格的事实清单**：数值只来自验收产物，不由人工改写；产物里没有的字段显式写「未记录」，不猜。
> 本文件是模板：字段与填写规则固定，新一次验收后按同样字段刷新数值。
> 事实来源：`tmp/maturity-ws/report.json`（raw 产物，未入库）与最新报告 [`teaching-journeys-report.md`](teaching-journeys-report.md)（canonical，入库）。
> 两处数值必须一致；不一致时以 raw 产物为准并修复 canonical 报告。

## 1. 运行标识

| 字段 | 值 | 来源 |
| --- | --- | --- |
| 验收类型 | 真实模型教学旅程验收（28 案例双回合；非门控解释质量维度同场采集） | `report.json` `mode=real` |
| harness | `scripts/maturity/real_teaching_journeys_minimax.py` | 报告头 / 脚本 |
| 矩阵规格 | `docs/maturity/teaching-case-matrix.md` §0 红线、§2（M1–M5） | 规格文件 |
| 提交 SHA | **未记录**（`report.json` 无 SHA 字段）。盘点时仓库 HEAD：`76a73758dd04da9975f22c629abcc05b42903483`（2026-10-14 17:03 +0800，仅用于定位，不等于运行时刻版本） | `git rev-parse HEAD` |
| 运行时间 | **未记录**（产物内无时间戳）。近似：`tmp/maturity-ws/report.json` 落盘 2026-10-14 08:35:11 +0800；报告标题日 2026-10-13 | 文件 mtime |
| 模型 | `MiniMax-M2.7`（harness 默认值；`report.json` 未落盘实际取值——若运行时设置过 `TRAINER_MATURITY_MODEL` 则以环境变量为准，本文件不代猜） | `scripts/maturity/real_teaching_journeys_minimax.py:36,1391` |
| 运行模式 | `real`（本 harness 无 mock 通路） | `report.json` |
| 时长/节奏 | 单并发、回合间隔 12s；28×2=56 回合，计划 30–45 分钟 | `teaching-case-matrix.md` §4 |

## 2. 案例与回合分类

| 字段 | 值 | 来源 |
| --- | --- | --- |
| 案例数 | 28（7 类 × 4：A 真实代码错误 / B 复杂调试 / C 跨语言迁移 / D 原理教学 / E 项目适应 / F 进阶用户 / G 长期恢复） | `report.json` `cases` |
| 回合数 | 56（每案例 2 回合） | `report.json` 逐案例 `turns` |
| 夹具校验 | 28/28 通过（pre-fix exit≠0 ×28；post-fix exit=0 ×28） | `report.json` 逐案例 `fixture` |
| `passed`（通过） | 55 | 逐回合分类计数 |
| `local_fallback`（诚实回退） | 1（D4-hash-contract 第 2 回合；不计入模型教学质量） | 逐回合分类 |
| `failed`（失败） | 0 | 逐回合分类计数 |
| `provider_error` | 0 | 逐回合分类计数 |
| `skipped_no_credentials` | 0 | 逐回合分类计数 |

**结论行（与 canonical 报告一致）：55 通过 / 1 次诚实回退（另有 56/56 轮次）。**

## 3. 解释质量（非门控观察维度）

| 字段 | 值 |
| --- | --- |
| 已评估回合 | 55（`provider_error` / `local_fallback` / `skipped_no_credentials` 回合不产出解释质量） |
| `solution_dump_suspected` 回合 | 5 / 55 |

| 维度 | ok | weak | unclear |
| --- | --- | --- | --- |
| addresses_learner | 51 | 4 | 0 |
| language_alignment | 48 | 6 | 1 |
| anchored_symbols | 1 | 17 | 37 |
| no_solution_dump | 42 | 5 | 8 |
| explains_reasoning | 20 | 18 | 17 |

> `unclear` = 输入不足以判定（诚实缺省，不猜）；解释质量不参与教学 pass/fail 判定（`app/llm/explanation_quality.py` 为非门控上报层）。

## 4. 平台状态

| 字段 | 值 | 来源 |
| --- | --- | --- |
| 运行载体 | 本地 sidecar（uvicorn `http://127.0.0.1:34900`，loopback；凭证 env-only、非明文外发） | `tmp/maturity-ws/maturity_sidecar.log:5` |
| 运行平台（OS/架构） | **未记录**（`report.json` 无平台字段）。盘点环境：darwin-arm64 / macOS 25.4.0 | 系统环境 |
| 三平台发布验收（win32 / darwin / linux） | **不在本文件范围**——本摘要只覆盖教学旅程真实模型验收；发布/打包验收由 `npm run verify` 矩阵负责 | 分工说明 |

## 5. 生成与刷新（机械步骤）

```bash
# 1) 跑验收（需 env-only 凭证；产物落在 TRAINER_MATURITY_WORKSPACE，默认 tmp/maturity-ws/）
server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py

# 2) 从 raw 产物取分类计数（本文件 §2）
python3 - <<'PY'
import json, collections
d = json.load(open('tmp/maturity-ws/report.json'))
print(collections.Counter(t['classification'] for c in d['cases'] for t in c['turns']))
print(d['explanation_quality_summary'])
PY

# 3) 把本文件数值与 docs/maturity/teaching-journeys-report.md 同步刷新；缺字段保持「未记录」
```

## 6. 诚实声明

- 分类逐回合记录；`local_fallback` 回合不计入模型教学质量（`teaching-case-matrix.md` §0 红线 3）。
- 本文件不是「通过证明」；任何通过结论以 `report.json` 逐回合分类 + canonical 报告为准。
- 未记录的字段（SHA / 时间 / 模型实际取值 / 运行平台）在产物中不存在，保持「未记录」，不得补猜。
