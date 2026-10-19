# P1 最终收敛验收记录（2026-10-20，macOS arm64 本地）

> 本文件只记录本次实际执行的命令、产物与结论。未执行的平台/设备门明确写
> **Not Executed**，不折算为 Passed。它不是发布声明，也不替代 owner 的发布授权。

## 0. 结论

- 本地 macOS arm64 候选通过：源码门、两套 200 场景矩阵、UI 几何、性能预算、
  原生 VSIX 打包/安装烟测，以及 **安装态 VSIX host E2E 35/35 步**。
- 真实模型基线仍是 2026-10-19 的 **32 案例 / 64 回合 = 64 passed** 产物（见
  [`docs/maturity/teaching-journeys-report.md`](../maturity/teaching-journeys-report.md)）。
- 本轮另用提供的 OpenAI 兼容中转（`https://linksub.fun`，`minimax-m3`）完成
  实连 provider smoke，并跑了 2 案例真实模型子集：3 passed / 1 provider_error
  （`ReadTimeout`，如实分类，无本地兜底伪装）。
- **不能宣告 “Trainer P1 Mature — Ready for Release”**：Windows x64 / Linux x64
  原生安装、真实 Remote SSH、真实浏览器扩展配对，以及 200% 字号/八语言视觉
  仍未执行；GitHub CI 与正式 Release 附件未在本环境验证。剩余阻断项见 §6。

## 1. 版本事实

| 字段 | 值 |
| --- | --- |
| Repository | `https://github.com/AI-yyf/trainer`（本地检出） |
| Baseline | `main` @ `7e440de614a5224c4d75ac7153c394a2ea1d4f84`（v1.3.4） |
| Work branch | `maturity/p1-final-convergence-2026-10-20`（未推送、未合并 `main`） |
| Source commit | `dc43797a13edb21a5946d29bd1022185d6be74c2` |
| Evidence commit | `ef66c85`（产物 provenance + 本记录数据文件；本文件随后单独提交） |
| Product version | `1.3.4`（`npm run verify:version`） |
| Working tree | clean（验收完成时） |
| Native artifact | `extension/trainer-extension-1.3.4-darwin-arm64.vsix` |
| Artifact bytes / SHA-256 | `124661094` / `563d7840cf9bd847ee1ae8be8b1d3ccb8f587e97bebb0deb12ff9e7a9a7f2c03` |
| Artifact provenance | `.vsix.build.json`: `sourceCommit=dc43797…`, `sourceDirty=false`, target `darwin-arm64` |
| CI | **Not Executed**（GitHub 网络不可达；本环境无法取得 run ID） |

## 2. 工程门（本地实际执行）

| Gate | 命令 | 结果 |
| --- | --- | --- |
| Consolidated verify | `npm run verify` | **pass**（exit 0） |
| Server suite | 包含在上项 | **3642 passed**, 28 subtests，0 failed（2m40s） |
| Extension suite | 包含在上项；另以 TAP 复核 | **2183 pass / 2184 tests / 0 fail**（1 skipped by suite） |
| TypeScript / CSS | 包含在上项 | pass（CSS sections balanced；webview + host `tsc --noEmit`） |
| Ruff / Pyright | 包含在上项 | pass；Pyright **0 errors / 0 warnings** |
| Version gate | `npm run verify:version` | pass（1.3.4） |
| Credential gate | `npm run verify:credentials` | pass（11,323 files scanned，0 findings） |
| UI geometry | `node scripts/verify-ui-geometry.mjs` | **471 / 471** |
| Preview experience matrix | `npm run test:experience-matrix` | **200 passed**（32.4s） |
| Real-sidecar experience matrix | `npm run test:experience-sidecar` | **200 passed**（17.8s） |
| Browser extension package | `npm run package:browser-extension` | pass：**20 files / 62,027 bytes**，含 8 个 `_locales` |
| Native VSIX package | `npm run package:vsix` | pass；见 §1 |
| Native install smoke | `TRAINER_SKIP_VSIX_REBUILD=1 node extension/scripts/verify-vsix-install.mjs` | **pass**（exit 0；安装到临时 VS Code profile 并列出 1.3.4） |
| Installed-VSIX host E2E | `TRAINER_SKIP_VSIX_REBUILD=1 npm run test:vsix-e2e` | **pass：35/35 steps, 0 fail**（46.3s；no rebuild） |
| Performance probe | `npm run perf:probe` | budgets pass；见 §4 |
| UI golden capture | `node scripts/capture-ui-golden.mjs` | pass：**10/10 screenshots** |

安装态 E2E 的真实 provider 统计（fixture，本地）：`models=2`，
`chatCompletions=18`，`streaming=3`，`toolProbe=2`。证据摘要：
[`p1-final-vsix-e2e.json`](p1-final-vsix-e2e.json)。

## 3. 真实模型与教学证据

| 运行 | 结果 | 证据 |
| --- | --- | --- |
| 2026-10-19 全矩阵真实模型 | **32 案例 / 64 回合 = 64 passed**，0 failed / 0 fallback / 0 provider_error | `tmp/maturity-ws/report.json`（未入库）+ canonical 报告 |
| 2026-10-19 历史 28 案例 | 55 passed / 1 honest fallback（已归档，不被覆盖） | [`2026-10-13-teaching-journeys-report.md`](../maturity/2026-10-13-teaching-journeys-report.md) |
| 本轮 live provider smoke（`linksub.fun` / `minimax-m3`） | **success**，7,986 ms | [`p1-final-provider-smoke.json`](p1-final-provider-smoke.json) |
| 本轮 2 案例真实模型子集（`01-mutable-default` + `L1-close-read-annotate`） | **3 passed / 1 provider_error**（第 1 案例 turn 1 `ReadTimeout`；turn 2 与 L1 两回合通过） | 本轮 `/tmp/trainer-maturity-smoke-ws/report.json`（临时产物，未入库） |

说明：

- 全矩阵产物的模型字段未记录（产物早于 run-metadata 插桩）；记录提交为
  `38969f5`。本轮起 harness 在 `report.json` 的 `run` 字段记录
  commit/dirty/model/provider host/platform/time/counts，并同时写 canonical
  报告与当天归档（[`scripts/maturity/real_teaching_journeys_minimax.py`](../../scripts/maturity/real_teaching_journeys_minimax.py)）。
- 子集的 `provider_error` 是上游超时，不是通过、也不是本地兜底成功；不得计入
  模型教学质量。
- 内容质量仍为独立评审栏（“待 owner 确认”），本轮未做人工审阅。

## 4. 性能实测

环境：macOS arm64，Node 26.8.2，headless Chromium，单机单样本；300 条会话消息，
300×100 字符流式注入。基线为 `docs/verification/perf-probe-baseline.json`
（2026-10-08）。

| 指标 | 基线 | 本次 | 预算 | 判定 |
| --- | --- | --- | --- | --- |
| Warm nav p90（plan / resources / training / settings） | 36 / 36 / 11 / 36 ms | 36 / 36 / 11 / 35 ms | < 100 ms | pass |
| 流式 burst longtask（>50ms） | 0 | **0** | 0 | pass |
| 流式期间导航 | — | 10 ms | — | 记录 |
| Cold first visit（plan / resources / training / settings） | 72 / 35 / 15 / 36 ms | 101 / 35 / 14 / 36 ms | — | 记录（plan 懒加载 chunk，单样本噪声内） |

完整数据：[`p1-final-perf-probe.json`](p1-final-perf-probe.json)。单样本数字仅证明
“该规模下无卡顿”，不构成架构无成本证明。

## 5. 本轮修复（含回归）

| 问题 | 根因 | 修改 | 回归 |
| --- | --- | --- | --- |
| Windows 后台资源整理单飞测试偶发失败 | 固定 `sleep(0.4)` 等不到 worker 线程完成 | 改为轮询真实 `_organizer_sweep_task` 并用 `asyncio.wait_for` 等待任务终态 | 本地连续 10/10 通过；未放宽断言 |
| 验收报告永远写死 `2026-10-13`，覆盖历史且 canonical 不更新 | harness `REPORT_PATH` 硬编码历史日期 | full real run 写 canonical + 当天归档；`TRAINER_MATURITY_REPORT_PATH` 抑制归档；新增 `run` 元数据 | `server/tests/test_maturity_harness_metadata.py`（4 tests） |
| canonical 仍写 28 案例 55/1，与 raw 32 案例 64/64 冲突 | 文档未随运行刷新 | 从 raw 产物重建 canonical；恢复 2026-10-13 历史；新增 2026-10-19 全矩阵归档；刷新 README/ACCEPTANCE_FACTS | 数值与 `report.json` 一致 |
| 安装态 E2E 保存后等待隐式 provider 测试，150s 超时 | 产品按 P1 合同不再在保存时强制探测 | E2E 显式调用 `trainer.provider.test` 并断言真实结果 | 该步 1.1s 通过；E2E 总 35/35 |
| 安装态 E2E 标题断言期待旧标题，与 shipped 单标题合同冲突 | 断言未跟上 `name=" "` / runtime `title=""` 设计 | 读取空标题赋值；断言“容器标题只显示一次” | E2E 标题/主题步通过 |
| 两张 golden 截图指向已删除的 `···` 溢出菜单 | 捕获脚本与 README 残留旧 UI | 删除 2 张 stale PNG、2 个 capture step 与 README 引用；刷新其余 10 张 | 捕获 10/10 通过 |

## 6. 功能矩阵与遗留

| 模块 | 实现状态 | 自动化 | 原生验收 | 遗留问题 |
| --- | --- | --- | --- | --- |
| Coach | 完整 | 2183 ext + 200 preview + 200 sidecar | VSIX E2E 流式/消息/恢复 | 300 条滚动与 200% 字号未做设备复验 |
| Provider | 完整 | provider/config/race 测试 | live smoke + E2E 显式 test | 本轮中转一次 `ReadTimeout`（上游） |
| Learning | 完整 | geometry + 200 matrix | E2E host-state | 无已知阻断 |
| Training | 完整 | server + E2E training steps | E2E 35 步含训练/复盘/恢复 | 无已知阻断 |
| Memory | 完整 | server suite | E2E reopen/记忆隔离 | 无已知阻断 |
| Resources | 完整 | download-safety + server + matrix | E2E resource detail/preview/restore | 无已知阻断 |
| Browser Extension | 可用 | 6 组 unit tests + 20-file package | **未执行真实浏览器配对/采集** | 真实 Chrome/Edge + Sidecar 配对仍需设备验收 |
| Remote SSH | 保持 Local Brain/Remote Hands | Linux nightly workflow + unit | **本机 darwin 不适用；未执行真实 SSH** | 需 Linux/Windows 实机验收 |
| MCP | 完整 | authority + client 测试 | 未接真实 MCP server | 真实 server 发现/失败恢复未设备验收 |
| Settings | 完整 | geometry + screenshots | E2E title/theme（dark/light/HC） | 8 语言视觉未逐屏 |
| Release | darwin-arm64 产物 | package + install + host E2E | **仅 macOS arm64** | win32-x64 / linux-x64 未构建；v1.3.4 正式 Release 附件未验证 |

**明确未执行（Not Executed，不计为 Passed）**

1. Windows x64、Linux x64 的 VSIX 安装与 host E2E。
2. 真实 Remote SSH 工作区验收（仅 Linux/Windows 目标）。
3. 真实 Chrome/Edge 扩展与 Sidecar 的配对、采集、离线队列、深链接。
4. 200% 字号、八语言逐屏视觉、长列表 300 条设备滚动的截图级复验。
5. GitHub Actions CI 与正式 Release/tag/push（网络与授权边界）。
6. 真实 MCP server 的端到端工具调用。

## 7. 视觉验收

- 10 张 golden 截图（zh-CN dark，420×900@2x；narrow 340×900@2x）位于
  [`assets/screenshots/`](../../assets/screenshots/)：Coach、Learning、Training、
  Resources、Progress、Settings（连接/快速设置）、Skill palette/manager、narrow。
- 逐屏人工检查 6 个主面：无遮挡、裁切、重复主操作或死按钮；Learning/Training/
  Progress 首屏各只有一个主操作；Settings 只呈现一个阻塞项（工作区信任）。
- Coach 短会话采用底部锚定，顶部留白是 CSS 中记录的设计决定
  （`coach-conversation-view.css` 的 resume-banner `margin-top: auto`），不是本轮回归；
  长会话滚动由 300 消息性能探针覆盖。

## 8. 复现命令

```bash
npm run verify
npm run verify:version
npm run verify:credentials
npm run verify:server-pyright
node scripts/verify-ui-geometry.mjs
npm run test:experience-matrix
npm run test:experience-sidecar
npm run package:browser-extension
npm run perf:probe
npm run package:vsix
TRAINER_SKIP_VSIX_REBUILD=1 node extension/scripts/verify-vsix-install.mjs
TRAINER_SKIP_VSIX_REBUILD=1 npm run test:vsix-e2e
node scripts/capture-ui-golden.mjs
```

真实模型复现（凭证仅环境变量）：

```bash
TRAINER_MATURITY_API_KEY=... \
TRAINER_MATURITY_PROVIDER_BASE_URL=https://<relay> \
TRAINER_MATURITY_MODEL=<model> \
server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
```

## 9. 最终判定

**本地 macOS arm64 候选：VERIFIED。**
**Trainer P1 Mature — Ready for Release：NOT YET（§6 的 1–6 未闭环）。**
