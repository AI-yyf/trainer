# Trainer v1.5 统一状态报告（2026-11-07）

> 唯一状态报告。所有数值来自本仓库当前 `main`（`4407d96`）的真实命令输出、
> 真实主机（141s）与真实 Release；未执行项显式标注，不做 PASS 冒充。

## 1. 现状

| 项 | 值 |
| --- | --- |
| 代码与 CI 基线 | `4407d96`（v1.4.1 tag = `adbf93a`，v1.4.0 tag = `2f1bb68`） |
| 本轮提交（v1.4.0..`4407d96`，不含本报告提交） | 80 个 |
| 代码差异（v1.4.0..HEAD） | 238 files, +36577 / −21966（含两次 CRLF→LF 规范化） |
| 最新 ci 工作流 | run 42481015260 **success** |
| 最新 Cross-Platform Verify | run 42481015243 **success（9/9）** |
| Release | v1.4.1 已发布（三平台 VSIX + build manifest） |

最近提交（最新在前；完整 72 个见 `git log v1.4.0..main`）：

```
4407d96 docs(matrix): 20 旅程 × 7 证据 + Provider/Memory/App 拆分 + SCIP JSON
9c87695 feat(skills): 项目蒸馏 Skill 按 workspace 隔离
1c016ab feat(evidence): 三套 Evidence 统一契约与读取流
2003806 design(settings): 教练/工作区/偏好统一为同一卡片表面
a158614 design(settings): 模型配置收敛为单一完整界面
76a17e3 test(goal): 跨平台工作区断言
eca6e4f test(goal): 证明 start/summary 快照恢复与清除 goal
01f0153 fix(goal): 评估进度发布到所有 live session
6ea1a98 fix(goal): 重启暂停目标时复用而非重复创建
e84577e feat(goal): GoalSession 服务端持久化 + 真实活动进度
1ef996c docs(status): 刷新到 586fa93/64 提交 + CI 9/9
586fa93 fix(training): 字符串匹配通过不再升级为 mastery
2f7eb47 docs(status): 刷新到 458440f/62 提交 + 3902 测试
458440f feat(review): 队列评分走 FSRS + 无回忆证据标记
b50e90d fix(review): mastery 调度带来源、ReviewScheduler 只读 FSRS
6c181c7 test(eval): host 断言 training_phase=verify
96da02c feat(review): 显式 training_phase + 失败 Verify 写 FSRS AGAIN
dae8952 ci: 触发 V4 复核
dcd122e chore(build): V4 VSIX manifest
601c09d fix(v4): 自由聊天/证据失效/技能恢复/FSRS due
ef95beb fix(provider): 数字 Token Plan 限额归为额度耗尽
4e8554f refactor(resources): 抽出 libraryPaths 纯路径责任
bdb8986 design(resources): + 图标靠搜索、回收站页脚化
1b53a23 feat(chat): ^sup^ / ~sub~ 字符上下标
```

V4 审计与首轮修复：`docs/maturity/2026-11-08-v4-audit.md`（自由聊天不再被 review 字样劫持；资料删除按资源哈希失效证据；Skill 未被应用不清零失败；FSRS due 回写 MasteryRecord）。

FSRS 单一调度已落地（96da02c..586fa93）：`/evaluate/current-file` 显式 `training_phase`，失败 Verify 写 AGAIN；`MasteryRecord.review_source` 区分 `fsrs`/`heuristic`，`update_mastery` 不再覆盖 FSRS 到期；`ReviewScheduler.process_mastery_review` 走 FSRS 评分；weakness/reflection/plan 到期项标 `no_recall_evidence`；字符串/验收匹配即使“通过”也不再记为 `verified_by_evaluator`，必须有真实动态检查通过才升级 mastery。

Goal 服务端实体化已落地：SQLite `goal_sessions` + `GoalService` 是唯一真源，`WorkbenchSnapshot.goal` 回传；`/goal/action` 支持 start/pause/resume/complete，显式新目标暂停旧焦点但保留历史；自动识别只接受明确能力学习表达，普通提问/闲聊不建目标；evaluation / training attempt evidence / host attestation 才记活动，按内容哈希或 `idempotency_key` 幂等。测试：`test_goal_session.py` 16 项 + `goalCommands.test.js` 5 项。真实 GUI 复核仍待 provider 额度，未标 PASS。

Settings 模型配置已收敛为单一完整界面：连接名称、服务地址、访问密钥（显示/隐藏 + 行内测试）、聊天模型、协议、思考模式/强度、输入/输出上限与连接诊断在同一张卡片内，底部只有取消/保存；删除了独立的“高级配置”二级页面。教练、工作区、偏好也统一为同样的卡片表面：每个分类内的连贯区块一张卡、一个标题、分组行，不再使用裸分隔线和平铺列表。模型目录拉取后自动打开选择器但**不静默替用户选模型**；粘贴 NewAPI 连接 JSON 会自动填入地址/密钥、设为 OpenAI-compatible 并自动发现模型。真实连接 `linksub.fun` 验证：模型列表 8 个、`/provider/test` connected、Remote-SSH L2 第 4 步真实回复 259 字，六步 6/6 PASS。

Evidence 三套存储已统一：新增 `UnifiedEvidence`（schema 1）与三个适配器（AttemptStore / handoff / memory），统一 `trust_level`、`result`、artifact/resource 版本字段和 fingerprint；新增 `GET /evidence/records` 只读统一流，按工作区隔离、时间倒序并标记 `duplicate_of`。handoff 证据序列化升为 version 3，重启不丢字段；AttemptStore 新增工作区级证据读取；memory 入队按 verified 写 trust_level。行为测试 `test_evidence_unification.py` 4 项；server 全套 **3923 passed**。原始存储保留各自生命周期，没有新增第四套数据库或第二套掌握评分。

项目蒸馏 Skill 已加 workspace 作用域：`SkillRecord.workspace_id` 随 registry 持久化；同名项目在不同 workspace 生成独立 id，不互相覆盖；注册、审核、激活、重试、失败/用量记录均校验 workspace；选择与注入只读取“全局 + 当前 workspace”，缺少 workspace 时只选全局；`/skill/list`、`/skill/status` 支持 workspace 过滤，`/skill/review` 跨 workspace 返回 404。行为测试 `test_skill_workspace_scope.py` 7 项；server 全套 **3930 passed**。

已建立唯一验收矩阵 `docs/maturity/2026-11-08-v4-acceptance-matrix.md`：20 条旅程 × 7 类证据逐条标 PASS/PARTIAL/GAP。矩阵明确：U 全 20 通过；S 6 通过；P 仅 3 通过；V/G/R 多数仍为 PARTIAL/GAP；L 9 通过。真实 GUI 没有一条旅程达到 PASS，不能用户单元测试冒充。缺口优先级与下一步已写入矩阵 §3。

旅程 2/3 已补真实 Provider 证据（`docs/verification/v4-journey-2-3-goal-real.md`，deepseek-v4.1-flash）：普通问题不建 Goal/plan/card；明确能力目标自动建 `实现 PPO Clip`，真实 sidecar 重启后同 goal_id 恢复，续接回合仍绑定该 Goal。矩阵 P 列：旅程 2/3 由 PARTIAL/GAP 更新为 PASS，P 汇总 5 PASS / 4 PARTIAL / 11 GAP。

模块拆分与 SCIP 推进：Provider 失败文案提取到 `llm/provider/failure_copy.py`；Memory 证据队列投影提取到 `memory/evidence_view.py`；App Goal 标题推导提取到 `lib/coachGoalTitle.ts`；`LspScipProvider` 从占位改为读取 `scip print --json` 导出，生成 `scip_reference` 边并诚实处理缺失/二进制/非法 JSON。新增 14 项行为测试（Provider 3、Memory 2、SCIP 5、App 4）。

## 2. 修复清单（按目标阶段）

### 阶段一 P0 可靠性
| 缺陷（先复现后修复） | 修复 | 证据 |
| --- | --- | --- |
| `importer.py` 只注册前 100 个 source_items（第 101 个文件永不可索引） | 全量注册 + `source_item_count` 完整性统计 + MAX_FILES 响亮告警 | `test_v15_reliability.py`：120 文件全量注册、第 117 个可搜 |
| `incremental.py` git 失败返回 '' 被当作无更新 | `IncrementalUpdateError`（含 exit/stderr）；`refresh_project` 返回 `ok:false/git_pull_failed` 且不暴露新符号表；本地无 upstream 诚实标 `skipped_no_upstream` | 同上：坏 ref 必抛、无上游跳过、无远端失败显式 |
| Skills 审核绕过：register 可预批准 action | action 一律钳制未审核，唯一入口 `mark_reviewed` | `test_skill_registry` |
| 审核备注 persist 后写入 → 重启丢失 | note 在 `mark_reviewed` 内持久化 | 重启断言 |
| 审核版本漂移：SKILL.md 改动后仍视为已审核 | 审核钉 content sha256；stale 拒激活且选择器不注入 | `changed on disk` 断言 |
| applied 依赖回复出现技能名（假机制） | 证据驱动：声明工具真实执行 → 契约标记命中 → skill_id 引用兜底，全量记入 `last_evidence` | 真实模型：4635 字讲稿 `applied=true, basis=contract_markers, cited=false` |
| agentic 注入竞态：skill_registry 仅路由惰性创建 | `runtime_skill_registry()` 单源惰性创建，两条 agentic 路径共用 | `test_skill_lifecycle`（list/选择同源） |
| HashingEmbedder 用 builtin hash（PYTHONHASHSEED 随机化 → CI 排序翻转） | SHA-1 固定桶 + 回归测试 | 向量跨种子逐位一致 |

### Release 对账（阶段一）
- v1.4.0：tag=`2f1bb68`、manifest sourceCommit 同、资产 sha 与 manifest 一致（`release-reconciliation-v1.4.0.md`）
- v1.4.1：tag=`adbf93a`、manifest sourceCommit 同、dirty=false、linux sha `149bbb92…` 与 manifest 一致（`release-reconciliation-v1.4.1.md`）

### 阶段二 知识底座与项目理解
- **Analysis Adapter**：tree-sitter-python 真实 AST（`syntax_exact`）、regex 近似（`approximate`）、LSP/SCIP 占位诚实报 `available=false`；合并取高证据等级；`limitation_summary` 汇总；`GET /project/analysis` 治理同 impact。
- **Resources 项目详情图谱**：`GET /project/summary` 单次有界取数（模块/入口/调用边/提供者/limitations）；独立 details 面板、首次展开才请求、八语种、错误仅本地化通用文案；不新增一级入口。
- **分层检索**：broad/narrow/verify 180/300/420 字符 excerpt 预算（超限截断标 `truncated`，引用字段不动）+ `read_resource_excerpt` 下一层入口；`search_cache_stats()` hits/misses/hit_rate/ttl 随工具响应返回。

### 阶段三 Skills / 教学闭环
- **教学质量五维**（`GET /teaching/quality`）：独立解题、提示有效性（受助通过率）、难度适配（0.4–0.85 健康带，带外读作 too_hard/too_easy）、跨项目迁移、引用完备率；样本 <3 = `insufficient_evidence`，不伪装 0/1；文字质量明示留人工。
- **Skill 生命周期统一**：`version` 内容变更递增；失败 streak → `failing` → 3 次 `quarantined`（停止注入，`retryable=false`）；成功清零；`POST /skill/retry` 恢复；`/skill/list` 与 agent 选择同一 registry/同一序列化。

## 3. 测试结果（本机真实运行）

| 套件 | 结果 |
| --- | --- |
| server pytest | **3941 passed / 0 failed**（28 subtests；含 FSRS、Goal、Evidence、Skill workspace、SCIP、模块拆分回归） |
| 新增行为测试 | `test_v15_reliability` 3、`test_project_analysis` 5、`test_harness_retrieval` 5、`test_teaching_quality` 3、`test_skill_lifecycle` 5、`test_skill_api` +1、`test_builtin_teaching_skill` 7 |
| extension（node:test） | exit 0，0 断言失败（含图谱面板守卫、Settings 模型选择器水合状态守卫） |
| tsc（extension+webview） | clean |
| verify-ui-geometry | **477/477** |
| verify:webview-recovery | `ok:true` |
| verify:credentials | 16125 文件 / 0 findings |
| verify:delivery | exit 0（verify + experience matrix + 打包） |
| bundled 镜像完整性 | 24/24 |
| ruff / pyright | clean |

## 4. CI 证据

| 工作流 | run | 结论 |
| --- | --- | --- |
| ci（main `4407d96`） | 42481015260 | success |
| Cross-Platform Verify（main `4407d96`，linux 构建 ubuntu-22.04） | 42481015243 | **success（9/9）** |
| Trainer Nightly Remote-SSH E2E（`2a45b00`） | 42474532862 | success |
| release（v1.4.1） | 42270707628 | success（三平台 VSIX + Release 发布） |

## 5. 跨平台安装证据

- **v1.4.1 官方资产**：`trainer-extension-1.4.1-{darwin-arm64,linux-x64,win32-x64}.vsix` + build manifest；linux 构建基座 ubuntu-22.04（glibc 2.35）。
- **141s（Ubuntu 22.04, x86_64）**：远端 VS Code Server CLI 安装成功 → `local.trainer-extension@1.4.1`；`--list-extensions --show-versions` 核验；bundled sidecar `--help` exit 0；`--host 127.0.0.1` 启动后 `/health` = `{"status":"ok","initialized":true,...}`。
- **发现并修复的发布缺陷**：v1.4.0 linux 资产要求 GLIBC_2.38，在 22.04 启动失败；v1.4.1 已替换。旧 v1.4.0 资产仍含缺陷（已被 v1.4.1 取代）。
- 已知事实：PyInstaller 产物跨 run 字节级不可复现，对账锚点为 `sourceCommit` + `sourceSnapshot.sha256`，非跨 run 的 VSIX 哈希。

## 6. 真实学习旅程与真实模型证据

- **11 步真实模型旅程**（`docs/maturity/p4-journey-2026-11-06/`）：理解轮 3154 字并引用真实锚点 `¶chunk:0@1`；sidecar 重启会话还原；切工作区零泄漏；M3.1-Flash↔M2.7 热切换；记忆摘要。
- **真实 Provider 回归**（`docs/maturity/2026-11-06-p4-real-provider.md`）：连通、完整教学轮、长讲义（2068 字完整落库）、工具成功 grounding、新会话首条 = **5 PASS + 1 NOT_EXECUTED**（空响应无法在健康网关强制；脚本化测试覆盖）。
- **RethinkFun 教学法真实模型**（MainMiniMax-M3）：4635 字状态流讲稿（旧方案失败先行、缺口推进、零空话）；`/skill/list` 证据 `applied=true, basis=contract_markers, markers=[缺口,失败,旧方案,为什么,状态], cited=false`。
- **回复格式矩阵**（`docs/verification/2026-11-07-message-format-matrix.md`）：
  行内/块级/`\(...\)`/`\[...\]`/反引号公式/```math/表格内公式/裸 aligned/转义美元/非法公式
  均有确定路径；粗体、斜体、删除线、行内代码、链接、单换行、标题、引用、列表、任务、分隔线、
  脚注、上下标、化学式、表格、Mermaid 同条回复共存（`formats-dark.png`）。
- **单色与 1 秒门禁**：`--accent`/`--link`/焦点环/状态色全部中性；`verify:local-latency`
  实测五条本地动作 34–384ms。
- **四屏真实 VS Code 审计**（真实 Electron + v1.4.1 VSIX + 真实 MiniMax）：
  Coach（完成横幅移除）、Learning（过程叙事/自检句过滤）、Resources（单一导入主操作）、
  Settings（模型选择器水合后收起、单句连通通知）；每屏均以真实截图 + 结构断言取证，
  证据见 `docs/verification/2026-11-07-{coach,learning,resources,settings}-screen-audit.md`。

## 7. Token 与性能基准

| 基准 | 门禁 | 状态 |
| --- | --- | --- |
| `bench:token`（全仓库 vs RAG vs 分层） | layered < full 且 localization_hit_rate ≥ 0.75 | ✅ 通过（历史实测分层约 80×↓） |
| `bench:incremental`（同仓库二次分析） | incremental_ratio ≤ 0.20 | ✅ 通过 |
| `bench:provenance`（引用可验证率） | ≥ 0.95 | ✅ 通过 |
| 检索预算 | broad/narrow/verify 180/300/420 字符；全库无差别注入被截断+`truncated` 标记 | ✅ 行为测试 |
| 缓存透明 | hits/misses/hit_rate/ttl 随 `search_resources` 返回 | ✅ 行为测试 |

## 8. 缺陷清单与风险分级

| 级别 | 缺陷/风险 | 状态 |
| --- | --- | --- |
| P0（已修） | importer 100 项截断；incremental git 失败误判；skill 审核绕过/备注丢失/版本漂移；applied 假判定；linux glibc 阻断；PYTHONHASHSEED flake；agentic 注入竞态 | ✅ 已修 + 测试 |
| P1（未完成） | **Remote-SSH 真窗口 2–6 步**：证据文件仍 PENDING-HUMAN（第 1 步自动化 PASS、后端 /health 实测 PASS） | ⏳ 需人工窗口 |
| P1（部分完成） | 阶段四逐屏真实 VS Code 审计：Coach ✅（314432a）、Learning ✅（fa26203）、Resources ✅（0af9b19）、Settings ✅（`docs/verification/2026-11-07-settings-screen-audit.md`） | ✅ 四屏完成 |
| P1（部分完成） | **巨型模块按职责拆分**（App/API Router/Provider/Memory/Resources）；禁止并行状态源 | 🟡 已拆 `coach_language_alignment`、`provider_payload`、`resources/libraryPaths`；App/Provider/Memory 未拆 |
| P2（部分完成） | **LSP 已接入**（`pylsp` 真实 JSON-RPC references，证据级 `lsp_reference`，可选依赖，失败时如实 unavailable）；SCIP 索引解析仍未接入（占位 + reason） | ✅ LSP / ⏳ SCIP |
| P2（已完成） | 项目分析知识自动沉淀为 Knowledge Skill 并关联资料库/Coach/计划（15c8088；`distill_project_knowledge` + 行为测试） | ✅ |
| P2（未完成） | 按需多模态（扫描 PDF/图表） | ⏳ 未开展 |
| P3（已完成） | `verify:delivery` 在本轮 HEAD 上的完整矩阵 | ✅ exit 0（verify + experience matrix + 打包，1.4.1 VSIX 产出） |
| P3（已知限制，已记录） | 教学质量报告仅学习证据维度，文字准确性留人工；难度带为产品策略非个体校准 | 文档明示 |
| P3（已知限制，已记录） | provider_error/timeout 计入技能失败 streak（可用性信号，非质量判断） | 文档明示 |
| P3（已闭环） | L2 六步 **6/6 PASS**（2026-11-08 新连接 minimax-m3，第 4 步真实回复 259 字）；辅助“测试连接”按钮自动化仍未观测 verified，单独记录 | `docs/verification/remote-ssh-l2-141s-evidence.md` |

## 9. 未完成项（如实）

1. Remote-SSH L2：六步 6/6 PASS（2026-11-08 新连接、真实窗口、第 4 步 259 字真实回复）；旧 provider 429 记录保留为历史。辅助 provider 测试按钮的自动化观测问题仍待修，不作为六步替代证据。
2. 阶段四剩余：App/Provider/Memory 巨型模块拆分、按需多模态理解；Resources 已抽出 `libraryPaths` 纯责任，四屏真实 VS Code 审计已完成。
3. SCIP 索引解析接入（LSP 已接入）；Understand Anything 适配。
4. 最终人工教学验收（主观质量）——自动化维度已给出，主观评审仍留人工。

## 10. 完成标准说明

以目标原文为准：**“真实用户能够持续、可靠、自然地完成完整学习旅程”**。
代码、测试、跨平台安装与真实模型证据已覆盖工程与后端可靠性；
L2 第 2–6 步与阶段四属于产品体验层，尚未验收 —— 本报告不宣称“彻底成熟”。
