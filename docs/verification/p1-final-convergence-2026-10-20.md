# P1 最终收敛验收记录（2026-10-20，三平台 + 本地 macOS）

> 本文件只记录实际执行的命令、产物与结论。未执行的平台/设备门明确写
> **Not Executed**，不折算为 Passed。它不是发布声明，也不替代 owner 的发布授权。

## 0. 结论

- **三平台发布门已全绿**：`Trainer Cross-Platform Verify` run `39345769307`
  （`14f42ee`）9/9 jobs success；Windows x64、macOS ARM64、Linux x64 的 VSIX
  均完成打包、原生安装与安装态 host E2E（35/39/35 步）。最终 UI 候选 `14f42ee` 的复跑见 §1。
- **Remote-SSH Layer 1 全绿**：run `39345782386`（`14f42ee`）两 job success；
  11/11 transport steps（exec、逐字节读、搜索、sha256、验证 pass/fail、
  中断→unknown、断线重连）。Layer 2（真人进入真实 Remote-SSH VS Code Server
  窗口）仍是 **Not Executed**。
- **浏览器扩展真实链路 23/23**：打包后的 MV3 扩展 + 真实 sidecar，覆盖配对、
  Web / GitHub README / PDF 采集、PDF/GitHub 仓库下载到项目目录、不覆盖、
  404 不重试、路径穿越拒绝、离线队列（web + download）+ flush、撤销、旧凭据 401。
- **200% 字号 + 八语言逐屏矩阵 96/96**：6 个 surface × 8 语言 × normal/200%；
  截图与 report 在 [`p1-final-a11y/`](p1-final-a11y/)；期间发现并修复了
  Progress 行标签/计数重叠与主按钮裁切。
- **非固定真实项目样本**：连接段附件两回合，`minimax-m3` 与 `glm-5.3` 均给出
  正确、引用真实符号的回复；独立 AI 审阅通过（附延迟/next_step caveat），
  **真人签核仍 Pending**（§3.1）。
- **本地工程门**：`npm run verify` exit 0；3644 server tests、2184 extension
  tests、471 geometry、200+200 experience scenarios、性能预算通过。
- **仍不能宣告 “Trainer P1 Mature — Ready for Release”**：真人教学签核、
  Remote-SSH Layer 2、96 张截图的人工逐屏签核、品牌 Chrome/Edge 未打包安装；
  非固定样本还有 480s 预算与结构化 next_step 两项 caveat。见 §6。
  PDF/GitHub 下载到项目目录已由 23/23 真实 E2E 覆盖（§7）。

## 1. 版本与产物事实

| 字段 | 值 |
| --- | --- |
| Repository | `https://github.com/AI-yyf/trainer` |
| Baseline | `main` @ `7e440de614a5224c4d75ac7153c394a2ea1d4f84`（v1.3.4） |
| Work branch | `maturity/p1-final-convergence-2026-10-20`（已推送；未合并 `main`） |
| Release-candidate source | **`14f42eef1135bc55b368df19bad6eef1ff23c78d`** |
| Product version | `1.3.4`（`npm run verify:version`） |
| Working tree | clean（本记录提交前） |
| CI runs | Cross-Platform `39345769307`；Remote-SSH `39345782386`；均 success |
| Server tests | **3644 passed**，28 subtests（`npm run verify`） |
| Extension tests | **2184 pass / 2185 tests / 0 fail**（1 skipped） |

### 三平台 VSIX（run `39345769307`，source `14f42ee`，`sourceDirty=false`）

| Target | Bytes | SHA-256 | Native install | Host E2E |
| --- | --- | --- | --- | --- |
| `win32-x64` | 92,726,183 | `dee61d901e64608476f9dd5283aecb55a6efb9fad22673a425e573918b9e5973` | ok=true | **35/35**, 151.3s |
| `darwin-arm64` | 121,950,161 | `396a09f939a9bdeb3e843c2587fb448be5448eb3aac596a01f9dd52f9fd46068` | ok=true | **35/35**, 31.3s |
| `linux-x64` | 156,320,065 | `5a5252f7c74cd6df651447ed24d63b9362e3da99d99afe9fd1ab53e10b39a554` | ok=true | **39/39**, 30.7s |

每个 VSIX 的 `.vsix.build.json` 记录来源提交、平台、运行时依赖和 VSIX
SHA-256；上表的 SHA-256 已用下载后的 VSIX 文件逐字节复核一致。机器可读汇总见
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
| `npm run test:browser-capture-e2e` | **23 / 23**（packaged MV3 + real sidecar，含下载） |
| `npm run test:ui-a11y` | **96 / 96**（8 语言 × 6 view × normal/200% 字号；见 §7） |
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
| 非固定真实项目样本（`network_fetch.py` 连接段，57 行） | **内容质量独立审阅通过（附 caveat）** | `minimax-m3` 2,535/803 chars（508.73s/3.91s）；`glm-5.3` 1,496/1,348 chars（398.43s/35.48s）；原文与审阅见 §3.1 |

### 3.1 非固定真实项目样本

- 附件只含 `server/app/network_fetch.py` 的连接段（`_ResolvedAddress` /
  `_ResolvedTarget` / `_connect_verified` / `_remaining_timeout`），57 行 /
  2,158 字符，SHA-256 `b12d0be223cf23e667d8583ec4892b640db0e3882763d68849c4150a936eaef2`。
  完整文件版本在中转上返回空/截断，已不作为样本。
- 原始回复：
  [`minimax-m3`](../maturity/2026-10-20-real-project-probe-minimax-m3.json) /
  [`glm-5.3`](../maturity/2026-10-20-real-project-probe-glm-5.3.json)。
- 独立 AI 审阅记录：
  [`2026-10-20-real-project-review.md`](../maturity/2026-10-20-real-project-review.md)。
  **该记录明确不是真人审阅；owner 人工签核仍为 Pending。**

诚实结论：

- 两个模型都正确解释了 `getaddrinfo` 的 AAAA 优先、`socket.connect()` 耗尽
  deadline、`_connect_verified` 的排序 + 5s 单地址上限，并给出了可执行的
  最小验证/测试切入点；内容质量通过独立审阅。
- **Caveat 1**：结构化 `coach_turn.next_step` 仍是泛化句（“先说清规则…” /
  “先在 network_fetch.py 里改一个小点…”），正文里的具体动作没有进入该字段；
  若 UI 只显示结构化字段，下一步会偏弱。
- **Caveat 2**：`minimax-m3` 回合 1 508.73s，超过 480s coach 预算（扩展会先
  超时）；`glm-5.3` 398.43s 在预算内但很慢。这是模型/中转延迟，不是发送链路
  逻辑错误；回合 2 为 3.91s / 35.48s。
- **人工审阅仍未执行**；不得把独立 Agent 审阅或固定矩阵通过记作真人审阅。

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
| 浏览器采集把 5xx/超时谎报为“Trainer 未运行” | 队列分支无条件 `recordConnection('offline')` | 仅 transport 失败记 offline；8 语言排队文案改为“未能完成采集” | 23/23 浏览器 E2E（含下载）；copy tests 63/63 |
| 安装态 E2E 等待隐式 provider 探测 | 产品已不在保存时强制探测 | E2E 显式 `trainer.provider.test` | 三平台 host E2E 35/39/35 |
| 安装态 E2E 标题断言过期 | 断言未跟上空白 pane title 设计 | 读取空标题赋值，断言单标题契约 | 三平台 title/theme 步 green |
| Progress 200% 字号标签/计数重叠 | 按钮内 flex 容器不允许换行，count 从标签内部开始 | `.progress-view__row-toggle` 允许 wrap；count 改为可换行 | 96/96 a11y；`progressRowOverlaps=0` |
| Progress 主按钮 200% 字号被裁切 | 共享 `.button` 的 `white-space: nowrap` | 该主操作允许换行、`max-width:100%` | de-DE 200% 截图 |
| es-ES composer 标签被压成单字母竖排 | `.template-context` 不换行，label 被两个按钮挤到 1ch | label 12em flex basis + context wrap；新增 `<4em` 断言 | es-ES 200% 截图；narrowLabels=0 |
| 八语言/200% 视觉无逐屏证据 | 只有 420/460 的 golden 与 DOM 矩阵 | 新增 8 语言 × 6 view × normal/200% 截图与断言 | `npm run test:ui-a11y` 96/96 |

## 6. 功能矩阵与遗留

| 模块 | 实现状态 | 自动化 | 原生验收 | 遗留问题 |
| --- | --- | --- | --- | --- |
| Coach | 完整 | 2184 ext + 200 preview + 200 sidecar | 三平台 host E2E | 非固定样本内容审阅通过；真人签核 Pending；结构化 next_step 泛化 |
| Provider | 完整 | provider/config/race 测试 | live smoke + 三平台显式 test | `minimax-m3` 508.7s 超 480s 预算；`glm-5.3` 398.4s 偏慢 |
| Learning | 完整 | geometry + 200 matrix | 三平台 host state | 无已知阻断 |
| Training | 完整 | server + host E2E | 三平台 host E2E | 无已知阻断 |
| Memory | 完整 | server suite | host reopen/隔离 | 无已知阻断 |
| Resources | 完整 | download-safety + server + matrix | 三平台 resource/preview/restore | 浏览器 PDF/GitHub 下载已通过真实 E2E |
| Browser Extension | 完整 | 6 组 unit + 23 项真实 E2E | Chrome for Testing + 真实 sidecar | 品牌 Chrome 155 / Edge 通过 `--load-extension` 安装不可自动化 |
| Remote SSH | Layer 1 完整 | Linux transport E2E 11/11 | CI ubuntu green | **Layer 2 真人窗口 Not Executed** |
| MCP | 完整 | authority + client 测试 | 未接真实 MCP server | 真实 server 发现/失败恢复未设备验收 |
| Settings | 完整 | geometry + screenshots | 三平台 title/theme（dark/light/HC） | 200%/八语言 96/96 已过；真人逐屏签核 Pending |
| Release | 三平台产物 | package + install + host E2E | **win32-x64 / darwin-arm64 / linux-x64 全绿** | 正式 tag/Release 未发布（授权边界） |

**明确未执行（Not Executed，不计为 Passed）**

1. 非固定真实项目样本的 **owner/真人教学签核**（内容样本与独立 AI 审阅已完成，
   见 §3.1；Agent 审阅不能替代人工）。
2. 真实 Remote-SSH VS Code Server 窗口（Layer 2）人工验收。
3. 96 张 200%/八语言截图已生成并通过自动断言；**人工逐屏签核**仍 Pending
   （本次人工查看了 4 张 contact sheet，其余留作 owner 复核）。
4. 品牌 Chrome / Edge 的 unpacked extension 安装（Chrome 155 已移除
   `--load-extension`；Edge 未安装）；Chrome for Testing 已通过。
5. 正式 tag / GitHub Release / 面向用户发布（需 owner 授权）。

## 7. 视觉验收

- 10 张 golden 截图（zh-CN dark，420×900@2x；narrow 340×900@2x）位于
  [`assets/screenshots/`](../../assets/screenshots/)：Coach、Learning、Training、
  Resources、Progress、Settings（连接/快速设置）、Skill palette/manager、narrow。
- 逐屏人工检查 6 个主面：无遮挡、裁切、重复主操作或死按钮；Learning/Training/
  Progress 首屏各只有一个主操作；Settings 只呈现一个阻塞项。
- **200% 字号 + 八语言矩阵**：`npm run test:ui-a11y` 生成 96 张截图
  （8 语言 × 6 view × normal-light/font200-dark），断言横向溢出、占位符文本和
  Progress 行重叠，**96/96 pass**。证据：
  [`p1-final-a11y/report.json`](p1-final-a11y/report.json) 与
  [`p1-final-a11y/`](p1-final-a11y/) 下 16 张 contact sheet。
- 该矩阵发现并修复了三个真实 200% 缺陷：Progress 标签/计数重叠（按钮内 flex
  不换行）、Progress 主按钮被裁切（共享按钮 nowrap）、es-ES composer 标签被
  压成单字母竖排（context 不换行）。de-DE/zh-CN/es-ES 200% 与 de-DE/es-ES/ja-JP
  normal 的 contact sheet 已人工复核；其余语言 sheet 留作 owner 逐屏签核。
- Coach 短会话底部锚定、顶部留白是 CSS 中记录的设计决定，不是回归；长会话由
  300 消息性能探针覆盖。
- 品牌 Chrome 155 的 flag 限制是浏览器行为，不是扩展缺陷；打包 MV3 已由
  Chrome for Testing 验证。
- **下载链路**：PDF 与 GitHub 仓库均真实写入 `Trainer Library/...`；同内容重下
  返回 `duplicate-local` 且字节不变（不覆盖）；404 为不可重试失败；`../` 目标
  目录被 422 拒绝且工作区外无写入；sidecar 离线时 web + PDF 下载排队，重启
  flush 后 `flushed=2`、PDF 落到目标目录。证据：
  [`p1-final-browser-capture.json`](p1-final-browser-capture.json)。

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
npm run test:ui-a11y
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

**三平台发布门：GREEN（run `39345769307`，`14f42ee`；35/39/35 host steps）。**
**Remote-SSH Layer 1：GREEN（run `39345782386`）；Layer 2：Not Executed。**
**浏览器扩展真实链路（含 PDF/GitHub 下载）：GREEN（23/23）。**
**200% 字号 + 八语言视觉矩阵：GREEN（96/96）。**
**非固定真实项目样本：内容独立审阅通过；真人签核 Pending。**

**Trainer P1 Mature — Ready for Release：NOT YET。**
剩余阻断项是 §6 的 1–5：owner/真人教学签核、Remote-SSH Layer 2、96 张截图的
人工逐屏签核、品牌 Chrome/Edge 安装、正式 Release 授权。它们不是已通过的项，
不能用固定矩阵或 Agent 评价替代。

## 10. Owner handoff（仅剩人工/授权动作）

| 待办 | 可直接使用的材料 |
| --- | --- |
| 非固定样本人工签核 | 原始回复 [`minimax-m3`](../maturity/2026-10-20-real-project-probe-minimax-m3.json) / [`glm-5.3`](../maturity/2026-10-20-real-project-probe-glm-5.3.json)；独立审阅 [`review`](../maturity/2026-10-20-real-project-review.md)（明确标注非人工） |
| Remote-SSH Layer 2 | [L2 手动验收清单](p1-final-remote-ssh-l2-checklist.md)；run [`39345782386`](https://github.com/AI-yyf/trainer/actions/runs/39345782386) 的 `trainer-remote-ssh-l2-vsix` 构件 |
| 96 张截图人工签核 | [contact sheets](p1-final-a11y/)（16 张，覆盖 normal-light/font200-dark × 8 语言）与 [report.json](p1-final-a11y/report.json) |
| 正式 Release 授权 | 候选源码 `14f42ee`；三平台 VSIX 与 SHA-256 见 §1；当前分支 tip 为测试/文档提交，未打 tag、未发布 Release |

本文件与上述材料只提供可核对的证据；真人签核、Layer 2 窗口验收和正式发布授权
必须由 owner 完成。
