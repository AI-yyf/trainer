# Trainer V4 验收矩阵（2026-11-08）

> 目的：把第十五节的 20 条真实旅程逐条映射到 7 类证据，明确 PASS / PARTIAL / GAP。
> 本文件只记录可复核证据；没有执行过的真实模型/GUI 旅程不因单元测试通过而标 PASS。

## 0. 证据等级

| 代码 | 等级 | 代表证据 |
| --- | --- | --- |
| U | 纯单元 / 行为测试 | `server/tests/`、`extension/tests/`、`shared` 行为测试 |
| S | 真实 Sidecar | 真实进程 `run_sidecar.py`，非 TestClient；`scripts/run-real-sidecar-experience-matrix.mjs`、`scripts/trainer-turn-smoke.mjs` |
| P | 真实 Provider | 真实公网模型；`docs/maturity/2026-11-06-p4-real-provider.md`、`docs/verification/remote-ssh-l2-141s-evidence.md` |
| V | 已安装 VSIX | v1.4.1 三平台资产 + 141s Linux 安装；`docs/verification/release-reconciliation-v1.4.1.md` |
| G | 真实 VS Code GUI | 真实 Electron/VS Code 窗口；`docs/verification/2026-11-07-*-screen-audit.md`、`scripts/run-real-vscode-gui.mjs` |
| R | Remote-SSH | 141s 真实远程窗口六步；`docs/verification/remote-ssh-l2-141s-evidence.md` |
| L | 长期时间模拟 / 持久化 | FSRS 时间推进、重启恢复、多会话 SQLite 持久化测试 |

图例：✅ PASS；🟡 PARTIAL（有部分真实或仅结构证据）；⬜ GAP / NOT_EXECUTED；— 不适用。

## 1. 20 条旅程矩阵

| # | 旅程 | U | S | P | V | G | R | L | 主要证据 / 缺口 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 第一次安装 Trainer，自然开始交流 | ✅ | ✅ | 🟡 | ✅ | 🟡 | ✅ | — | U: first-run/e2e；S: experience matrix；V: v1.4.1 安装；R: 141s 安装；P/G：真实模型首条自然交流未单独归档 |
| 2 | 随口提问，不产生不必要长期目标 | ✅ | 🟡 | 🟡 | ⬜ | 🟡 | ⬜ | — | U: `test_goal_session` 识别边界 + `sendIntelligence`；P：真实闲聊未做 Goal 断言 |
| 3 | 明确能力目标，Goal 自动建立并持续追踪 | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | 🟡 | U: 17 项 Goal 行为测试；S: API/持久化；P/G：真实对话自动建 Goal 未执行 |
| 4 | 多次会话继续同一任务，不复述背景 | ✅ | ✅ | ✅ | 🟡 | 🟡 | 🟡 | ✅ | U: recovery；S/P: P4 11 步旅程；R: L2 第 4 步；G：跨会话真实窗口未单独归档 |
| 5 | 表达教学偏好，后续自动适配 | ✅ | 🟡 | ⬜ | ⬜ | 🟡 | ⬜ | 🟡 | U: memory/settings；G: Settings 四屏审计；P：真实偏好适配未验证 |
| 6 | 改变偏好，系统修正旧习惯 | ✅ | 🟡 | ⬜ | ⬜ | 🟡 | ⬜ | 🟡 | U: preference overwrite；P/G：跨轮真实修正未验证 |
| 7 | 提示帮助下完成，不误判独立掌握 | ✅ | 🟡 | 🟡 | ⬜ | ⬜ | ⬜ | — | U: false-mastery 闸门 + skill projection；P：真实受助任务未做掌握断言 |
| 8 | 独立完成，真实证据自动同步 Learning | ✅ | ✅ | 🟡 | ⬜ | 🟡 | ⬜ | ✅ | U: attempt/evidence/skill projection；S: sidecar matrix；G/P：真实独立完成→Learning 未归档 |
| 9 | 数天后忘记，自然安排复习 | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | ✅ | U/L: FSRS due/AGAIN/时间推进；P/G：真实数天遗忘旅程未执行 |
| 10 | 正确延迟回忆，间隔延长 | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | ✅ | U/L: FSRS GOOD/EASY 间隔；真实延迟回忆未执行 |
| 11 | 拒绝复习或忙碌，不被打扰 | ✅ | 🟡 | ⬜ | ⬜ | 🟡 | ⬜ | — | U: review queue governance；G：preview；P：真实打断/拒绝未验证 |
| 12 | 长期未上线返回，不积压提醒 | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | 🟡 | U: 上限/静默/去重；L：时间模拟部分；真实长离线未执行 |
| 13 | 跨项目同概念复用但不泄漏代码 | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | ✅ | U: Skill workspace 7 项隔离 + memory share scope；P/G：真实双项目未验证 |
| 14 | 切换模型和重启 VS Code，状态恢复 | ✅ | ✅ | ✅ | 🟡 | 🟡 | 🟡 | ✅ | U/S/P: recovery + P4 模型热切换；R: L2 重启/恢复；G：真实重启未单独归档 |
| 15 | 资料版本变化，旧引用/知识关系更新 | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | ✅ | U: resource version + evidence invalidation；P/G：真实资料变更未验证 |
| 16 | Skill 自动选择/执行/记录/失败隔离 | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ✅ | U: lifecycle/runtime/workspace；P: P4 `applied=true,basis=contract_markers`；G：真实 Skill UI 未归档 |
| 17 | Provider 超时/中断，不制造虚假结果 | ✅ | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | — | U: recovery/stream idle timeout；P：真实超时无法在健康网关强制，保持部分 |
| 18 | 多窗口并发，不重复推进计划/复习 | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | 🟡 | U: plan revision、singleflight、SQLite 写锁；真实双窗口未执行 |
| 19 | 修改/撤销记忆，教学行为同步变化 | ✅ | 🟡 | ⬜ | ⬜ | 🟡 | ⬜ | ✅ | U: memory update/clear；G: Settings 记忆面板；P：真实撤销后教学变化未验证 |
| 20 | 连续多个项目/主题，仍理解当前重点 | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | 🟡 | 🟡 | U: workspace 隔离/恢复；R：L2 项目切换；真实多项目长跑未执行 |

## 2. 汇总

| 等级 | PASS | PARTIAL | GAP |
| --- | --- | --- | --- |
| U 单元/行为 | 20 | 0 | 0 |
| S 真实 Sidecar | 6 | 14 | 0 |
| P 真实 Provider | 3 | 5 | 12 |
| V 已安装 VSIX | 1 | 2 | 17 |
| G 真实 GUI | 0 | 9 | 11 |
| R Remote-SSH | 1 | 3 | 16 |
| L 长期/持久化 | 9 | 6 | 0（5 项不适用） |

> G 列全部为 PARTIAL 或 GAP：已有 Settings 四屏真实审计与 L2 窗口，但没有把 20 条旅程逐条在真实 GUI 中归档。
> P 列只有 P4 旅程/L2 第 4 步等少数真实模型证据；不得把 3930 个单元测试当作真实模型验收。

## 3. 缺口优先级

| 优先级 | 缺口 | 下一步 |
| --- | --- | --- |
| P0 | 旅程 3/5/6/9/10/11/12 的真实 Provider/GUI 闭环 | 真实模型下逐条录制对话 + Learning/Review 结果；provider 额度恢复后补 |
| P0 | 旅程 15/18/19/20 的真实版本变化、双窗口、记忆撤销、多项目长跑 | 真实 VS Code GUI + 双窗口 + 资料变更脚本 |
| P1 | 20 条旅程尚未形成逐条截图/日志归档 | 用本矩阵作为清单，逐条补 `docs/verification/v4-journey-*` |
| P1 | App/Provider/Memory 巨型模块拆分 | 先锁定行为测试，再按单一职责迁移 |
| P2 | SCIP 索引解析 | 从占位改为可解析 JSON/CLI 导出 |
| P2 | 按需多模态（扫描 PDF/图表） | 资源 ingest + vision probe 扩展 |

## 4. 已有真实证据索引

- P4 真实 Provider：`docs/maturity/2026-11-06-p4-real-provider.md`（5 PASS + 1 NOT_EXECUTED）。
- Remote-SSH L2：`docs/verification/remote-ssh-l2-141s-evidence.md`（2026-11-08 六步 6/6 PASS）。
- 四屏真实 GUI：`docs/verification/2026-11-07-{coach,learning,resources,settings}-screen-audit.md`。
- Release/VSIX：`docs/verification/release-reconciliation-v1.4.1.md` + CI Cross-Platform 9/9。
- 行为测试：server 3930 passed（含 FSRS/Goal/Evidence/Skill workspace）；extension suite 0 失败；Settings e2e 8 passed。
- 长期时间/持久化：`test_live_training_fsrs_on_verify.py`、`test_review_scheduler_fsrs.py`、session/plan revision 回归。

## 5. 诚实声明

- 本矩阵是验收**清单**，不是完成证明。
- 标 ✅ 的单元/行为证据只证明对应逻辑；标 🟡 的真实证据只覆盖该次录制范围；标 ⬜ 的条目没有执行记录。
- 任何后续 PASS 必须补对应证据文件/命令输出，不能只改本表。
