# Trainer 成熟度统一设计：TeachingTurnFacts 契约、前端控制器边界与分阶段计划

- 日期：2026-10-13（v2，修订已评审阻塞项）
- 分支：`maturity/teaching-loop`（基线 `d2e30f4`，工作树干净）
- 依据：三份只读审计（任务输入）+ 独立评审意见（JSON）+ 本会话定向复核。本文关键锚点均已第一手读取，标注「已核」；转述标注来源。
- v2 修订记录（均已代码复核）：
  1. 撤销「四流程汇入 execute_turn 单一装配点」的错误断言——改为**四个持久化点前共享同一 helper**（§2.3，runtime 线接线计入工作量）。
  2. 定死有界纠错重试的 await 位置、修正文本载体、一次性语义与流式合法结果（§2.3/§2.5）。
  3. 补 `requires_confirmation` 的前端渲染消费端（R1 前端项）——此前全仓只有类型声明。
  4. 所有权图以编排实际 own 声明为准（`out/maturity-teaching-loop.workflow.ts:201/229`），删除「编排脚本串行化」的虚构表述，改为**单文件单写者 + 接口冻结**（编排实际并行跑三 lane：同文件 `Promise.all`，:461/:575）。
  5. 定义 claim 级 grounded 判据、字段级记忆准入映射、误报预算、provenance 枚举补 `local_fallback`、gate_outcome 下发通道、claim_key/domain 归一化、unverifiable 语义（§2.5-§2.7）。
- 状态：R1–R3 执行的设计基线。任何实现与验收不得突破 §5 不变量。

## 0. 红线（对所有阶段生效）

**安全**：任何疑似凭证/令牌/密钥的值不得出现在回复、报告、日志或提交信息里，一律写「***（已脱敏）」；扫描结果只给文件名与行号。已确认一处疑似真实凭证：`scripts/maturity/real-teaching-journeys-minimax.py:28`（值脱敏；同一前缀曾出现在历史提交的测试文件中——runtime 审计）→ R1 从现行代码移除，改环境变量/本地未跟踪配置；**凭证不得经明文 HTTP 传输**（优先 HTTPS 端点；若中转站不支持 TLS，停止向其发送凭证，而不是「改成 https 即可」），标记**需人工轮换**，绝不改写 git 历史。禁止 force push、禁止向 main 推送、禁止发布 Release。

**诚实**：类型修复禁用 Any/cast/@ts-ignore/删断言掩盖；没有真实模型调用不得宣称「真实模型通过」；模型输出、Provider 失败、本地兜底、模拟结果严格分类。内容质量栏目由**独立评审 agent 填写并标注「待 owner 确认」**，不记为人工审阅（编排已设「教学验收复核员」：`workflow.ts:561-568`）。

## 1. 现状定位（实际代码，已核）

### 1.1 已存在的教学事实设施（本分支）

- `server/app/llm/turn_grounding.py`（388 行，已核全文）：纯规则层——`next_step_is_grounded(:213)`、`sanitize_memory_anchor(:281)`、`grounding_correction_instruction(:306)`、`evaluate_next_step_grounding(:340，retry_generate 契约)`。缺口：`next_step_is_grounded(:232-240)` 是「**任一**符号命中语料即整条放行」；`_COMMON_TOOLCHAIN_SYMBOLS(:46-48)` 含 `log/todo/fixme` 等项目名词；文件指针 `:189-198` 一律放行、存在性自述 out of scope（`:51-57`）；复评成功时**丢弃 retried_text**（`:368-381` 只返回 grounded/referenced_symbols）。
- grounding 门 `apply_next_step_grounding_policy`（`routers.py:10600-10652`，已核）：只校验 `coach_turn.next_step`；**同步函数**；docstring 自述 retry 未接线（`:10620-10626`）。
- 四流程真实结构（已核，v2 纠偏）：
  - `POST /turn`：无条件 `await execute_turn`（`:21941`）；execute_turn 内 gate `:20432` → persist `:20439`。
  - `POST /session/message`：**仅 provider 不可用**时走 execute_turn（`:21002-21004`）；provider 可用时内联，gate `:21473` → persist `:21480`。
  - `POST /session/message/stream`：内联 gate `:22711` → persist `:22718`；流失败恢复**嵌套** `await session_message`（`:22555`）。
  - `POST /turn/stream`：execute_turn 仅用于 preparation（`:23184`）与 grounding-recovery 兜底（`:23843`，stream=False）；持久化内联在 `:24039/24046`。
- gate 在同一回合被求值**两次**：persist 前（`ground_coach_turn_payload_before_persistence`，`:10675` 内调）与响应构建（`build_session_response`，`:11307`）。
- 记忆写入 `record_turn_reflection`（`memory/service.py:7465-7528`，已核）：只有 focus 走 `sanitize_memory_anchor(:7474)`；`reflection_parts(:7478-7486)`、`action_items(:7491-7497)`、`latest_coach_*(:7504-7526)` 原样入库；`review_note(:7484-7485,7508)`、`review_queue_summary`（`routers.py:11424`）同样来自模型且无 provenance。
- 正文提取器 `server/app/llm/reply_continuity.py:16-44`（已核全文）：`visible_next_step` 只提取、不比较。
- `requires_confirmation` 消费端缺失（已核 grep，大小写不敏感）：webview/shared 仅 `extension/webview/src/lib/types.ts:575` 类型声明；`extension/src/commands/sessionCommands.ts:214/219` 是无关的 organize_resources 字段。降级目前只在 API JSON 里带旗标。
- 文件存在性核验的远端分支（已核）：`server/app/llm/tools.py:482-502` 对 URL 根（`://`）返回 None——远程工作区无法做本地核验。

### 1.2 结论

事实正则已经存在，但**契约不完整且接线位置错误**：判定粒度整条而非逐断言；判定域不含正文与一致性；记忆写入不看来源；纠错能力未接线；降级无前端消费端。本设计扩展既有规则层，**不新建第二套教学引擎**。

## 2. TeachingTurnFacts 契约（教学事实唯一权威）

### 2.1 结构

在 `server/app/llm/turn_grounding.py` 内新增（冻结 dataclass，与既有纯规则同域）：

```text
TeachingFact:
  kind:        "error_text" | "code_fragment" | "symbol" | "file_path" | "call_site" | "behavior_claim"
  value:       str
  provenance:  "tool_verified" | "learner_provided" | "model_claim" | "local_fallback"
  source:      "user_message" | "current_file" | "workspace_tools" | "reply_body" | "next_step" | "history"
  turn_id:     str

TeachingTurnFacts:
  turn_id / request_id
  learner_provided:  list[TeachingFact]    # 本回合学习者已给出（= already-provided 清单）
  workspace_verified: list[TeachingFact]   # 工具/文件系统返回值核验过
  next_step_claims:  list[TeachingFact]    # 结构化 next_step 中的断言（参与降级）
  reply_claims:      list[TeachingFact]    # 正文对学习者代码的符号级断言（不参与降级，见 2.5②）
  conflicts:         list[{domain, reply_claim, next_step_claim, winner}]
  verdicts:          dict[claim_key, "grounded" | "ungrounded" | "unverifiable"]
  gate_outcome:      "grounded" | "corrected" | "downgraded" | "recovery_override"
  memory_provenance: dict[field, provenance]  # summary/next_step/decision/teaching_note/review_note/
                                              #   review_queue_summary/evidence/focus
```

- `claim_key = f"{kind}:{normalize_code_symbol(value) or normalized_text}"`；冲突裁决的 `domain`（归一化符号/文件路径）由 `turn_grounding.py` 的归一化函数（`normalize_code_symbol :103-110` 等）**唯一负责**。
- `provenance` 缺省一律按 `model_claim` 处理；`local_fallback` 表示本地兜底/恢复通道产出（无 retry、不写 mastery/focus、永不呈现为模型完成）。

### 2.2 唯一权威来源

- **代码事实**唯一来源 = sidecar 工作区工具/文件系统的返回值（`workspace_verified`）；模型正文中的符号声明默认 `model_claim`。
- **学习者已给事实**唯一来源 = 本回合消息、附件、`current_file`、历史学习者消息。
- **判定实现唯一**：`build_teaching_turn_facts` + `evaluate_turn_grounding` 只有一份实现（turn_grounding.py）；webview 与 harness 不得成为第二权威（harness 本地复算仅用于**对账**，不一致必须显式判失败，见 R2 项）。

### 2.3 生产者 / 消费者 / 生命周期（v2 纠偏）

不存在「四条流程都汇入 execute_turn 的单一装配点」（v2 已核，见 §1.1）。契约的共用机制 = **同一个 pre-persistence 步骤在四个持久化点前被调用**（照既有 `ground_coach_turn_payload_before_persistence`（`:10654`）模式）：

- **生产者（唯一实现，四处调用）**：`build_teaching_turn_facts(...)`（纯函数）+ 每流程一处的 async 步骤 `resolve_turn_grounding_async(...)`（routers.py；**await 位置 = reply 完成之后、持久化点之前**——这是 gateway 里唯一一处可 await provider 重试的位置）。禁止按流程复制判定逻辑。
- **应用（同步、幂等）**：`apply_grounding_decision(...)` 将 `corrected_next_step` 写回 payload、追加 agent_meta 戳，并把决策缓存于 payload 私有键；`build_session_response`（`:11307`）与 persist 前置调用消费缓存决策，**不再重新求值**——保证「每回合决策至多求值一次、纠错至多一次」（修复现状两次求值）。
- **corrected 文本载体**：`GroundingDecision` 增补 `corrected_next_step: str | None`；调用方以 `model_copy(update=...)` 写回 next_step（现状 `:10652` 只降级、不回写修正文本）。
- **retry 合法性**：仅当 reply 为**模型完成**（`agent_meta.fell_back` 为假）且 provider 可用；至多一次；恢复/本地兜底路径**跳过 retry**，直接进入降级并按 `local_fallback` 标注。
- **流式语义（合法结果枚举）**：流式正文不可改写；纠错只改结构化 next_step，随最终快照下发；结论只有 grounded / corrected / downgraded 三态且全部有 agent_meta 戳；若纠错文本与已下发正文在同域冲突或仍 ungrounded → 降级。**不存在「静默改写已下发正文」这一分支**。
- **消费者**：①gate/降级 ②retry ③`persist_turn_reflection`（provenance 过滤）④`build_coach_context`（already-provided 注入下一轮）⑤`build_session_response` + webview 渲染（requires_confirmation；R1 前端补齐消费端）⑥R2 harness（只读响应 agent_meta）。

```text
四流程（reply 完成）→ resolve_turn_grounding_async（facts→决策→≤1 次纠错）
  → apply_grounding_decision（幂等；缓存决策）→ persist_turn_reflection（provenance 过滤）
  → build_session_response（消费缓存决策，不复评）
```

### 2.4 与既有机制的关系

扩展 `turn_grounding.py` 纯规则层与 `ground_coach_turn_payload_before_persistence` 接线模式；不新增状态机、不新增持久化通道。跨进程面最小增量：响应 `agent_meta` 固定键（见 2.5⑤），不先动 `WorkbenchSnapshot` 大面。

### 2.5 grounding 治理规则（v2）

1. **next_step 逐断言、全量锚定**：next_step 中每条含符号断言**所有**符号都必须能在 reply ∪ 当前代码 ∪ 历史 ∪ `workspace_verified` ∪ `learner_provided` 中找到锚点（现状是「任一符号命中即整条放行」）。白名单收窄为**语言内置/工具动词**（保留 `print`/`console` 等语言内置与命令词；移除 `log/todo/fixme` 等项目名词，`:46-48`）；文件指针在装配点做一次存在性核验。
2. **正文断言不参与降级（显式误报预算）**：正文已下发、不可改写；`reply_claims` 若参与降级，会把教学正常引入新符号（如 `enumerate`）的回复大面积误降。它们只用于：①与 next_step 同域冲突 → 判 **next_step 断言** ungrounded；②记忆准入过滤与诊断。
3. **一致性（域级）**：同一 domain（归一化符号/文件路径）内以 `workspace_verified > learner_provided > model_claim` 裁决，败方 next_step 断言 ungrounded；`visible_next_step`（reply_continuity.py:16-44）纳入比较；`learner_provided` 中的事实被再次索要（多语言「请提供/贴出来/please share/paste」且目标 ∈ learner_provided）→ ungrounded。**R2 实现定案（已核代码）**：域级冲突 = 同一 domain 同时被 reply 与 next_step 声称、且无 workspace/learner 事实佐证、且 next_step 段为「信息索取」语境（多语言索取标记，创建指令排除）——仅此形态判该 next_step 断言 ungrounded 并记入 `conflicts`；正文正常引入新符号（如 `enumerate`）永不成为冲突（显式误报预算）。索取无任何事实佐证的符号 = 虚构索取 → ungrounded。
4. **有界纠错与一次性**：见 2.3；评估层支持 `retry_generate`（`:340-387`），装配层提供 await 位置与缓存。
5. **诚实降级 + 可核对通道**：`requires_confirmation`（`core/models.py:2713` 语义）+ 响应 `agent_meta` 固定键 `{grounding_outcome: grounded|corrected|downgraded, grounding_ungrounded_symbols: list[str], grounding_retry_used: bool, next_step_requires_confirmation: bool}`；只对既有非空 agent_meta 追加戳（保持干净回复 agent_meta 缺省契约，`:10645-10649`）。前端 R1 渲染消费端；harness 从响应读取（不新增持久化，尊重 nonGoals）。
6. **unverifiable 语义**：无法做存在性核验时（远程/URI 工作区，`tools.py:482-502` 返回 None），文件指针既不算核验通过、也不构成降级理由；不得伪造「已核验」。**创建类指令豁免（R2 定案）**：next_step 明确要求创建/新建文件（`_CREATION_VERB_PATTERN`）时，文件不存在是预期状态，核验结论为 unverifiable、绝不降级；仅「查看/打开/修改」类文件引用才会因文件缺失判 ungrounded。

### 2.6 接口冻结（并行 lane 编码契约）

编排并行跑三 lane（`workflow.ts:461/:575`），跨 lane 协作以本契约为准：

```python
# ── server/app/llm/turn_grounding.py（teaching 线所有） ──
def build_teaching_turn_facts(*, turn_id: str, reply_text: str, code_text: str,
    history_text: str, user_message: str, workspace_evidence: object = None,
    agent_evidence: object = None) -> TeachingTurnFacts: ...
def evaluate_turn_grounding(facts: TeachingTurnFacts, *,
    retry_generate: Callable[[], str] | None = None) -> GroundingDecision: ...
@dataclass(frozen=True)
class GroundingDecision:
    grounded: bool; referenced_symbols: list[str]; retry_used: bool
    requires_confirmation: bool; corrected_next_step: str | None = None
```

冻结语义（R2 定案，已核）：`retry_used` = 「本回合执行过一次纠错重试」（空再生也算一次尝试）；规则层与装配层共用这一份实现（装配层总是把尝试传入 `evaluate_turn_grounding`），`corrected_next_step` 仅在重试产出可用修正时非空。`referenced_symbols` 语义为「**未锚定**符号」。

```python
# ── server/app/api/routers.py（runtime 线所有；接线） ──
async def resolve_turn_grounding_async(*, coach_turn_payload, reply_content, request,
    agent_meta, history_text) -> GroundingDecision: ...   # await 位置：reply 完成后
def apply_grounding_decision(*, coach_turn_payload, decision: GroundingDecision) -> None: ...  # 幂等、缓存
```

```python
# ── server/app/memory/service.py（teaching 线所有） ──
def record_turn_reflection(..., memory_provenance: Mapping[str, str] | None = None) -> None: ...
# ── server/app/api/routers.py（runtime 线所有；传参） ──
def persist_turn_reflection(..., grounding_decision: GroundingDecision | None = None) -> None: ...
```

### 2.7 字段级记忆准入映射（v2）

粒度 = **字段 + claim 级**（无「段落」级 NLP 裁剪）：

| 字段 / 用途 | 准入规则 |
|---|---|
| next_step → action_items / latest_coach_next_step / review hints | 仅 `grounding_outcome ∈ {grounded, corrected}`；downgraded 时写降级形态 + marker，不写伪造步骤 |
| mastery / curriculum / current_focus / coach_anchor | 仅 `tool_verified` 或 `learner_provided` 佐证的事实；focus 保持 `sanitize_memory_anchor` |
| summary / decision / teaching_note / **review_note** / **review_queue_summary** / evidence | 标来源后准入（默认 `model_claim`，兜底为 `local_fallback`），**永不作为 verified mastery 依据**；与 workspace_verified/learner_provided 同域冲突的具体 claim 文本剔除 |
| unverifiable 断言 | 不进硬门字段；可作叙述但标 `model_claim` |

## 3. 前端控制器边界

现状（已核）：`App.tsx` 14,669 行、组件体约 1.1 万行；根组件 `useWorkbenchState()` 无 selector 整店订阅（`:3655`），流式每条 chunk 全量重渲染（`useWorkbenchState.ts:1074-1097`）；五域 split-brain；host 消息双头路由（`App.tsx:4432-4573` vs `useWorkbenchState.ts:869+`）；四个控制器名在源码与 git 历史零命中（本会话 grep 复验）；`requires_confirmation` 无渲染消费端（仅 `types.ts:575`）。

**所有权原则**：store = 与 host/sidecar 对账过的**事实**；控制器 = 单会话**交互态 + 本域 host 消息处理**；App = 组装与路由壳。

| 域 | 控制器（新） | 控制器持有（交互态 + 域拦截） | store 持有（事实） | App 迁出点 |
|---|---|---|---|---|
| Provider | `useProviderConnectionController` | providerDraft（待提交补丁）、测速 results/pending、apiKeyFocusRequest | **单一 ProviderFacts**（收敛三副本） | `:3677-3694`、`:3699-3715`、`:3732`、`:4501-4505` |
| Coach Session | `useCoachConversationController` | optimisticTurns、pendingMessageAction、previewSessionId、lastTurnView、coachContextTransition、streaming 订阅选择 | conversation 持久事实、streaming 原文、会话列表（`useCoachHistory` 并入编排） | `:3675`、`:3774-3777`、`:3796-3798`、`:3802-3820` |
| Training | `useTrainingCardController` | remoteVerification + requestRef、trainingPersistencePending + resolvers、attemptLifecycle（顶层调用修复）、composer flash/verify/return/route/drafts | workspaceTrainingState、trainingRestoreContext、训练卡事实 | `:3733-3742`、`:3753-3765`、`:3793-3795`、`:10131`、`:4452-4500` |
| Learning Plan | `useLearningPlanController` | planComposerMode、coachPlanContext、pendingPlanComposerDraftReplacement | plan（乐观锁语义原样） | `:3744-3745`、`:3767-3768` |
| Operation Status | `useOperationStatusController` | surface 路由消费；settingsFeedback/trainingVerifyNotice/userFeedback 并入 | **单通道** `operationMessage` + operations 台账 + 必填 surface | `:3719`、`:3746`、`:3766`、`:3821` |

**边界规则**：① `applyHostMessage`（`:4432`）保留唯一入口，按域委派 handler，处理后 return 或转发 store，禁止第三条路由。② 每控制器独立文件、可独立测试、按域迁移回滚。③ 流式订阅下沉 `CoachConversationView`，App 根改概要订阅（R3）。④ `:4510` 字符串契约改 `[[trainer-learning-feedback:{requestId}]]` marker。⑤ **grounding 降级消费端**（R1）：`requires_confirmation` / `next_step_requires_confirmation` 在教练下一步与流式终帧上渲染为「建议确认」语义 + 8 语言文案——没有消费端的降级不算诚实落地。

## 4. 三条线互斥文件所有权图（以编排 own 声明为准）

编排实际 own 声明（`out/maturity-teaching-loop.workflow.ts`）：

- teaching（`:201`）：`server/app/llm/**`、`server/app/pedagogy/**`、`server/app/memory/**`、`server/app/training/**`、`server/app/planner/**`、`server/tests/`（**新建测试文件，不往 test_api.py 追加**）、`scripts/maturity/**`、`shared/src` 教学契约类型（models.ts/protocol.ts 的教学部分）。
- frontend（`:215`）：`extension/webview/src/**`、`shared/src/tokens.ts`。不改 `server/` 与 `extension/src/`。
- runtime（`:229`）：`server/app/api/**`、`server/app/core/**`、`server/app/db/**`、`server/app/workspace/**`、`server/app/resources/**`、`server/app/ingest/**`、`server/app/specs/**`、`extension/src/**`、`remote-extension/**`、`scripts/**`（teaching/maturity 除外）、`.github/**`、`e2e/**`、`extension/tests/**`、`server/tests/test_api.py` 与运行时相关测试。

**关键推论（v2 修订）**：

1. `server/app/api/**`（含 `routers.py`）归 **runtime 单写者**；teaching **不编辑 routers.py**，只交付 `turn_grounding.py`/`reply_continuity.py` 的纯规则与测试；接线（四持久化点、async 步骤、缓存应用、agent_meta 戳、provenance 传参）全部计入 runtime 项（R1/R2），接口按 §2.6 冻结。
2. 编排**没有**同文件串行化：轮次内三 lane 并行（`Promise.all`，`:461/:575`）。因此规则是**同一轮内单文件单写者**：routers.py 仅 runtime 可写；`memory/service.py` 仅 teaching 可写（runtime 通过 `persist_turn_reflection` 传参，不直接改 memory 内容策略）；`extension/webview/**` 仅 frontend。任何 lane 需要改他方文件时，改为「接口冻结 + 对方 lane 的 R 内事项」，**禁止并发直写**。
3. `server/tests/**`：teaching 新建教学测试文件；runtime 拥有 `test_api.py` 与运行时测试；grounding 接线的回归测试写进 `test_api.py`（runtime）。
4. `shared/src/**`：teaching = `models.ts`/`protocol.ts` 教学契约段；frontend = `tokens.ts` 与 UI 治理文件（`operationMessageGovernance.ts` 等）；runtime = `commands.ts` 等其余。镜像变更必须同一提交同步 `server/app/core/models.py` ↔ `shared/src/models.ts` 并跑双方类型门。
5. `extension/bundled/**` 归 runtime：入库副本，由 `extension/scripts/sync-bundled-server.mjs` 同步、`verify-package.mjs` 做字节级 parity；server 改动后打包前必须同步（编排 phase 6 执行，`workflow.ts:617-625`），防止测试测到旧副本。
6. `App.tsx`/`extension/webview/**`：frontend 独占；`docs/maturity/DESIGN.md`：架构维护。

## 5. 不变量清单（所有改动不得破坏）

1. `/training/attempt/evidence` 恒记 `self_reported`，客户端 `trust_level` 永不采信（`server/app/api/routes/training_attempts.py:176`，已核；workspace 从 attempt 记录反查 `:135`）。
2. host 可信证据仅 `/training/verification/attest` 白名单来源（`routes/learning.py:159-179`，审计）；资源引用服务端解析，版本不符 409（`training_attempts.py:151-162`，已核）。
3. plan 乐观锁：正式保存推进 `_plan_revision`，冲突 409 `plan_revision_conflict`，不静默覆盖。
4. `connection_lost ≠ task_failed`：attestation 递送 `not_arrived` 可重发一次、`ambiguous` 绝不自动重发、未确认递送面 `[[trainer-attestation-undelivered]]`（`trainingAttestation.ts:253-284`，审计）。
5. **验证成功但持久化失败不得显示为可信掌握**：attest 未确认递送前不渲染 verified；中断/取消/超时 fail-closed 不落证据。
6. `agent_meta.fell_back` 诚实标记；本地兜底不得冒充模型完成；journey 分类显式区分。
7. 四条流程「先 gate 后 persist」顺序保持（`:20432/20439、:21473/21480、:22711/22718、:24039/24046`，已核）；每回合 grounding 决策唯一并被缓存（R2 定案：纠错路径允许「初判 + 重试复评」共至多两次 evaluate 调用，缓存以被评测的 next_step 文本为键，文本被后续执行遍替换即重评），纠错至多一次。
8. **降级必须有消费端**：R1 起 `requires_confirmation` 在前端渲染；未经渲染的降级视为未完成。
9. anchor/focus 防漂移过滤保持（`sanitize_memory_anchor`；`coaching_adaptation_mixin.py:157-176`）。
10. Coach 写工具双重硬拒绝（`server/app/llm/tools.py:60-61、174、203-228`）不得放松。
11. 凭证不出 UI host：SecretStorage 唯一入口；Companion 零凭证；脚本凭证仅环境变量/未跟踪本地配置且不经明文 HTTP。
12. 类型门真实通过：修复不得用 Any/cast/@ts-ignore 掩盖；`routers.py:21474` 修复优先真修复（形参显式扩为 `CoachTurnPayload | dict[str, object] | None`），如不可行才用既有 `coach_turn_mapping` 适配器并在提交说明记录其为既有受控边界（非新增 cast），验收一律 `scripts/run-server-pyright.mjs` 退出 0。
13. 已验证卡重放防御（`memory/service.py:7980-7983`）保持；reliability 单槽重放窗口边界只收紧不放松。
14. Composer 单一输入框所有权 + IME 守卫（`CoachComposer.tsx:300-303`）保持。
15. 训练验证结果三态 `passed/failed/unknown` 不合并、不美化（`TrainingWorkbenchView.tsx:2811-2816`）。
16. `requires_confirmation` 是 UI 渲染语义（`core/models.py:2713`），不得用文案层掩盖降级事实。

## 6. 分阶段计划与门

**优先级序**：安全和 CI → 教学事实正确性 → 完整教学闭环 → 前端体验 → 代码架构 → 正式交付。

### R1（P0）

- runtime：① 凭证移除（env + 非明文传输 + 跨平台路径）；② `scripts/verify-no-plaintext-credentials.mjs`；③ `scripts/run-server-pyright.mjs`；④ `routers.py:21474` 类型修复（恢复 pyright 步骤绿；其余 CI 步骤按 ci.yml 顺序由编排验证，不宣称「完整 CI 绿」）；⑤ **grounding 四持久化点统一接线**（async 决策 + 幂等应用 + 缓存一次性 + agent_meta 戳）。
- teaching：① 契约与 rules 核心（`build_teaching_turn_facts`、逐断言全量锚定、`corrected_next_step` 载体、白名单收窄、文件核验输入、claim/domain 归一化、测试）；② 28 案例矩阵规格落盘（4 既有 + 24 新增 = 28，7 类 × 4 组，含客观判据与独立评审栏）。
- frontend（P0 之下并行起步）：hooks 违例修复、训练卡恢复指引渲染、学习反馈协议 marker、**requires_confirmation 渲染（8 语言）**、`useTrainingCardController` 试点。
- 验收门：`run-server-pyright.mjs` 退出 0；`verify-no-plaintext-credentials.mjs` 退出 0；`test_turn_grounding.py` 通过；接线回归（test_api.py）通过；四流程同一 helper 生效（评审/检查点可核）。

### R2（教学闭环 + 其余 P1）

- teaching：① 正文断言（reply_claims）、域级一致性、重复索要防护（矩阵回归）；② 字段级记忆准入（provenance 过滤，含 review_note/review_queue_summary；接口按 §2.6）；③ `real_teaching_journeys_minimax.py` 交付并执行（28 组；凭证 env/未跟踪配置、非明文传输、逐案例 passed/failed/provider_error/local_fallback/mock/**skipped_no_credentials**；服务端戳 vs 本地复算对账，不一致即判失败；无凭证时全部 skipped 并如实说明，绝不宣称真实模型通过；结果写 `docs/maturity/`；旧 scratch 删除）。
- runtime：① 可靠性账本诚实化；② 信任敏感写路径 workspace 归属校验（含 `runtime.py:791-812` 的静默回退分支，attest/evidence 不一致 409）；③ `persist_turn_reflection → record_turn_reflection` provenance 传参接线。
- frontend：① `useOperationStatusController` 单通道收敛；② `useProviderConnectionController` + ProviderFacts 单所有者。

### R3（收敛轮：真实模型验证暴露的问题 + 轮次审查发现）

- teaching：按 journey 报告与复核发现修 grounding 误报/漏报与提示词（内容质量保持独立评审 + 待 owner 确认）。
- frontend：`useCoachConversationController` + `useLearningPlanController` + 根组件 selector 化（流式订阅下沉）。
- runtime：正式交付门收敛（先复现当前 release Extension test suite 状态再修根因；确认 bundled 同步；不发布；不打 tag）。

## 7. nonGoals 与 deferred

见提交报告的 `nonGoals` / `deferred` 字段；与本节一一对应。核心克制条款：不新增第二套状态机 / 教学引擎 / Provider 逻辑 / 第二判定源；不大规模重写成熟模块；不加低价值测试；规则层不做教学质量评分。
