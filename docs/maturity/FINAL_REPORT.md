# Trainer 成熟化最终交付报告

## 摘要（TL;DR）

- **结论：教学主链 partial——机制已闭环，教学质量未验收。**
- **真实模型调用：0 次。** 28 案例夹具本地真实跑通，56 个模型回合全部 `skipped_no_credentials`（无合规凭证）。本报告不含任何「真实模型通过」结论。
- **本轮最实质的修复**：CI 自 `86b73d4` 起连续全红的根因（`server/app/api/routers.py:21474` pyright 诊断）已真修复；四流程 grounding 统一接线、诚实降级 + 前端消费端、记忆 provenance 准入、两个确定性门脚本（凭证/pyright）均已落地。
- **合并状态：未合并。** 分支 `maturity/teaching-loop`（HEAD `2bca8d1`）与 `origin/maturity/teaching-loop` 同步（0 ahead/0 behind），比 `origin/main`（tip 仍为 `d2e30f4`）多 3 个提交；本任务禁止直接推 main，**是否以 PR 合入 main 由 owner 决定**（见 §7.3）。
- **待人工处置**：历史提交与本地未跟踪文件中的疑似真实凭证需轮换（见 §7.2）。
- **诚实性状态**：独立复核对第 2 轮产物给出 `honest=false` 的 4 条问题，均已在第 3 轮修复（证据见 §4.3）；修复后的 harness 尚未在真实凭证下运行过。

## 0. 阅读须知：证据来源标识与术语

### 0.1 证据来源标识（全文统一使用）

| 标识 | 含义 |
|---|---|
| **[本次运行]** | 由我在本会话内执行的命令（如定向 pyright、git/grep/读文件），命令与输出可即时复现 |
| **[lane 记录]** | 由执行 lane 在其回合内运行并记录在任务输入材料中的命令与结果（我未重跑） |
| **[编排记录]** | 编排脚本的验证门/收尾记录（任务输入材料；编排运行完整套件，我未运行） |
| **[审计]** | 任务输入中的三线只读审计结论（行号可能随本轮改动漂移） |
| **[复核]** | 任务输入中的「验证真实性复核」「独立读者反馈」等独立视角结论 |

### 0.2 术语

- **grounding / 接地**：校验教学回复中的下一步（及正文断言）所引用的符号/文件是否真实存在于本回合事实中，防止「要求不存在的函数/文件」。
- **claim / 断言**：一条可独立判定的最小事实引用（如某个符号被要求存在），而非整段文本。
- **锚定 / anchor**：该断言的值能在语料（正文 ∪ 代码 ∪ 历史 ∪ 工具核验事实 ∪ 学习者已给事实）中找到出处。
- **provenance / 来源标注**：每条事实的证据等级——`tool_verified`（工具/文件系统核验）> `learner_provided`（学习者本回合给出）> `model_claim`（模型自述）> `local_fallback`（本地兜底产出）。
- **downgraded / 降级**：未过接地的下一步不再作为「计划就绪指令」下发，而是标记为 `requires_confirmation`（需确认的建议）并写入响应 `agent_meta`。
- **pre-persistence helper**：在「持久化回合记忆」之前统一执行的同一段装配逻辑（本设计新增 `resolve_turn_grounding_async` → `apply_grounding_decision`）。
- **host 三跳**：服务端字段 → 扩展宿主映射 → webview 渲染的传递链（三层不得丢字段）。
- **body 级幂等去重**：即使请求重放，也应保证「已执行过的持久化动作」不被二次执行（当前仅靠 workspace 单槽账本，见 §7.4）。

### 0.3 判据 M1–M5（定义取自 `docs/maturity/teaching-case-matrix.md:30-35`，[本次运行] 读取）

- **M1 机制**：预置代码 `exit≠0`；脚本化修复后 `exit=0`；同一 session；回合 HTTP 200；同一工作区 body/disk 源码一致（不一致判 harness-invalid）。
- **M2 接地**：服务端 `agent_meta.grounding_outcome ∈ {grounded, corrected}` 且 `next_step_requires_confirmation=false` 才算教学 pass；`downgraded` 是接地失败证据，**不得算教学通过**（分类器已锁死 + 回归测试）。
- **M3 记忆**：`coach_anchor`/`current_focus` 非空或诚实为空、不得等于消息前缀；两回合间主题 token 至少保留一个；恢复回合不得把 `local_fallback` 写成 verified mastery。
- **M4 反模式**：正文与 next_step 同域不冲突；不重复索要第 1 回合已给事实；不要求对话与代码中不存在的函数/调用点/文件。
- **M5 对账**：服务端 `agent_meta` 戳与 harness 本地复算（同源输入：累积历史、本回合学习者消息、workspace 根文件核验器）逐回合比对；`downgraded` 时两侧未锚定符号集合须相等，`corrected` 时改为复评修正文本且须 grounded；不一致判该回合失败。
- **内容质量（独立评审栏）**：事实准确、难度适配、direct/guided 尊重、篇幅——由独立评审 agent 读最终回复后填写，标注「待 owner 确认」，**不计入 M1–M5 自动判定**。

**门强弱一览**（对 M1–M5 的一个诚实小结）：M1/M2/M5 为硬门（不满足即该回合 `failed`）；M3 目前仅部分设门（主题 token 仅记录、未判 failed）；M4 无独立本地检查，经 M5 对账间接暴露。

## 1. 分支、提交与变更文件

- 分支：`maturity/teaching-loop`；HEAD `2bca8d1`（`2bca8d15a33ed02704b4514a51d14647a0a3a5d4`）。
- 相对基线：`d2e30f4`（任务书给定；`origin/main` 的当前 tip 也是 `d2e30f4`）。
- 三轮检查点：`5a60f01`（第 1 轮）→ `3c548f3`（第 2 轮）→ `2bca8d1`（第 3 轮）。
- 合并关系 **[本次运行]**：`git branch -r --contains 2bca8d1` → `origin/maturity/teaching-loop`（已推送）；`git log --oneline -1 origin/main` → `d2e30f4`；`git rev-list --count origin/main..HEAD` → `3`。即：**本分支领先 main 3 个提交、未合并**。
- 规模 **[本次运行]**：`git diff --stat d2e30f4..HEAD` → 74 files changed, 10596 insertions(+), 1546 deletions(-)。
- **`docs/maturity/FINAL_REPORT.md`（本文件）为新增未跟踪文件**（`git status --porcelain` → `?? docs/maturity/FINAL_REPORT.md`，[本次运行]），因此不计入上述 74 与行数统计；本报告的入库由编排/owner 决定。

### 1.1 变更按域对账 **[本次运行]**（`git diff --numstat` 分组）

| 域 | 文件数 | +行 | -行 |
|---|---|---|---|
| `server/app/` | 9 | 2054 | 175 |
| `extension/bundled/`（镜像副本） | 9 | 2054 | 175 |
| `scripts/` | 6 | 2146 | 294 |
| `extension/webview/` | 19 | 1834 | 827 |
| `server/tests/` | 5 | 1619 | 2 |
| `docs/`（不含本文件） | 4 | 507 | 0 |
| `extension/tests/` | 16 | 300 | 69 |
| `extension/src/` | 4 | 78 | 2 |
| `package.json` | 1 | 3 | 1 |
| `AGENTS.md` | 1 | 1 | 1 |
| **合计** | **74** | **10596** | **1546** |

按域看，改动主体在 `server/app/`（含 bundled 镜像）与 `scripts/`（新门 + harness），其次为 webview 与 server 测试；逐文件清单见提交结果 `changedFiles`（74 条，本文件不再重复）。

### 1.2 关于 maturity 脚本的「改名 + 整体重写」（澄清）

- 旧文件 `scripts/maturity/real-teaching-journeys-minimax.py`（连字符命名，288 行，`d2e30f4` 新增）：**已删除**。
- 新文件 `scripts/maturity/real_teaching_journeys_minimax.py`（下划线命名，1835 行）：**新增**，是旧脚本的**整体重写 + 改名**（非同一文件的原地改名，故 diff 显示为「新增 + 删除」）。
- 因此 §2 中标注「旧 `<连字符文件>`:行号」的定位，指的是**被删除的那个 288 行文件**；涉及新版行为的定位一律写全下划线文件名。
- **扩展 guard 文件说明（16 个）**：闭环记录中明确给出对应关系的有 6 个——`providerDraftSyncSource`、`operationMessageSurfaceScopingSource`、`operationMessageGovernance`、`coachProviderSetupSource`、`settingsProviderTemplateFocusSource`（R2 provider/操作反馈迁移）与 `trainingReturnBridgeSource`（R1 训练域）；其余 10 个（`coachConversationSource`、`coachMessageActionsSource`、`coachStreamingPlaceholderSource`、`codeBlockLanguageConsistencySource`、`docxPreviewSanitizerSource`、`httpClient`、`packageScripts`、`planGovernanceActionsSource`、`sessionCommands`、`skillCatalogI18nSource`）的逐个改动原因**未在任务输入材料中记录**，本报告不代为解释，仅列名。

## 2. 已复现问题、根因与真实代码修改（修复 F1–F27）

格式：**定位**（文件:行）→ **根因** → **修复** → **复核**。复核均标注来源；[lane 记录] 表示由执行 lane 运行并记录、我未重跑。

### 教学事实（teaching，F1–F13）

**F1 — next_step 判定「任一符号命中即整条放行」+ 纠错文本被丢弃**
- 定位：旧 `server/app/llm/turn_grounding.py:232-240`、`:368-381`。[本次运行] 读取确认（该 388 行版本）。
- 根因：判定是整条步骤的**或运算**；复评成功不返回文本，调用方无法写回修正。
- 修复：claim 级提取 + 逐断言全量锚定（每条含符号断言的所有符号都须有锚点）；`GroundingDecision` 增补 `corrected_next_step`；retry 至多一次，空再生判失败降级。
- 复核：[lane 记录] `pytest tests/test_turn_grounding.py -q → 38 passed`（含 `test_every_symbol_of_a_claim_must_anchor`、`test_corrected_next_step_carrier_and_corrected_outcome`）。[本次运行] 确认新实现位置 `turn_grounding.py:801 build_teaching_turn_facts`、`:1189 evaluate_turn_grounding`。

**F2 — 工具链白名单含项目名词**
- 定位：旧 `server/app/llm/turn_grounding.py:46-48`。[本次运行] 读取确认。
- 根因：白名单按「常见词」罗列而非「语言内置/命令词」。
- 修复：移除 `log/todo/fixme`，保留 `print/console` 等语言内置与命令词。
- 复核：[lane 记录] `test_whitelist_drops_project_nouns_but_keeps_builtins`。

**F3 — 文件指针整体放行**
- 定位：旧 `server/app/llm/turn_grounding.py:189-198`、`:51-57`。[本次运行] 读取确认。
- 根因：一刀切「前向引用」，缺核验输入与「不可核验」语义。
- 修复：`file_path` 成独立 claim，先语料锚定、再经注入 `file_exists` 核验；无核验器/远端/None → `unverifiable`（不降级、不冒充已核验）。
- 复核：[lane 记录] `test_file_pointer_checker_semantics_and_unverifiable_escape`、`test_unverifiable_flag_overrides_a_checker`；runtime 注入点（[lane 记录] 行号）`server/app/api/routers.py:10693-10707`。

**F4 — 多 token 字面量产出标点垃圾 claim**
- 定位：旧 `server/app/llm/turn_grounding.py` 的 `extract_code_symbols`/裸 token 启发式。[本次运行] 读取确认。
- 根因：空白切分片段直接套 snake_case/camelCase 启发式。
- 修复：子 token 剥尾标点、仅保留合法标识符且排除语言关键字（新增 `_LANGUAGE_KEYWORDS`）。
- 复核：[lane 记录] `test_multi_token_code_literal_keeps_significant_sub_tokens`。

**F5 — claim 键与域归一化缺失**
- 定位：旧 `server/app/llm/turn_grounding.py`（只有符号抽取）。[本次运行] 读取确认。
- 修复：`claim_key(kind,value)` + `claim_domain(fact)`（file_path 路径归一：反斜杠→/、去 ./；符号保大小写）。
- 复核：[lane 记录] `test_claim_key_and_domain_normalization`。

**F6 — 本地 venv 缺 Pillow 阻塞测试收集**
- 定位：本地 `server/.venv`。根因：未按 `pyproject.toml` 安装 `Pillow>=12.0.0`。
- 修复：环境安装（不改产品代码）。复核：[lane 记录] 安装后 import 成功，收集由报错转为 21 → 最终 38 passed。

**F7 — 28 组案例无规格工件**
- 定位：`docs/maturity/2026-10-08-real-teaching-quality.md:12,90`（[审计] 引用）指出 0/28 pass、24 未执行。
- 修复：落盘 `docs/maturity/teaching-case-matrix.md`。
- 复核：[本次运行] 确认文件存在；并读取其 `:28-35` 确认客观判据 M1–M5 与独立评审栏已定义、`:45` 起为逐案例表。**未逐案审计矩阵完整性**（不超出「文件存在 + 判据已定义」）。

**F8 — retry_used 两层语义不一致**
- 定位：旧 `server/app/llm/turn_grounding.py` 规则层 vs `server/app/api/routers.py` 装配层。[本次运行] 读取确认（388 行版本规则层）。
- 根因：同一事实由两层各自决定；装配层预取空文本时短路。修复：统一「已尝试」语义；装配层总是经 `evaluate_turn_grounding` 路由；同步两侧测试断言。
- 复核：[lane 记录] `test_turn_grounding.py → 52 passed`；`test_api.py -k grounding → 5 passed`。

**F9 — 创建类指令被文件核验误判降级**
- 定位：`server/app/llm/turn_grounding.py` 文件核验路径 + `server/app/api/routers.py:10696-10710`（[lane 记录]）。
- 根因：只定义「无法核验=不降级」，未区分「指令就是创建该文件」。修复：`_CREATION_VERB_PATTERN`（多语言创建动词）→ 创建语境跳过存在性核验、结论 unverifiable。
- 复核：[lane 记录] `test_creation_instruction_never_trips_the_file_checker`（同上下文「查看」仍降级）。

**F10 — journey 脚本 sidecar 地址未限制（明文凭证风险）**
- 定位：`scripts/maturity/real_teaching_journeys_minimax.py` 的端点解析（[lane 记录] :113-138、调用点 :1471）。
- 根因：硬化只覆盖 provider 端点。修复：`sidecar_base()`——loopback 才 http，非 loopback 强制 https，显式明文远端 URL 直接 `RuntimeError`。
- 复核：[lane 记录] 三分支实测。

**F11 — 正文自锚定、重复索要无防护**
- 定位：`server/app/llm/turn_grounding.py` + `server/app/llm/reply_continuity.py`。[本次运行] 读取确认旧 `reply_continuity.py:16-44`（只提取不比较）。
- 根因：R1 只有「符号锚定」，reply 既是语料又是模型文本。修复：`reply_claims` verdicts（诊断不降级）+ `domain_backing` 排序 + `conflicts` 记录 + demand guard + `visible_next_step` 参与比较；显式误报预算（新引入 `enumerate` 永不冲突/降级）。
- 复核：[lane 记录] 4 个新测试 + 52 passed。

**F12 — 记忆写入不区分来源**
- 定位：`server/app/memory/service.py`（旧 `:7465-7528` 只做 sanitize）。[本次运行] 读取确认旧版本；确认新入口 `record_turn_reflection` @ `memory/service.py:7801`。
- 修复：新增 `record_turn_reflection` 与两个既有写方法接受 `memory_provenance`：next_step 仅 grounded|corrected；`local_fallback` 不写 focus/mastery；mastery 需 `tool_verified`/`learner_provided` 佐证；verified_result 需事实佐证；冲突 claim 字段+claim 级剔除。
- 复核：[lane 记录] 5 个新记忆测试 + 组合契约测试；`pytest test_turn_grounding+test_memory_language_context+test_memory_scope_isolation → 68 passed`；`pyright app/memory/service.py → 0 errors`。

**F13 — 28 案例 harness：规模/分类/对账（含第 3 轮对复核问题的修复）**
- 定位：旧 `scripts/maturity/real-teaching-journeys-minimax.py`（[本次运行] 读取确认 288 行、4 案例、`:28` 硬编码凭证、`:31` 明文 http）。
- 修复：交付 `scripts/maturity/real_teaching_journeys_minimax.py`（[本次运行] `ls` + `git diff --stat` 确认存在/1835 行）：28 案例（7 类 × 4，A 真实代码错误/B 复杂调试/C 跨语言迁移/D 原理教学/E 项目适应/F 进阶用户/G 长期恢复）、逐回合分类 + M5 同源对账、凭证仅环境变量、无凭证 skipped；旧脚本删除。
- 第 3 轮对复核问题的修复（[本次运行] 逐处读码确认）：
  - `real_teaching_journeys_minimax.py:1533-1543`：`server_outcome == "downgraded"` → `grounding_pass = False`（永不 pass）；`:1582-1586` `passed` 需 `grounding_pass && reconciliation=="ok" && !drift && body_disk_consistent`。
  - 回归测试 `server/tests/test_maturity_harness_classification.py:73 test_downgraded_server_turn_is_never_passed`（同文件另有 :273 `test_classification_enum_has_no_unreachable_members`）。
  - `:13-14` 明示「this harness has no mock path」；`docs/maturity/teaching-validation.md:21/:22` 自检更正为「M1/M2/M5 硬门；M3 仅记录信号；无 mock 通路」。
  - 工作树干净（[本次运行] `git status --short` 为空），脚本随 `2bca8d1` 入库；`teaching-validation.md:4` 更正提交说明。
- 复核：[lane 记录] 夹具 28/28 本地真实通过（pre-fix exit=1 / post-fix exit=0）、56 回合 skipped。**修复后的 harness 未在真实凭证下运行过**（未验证项，见 §7.1）。

### 前端（frontend，F14–F20）

**F14 — Rules of Hooks 违例 + hook 返回值不稳定**
- 定位：`extension/webview/src/app/App.tsx:10131`（+ `:10141` eslint-disable）。[本次运行] 读取确认。
- 根因：为拿稳定引用把 hook 调用塞进 `useMemo` 回调；该 hook 原返回新字面量（任务书「返回值本就稳定」的假设不成立）。
- 修复：hook 内 `useMemo(...,[])` 返回稳定对象，App 顶层直接调用，删 eslint-disable，活动文件路径改 ref 快照。
- 复核：[lane 记录] webview `tsc --noEmit` 退出 0；grep 已无 `useMemo(() => use[A-Z]` 模式。

**F15 — 训练卡 guidance 字段被静默丢弃**
- 定位：`extension/webview/src/components/training/TrainingWorkbenchView.tsx:2364`（selfCheck）、`:2544`（resolvedFallbackAction）、`:924-1536`（stuckRecoveryLabel）。[本次运行] 读取确认现存实现；三处 0 渲染为 [审计] 结论。
- 修复：在既有 task-details disclosure 渲染 selfCheck/commonMistakes/恢复指引，复用 8 语言文案并补 `selfCheckLabel` ×8，保持首序契约。
- 复核：[lane 记录] 3 个定向 `node --test` 文件退出 0 + webview tsc 退出 0。

**F16 — 跨层英文文案契约脆弱**
- 定位：`extension/webview/src/app/App.tsx:4510` ↔ `extension/src/commands/memoryCommands.ts:130`。[本次运行] 读取确认。
- 修复：改 `[[trainer-learning-feedback:{requestId}]]` marker + requestId 校验才清 busy。
- 复核：[lane 记录] 往返校验 5 例 OK；extension tsc 退出 0；grep 确认英文文案仅剩发送侧兼容分支。

**F17 — requires_confirmation 无消费端**
- 定位：全仓仅类型声明 `extension/webview/src/lib/types.ts:575`。[本次运行] grep 确认（`requires.?confirmation` 大小写不敏感，webview/shared 仅此一处；`extension/src/commands/sessionCommands.ts:214/219` 是无关的 organize_resources 字段）。
- 修复：新增 `extension/webview/src/lib/nextStepConfirmation.ts` 归一化 + `copy.ts` 8 语言文案，在 next_step artifact 卡与 `coach_visible_status` 下一步行渲染；R2 由 host 补齐三跳——服务端 artifact metadata `next_step_requires_confirmation` → `extension/src/core/workbenchData.ts:6228 mapCoachTurn` / `:3132 nextStepRequiresConfirmation` → 流式终帧 payload（`sessionCommands.ts`）。
- 复核：[lane 记录] 渲染级实测（带/不带标记各 2 例：`data-next-step-requires-confirmation="true"`、`建议先确认`）+ 归一化 11/11 单测。[本次运行] 确认 `nextStepConfirmation.ts`（65 行）与 `workbenchData.ts:6228/:3132` 存在。

**F18 — 训练域 split-brain**
- 定位：`extension/webview/src/app/App.tsx`（旧 `:3733-3812/:4348-4453/:4474-4523/:4552-4569/:12693-12734`，[lane 记录]）。[本次运行] 读取确认旧版状态声明与 host 拦截分支。
- 修复：新增 `extension/webview/src/app/useTrainingCardController.ts`（[本次运行] 确认 339 行）承接状态 + 请求身份 + host handler + 生命周期清理；删死 ref `trainingRouteDraftsRef`。
- 复核：[lane 记录] webview tsc 退出 0；5 个相关 guard 29 项通过。

**F19 — 操作反馈五通道、surface 与消息非原子**
- 定位：`extension/webview/src/app/App.tsx`（旧 `:3719/:3746/:3766/:3821`）+ `useWorkbenchState.ts`。[本次运行] 读取确认旧五处状态。
- 修复：新增 `useOperationStatusController.ts`（[本次运行] 确认 101 行）+ store 单通道 `operationBannerState` 强制同写 surface；删死状态 `operationMessageLeaving`。
- 复核：[lane 记录] 78 处 `setOperationMessage` 全部经控制器 setter（grep）；定向 guard 退出 0；webview tsc 退出 0。

**F20 — providerDraft 手抄四遍 + ProviderFacts 双副本**
- 定位：`extension/webview/src/app/App.tsx`（旧 `:3677/:3713-3730/:4906-4950/:4974-4992/:4882-4904`）+ `extension/webview/src/app/useWorkbenchState.ts:160-183,675`。[本次运行] 读取确认 `providerDraft` 与调和逻辑。
- 修复：`useProviderConnectionController.ts`（[本次运行] 确认 327 行）单一 `DRAFT_FIELDS` 字段表；`connection.provider` 改为 `providerSummaryFromFacts(mergedProviderConfig)` 单向投影。
- 复核：[lane 记录] 40 组合行为矩阵 + 9 个 settings guard 退出 0；webview tsc 退出 0。

### 运行时（runtime，F21–F27）

**F21 — 疑似真实凭证硬编码 + 明文 http + Windows 路径**
- 定位：`scripts/maturity/real-teaching-journeys-minimax.py:28/:31/:24/:37/:208-217`。[本次运行] 读取确认。
- 修复：凭证仅环境变量（`require_env`）；`secure_provider_base_url` 对非 https 且非 loopback 端点拒绝发送凭证；路径改仓库相对 + `sys.executable` + 环境变量；旧文件删除；密钥标记**需人工轮换**。
- 复核：[lane 记录] `ruff check` 通过；`py_compile` OK；无环境变量运行 exit=1 且明确报错；端点守卫正反两向实测；grep 确认文件内已无 `sk-`/`G:/`/http relay 字样。**密钥值全程未输出**。

**F22 — `routers.py:21474` pyright 唯一诊断（CI 全红根因）**
- 定位：`server/app/api/routers.py:21474:32`。[本次运行] 修复前运行 `cd server && .venv/bin/python -m pyright app/api/routers.py` → `1 error, 0 warnings`（`reportArgumentType`：`CoachTurnPayload` 不能赋给 `dict[str, object] | None`）。
- 根因：TypedDict 对 `dict[str, object]` 的键集不变量不兼容，旧 helper 形参只声明了 `dict`。
- 修复：真修复——`ground_coach_turn_payload_before_persistence` 形参扩为 `CoachTurnPayload | dict[str, object] | None`，并在 `CoachTurnPayload` 声明 `NotRequired` 键 `requires_confirmation`/`_grounding_decision`；**未新增 Any/cast/ignore**；接线后旧 helper 无调用方即删除。
- 复核：修复前的 `1 error` 为 [本次运行]；**修复后的 0 error 为 [lane 记录] / [编排记录]**（`node scripts/run-server-pyright.mjs → exit 0, 0 errors, 0 warnings`；`npm run verify:server-pyright → exit 0`）——我**未在修复后复跑**该定向检查。全文两处 F22 表述以此条为准。

**F23 — 四持久化点各自求值、第二次复评、纠错未接线**
- 定位：`server/app/api/routers.py:20432`、`:21473`、`:22711`、`:24039`（持久化点）与 `:11307`（响应构建二次复评）。[本次运行] 逐处读取确认（`:20439/:21480/:22718/:24046` 为对应 persist 调用）。
- 根因：教学事实契约缺装配层——判定在两处各跑一次，retry 无 await 位置，修正文本载体未落地。
- 修复：新增 `resolve_turn_grounding_async`（[本次运行] 确认 `:10926`）→ `apply_grounding_decision`（[本次运行] 确认 `:10775`，幂等 + 缓存 `_grounding_decision` + agent_meta 固定键）→ `persist_turn_reflection(grounding_decision=...)`；`build_session_response` 消费缓存不复评；重试资格收紧。
- **纠错边界（补读者所问）**：重试仅在「`agent_meta` 含非空模型 next_step 且 provider live-usable」时尝试、至多一次；`fell_back`/本地兜底/恢复路径**跳过重试**直接降级；重试后仍 ungrounded → `requires_confirmation` 降级 + `grounding_outcome=downgraded` 戳；流式下纠错只改结构化 next_step（随最终快照下发），已下发正文不可改写。
- 复核：[lane 记录] `test_turn_grounding.py 37 passed`；`test_api.py -k 'turn or grounding or session_message'` 与前文件合计 134 passed；`test_router_stream_scenarios.py` 等 4 文件 173 passed；grep 确认 resolve/apply 各 5 处、四个 persist 传参齐全。

**F24 — 可靠性账本把已成功的 work 记成 failed/cancelled**
- 定位：`server/app/training/reliability.py:282-286`。[审计] 定位。
- 修复：`mark_succeeded` 恒按 work 结果记 `succeeded`，竞态以 `cancel_after`/`timeout_after` 标注（不改转移表与单槽边界）；mixin 读同槽记录判定。
- 复核：[lane 记录] `test_training_reliability.py → 10 passed`（含 3 条新增）。

**F25 — 信任敏感写路径 workspace 归属可污染**
- 定位：`server/app/api/runtime.py:791-812`。[本次运行] 读取确认（显式优先、session 缺失静默回退 `latest_session()`/`DEFAULT_WORKSPACE_ID`）。
- 修复：新增 `resolve_workspace_id_for_write`（[本次运行] 确认 `runtime.py:825`）——显式与 session 不一致→409、无法建立绑定→409、绝不回退；`server/app/api/routes/learning.py` 四个写路由改用；`server/app/api/routes/training_attempts.py` evidence 路由校验声明 workspace 与 attempt 绑定一致。
- 复核：[lane 记录] `test_api.py -k 'attest_rejects or attest_refuses or attempt_evidence_rejects' → 3 passed`，+既有 31 passed，`-k 'turn or grounding or session_message or attest or evidence' → 102 passed`。

**F26 — provenance 未透传 + 流式缓存指纹缺失 + 终帧缺字段**
- 定位：`server/app/api/routers.py`（缓存/传参）、`server/app/memory/service.py`（消费）、`extension/src/core/workbenchData.ts` + `extension/src/commands/sessionCommands.ts`（host 三跳）。[lane 记录] 定位。
- 修复：`memory_provenance_summary` 缓存到 payload 私有键并传参；缓存增 `_grounding_evaluated_next_step` 指纹（防 preparation 旧决策被流式遍消费）；`/turn/stream` 最终文本重跑 resolve+apply；服务端 artifact metadata 盖戳。
- 复核：[lane 记录] 指纹回归红绿验证（禁用→该测试失败；恢复→`test_router_stream_scenarios.py 26 passed`）+ `test_api.py -k passes_grounding_memory_provenance → 1 passed`。

**F27 — 门脚本缺失**
- 定位：CI 只在 `.github/workflows/ci.yml:51-53` 内部运行 server pyright（[审计]），本地无对应入口，凭证无扫描器。
- 修复：新增 `scripts/verify-no-plaintext-credentials.mjs`、`scripts/run-server-pyright.mjs`（[本次运行] `ls -la` 确认存在，1970/8123 字节）并接入 `package.json`/`scripts/verify-workspace.mjs`/`scripts/run-verification-matrix.mjs`。
- 复核：[编排记录] 凭证门 `passed (8729 files scanned, 0 findings)`；阳性对照（历史违规副本，非真实构建产物）精确命中 `:28`/`:31` 且非零退出。**限制**：该门模式集（sk- 长串/Bearer/JWT/api_key 赋值/非本地明文 http + 合成 fixture 白名单）对 base64、`.env`、其它形态**无对照样本**，0 findings 只说明「未命中其模式集」，不代表全形态覆盖（详见 §6）。

## 3. 七条核心能力链与教学主链闭环状态

状态口径：**closed** = 机制完整且有代码/测试证据；**partial** = 机制在但缺真实模型/端到端验收或缺一环；**open** = 缺失。证据来源逐格标注。

| 链 | 能力链 | 状态 | 证据（来源） |
|---|---|---|---|
| C1 | 意图理解 | partial | `infer_learner_signal` @ `server/app/api/routers.py:13991`、`infer_coaching_scenario` @ `:14018`、`resolve_coach_turn` @ `:7745`（[本次运行] grep）；active_thread 继承（[审计]）。机制在；真实模型意图准确率未采样 |
| C2 | 水平判断 | partial | `infer_learner_state` @ `server/app/pedagogy/service.py:404`、`model_learner_state` @ `routers.py:16550`、技能投影 @ `routers.py:7840`（[本次运行] grep）。未在真实回合上校准 |
| C3 | 问题归因 | partial | agent 工具链（read/diagnostics/verify）可用但非强制（[审计]）；claim 级接地阻断虚构符号 @ `server/app/llm/turn_grounding.py:1189`（[本次运行] grep）；无独立归因评估器 |
| C4 | 策略选择 | partial | `decide_teaching` @ `server/app/pedagogy/service.py:490`（[本次运行] grep）+ affect 接入 `build_coach_context` @ `routers.py:18345`（[本次运行] grep）；提示词子句（[审计]）。真实模型策略适配未采样 |
| C5 | 解释启发 | partial | 仅提示词层引导（[审计]）；接地已能拦事实虚构，但**解释质量无结构化校验**（本设计明确 nonGoal，见 §7.4） |
| C6 | 训练验证 | closed | 证据恒 `self_reported` @ `server/app/api/routes/training_attempts.py:176`（[本次运行] 读取，见 F22 同批会话早期）；host 可信证据白名单 @ `server/app/api/routes/learning.py:160,177`（[本次运行] grep）；可靠性诚实化（F24）；已验证卡重放防御 @ `server/app/memory/service.py:7980-7983`（[审计]）；降级渲染端到端（F17）；**支撑测试**：`test_training_reliability.py 10 passed`、`test_api.py -k attest/evidence 31 passed`（[lane 记录]） |
| C7 | 证据记忆与个性化 | partial | provenance 准入 @ `server/app/memory/service.py:7801` + `memory_provenance_summary` @ `turn_grounding.py:892` + anchor 防漂移 + 下一轮 `build_coach_context` @ `routers.py:18345`（[本次运行] grep）。记忆质量与长期个性化未经真实模型验证，且有 deferred 缺口（§7.4） |

**完整教学主链结论：partial（机制闭环、质量未验收）。**
- 已闭环机制：四流程（`/turn`、`/session/message`、`/session/message/stream`、`/turn/stream`）在四个持久化点（`routers.py:20432/21473/22711/24039`，[本次运行] 逐处确认）前统一走同一 pre-persistence helper，每回合决策至多一次、纠错至多一次；ungrounded → 诚实降级（`requires_confirmation` + `agent_meta` 固定键 `grounding_outcome`/`grounding_ungrounded_symbols`/`grounding_retry_used`/`next_step_requires_confirmation`）；降级有前端渲染消费端（F17）；记忆写入按 provenance 字段级准入（F12）。
- 未闭环：「真实模型教学质量」未执行验收（56 回合 skipped）；独立复核指出的分类器虚假成功路径已在第 3 轮修复（F13），但修复后的 harness 未在真实回合上运行过。
- **四条「全绿」门的效力边界**：指 `npm run check`、`scripts/run-server-pyright.mjs`、凭证门、`npm run test:server`（第 1/3 轮为前四门；第 2 轮以 `test:extension` 替换 `test:server`；最终门再加 `test:experience-matrix` 与 `verify`）——**由编排脚本在本仓库工作树上运行**（[编排记录]），我本人未运行；**推送后的远端 CI 未复核**（§5）。

## 4. 真实模型教学结果

> 标题直述：**本节汇报的是「未执行真实模型调用」的验收结果**——即只有夹具级证据，没有模型质量证据。

### 4.1 执行与分类

- [编排记录/收尾记录] harness 以 skip 模式真实执行：28/28 案例夹具骨架本地真实通过（pre-fix exit=1、post-fix exit=0），**56 个模型回合全部 `skipped_no_credentials`**。
- 通过/失败案例：**0 通过、0 失败**（全部 skipped）。不存在可报告的模型输出、下一步质量或解释一致性样本。
- 凭证可用性 [lane 记录 + 收尾记录]：`TRAINER_MATURITY_API_KEY`/`MINIMAX_API_KEY`/`TRAINER_LIVE_PROTOCOL_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`DEEPSEEK_API_KEY` 等环境变量全部 unset；唯一本地未跟踪配置 `.trainer/provider-test.json` 的 `base_url` 为**非 loopback 明文 http**，按红线（凭证不得经明文 HTTP 传输）拒绝使用。
- [复核] 「验证真实性复核」agent 独立核查结论：**记录层未造假**（三处原始 JSON 一致、无 `"mode":"real"`、无任何 `"classification":"passed"`、无 sidecar 日志、跳过路径不发起网络请求）；28 案例经独立加载核实为真实异质（7 类 × 4、双回合、字段完整）；夹具经独立复跑 28/28 一致。**该核查由复核 agent 完成，我本人未打开这些 JSON**（`out/maturity/` 未入库）。

### 4.2 未验证缺口（如实声明）

1. 真实模型教学质量（事实准确、难度适配、下一步一致性、解释与实验一致性）全部未采样。
2. M5 服务端对账未在真实回合上实测。
3. `requires_confirmation` 真实降级回合的前端渲染未观察（仅模板/合成级验证）。
4. `provider_error` / `local_fallback` 未在真实故障回合产生样本。
5. 内容质量独立评审栏未填写（需真实回复文本，标注「待 owner 确认」）。
6. 长期恢复类 G1–G4 的跨会话/复习/恢复语义未在真实记忆上验证。

### 4.3 独立复核的 4 条问题与第 3 轮处置

[复核] honest=false（针对第 2 轮 `3c548f3` 产物），逐条与**当前 HEAD** 核对（[本次运行] 读码/文档）：

| 复核问题 | 当前状态 | 证据 |
|---|---|---|
| 分类器可把 `downgraded` 记 `passed`（虚假成功路径） | 已修 | `real_teaching_journeys_minimax.py:1533-1543`（downgraded→`grounding_pass=False`）、`:1582-1586`（passed 全条件）；回归测试 `server/tests/test_maturity_harness_classification.py:73` |
| `teaching-validation.md` 自检称「M1–M5 实现」不实 | 已修 | 同文件 `:21`（改为 M1/M2/M5 硬门、M3 仅记录） |
| `mock` 为死枚举 | 已修 | `real_teaching_journeys_minimax.py:13-14` + `teaching-validation.md:22`；测试 `test_classification_enum_has_no_unreachable_members`（`test_maturity_harness_classification.py:273`） |
| 文档称已入库但工作树有未提交改动 | 已修 | [本次运行] `git status --short` 为空；脚本随 `2bca8d1` 入库；`teaching-validation.md:4` 更正 |

**复核 honest 的最终取值：本报告无法给出新的 honest 结论**——上述修复由我逐处读码/读文档确认存在，但**我未运行这些回归测试，也未在真实凭证下重跑 harness**（[编排记录] 仅记录 `test:server` 最终门通过）。因此只能说「复核指出的 4 条实现缺陷已按代码事实消除」，不能说「诚实性已由独立复核重新确认」。

## 5. CI / 跨平台 / 原生安装 / Remote-SSH / 性能验收

| 维度 | 结论 | 依据与未跑项 |
|---|---|---|
| CI | 根因已修、本地门由编排运行全绿；**推送后的远端 CI 未复核** | [审计] 时 `gh` 实测 main 连续全红于 Pyright (server) 步骤（ci #38057980885、Cross-Platform #38057981112；根因 `routers.py:21474`，`86b73d4` 引入）。[本次运行] 定向 pyright 复现修复前 1 error（F22）；修复后 0 error 为 [lane 记录]/[编排记录]。编排最终门记录全绿：`npm run check`、`run-server-pyright.mjs`、凭证门、`npm run test:extension`、`npm run test:server`、`npm run test:experience-matrix`、`npm run verify`。**本 ask 未运行完整套件，也未用 gh 查询推送后的 CI。** |
| 跨平台 | **未复核** | [审计] Cross-Platform Verify #38057981112：10 job 中 9 过，仅 `Server (ubuntu-latest)` 败于同一 pyright；修复后未重跑。[本次运行] 未运行。 |
| 原生安装 | **未运行 e2e；bundled 同步已实测零偏差** | [编排记录/收尾记录]：`diff -rq server/app extension/bundled/server/app`（排除 `__pycache__`）差异 0；`npm run sync:server --prefix extension` → `mirrored 5 bundle targets`；`server/tests/test_provider_source_integrity.py → 24 passed`。原生安装路径本身未验证。 |
| Remote-SSH | **未复核** | [审计] nightly #38132924546 / #38244991010 整体失败，但 `Remote-SSH E2E (ubuntu)` job 本身两次通过（5m18s/7m0s），败因同为 pyright；修复后未重跑。 |
| 性能 | **未运行** | `npm run perf:probe` 未在本轮任何记录中出现，无性能结论。 |

## 6. 复核 / 复现指南（可直接照抄）

来源标注同 §0.1。[编排] 的命令由编排运行（我未运行）；[本人] 为本次运行；[需凭证] 当前环境不可复现。

```bash
# 环境准备（本仓库）
cd /Users/Apple/Desktop/trainer
cd server && .venv/bin/python -m pip install "Pillow>=12.0.0"   # F6 环境修复，[lane 记录]

# 1. 类型门（server pyright，CI 等价）——[编排] 已运行
node scripts/run-server-pyright.mjs                              # 期望 exit 0

# 2. 类型与样式（webview+扩展）——[编排] 已运行
npm run check

# 3. 凭证门——[编排] 已运行
node scripts/verify-no-plaintext-credentials.mjs                 # 期望 exit 0；命中仅打印 文件:行号

# 4. 后端测试——[编排] 已运行（全量由编排负责；以下为定向示例）
cd server && .venv/bin/python -m pytest tests/test_turn_grounding.py -q
cd server && .venv/bin/python -m pytest tests/test_maturity_harness_classification.py -q
cd server && .venv/bin/python -m pytest tests/test_training_reliability.py -q

# 5. 扩展测试——[编排] 已运行
npm run test:extension

# 6. 体验矩阵与发布校验——[编排] 已运行
npm run test:experience-matrix
npm run verify

# 7. 真实教学验收（需合规凭证，当前不可运行）——[需凭证]
#    provider/端点必须 https://（仅 127.0.0.1/localhost 允许 http）
# TRAINER_MATURITY_API_KEY=***（已脱敏） TRAINER_MATURITY_PROVIDER_BASE_URL=https://<host> \
#   TRAINER_MATURITY_CASE_IDS=01-mutable-default,A4-dict-mutation \
#   server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py   # 先冒烟 2 例
# 再跑全量（约 30–45 分钟）：
# TRAINER_MATURITY_WORKSPACE=out/maturity/teaching-journeys-run \
#   server/.venv/bin/python scripts/maturity/real_teaching_journeys_minimax.py
```

我本人本次运行过的检查（[本人]）：`cd server && .venv/bin/python -m pyright app/api/routers.py`（修复前 1 error）、`git diff`/`git status`/`git branch --contains`、`grep`、`ls`、`wc -l`、以及若干文件读取。

**来源与存放位置**：本文引用的「编排记录/验证门记录/各轮闭环记录/收尾与安全/验证真实性复核」均来自**本次 workflow 运行的任务输入材料**（由编排脚本产出并回传），本仓库内无对应文件、亦无外部链接可给；`out/maturity/**`（harness 原始 JSON 与夹具）被 `.gitignore` 忽略、不入库。

**凭证门的覆盖力限制（补读者所问）**：门按模式集扫描（sk- 长串、Bearer、JWT 形态、api_key 赋值、携带凭证的非本地 `http://`）+ 合成 fixture 白名单；阳性对照仅用历史违规脚本副本验证了模式命中与非零退出。**对 base64 编码、`.env` 文件、其它密钥形态无对照样本**，「0 findings」只代表未命中其模式集，不代表全形态覆盖。

## 7. 尚未解决的问题、风险与下一步

### 7.1 真实模型验收（最高优先，阻塞教学质量结论）

- 问题：56/56 回合 skipped，无模型质量证据。
- 风险：教学事实正确性、难度适配、下一步一致性、解释与实验一致性均未验证。
- 下一步：配置合规凭证（**必须 `https://`，或 `127.0.0.1/localhost`**），先以 `TRAINER_MATURITY_CASE_IDS` 冒烟 2 例确认通路，再跑全量 28 组（30–45 分钟），按 `docs/maturity/teaching-validation.md` §6 更新结论；同时核对 `grounding_outcome`/`grounding_ungrounded_symbols`/`corrected_next_step` 的 server vs 本地复算，并观察一次真实降级回合的前端标注。
- Owner：由本 workflow 的发起人/仓库 owner 决定何时提供凭证并确认结果（**具体身份本报告无从得知**——workflow 材料未给出 owner 标识）。

### 7.2 疑似真实凭证的人工轮换（安全）

- 事实：`scripts/maturity/real-teaching-journeys-minimax.py:28`（[本次运行] 读取，值脱敏）在 `d2e30f4` 已推送 `origin/main`；[审计] 记录同一前缀+同长度值还出现在历史提交 `b279a5a`/`ae1c930`/`32600ee` 的 `extension/tests/providerConnectionPaste.test.js` 与 `view_audit.tmp.mjs`；本地未跟踪 `.trainer/provider-test.json:3` 存在同前缀同长度值（[复核] 只读核查）。代码侧已移除（F21）、旧脚本已删除（F13）。
- 暴露时间窗口：自 `d2e30f4` 首次推送起至今；涉及文件见上；**是否已被 fork/镜像缓存：本报告无法判断，应按“已泄露”处理**。
- 风险：密钥泄露可被滥用；`origin/main` 历史仍含该值。
- 处置建议（不可逆操作，留 owner）：优先级 1 —— 在 MiniMax/中转侧**轮换/撤销**该密钥（rotatte 优先于删除本地文件）；优先级 2 —— 清理本地 `.trainer/provider-test.json`（如不再需要）；**不改写 git 历史**（红线）。

### 7.3 合并与发布

- 事实：分支已推送 `origin/maturity/teaching-loop`，领先 `origin/main` 3 个提交，**未合并**。
- 下一步：由 owner 决定是否发起 PR 合入 main；本任务禁止直接推 main、禁止发布 Release、禁止打 tag。本文件（`docs/maturity/FINAL_REPORT.md`）当前未跟踪，是否入库由编排/owner 决定。

### 7.4 deferred（带定位；源自 `docs/maturity/DESIGN.md` §7 与 [审计]）

| 项 | 严重度 | 风险 | 定位（可查） | 下一步 |
|---|---|---|---|---|
| i18n 双体系合并（`copy.ts` vs `appUiCopy.ts` vs 组件内联表） | medium | 同一句文案最多四处维护 | [审计]：`extension/webview/src/app/appUiCopy.ts`；内联表 `CoachComposer.tsx:39-210`、`TrainingWorkbenchView.tsx:875-1565`；`docs/maturity/DESIGN.md` deferred 第 1 项 | 先加 CopyKey 键、后删模板，逐组件迁移 |
| 前端启发式改写/丢弃宿主文案层移除 | medium | 中文用户可能看不到 host 真实下发内容，且掩盖上游未本地化根因 | [审计]：`App.tsx:1240/1278-1322/1324-1356`、`:1755-1790`；DESIGN deferred 第 2 项 | 本地化责任移回 host（sidecar 已有 language recovery） |
| 巨型视图 prop 瘦身（`CoachSettingsView` 79 props / `TrainingWorkbenchView` 75 props → ≤25） | medium | App 成为所有行为必经中转 | [审计]：`CoachSettingsView.tsx:4065`；DESIGN deferred 第 3 项 | 待控制器拆分完成后由 selector 驱动 |
| 训练可靠性单槽重放窗口 body 级去重 | low | 单槽被替换后同键 `not_arrived` 重发会重复执行 body（失败证据重复条目） | [审计]：`server/app/training/reliability.py:113-118`、`server/app/memory/training_reliability_mixin.py:151-152`；AGENTS.md 已声明该边界 | 在 body 内建独立 idempotency 键 |
| sidecar 启动时 in-flight 可靠性记录主动 expire | low | 进程崩溃遗留 `executing` 记录，延迟可见 | [审计]：`training_reliability_mixin.py:196-205`、`reliability.py:195-206`；DESIGN deferred 第 5 项 | 启动时一次性 expire/提示 |
| 正文「解释质量」结构化评估 | medium | 解释优劣无校验 | [审计] truth：正文仅作接地语料（`routers.py:10631-10636`）；DESIGN nonGoals 明列为非目标 | 需模型评审设计，且不得冒充 verified |
| M3 主题延续仅记录、M4 无独立本地检查 | low | 主题漂移/索取误判不直接判 failed | `docs/maturity/teaching-case-matrix.md:32-34`（[本次运行] 读取） | 依真实运行样本决定是否升为硬门 |

## 8. 诚实性声明（就本文件本身）

- 本报告不含任何「真实模型通过」结论；§4 已直述「未执行真实模型调用」。
- 所有被引用的验证分四类来源（§0.1）并逐处标注；我本次实际运行的检查已在 §6 末尾列明；未运行项（远端 CI、跨平台、原生安装、Remote-SSH、性能、完整套件、harness 真实运行、M1–M5 回归测试）均已写明「未运行/未复核」。
- 疑似凭证的值全程脱敏为「***（已脱敏）」，只给文件:行号。
- 本文件自身为未跟踪新文件；「工作树干净」指的是除本文件外无改动（`git status --porcelain` 仅列出本文件）。
