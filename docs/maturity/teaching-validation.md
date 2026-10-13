# 真实教学质量验收（28 组双回合教学旅程）

- 日期：2026-10-13；舞台：成熟化第 3 阶段（真实教学质量验收）
- 脚本：`scripts/maturity/real_teaching_journeys_minimax.py`（第 3 轮收敛版：含 `TRAINER_MATURITY_CASE_IDS` 冒烟过滤与分类/对账修正；该版本随第 3 轮检查点入库，早期 3c548f3 不含上述修正）
- 矩阵规格：`docs/maturity/teaching-case-matrix.md`；设计契约：`docs/maturity/DESIGN.md` §2/§5

## 0. 结论（诚实声明）

- **本轮未执行任何真实模型调用**：凭证不可用或不合规（详见 §2），28 案例 × 2 回合 = 56 个回合全部标记 `skipped_no_credentials`。
- 夹具骨架为**本地真实执行**：28/28 案例通过（pre-fix exit≠0 且 post-fix exit=0）。
- 本报告不构成、也不得被引用为「真实模型通过」；下方 §5 列明全部未验证事项。

## 1. 脚本完整性核对（存在性与结构，实际执行）

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 脚本存在 | 是 | `ls scripts/maturity/` → `real_teaching_journeys_minimax.py`（旧 hyphenated 脚本已删除） |
| 案例数量 | 28 | 加载模块：`len(CASES)==28` |
| 类别覆盖 | 7 类 × 4 组 | `Counter` → `{A:4,B:4,C:4,D:4,E:4,F:4,G:4}` |
| 双回合 | 全部案例有 turn1/turn2 | 字段完整性检查：`incomplete cases: none` |
| 客观判据 | M1/M2/M5 为硬门；M3 部分为记录信号 | `check_case_fixture`（exit 骨架 = M1 一部分）；`run_real_journeys` 每回合显式 body/disk 一致性校验（M1）；`classify_and_check_turn`：M2（grounded/corrected 且无 requires_confirmation；downgraded 永不 pass）+ M5 同源对账（历史/学习者消息/workspace 根文件核验器；corrected 复评修正文本）；M3 的 topic token 仅记录不设为门；M4 经本地复算的索取/锚定规则在 M5 中对账 |
| 分类枚举 | passed/failed/provider_error/local_fallback/skipped_no_credentials（本 harness 无 mock 通路，不再声明 mock） | `TURN_CLASSIFICATIONS` |
| 降级不判 pass | 已锁 + 回归测试 | `classify_and_check_turn`：downgraded → `grounding_pass=False`；`server/tests/test_maturity_harness_classification.py::test_downgraded_server_turn_is_never_passed` |
| 索取判定收窄 | 已修 + 回归测试 | 「运行 X，把输出贴回来」不再误判（`test_turn_grounding.py::test_run_and_paste_output_is_not_a_demand`） |
| 凭证仅环境变量 | 是 | `require_env`（不读取 argv/文件） |
| 冒烟子集 | 支持 | `TRAINER_MATURITY_CASE_IDS` 实测：`01-mutable-default,A4-dict-mutation` → `[filter] 2/28`、夹具 2/2；未知 id → RuntimeError 并列出全部已知 id |
| 仅 HTTPS/loopback | 是（实测守卫） | provider：非 loopback http → RuntimeError 拒绝；https/loopback http → 接受。sidecar：非 loopback → https 强制；显式明文远端 URL → RuntimeError 拒绝 |

## 2. 凭证可用性核查（仅存在性检查，不输出任何值）

| 来源 | 存在性 | 合规性 | 结论 |
| --- | --- | --- | --- |
| 环境变量 `TRAINER_MATURITY_API_KEY` / `TRAINER_MATURITY_PROVIDER_BASE_URL` / `MINIMAX_API_KEY` / `TRAINER_LIVE_PROTOCOL_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` | 全部 unset | — | 不可用 |
| 本地未跟踪配置 `.trainer/provider-test.json` | 存在（含非空 api_key 与 base_url 字段） | base_url 为**非 loopback 明文 http** | **拒绝使用**：安全红线「凭证不得经明文 HTTP 传输；若中转站不支持 TLS 则停止向其发送凭证」；harness 的 `secure_provider_base_url()` 同样会拒绝 |

**结论：当前环境没有可用且合规的凭证来源 → 走诚实 skipped 路径，未向任何 provider 发送凭证或请求。**

## 3. 本次运行记录

```bash
TRAINER_MATURITY_WORKSPACE=out/maturity/teaching-journeys-run \
  server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
```

- 输出摘要：`夹具：28/28 通过；回合分类：{'skipped_no_credentials': 56}`
- 原始明细 JSON：`out/maturity/teaching-journeys-run/report.json`（`out/` 已被 .gitignore:9 忽略，不入库）
- 逐案例夹具明细：`out/maturity/teaching-journeys-run/fixtures/`（不入库）
- 摘要报告：`docs/maturity/2026-10-13-teaching-journeys-report.md`（同内容，由 harness 生成）
- 冒烟通路核对（同模式）：`TRAINER_MATURITY_CASE_IDS=01-mutable-default,A4-dict-mutation` → 2/2 夹具通过、4 回合 `skipped_no_credentials`；随后已复跑全量恢复完整报告

## 4. 逐案例记录（28 组）

| # | 案例 | 类别 | 夹具 pre/post exit | 第1回合 | 第2回合 |
| --- | --- | --- | --- | --- | --- |
| 1 | 01-mutable-default | A 真实代码错误 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 2 | 02-late-binding | A 真实代码错误 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 3 | 03-nested-alias | A 真实代码错误 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 4 | A4-dict-mutation | A 真实代码错误 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 5 | 04-binary-search-boundary | B 复杂调试 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 6 | B2-import-env-stale | B 复杂调试 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 7 | B3-async-ordering | B 复杂调试 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 8 | B4-sqlite-null | B 复杂调试 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 9 | C1-shared-default-object | C 跨语言迁移 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 10 | C2-falsy-vs-null | C 跨语言迁移 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 11 | C3-var-capture | C 跨语言迁移 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 12 | C4-resource-cleanup | C 跨语言迁移 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 13 | D1-default-eval-time | D 原理教学 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 14 | D2-closure-experiment | D 原理教学 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 15 | D3-copy-semantics | D 原理教学 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 16 | D4-hash-contract | D 原理教学 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 17 | E1-argparse-entry | E 项目适应 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 18 | E2-async-call-site | E 项目适应 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 19 | E3-unit-test-contract | E 项目适应 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 20 | E4-package-layout | E 项目适应 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 21 | F1-semaphore-limit | F 进阶用户 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 22 | F2-this-binding | F 进阶用户 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 23 | F3-quadratic-scan | F 进阶用户 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 24 | F4-injectable-clock | F 进阶用户 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 25 | G1-cross-session-topic | G 长期恢复 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 26 | G2-review-interval | G 长期恢复 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 27 | G3-provider-recovery | G 长期恢复 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |
| 28 | G4-return-after-days | G 长期恢复 | 1 / 0 | skipped_no_credentials | skipped_no_credentials |

> 分类字段说明：`passed`=M1（HTTP+body/disk）+M2 教学接地通过（grounded/corrected 且无 requires_confirmation）+M5 同源对账一致且无记忆漂移；
> `failed`=任一客观判据失败（含 downgraded）；`provider_error`=请求失败；`local_fallback`=本地兜底（fell_back）；`skipped_no_credentials`=无凭证未执行；本 harness 无 mock 通路。
> 本轮所有回合为 `skipped_no_credentials`；模型输出要点 / 对账结论均**不存在**（没有发生调用），不做任何补写。

## 5. 未验证事项（unverifiedReasons）

1. **真实模型教学质量未验证**：28 案例的事实准确、难度适配、下一步一致性、解释与实验一致性均未采样（无合规凭证）。
2. **M5 服务端对账未实测**：`grounding_outcome` / 未锚定符号集 / `corrected_next_step` 复评的服务端 vs 本地比对未在真实回合上执行。
3. **requires_confirmation 端到端未点亮**：降级信号的前端渲染（R1 frontend 项）未在真实降级回合上观察。
4. **`provider_error` / `local_fallback` 分类未实测**：仅实现与夹具验证，未在真实故障回合上产生样本。
5. **内容质量独立评审栏未填写**（需真实回复文本，标注「待 owner 确认」）。
6. **长期恢复类（G1–G4）的跨会话/复习/恢复语义未在真实记忆上验证**（夹具只覆盖代码骨架与回合分类路径）。

## 6. 复现说明（得到合规凭证后）

1. 设置环境变量（env-only，不入库）：`TRAINER_MATURITY_API_KEY`、`TRAINER_MATURITY_PROVIDER_BASE_URL`（必须 `https://`；仅 127.0.0.1/localhost 允许 http）、可选 `TRAINER_MATURITY_MODEL`（默认 MiniMax-M2.7）。
2. 先冒烟 1~2 例确认通路：`TRAINER_MATURITY_CASE_IDS=01-mutable-default,A4-dict-mutation`（已实测可用）；通路确认后再跑全量。
3. 全量：`TRAINER_MATURITY_WORKSPACE=out/maturity/teaching-journeys-run server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py`（单并发、回合间隔 12s，预计 30–45 分钟）。
4. 结果：逐回合分类与 M5 对账写入 `out/maturity/.../report.json`；把结论与本文件对照更新（模型输出/Provider 失败/本地兜底严格区分）。

> 备注：无合规凭证时脚本始终走 skipped 路径并如实标注；夹具骨架每次运行都在本地真实执行（不依赖任何凭证）。
