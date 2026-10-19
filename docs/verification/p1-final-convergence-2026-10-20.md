# P1 最终收敛验收记录（2026-10-20，三平台 + 本地 macOS）

> 本文件只记录实际执行的命令、产物与结论。未执行的平台/设备门明确写
> **Not Executed**，不折算为 Passed。它不是发布声明，也不替代 owner 的发布授权。

## 0. 结论

- **三平台发布门已全绿**：GitHub Actions `Trainer Cross-Platform Verify`
  run `39323264391`（`ee36bc6`）9/9 jobs success；Windows x64、macOS ARM64、
  Linux x64 的 VSIX 均完成打包、原生安装与安装态 host E2E（35/39/35 步）。
- **Remote-SSH Layer 1 全绿**：run `39323280968`（`ee36bc6`）两 job success；
  11/11 transport steps（exec、逐字节读、搜索、sha256、验证 pass/fail、
  中断→unknown、断线重连）。Layer 2（真人进入真实 Remote-SSH VS Code Server
  窗口）仍是 **Not Executed**。
- **浏览器扩展真实链路 15/15**：打包后的 MV3 扩展 + 真实 sidecar，覆盖配对、
  Web / GitHub README / PDF 采集、离线队列 + flush、库状态、撤销、旧凭据 401。
- **本地工程门**：`npm run verify` exit 0；3644 server tests、2184 extension
  tests、471 geometry、200+200 experience scenarios、性能预算通过。
- **仍不能宣告 “Trainer P1 Mature — Ready for Release”**：真实教学质量的
  **非固定夹具样本 + 人工审阅**未成立（提供的测试中转无法完成完整 coach turn：
  两个模型返回空回复、两个超时）；Remote-SSH Layer 2、200% 字号/八语言逐屏
  视觉、品牌 Chrome/Edge 未打包安装、下载到项目目录的真实链路仍未执行。
  见 §6。

## 1. 版本与产物事实

| 字段 | 值 |
| --- | --- |
| Repository | `https://github.com/AI-yyf/trainer` |
| Baseline | `main` @ `7e440de614a5224c4d75ac7153c394a2ea1d4f84`（v1.3.4） |
| Work branch | `maturity/p1-final-convergence-2026-10-20`（已推送；未合并 `main`） |
| Release-candidate source | **`ee36bc637b9622f4e9851fe418201e96f2827275`** |
| Product version | `1.3.4`（`npm run verify:version`） |
| Working tree | clean（本记录提交前） |
| CI runs | Cross-Platform `39323264391`；Remote-SSH `39323280968`；均 success |
| Server tests | **3644 passed**，28 subtests（`npm run verify`） |
| Extension tests | **2184 pass / 2185 tests / 0 fail**（1 skipped） |

### 三平台 VSIX（run `39323264391`，source `ee36bc6`）

| Target | Bytes | SHA-256 | Native install | Host E2E |
| --- | --- | --- | --- | --- |
| `win32-x64` | 92,029,481 | `38e798f0429c6607baa0575b78dd24ed6fe4e6b614156c413b11c75a81cf5b11` | ok=true | **35/35**, 125.8s |
| `darwin-arm64` | 120,837,217 | `207bbd1305bdfe84b6153aff981eee80cb2ce4f92edc8cac96a158af8ae26729` | ok=true | **35/35**, 34.7s |
| `linux-x64` | 154,930,073 | `e06fb36791c9baf7495d4b7dc0f5aaa8254e7d1a60a5ee43e6c7debc05c962b5` | ok=true | **39/39**, 32.5s |

每个 VSIX 同时上传 `.vsix.build.json`（来源提交、平台、运行时依赖、文件
SHA-256）。机器可读汇总见
[`p1-final-cross-platform.json`](p1-final-cross-platform.json)。

## 2. 工程门（本地实际执行）

| Gate | 结果 |
| --- | --- |
| `npm run verify` | **pass**（exit 0） |
| Server suite（含其中） | **3644 passed**, 28 subtests |
| Extension suite | **2184 pass / 0 fail**（1 skipped） |
| TypeScript / CSS | pass（CSS sections + webview/host `tsc --noEmit`） |
| Ruff / Pyright | pass；Pyright 0 errors / 0 warnings |
| `npm run verify:version` | pass（1.3.4） |
| `npm run verify:credentials` | pass（0 findings） |
| `node scripts/verify-ui-geometry.mjs` | **471 / 471** |
| `npm run test:experience-matrix` | **200 passed** |
| `npm run test:experience-sidecar` | **200 passed** |
| `npm run package:browser-extension` | 20 files / **62,184 bytes**，8 个 `_locales` |
| `npm run test:browser-capture-e2e` | **15 / 15**（packaged MV3 + real sidecar） |
| `npm run test:vsix-e2e` | 本地 35/35（dc43797 产物）；CI 三平台另见 §1 |
| `npm run perf:probe` | budgets pass（见 §4） |
| `node scripts/capture-ui-golden.mjs` | 10/10 screenshots |

## 3. 真实模型与教学质量

| 运行 | 结果 | 说明 |
| --- | --- | --- |
| 2026-10-19 全矩阵 | **32 案例 / 64 回合 = 64 passed** | 固定夹具；0 failed / 0 fallback / 0 provider_error |
| 历史 28 案例 | 55 passed / 1 honest fallback | 已归档在 `2026-10-13-teaching-journeys-report.md` |
| Live provider smoke（`linksub.fun` / `minimax-m3`） | success，7.99s | 小提示词探测 |
| 2 案例真实子集（`minimax-m3`） | 3 passed / 1 provider_error（`ReadTimeout`） | 上游超时；未伪装为通过 |
| 非固定真实项目探针（本仓库 `server/app/network_fetch.py`） | **未成立** | `deepseek-v4.1-flash` 与 `glm-5.3` 返回空/截断回复，产品落到确定性 intake 模板；`minimax-m3` / `kimi-k3` 在完整 coach turn 上超时（300s/600s） |

诚实结论：

- 固定 32 案例矩阵的 **64/64** 是当前唯一完整的真实模型教学证据；它不是
  “所有真实教学质量合格”的证明。
- 非固定真实项目样本在本次提供的测试中转上**没有取得可用模型回复**，因此
  不计为教学通过，也不能替代人工审阅。产品在该情形下返回的是安全的 intake
  模板（不伪造下一步），但这不是高质量教学回答。
- **人工审阅未执行**；不得把 Agent 评价或固定矩阵通过记作人工审阅。

## 4. 性能实测

环境：macOS arm64，Node 26.8.2，headless Chromium，单机单样本；300 条会话消息，
300×100 字符流式注入。基线 `docs/verification/perf-probe-baseline.json`。

| 指标 | 基线 | 本次 | 预算 | 判定 |
| --- | --- | --- | --- | --- |
| Warm nav p90（plan/resources/training/settings） | 36/36/11/36 ms | 36/36/11/35 ms | < 100 ms | pass |
| 流式 burst longtask（>50ms） | 0 | **0** | 0 | pass |
| 流式期间导航 | — | 10 ms | — | 记录 |
| Cold first visit（plan/resources/training/settings） | 72/35/15/36 ms | 101/35/14/36 ms | — | 记录（plan lazy chunk，单样本噪声） |

完整数据：[`p1-final-perf-probe.json`](p1-final-perf-probe.json)。

## 5. 本轮修复（问题 → 根因 → 修改 → 回归）

| 问题 | 根因 | 修改 | 证据 |
| --- | --- | --- | --- |
| Windows 后台整理单飞测试偶发失败 | 固定 `sleep(0.4)` 等不到 worker | 轮询真实 `_organizer_sweep_task` 并 `wait_for` 终态 | 本地 10/10；CI Windows server green |
| 验收报告覆盖历史/ canonical 不更新 | harness 硬编码 `2026-10-13` | full real run 写 canonical + 当天归档；新增 `run` 元数据 | `test_maturity_harness_metadata.py`（4 tests） |
| 文档 55/1 与 raw 64/64 冲突 | 文档未随运行刷新 | 重建 canonical、恢复历史、新增 2026-10-19 归档 | 与 `report.json` 一致 |
| Windows 资源索引被记为失败 | `/resource/index` 使用 15s 通用超时，Windows 首轮解析 >15s | 索引使用 120s 长任务预算 | 资源命令 40/40；CI Windows host green |
| 受控抓取在 IPv6 不可达时超时 | 首个 AAAA 地址耗尽整个 deadline，IPv4 从不尝试 | IPv4 优先 + 单次连接上限；保留 DNS 钉扎与私网拒绝 | `test_network_fetch.py` 35 passed；live `example.com` 200 |
| Windows 首次 sidecar 启动超时 | 非 macOS 仅 20s startup 预算 | 全平台统一 120s 有界首启窗口 | CI Windows host green |
| 浏览器采集把 5xx/超时谎报为“Trainer 未运行” | 队列分支无条件 `recordConnection('offline')` | 仅 transport 失败记 offline；8 语言排队文案改为“未能完成采集” | 15/15 浏览器 E2E；copy tests 63/63 |
| 安装态 E2E 等待隐式 provider 探测 | 产品已不在保存时强制探测 | E2E 显式 `trainer.provider.test` | 三平台 host E2E 35/39/35 |
| 安装态 E2E 标题断言过期 | 断言未跟上空白 pane title 设计 | 读取空标题赋值，断言单标题契约 | 三平台 title/theme 步 green |

## 6. 功能矩阵与遗留

| 模块 | 实现状态 | 自动化 | 原生验收 | 遗留问题 |
| --- | --- | --- | --- | --- |
| Coach | 完整 | 2184 ext + 200 preview + 200 sidecar | 三平台 host E2E | 非固定真实项目样本未取得可用模型回复 |
| Provider | 完整 | provider/config/race 测试 | live smoke + 三平台显式 test | 测试中转在长 coach turn 上超时/空回复 |
| Learning | 完整 | geometry + 200 matrix | 三平台 host state | 无已知阻断 |
| Training | 完整 | server + host E2E | 三平台 host E2E | 无已知阻断 |
| Memory | 完整 | server suite | host reopen/隔离 | 无已知阻断 |
| Resources | 完整 | download-safety + server + matrix | 三平台 resource/preview/restore | 下载到项目目录的真实链路未做浏览器 E2E |
| Browser Extension | 完整 | 6 组 unit + 15 项真实 E2E | Chrome for Testing + 真实 sidecar | 品牌 Chrome 155 / Edge 通过 `--load-extension` 安装不可自动化 |
| Remote SSH | Layer 1 完整 | Linux transport E2E 11/11 | CI ubuntu green | **Layer 2 真人窗口 Not Executed** |
| MCP | 完整 | authority + client 测试 | 未接真实 MCP server | 真实 server 发现/失败恢复未设备验收 |
| Settings | 完整 | geometry + screenshots | 三平台 title/theme（dark/light/HC） | 200% 字号 / 八语言逐屏截图未执行 |
| Release | 三平台产物 | package + install + host E2E | **win32-x64 / darwin-arm64 / linux-x64 全绿** | 正式 tag/Release 未发布（授权边界） |

**明确未执行（Not Executed，不计为 Passed）**

1. 非固定复杂真实项目的可用真实模型教学样本 + 人工审阅。
2. 真实 Remote-SSH VS Code Server 窗口（Layer 2）人工验收。
3. 200% 字号与八语言逐屏截图审查（八语言 200 场景矩阵已通过 DOM 断言）。
4. 品牌 Chrome / Edge 的 unpacked extension 安装（Chrome 155 已移除
   `--load-extension`；Edge 未安装）；Chrome for Testing 已通过。
5. PDF / GitHub 仓库 **下载到当前允许的项目工作区** 的真实浏览器 E2E
   （采集与索引已通过，下载安全有 server 单测）。
6. 正式 tag / GitHub Release / 面向用户发布（需 owner 授权）。

## 7. 视觉验收

- 10 张 golden 截图（zh-CN dark，420×900@2x；narrow 340×900@2x）位于
  [`assets/screenshots/`](../../assets/screenshots/)：Coach、Learning、Training、
  Resources、Progress、Settings（连接/快速设置）、Skill palette/manager、narrow。
- 逐屏人工检查 6 个主面：无遮挡、裁切、重复主操作或死按钮；Learning/Training/
  Progress 首屏各只有一个主操作；Settings 只呈现一个阻塞项。
- Coach 短会话底部锚定、顶部留白是 CSS 中记录的设计决定，不是回归；长会话由
  300 消息性能探针覆盖。
- 品牌 Chrome 155 的 flag 限制是浏览器行为，不是扩展缺陷；打包 MV3 已由
  Chrome for Testing 验证。

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
npm run test:browser-capture-e2e
npm run perf:probe
npm run package:vsix
TRAINER_SKIP_VSIX_REBUILD=1 node extension/scripts/verify-vsix-install.mjs
TRAINER_SKIP_VSIX_REBUILD=1 npm run test:vsix-e2e
node scripts/capture-ui-golden.mjs
```

跨平台与 Remote-SSH 门：

```bash
gh workflow run cross-platform-verify.yml \
  --ref maturity/p1-final-convergence-2026-10-20 \
  -f run_vsix_host_e2e=true
gh workflow run nightly-remote-ssh.yml \
  --ref maturity/p1-final-convergence-2026-10-20
```

## 9. 最终判定

**三平台发布门：GREEN（run `39323264391`）。**
**Remote-SSH Layer 1：GREEN（run `39323280968`）；Layer 2：Not Executed。**
**浏览器扩展真实链路：GREEN（15/15）。**

**Trainer P1 Mature — Ready for Release：NOT YET。**
剩余阻断项是 §6 的 1–5：非固定真实教学质量与人工审阅未成立、Remote-SSH
Layer 2、200% 字号/八语言逐屏、品牌 Chrome/Edge 安装、下载到项目目录的真实
浏览器链路。它们不是已通过的项，不能用固定矩阵或 Agent 评价替代。
