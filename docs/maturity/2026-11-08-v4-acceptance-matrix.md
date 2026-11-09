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
| 1 | 第一次安装 Trainer，自然开始交流 | ✅ | ✅ | 🟡 | ✅ | ✅ | ✅ | — | U: first-run/e2e；S: experience matrix；V: v1.4.1 安装；R: 141s 安装；G: `docs/verification/v4-gui-20-journeys/`（真实窗口三目的地与输入框）；P：真实模型首条自然交流未单独归档 |
| 2 | 随口提问，不产生不必要长期目标 | ✅ | ✅ | ✅ | ⬜ | ✅ | ⬜ | — | U: `test_goal_session` + `sendIntelligence`；S/P：`docs/verification/v4-journey-2-3-goal-real.md`；G：真实窗口发送随口问题后无 Goal 条 |
| 3 | 明确能力目标，Goal 自动建立并持续追踪 | ✅ | ✅ | ✅ | ⬜ | ✅ | ⬜ | 🟡 | U: 18 项 Goal 行为测试；S/P：真实对话自动建 Goal + 重启同 id + 续接；G：真实窗口自动出现 Goal 条，Reload Window 后仍恢复 |
| 4 | 多次会话继续同一任务，不复述背景 | ✅ | ✅ | ✅ | 🟡 | ✅ | 🟡 | ✅ | U: recovery；S/P: P4 11 步旅程；R: L2 第 4 步；G：真实窗口继续同一 Goal 并保留上下文 |
| 5 | 表达教学偏好，后续自动适配 | ✅ | 🟡 | ✅ | ⬜ | ✅ | ⬜ | 🟡 | U: memory/settings；G: 真实窗口写入偏好；P: hands-on / concept-first 同题回复不同 |
| 6 | 改变偏好，系统修正旧习惯 | ✅ | 🟡 | ✅ | ⬜ | ✅ | ⬜ | 🟡 | U: preference overwrite；G/P: 真实窗口改偏好后同题回复不同 |
| 7 | 提示帮助下完成，不误判独立掌握 | ✅ | 🟡 | 🟡 | ⬜ | ⬜ | ⬜ | — | U: false-mastery 闸门 + skill projection；P：真实受助任务未做掌握断言 |
| 8 | 独立完成，真实证据自动同步 Learning | ✅ | ✅ | 🟡 | ⬜ | 🟡 | ⬜ | ✅ | U: attempt/evidence/skill projection；S: sidecar matrix；G/P：真实独立完成→Learning 未归档 |
| 9 | 数天后忘记，自然安排复习 | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ✅ | U/L: FSRS due/AGAIN；S/P: day0→day3 due queue + 真实模型复习回合；G：真实 GUI 未录 |
| 10 | 正确延迟回忆，间隔延长 | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ✅ | U/L: FSRS GOOD/EASY；S/P: guided-pack 卡 + Day0→Day2 时钟，第二次 Good interval 2 天，真实模型延迟回忆 200 |
| 11 | 拒绝复习或忙碌，不被打扰 | ✅ | ✅ | ✅ | ⬜ | ✅ | ⬜ | — | U/S/P: skip 真实延后；G: 真实窗口复习控制；忙碌回合不强行拉回 |
| 12 | 长期未上线返回，不积压提醒 | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | 🟡 | U/S/P: day30 due 无重复，真实模型给最小回顾问题 |
| 13 | 跨项目同概念复用但不泄漏代码 | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | ✅ | U: Skill workspace 7 项隔离 + memory share scope；P/G：真实双项目未验证 |
| 14 | 切换模型和重启 VS Code，状态恢复 | ✅ | ✅ | ✅ | 🟡 | ✅ | 🟡 | ✅ | U/S/P: recovery + P4 模型热切换；R: L2 重启/恢复；G：真实窗口切换 model、Reload Window 后 Settings 仍显示新 model |
| 15 | 资料版本变化，旧引用/知识关系更新 | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ✅ | U: resource version/invalidation；S: 旧 version 409；P: 真实模型先引 AlphaQueue，重索引后引 BetaQueue；G：真实 GUI 未验证 |
| 16 | Skill 自动选择/执行/记录/失败隔离 | ✅ | ✅ | ✅ | ⬜ | ✅ | ⬜ | ✅ | U: lifecycle/runtime/workspace；P: P4 `applied=true,basis=contract_markers`；G: 真实窗口技能目录可读 |
| 17 | Provider 超时/中断，不制造虚假结果 | ✅ | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | — | U: recovery/stream idle timeout；S: 真实 sidecar + hanging endpoint 返回诚实失败、不伪造答案；P：公网网关真实中断仍保持部分 |
| 18 | 多窗口并发，不重复推进计划/复习 | ✅ | ✅ | ✅ | ⬜ | ✅ | ⬜ | 🟡 | U: plan revision/singleflight；S/P: 两个并发客户端同一 expected_revision，一个 200 一个 409；G: 同一 VS Code 实例两个真实窗口（folder + `.code-workspace`）并发冻结同一 live 计划，revision 1→2 仅一次提交，两窗口均显示已暂停；`docs/verification/v4-gui-dual-window-journey/` |
| 19 | 修改/撤销记忆，教学行为同步变化 | ✅ | ✅ | ✅ | ⬜ | ✅ | ⬜ | ✅ | U/S: 真实 sidecar 覆盖/撤销；P: 清空 global memory 并切换 hands-on→concept-first 后同题回复不同；G: 真实窗口记忆开关 |
| 20 | 连续多个项目/主题，仍理解当前重点 | ✅ | 🟡 | ✅ | ⬜ | ⬜ | 🟡 | 🟡 | U: workspace 隔离/恢复；R：L2 项目切换；P: A=AlphaQueue，B=BetaQueue，无跨项目泄漏 |

## 2. 汇总

| 等级 | PASS | PARTIAL | GAP |
| --- | --- | --- | --- |
| U 单元/行为 | 20 | 0 | 0 |
| S 真实 Sidecar | 12 | 8 | 0 |
| P 真实 Provider | 15 | 4 | 1 |
| V 已安装 VSIX | 1 | 2 | 17 |
| G 真实 GUI | 11 | 1 | 8 |
| R Remote-SSH | 1 | 3 | 16 |
| L 长期/持久化 | 9 | 6 | 0（5 项不适用） |

> G 列已有 11 条 PASS：旅程 1/2/3/4/5/6/11/14/16/18/19 在真实 VS Code Electron + 当前 VSIX 中逐条断言。其余 GUI 证据为 PARTIAL/GAP：fixture provider 不能替代真实模型，训练卡、数天时钟、资料导入、跨项目仍未在 GUI 中闭环。
> P 列只有 P4 旅程/L2 第 4 步等少数真实模型证据；不得把 3930 个单元测试当作真实模型验收。

## 3. 缺口优先级

| 优先级 | 缺口 | 下一步 |
| --- | --- | --- |
| P0 | 旅程 3/5/6/9/10/11/12 的真实 Provider/GUI 闭环 | 5/6 已完成真实模型；9/10/11/12 仍缺真实 due queue/长离线；时钟 harness 见 `v4-clock-harness.md` |
| P0 | 旅程 15/19/20 的真实版本变化、记忆撤销、多项目长跑 | 18 已完成真实双窗口并发；15/19/20 仍需 GUI 级版本变更、记忆撤销、多项目长跑 |
| P1 | 20 条旅程尚未形成逐条截图/日志归档 | 用本矩阵作为清单，逐条补 `docs/verification/v4-journey-*`；GUI 20 旅程与 Remote-SSH 重连已归档 |
| P1 | App/Provider/Memory 巨型模块拆分 | Provider 已拆出 15 个 `llm/provider/*` 模块（约 3.8k 行）；Memory snapshot 已迁到 `memory/snapshot_builder.py`（989 行，service 减约 970 行）；App render 仍偏大 |
| P2 | SCIP 索引解析 | ✅ JSON + 二进制 protobuf（`.scip`）解析；`test_scip_adapter` 6 项行为测试 |
| P2 | 按需多模态（扫描 PDF/图表） | ✅ 扫描 PDF/图片本地 Tesseract OCR；图表走真实 provider vision（`v4-multimodal-journey.md`，Beta/70 PASS） |
| P0 | 三平台 VSIX / 安装矩阵 | ✅ 三平台 package + installed host E2E 9/9；`v4-release-matrix-2026-11-08.md` |

## 4. 已有真实证据索引

- P4 真实 Provider：`docs/maturity/2026-11-06-p4-real-provider.md`（5 PASS + 1 NOT_EXECUTED）。
- Remote-SSH L2：`docs/verification/remote-ssh-l2-141s-evidence.md`（2026-11-08 六步 6/6 PASS）。
- 四屏真实 GUI：`docs/verification/2026-11-07-{coach,learning,resources,settings}-screen-audit.md`。
- 20 旅程真实 GUI 脚本：`scripts/run-v4-gui-journeys.mjs`；报告 `docs/verification/v4-gui-20-journeys/`（11 PASS / 5 PARTIAL / 4 BLOCKED，fixture provider 仅作 GUI 证据）。
- 双窗口 GUI 旅程 18：`docs/verification/v4-gui-dual-window-journey/`（同一 VS Code 实例两个真实窗口共享 live 计划；并发冻结 revision 1→2，两窗口均显示已暂停）。
- 真实 Provider 目标旅程（2026-11-09 重跑）：`v4-provider-journeys.md`（5/6/15/19/20）、`v4-review-provider-journeys.md`（9/11/12）、`v4-fsrs-delayed-recall.md`（10），全部 PASS；`linksub.fun` / `deepseek-v4.1-flash`。
- 完整性旅程：`docs/verification/v4-integrity-journeys.md`（真实 sidecar；版本冲突 409、记忆撤销、provider 故障不伪造）。
- 性能门禁：`docs/verification/v4-perf-probe-2026-11-08.json`（streaming longtask 0 ≤ 0；warm nav p90 63ms < 100ms）。
- Remote-SSH 重连：`docs/verification/v4-remote-ssh-reconnect-2026-11-08.md`（CI Layer 1，11/11 steps，含 reconnect）。
- 三平台发布矩阵：`docs/verification/v4-release-matrix-2026-11-08.md`（commit 485e25e，9/9 jobs；三平台 VSIX + installed host E2E）。
- 真实 Provider 旅程：`docs/verification/v4-provider-journeys.md`（deepseek-v4.1-flash；5/6 PASS，15/19/20 PARTIAL，9/10/11/12/18 未执行）。
- 时钟 harness：`docs/verification/v4-clock-harness.md`（FSRS 数天跨度；另见 `v4-fsrs-delayed-recall.md`）。
- FSRS 延迟回忆：`docs/verification/v4-fsrs-delayed-recall.md`（Day0→Day2，interval 2 天，真实模型延迟回忆）。
- 多模态图表：`docs/verification/v4-multimodal-journey.md`（真实模型读取柱状图，Beta/70）。
- 复习 Provider 旅程：`docs/verification/v4-review-provider-journeys.md`（9/11/12 PASS；10 未执行）。
- 双客户端并发：`docs/verification/v4-dual-window-journey.md`（PASS：200 + 409，revision 只前进一次；不是双 GUI 窗口）。
- Release/VSIX：`docs/verification/release-reconciliation-v1.4.1.md` + CI Cross-Platform 9/9。
- 行为测试：server 3930 passed（含 FSRS/Goal/Evidence/Skill workspace）；extension suite 0 失败；Settings e2e 8 passed。
- 长期时间/持久化：`test_live_training_fsrs_on_verify.py`、`test_review_scheduler_fsrs.py`、session/plan revision 回归。

## 5. 诚实声明

- 本矩阵是验收**清单**，不是完成证明。
- 标 ✅ 的单元/行为证据只证明对应逻辑；标 🟡 的真实证据只覆盖该次录制范围；标 ⬜ 的条目没有执行记录。
- 任何后续 PASS 必须补对应证据文件/命令输出，不能只改本表。
