# Trainer

<div align="center">

<img src="assets/banner.png" alt="Trainer — 训练你的 AI · 与你的 AI 共同成长 · Where AI and Humans Grow Together" width="100%" />

**一个住在 VS Code 侧边栏里的长期编程教练。**
**A long-term coding coach that lives in your VS Code sidebar.**

**它规划、出题、验收、记住你的一切——但绝不替你写代码。**
**It plans, drills, verifies, and remembers everything about you — but never writes your code.**

**// 产出 ≠ 成长 // 验证 + 复习 = 成长**
**// Output ≠ Growth // Verify + Review = Growth**

[![Release](https://img.shields.io/badge/release-v1.0.3-1f6feb)](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)
[![License](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-8b949e)](#安装--install)
[![Tests](https://img.shields.io/badge/tests-3%2C328%20cases-F59E0B)](#质量门禁--quality-gates)
[![i18n](https://img.shields.io/badge/i18n-8%20languages-A78BFA)](#i18n--eight-languages)

[为什么 · Why](#为什么需要-trainer--why-trainer) ·
[安装 · Install](#安装--install) ·
[三步配置 · Setup](#三步配置没有第四步--three-steps-no-fourth) ·
[核心机制 · Mechanics](#核心机制--core-mechanics) ·
[五视图 · Five Views](#五个视图--five-views) ·
[对比表 · Comparison](#对比一下--compare) ·
[五分钟演示 · 5-Min Demo](#五分钟演示--five-minute-demo) ·
[设计理念 · Design](#为什么看起来不一样--why-it-feels-different) ·
[架构 · Architecture](#架构--architecture) ·
[安全 · Safety](#安全模型--safety-model) ·
[质量 · Quality](#质量门禁--quality-gates) ·
[致谢 · Acknowledgements](#致谢--acknowledgements) ·
[角色 · Cast](#角色阵容--the-cast)

</div>

---

## 角色阵容 · The Cast

每一个 harness 都有自己的人设、桌面和毛病。Trainer 娘站在中间，不替你写代码，但跟每个人都聊得来。

Every harness has her own persona, desk, and quirks. Trainer stands in the middle — she won't write your code, but she gets along with all of them.

<div align="center">

| Trainer 娘 · protagonist | Cursor 娘 · vibe coder | Claude Code 娘 · writer |
|:---:|:---:|:---:|
| <img src="assets/portraits/trainer.png" width="200" alt="Trainer 娘" /> | <img src="assets/portraits/cursor.png" width="200" alt="Cursor 娘" /> | <img src="assets/portraits/claude-code.png" width="200" alt="Claude Code 娘" /> |
| `你写 · 我教 · 我们一起长` | `tab tab tab` · `Mark Done?` | `Bash is all you need` |

| Codex 娘 · auto-pr | Kimi Code 娘 · long-context | Workbuddy 娘 · office |
|:---:|:---:|:---:|
| <img src="assets/portraits/codex.png" width="200" alt="Codex 娘" /> | <img src="assets/portraits/kimi-code.png" width="200" alt="Kimi Code 娘" /> | <img src="assets/portraits/workbuddy.png" width="200" alt="Workbuddy 娘" /> |
| 5 个 `auto-generated` · 1 个 `verified ✓` | 200K context 还能再翻一页 | `误入 · Not a Coding Harness` |

| Trae 娘 · free lunch | Devin 娘 · robot arm | ZCode 娘 · terminal |
|:---:|:---:|:---:|
| <img src="assets/portraits/trae.png" width="200" alt="Trae 娘" /> | <img src="assets/portraits/devin.png" width="200" alt="Devin 娘" /> | <img src="assets/portraits/zcode.png" width="200" alt="ZCode 娘" /> |
| `for free` · forever? | 5 PR · 全 `unmerged` | `zcode run → done` · 无 FSRS |

| Qoder 娘 · specs | MiMo Code 娘 · 3 沙漏 | Codebuddy 娘 · penguin |
|:---:|:---:|:---:|
| <img src="assets/portraits/qoder.png" width="200" alt="Qoder 娘" /> | <img src="assets/portraits/mimo-code.png" width="200" alt="MiMo Code 娘" /> | <img src="assets/portraits/codebuddy.png" width="200" alt="Codebuddy 娘" /> |
| page 47 · `Evaluation criteria: undefined` | memory 沙漏裂了 · 流成 `Trainer` | 抱着企鹅的 QQ 登录窗 |

| DeepSeek 娘 · 蓝色大肥鱼 | | |
|:---:|:---:|:---:|
| <img src="assets/portraits/deepseek.png" width="200" alt="DeepSeek 娘" /> | | |
| 一碗白饭 · 全场最小的账单 `¥2/1M tokens` | | |

</div>

> 12 个 harness，1 个 Trainer。`workbuddy` 走错了房间，`codebuddy` 抱着腾讯的企鹅，`deepseek` 抱着白饭——它们不写代码，但都被 Trainer 收编。
> 12 harnesses, 1 Trainer. `workbuddy` walked into the wrong meeting; `codebuddy` is cuddling a Tencent penguin; `deepseek` is hugging her rice bowl — none of them write code, but Trainer has adopted them all.

---

## 为什么需要 Trainer · Why Trainer Exists

> 开发者卡住，从来不是因为缺教程。
> 是因为没有东西把学习闭环关上。

> Developers don't stall for lack of tutorials.
> They stall because nothing closes the learning loop.

和 LLM 聊完天，内容就蒸发了；视频看完了，是被动的；周二那个"差一点就懂了"的概念，周五就不见了。
A chat with an LLM evaporates the moment it ends; videos are passive; the concept you almost understood on Tuesday is gone by Friday.

更糟的是 **vibe coding**：让 AI 写三个月代码，自己一行也没懂。
Worse: **vibe coding** — letting AI write code for three months while you understand none of it.

收藏夹越来越厚，产出却停在原地。仓库越来越大，脑子越来越空。
Bookmarks pile up while output stays flat. Repos grow while your mind empties.

**Trainer 从编辑器内部解决这个问题。**
**Trainer solves this from inside the editor.**

它不是聊天壳子，而是有记忆、有课程、有考试政策的教练：
It's not a chat shell — it's a coach with memory, a curriculum, and an exam policy:

- 它把你的学习**规划**成阶段，并追踪你实际走到哪——而不是你"觉得"走到哪
  It **plans** your learning into stages and tracks where you actually are — not where you feel you are
- 它用闪卡、理论演练、场景实验**训练**你
  It **trains** you with flash cards, theory drills, and scenario experiments
- 它对照你的**真实代码验收**掌握度——聊明白 FastAPI 不算数，当前文件证明才算数
  It **verifies** mastery against your real code — talking about FastAPI counts for nothing until the current file proves it
- 它跨会话、跨项目、跨周地**记住**你，并按 FSRS 遗忘曲线安排复习
  It **remembers** you across sessions, projects, and weeks, scheduling reviews on the FSRS forgetting curve
- 它**绝不替你写生产代码**——你写，它教，**你们一起长**
  It **never writes production code for you** — you write, it teaches, **you grow together**

<div align="center">

| vibe coding · 今天的常态 | Trainer · 你值得的样子 |
|:---:|:---:|
| `def ship(code):` <br> `    ai.write(code)` <br> `# 你懂了吗？` <br> `    return forget(code)` | `def ship(code):` <br> `    you.write(code)` <br> `    ai.verify(code)` <br> `    you.recall(code)` <br> `    return grown(code)` |
| 产出 = 遗忘 · output = forgetting | 产出 + 记忆 + 复习 = 成长 · output + memory + review = growth |

</div>

---

## 安装 · Install

**从 VSIX（预构建，三平台）· From VSIX (prebuilt, three platforms):**

去 [v1.0.3 Release](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3) 下载对应平台的 `.vsix`（`darwin-arm64` / `linux-x64` / `win32-x64`）。
Grab the `.vsix` for your platform (`darwin-arm64` / `linux-x64` / `win32-x64`) from the [v1.0.3 release](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3).

VS Code 扩展面板 → `···` → *从 VSIX 安装* → 重载窗口。
VS Code Extensions panel → `···` → *Install from VSIX* → reload window.

**从源码 · From source:**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer && npm install
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build
```

在 VS Code 中打开本仓库按 F5（扩展开发宿主），或安装打包好的 VSIX。
Open this repo in VS Code and press F5 (Extension Development Host), or install the packaged VSIX.

**系统要求 · Requirements:** VS Code ≥ 1.96 · Python ≥ 3.12 (源码构建) · macOS / Linux / Windows

---

## 三步配置，没有第四步 · Three Steps, No Fourth

1. 打开 Trainer 侧边栏 → 设置
   Open the Trainer sidebar → Settings
2. 粘贴中转站连接信息（国内中转站复制的整段 JSON 直接识别，自动拆出地址和密钥）→ 粘贴 API 密钥
   Paste your relay connection info (the full JSON block copied from a relay dashboard is parsed automatically — endpoint and key are split out for you) → paste your API key
3. 点**保存并连接**
   Hit **Save & Connect**

Trainer 自动拉取在线模型列表、自动选择默认模型、自动验证流式链路。
Trainer pulls the live model list, picks a default model, and verifies the streaming path in one pass.

密钥错了会明确告诉你 `invalid_key_or_permission`，不是一个含糊的转圈。
A bad key reports `invalid_key_or_permission` — not a vague spinner.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="快速设置 · Quick setup" width="420" />
</p>

---

## 核心机制 · Core Mechanics

### ① 验证门禁 —— 你写代码，代码替你证明 · Verification Gates

训练卡推进到"已实现"必须先对当前文件跑验收；手动"标记完成"按钮被有意删除。
A training card cannot advance to "implemented" until verification runs against your actual file; a manual "mark done" button is deliberately absent.

伪造学习最快的方式是全标完成。Trainer 拒绝这样做。
The fastest way to fake learning is checking every box. Trainer refuses.

<p align="center"><img src="assets/feat-verify.png" alt="验证门禁 · Verification gates" width="720" /></p>

**怎么做到的 · How:**
- 服务端 `EvaluatorService` 在 **临时目录**复制当前文件 → 跑 ruff + pyright + pytest → 撕掉 tempdir
  Server `EvaluatorService` **copies** the current file into a `tempfile.TemporaryDirectory`, runs ruff + pyright + pytest, tears down the tempdir
- **从不**在用户工程里跑工具——杜绝 `.pytest_cache` 污染
  Tools **never** run in the learner&apos;s project — no `.pytest_cache` pollution
- 每条验收都有显式 `acceptance_criteria` + `expected_symbols` 列表，逐项 Matched/Missing 报告
  Every check reports per-criterion Matched/Missing detail
- 代码：`server/app/evaluator/service.py:198-312`

### ② 长期记忆 —— FSRS 遗忘曲线调度 · Long-Term Memory

掌握度、易错点、复习到期全部进 SQLite + Qdrant 语义检索。
Mastery, weak spots, and due reviews live in SQLite with Qdrant semantic retrieval.

复习按 FSRS 曲线出现，**快忘的时候才见，记得牢的不烦你**。
Reviews surface on the FSRS forgetting curve — they show up right before you&apos;d forget, and stay quiet while you still remember.

<p align="center"><img src="assets/feat-memory.png" alt="长期记忆 · Long-term memory" width="720" /></p>

**怎么做到的 · How:**
- 双层记忆：结构化（`StructuredMemoryService` ~480 条记录）+ 语义（Qdrant + sentence-transformer fallback）
  Two-layer memory: structured + semantic, with offline-friendly fallback
- **`_should_delay_live_thread_reviews()`** —— 流状态期间主动抑制复习，不打断思路
  Active-thread suppression: FSRS reviews held back during idea-implementation flow
- **可迁移技能跨工作区失效关闭**：一个项目成功 ≠ 全局掌握；要 ≥2 个工作区都通过才晋升 global
  Transferable skill gate: one project success never becomes global mastery; promotion requires ≥2 workspaces
- 关键代码：`server/app/memory/service.py:1357-1597` · `transfer_skills.py:81-113` · `review_scheduler.py:522-544`

### ③ 训练闭环 —— 到期才出现，验收才推进 · The Training Loop

闪卡、理论演练、场景实验都在训练视图排队：复习到期出现，卡片验收通过推进，对话里的知识缺口可以一键转成训练卡片。
Flash cards, theory drills, and scenario experiments queue in the Training view: reviews appear when due, cards advance when verified, and any knowledge gap in a conversation converts into a training card with one click.

<p align="center"><img src="assets/feat-training.png" alt="训练闭环 · The training loop" width="720" /></p>

**怎么做到的 · How:**
- **5 阶段状态机** `LEARN → TRY → VERIFY → REFLECT → RETURN`，每阶段写入 `phase_history`
  5-phase state machine, every transition logged
- **可信验证源白名单**：`automated_test` / `evaluator` / `ide_current_file` / `server_evaluator` / `test_runner` / `verification_service` —— "manual claim" 永远不推进
  Trusted verification sources: only 6 named sources can advance a card past VERIFY
- 卡片 UI 层面 `onSkip` / `onRate` **已被 `@deprecated Unused`** —— 唯一的推进路径是 `onCardStatusTransition`
  The UI physically cannot skip/grade without a verified transition
- 关键代码：`server/app/training/handoff.py:40-47` · `extension/webview/src/components/training/TrainingCardPanel.tsx:78-85`

### ④ 绝不代写 —— 你写，它教，你们一起长 · You Write, Coach Guides

教练可以读你的文件、看诊断、搜工作区，但生产代码永远出自你的手。
The coach reads your files, checks diagnostics, and searches the workspace — but production code always comes from your hands.

`direct` 模式直接给答案；`coach-first` 模式先让你想——**认知负荷是你的，不是它的**。
`direct` answers immediately; `coach-first` makes you think first. **The cognitive load is yours, not its.**

<p align="center"><img src="assets/feat-youwrite.png" alt="绝不代写 · You write, coach guides" width="720" /></p>

**怎么做到的 · How:**
- `PedagogyService` 每个回合产出 12 字段 `ImplementationGuide`，每字段都是"下一步允许问什么"的硬约束
  `PedagogyService` emits a 12-field `ImplementationGuide` — every field is a constraint on what the coach may ask next
- `ImplementationCoach._current_step` 永远锚定到"第一个失败路径"或"第一个 `workspace_understanding.entry_points`"
  `_current_step` is anchored to "the first failing path" or "the first known entry point" — never "explore the codebase"
- `AffectService` 在你重复碰壁两次时切换到 `concise_rescue` 模式——教练的**语气随你的状态变**
  Affect-driven tone: repeated failures → `concise_rescue` mode
- 关键代码：`server/app/pedagogy/implementation_coach.py:140-186` · `affect/service.py:142-152`

---

## 五个视图 · Five Views

> 五个固定顶层视图。每个视图都有明确职责边界。
> Five fixed top-level views. Each has a strict responsibility boundary.

| 视图 View | 中文 | English | 一句话 |
|-----------|------|---------|--------|
| **对话 Coach** | 教练对话 | Streaming coach chat | **入口**：工具访问 + `$` 技能面板 + 图像附件 + 答案模式 |
| **计划 Plan** | 学习计划 | Learning plan | **地图**：阶段、进度、证据、计划冻结/解冻 |
| **资料 Resources** | 资料库 | Library | **书柜**：FTS5 检索 + 三级沙箱预览 + 回收站可恢复 |
| **训练 Training** | 训练视图 | Training | **操场**：FSRS 闪卡 + 理论演练 + 场景实验 + 验证门禁 |
| **设置 Settings** | 设置 | Settings | **控制台**：59 命令 + 端点测速 + 思考强度 + 工作区准入 |

<p align="center">
  <img src="assets/screenshots/plan.png" alt="计划视图 · Plan view" width="260" />
  <img src="assets/screenshots/resources.png" alt="资料视图 · Resources view" width="260" />
  <img src="assets/screenshots/training.png" alt="训练视图 · Training view" width="260" />
</p>

### 教练对话 · Coach View（入口）

流式教练对话：工具访问（读文件/诊断/搜索）、`$` 技能面板、图片附件、答案模式、上下文用量环、会话历史与分享。
Streaming coach chat with tool access, `$` skill palette, image attachments, answer modes, context-usage ring, session history and share.

**每条教练回复都是可操作的学习材料**：
Every coach reply carries three quick actions underneath:

- **复制该回复为 Markdown** · Copy reply as Markdown
- **整段存入资料库**（可全文检索、可预览）· Save to library (searchable + previewable)
- **转成待验收的训练卡片**——不是会话级，是消息级 · Convert to verifiable training card — per message, not per session

<p align="center"><img src="assets/screenshots/message-actions.png" alt="回复级快捷操作 · Per-message actions" width="520" /></p>

### 自定义 `$` 技能 —— 可创建、可分享、可安装 · Custom `$` Skills

输入 `$` 呼出技能面板：内置技能之外，你可以把自己的 prompt 封装成技能，设置触发词和关键词，分享给别人，或安装别人分享的技能——**全走纯数据通道，不执行代码**。
Type `$` to open the skill palette: beyond built-ins, you can wrap your own prompts into skills with trigger words and keywords, share them with others, or install skills others share — **all through a pure data channel, no code execution**.

<p align="center">
  <img src="assets/screenshots/skill-deck.png" alt="技能面板 · Skill palette" width="380" />
  <img src="assets/screenshots/skill-manager.png" alt="技能管理 · Skill manager" width="380" />
</p>

<p align="center"><img src="assets/feat-skills.png" alt="自定义技能 · Custom skills" width="720" /></p>

**怎么做到的 · How:**
- 自定义技能是**纯 JSON 导入**——`{ _type, version, trigger, title, prompt, keywords }`
  Custom skills are pure-JSON imports — no `eval`, no `Function()`, no code path
- 字段硬限：prompt ≤ 4000 字符、title ≤ 160、keywords ≤ 16、用户自定义技能 ≤ 24 个
  Hard caps: prompt ≤ 4000 chars, title ≤ 160, keywords ≤ 16, user skills ≤ 24
- 内置触发词冲突时**内置优先**——用户导入的 `$explain` 永远打不赢内置的 `$explain`
  Built-in triggers win collisions — a user-imported `$explain` cannot shadow the shipped one
- 关键代码：`shared/src/skillCatalog.ts:614-764`

---

## 对比一下 · Compare

> Trainer 不是为了替代谁，而是为了补全一个空白。
> Trainer isn&apos;t here to replace anyone — it fills a gap no one else owns.

| 维度 · Dimension | vibe coding 工具 · vibe tools | 普通聊天 IDE · chat IDEs | 闪卡 App · flashcard apps | **Trainer** |
|---|---|---|---|---|
| 替你写代码 · Writes code for you | ✅ | ✅ | ❌ | ❌ |
| 验证你的代码 · Verifies your code | ❌ | ❌ | ❌ | ✅ 当前文件验收 |
| 跨会话记忆 · Remembers across sessions | ⚠️ 上下文窗口 | ⚠️ 摘要 | ✅ | ✅ SQLite + Qdrant |
| 按遗忘曲线复习 · Spaced repetition on FSRS | ❌ | ❌ | ✅ | ✅ + 流状态抑制 |
| 工作区权限模型 · Workspace permission tiers | ❌ | ⚠️ 信任弹窗 | ❌ | ✅ 6 级 + 远程硬锁 |
| 训练卡验证门禁 · Card progression gated | ❌ | ❌ | ⚠️ 手动勾选 | ✅ 强制 verified |
| 跨项目可迁移技能 · Transferable skill promotion | ❌ | ❌ | ❌ | ✅ 跨工作区失效关闭 |
| 8 语言 i18n · 8-language i18n | ⚠️ | ⚠️ | ⚠️ | ✅ 600+ keys × 8 |
| 测试套件 · Test suite | 闭源 | 闭源 | 闭源 | ✅ **3,328 cases**（开源）|
| 拒绝代写 · Refuses to write for you | ❌ | ❌ | n/a | ✅ 哲学底线 |

> **一句话**：其他工具让你更快写代码；Trainer 让你**真的会写**。
> One-liner: other tools make you write faster; Trainer makes you actually write.

---

## 五分钟演示 · Five-Minute Demo

> 这是你装上 Trainer 后前五分钟的真实剧本。
> Here&apos;s what your first five minutes actually look like.

### T+0:00 — 打开侧边栏 · Open the sidebar
点击活动栏的 Trainer 图标。侧边栏弹出，**默认进入对话视图**。
Click the Trainer icon in the activity bar. The sidebar opens, defaulting to **Coach view**.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="首次打开 · First open" width="420" />
</p>

### T+0:30 — 设置供应商（首次） · Configure provider (first time only)
左侧导航 → **设置** → 粘贴你的中转站 JSON + API 密钥 → 保存并连接。
Settings → paste your relay JSON + API key → Save & Connect.

Trainer 自动拉取在线模型、选默认、验证流式。密钥错 → 明确告诉你 `invalid_key_or_permission`。
Trainer pulls the live model list, picks a default, verifies streaming. Bad key → tells you `invalid_key_or_permission`.

### T+1:30 — 第一次对话 · First conversation
回到 **对话** 视图，敲：`@current_file 解释一下这段 async/await 在做什么？`
Switch to Coach, type: `@current_file explain what this async/await is doing?`

Trainer 流式回复，**不会**给你写重写后的代码——它指着第 17 行说："这里 `await asyncio.gather(*tasks)` 是 fan-out；第 23 行的 `return` 是 barrier。如果你想真正学会，下一步写一个 fan-out 后立刻 cancel 一个的版本，我陪你跑验收。"
Trainer streams a reply. **It does not rewrite your code.** It points at line 17: "this is fan-out"; line 23: "this is the barrier. To actually learn this, write a version that cancels one task mid-flight — I&apos;ll run verification with you."

### T+2:30 — 一键转训练卡 · One-click training card
你读完那条回复。**鼠标悬停** → 三个按钮：`复制` / `存入资料库` / **`转训练卡`**。
Hover over the reply. Three buttons: `Copy` / `Save to library` / **`Create training card`**.

点 `转训练卡` → 卡片生成 → 进入训练视图 → 排在 FSRS 队列里 3 天后到期。
Click `Create training card` → card generated → enters Training view → FSRS schedules it for 3 days from now.

### T+4:00 — 自己写，被验收 · Write yourself, get verified
你写代码。Trainer **不替你写**。
You write code. Trainer **does not write it for you**.

打开训练视图 → 看到那张卡 → 翻面看 pass criteria → 写完 → 点 `请求验收` → Trainer 在临时目录跑 ruff + pyright + pytest → 报告通过 / 指出哪个 acceptance criterion 没匹配。
Open Training → flip card → see pass criteria → write → click `Request verification` → Trainer runs ruff + pyright + pytest in a sandbox → reports pass or flags missing criterion.

### T+5:00 — 你的第二天 · The next day
明天打开 VS Code：Trainer 在侧边栏**自动恢复**——上次的会话、计划、卡片进度全在。
Open VS Code tomorrow: Trainer auto-restores — last session, plan, card progress all there.

那张卡片在 FSRS 节奏盘上**闪烁**——今天到期。
That card pulses on the FSRS rhythm disk — due today.

**你不再是 vibe coding 的开发者了。**
**You are no longer a vibe-coding developer.**

---

## 为什么看起来不一样 · Why It Feels Different

### 诚实的失败 · Honest Failure

密钥错了会明确告诉你 `invalid_key_or_permission`；连不上告诉你 `network`；模型回复损坏时明确说"这条回复没有读清，请重发"——**绝不把损坏的输出当作答案**。
A bad key says `invalid_key_or_permission`; unreachable says `network`; a corrupted reply says "this reply wasn&apos;t read clearly, resend" — **broken output is never dressed up as an answer**.

未知网关不会被默认当成 OpenAI 兼容。
Unknown gateways aren&apos;t silently assumed OpenAI-compatible.

**怎么做到的 · How:** 错误分类器（`provider_service.py:2823-2874`）+ 凭据脱敏（`provider_protocols.py:640-681`）+ 未知指纹探测（`provider_gateway.py:39-70`）。

### 端点测速 · Endpoint Speed Test

多个服务商端点并行竞速（**先热身消首包惩罚，再计时**）。
Provider endpoints race in parallel (**warm-up first to cancel cold-start penalty, then timed**).

500ms 内绿色，1 秒内黄色。点一下就采用最快端点。
Green under 500 ms, yellow under 1 s. One click adopts the fastest.

<p align="center"><img src="assets/feat-speed.png" alt="端点测速 · Endpoint speed test" width="720" /></p>

**怎么做到的 · How:** `Promise.all` 并行 + 每条 URL 先发一次被丢弃的热身请求，再对第二次请求计时（`providerWebviewCommands.ts:2275-2352`）。

### 上下文用量环 · Context-Usage Ring

对话视图顶部有实时上下文用量环，**压缩发生前你就看得到**。
A live context-usage ring sits atop the conversation — **you see compression coming before it happens**.

### 思考强度 · Thinking Intensity

按模型证据开启——**声明了能力或实测通过才发 thinking 参数**，绝不盲目透传。
Gated on per-model evidence — declared capability **or** verified probe. Never blindly forwarded.

### 资料库全权 · Full-Power Library

<p align="center"><img src="assets/feat-library.png" alt="资料库全权 · Full-power library" width="720" /></p>

上传即索引、全文检索（FTS5）、**沙箱分级预览**（Tier A 富渲染 / Tier B 转换 / Tier C 元数据 + 原生编辑器回退）、删除进回收站可恢复。
Uploads indexed on arrival, FTS5 full-text search, **3-tier sandbox preview** (A rich / B converted / C metadata + native editor fallback), deletions go to restorable recycle bin.

**3 域物理隔离**：workspace（你的项目）/ sandbox（处理区）/ trash（回收站）——**永不混淆**。
**3-zone physical separation**: workspace / sandbox / trash. Never mixed.

教练回复也能一键入库——**搜得回来才算学到**。
Coach replies drop in with one click — **if you can search it back, you actually learned it**.

### 长程状态 · Long-Horizon State

计划可冻结/解冻；会话跨重启存活；卡片进度存进 SQLite；复习按 FSRS 曲线到期，**不是按待办清单**。
Plans freeze and unfreeze; sessions survive restarts; card progress lives in SQLite; reviews come due on the FSRS curve — **not on a to-do list**.

---

## 架构 · Architecture

### 系统拓扑 · System Topology

```
┌─────────────────────────────────────────────────────────────┐
│                    VS Code 窗口 Window                        │
│  ┌───────────────────────────────────────────────────────┐  │
│  │   Trainer 侧边栏 Sidebar                              │  │
│  │   (React 19 + Zustand, 8 语言 i18n, 24 模块治理)     │  │
│  │                                                       │  │
│  │   ─── postMessage ─── CommandRegistry ── 59 commands  │  │
│  │                                       │               │  │
│  └───────────────────────────────────────┼───────────────┘  │
│                                          │                   │
│                          ┌───────────────▼──────────────┐    │
│                          │  FastAPI sidecar (127.0.0.1)│    │
│                          │  PyInstaller --onedir frozen│    │
│                          │  (250 MB / 6 platform arch) │    │
│                          │                              │    │
│                          │  ├── ReAct agent loop        │    │
│                          │  │   (双通道流 + 熔断器)     │    │
│                          │  ├── Pedagogy (12 字段指南)  │    │
│                          │  ├── Affect (重复失败 → rescue)│  │
│                          │  ├── Memory                  │    │
│                          │  │   SQLite + Qdrant 语义    │    │
│                          │  ├── FSRS scheduler          │    │
│                          │  ├── Authority (6 级 + 远程锁)│   │
│                          │  ├── Provider (5 协议 + 拒入) │    │
│                          │  ├── Training handoff (5 相)  │    │
│                          │  └── Resources (3 域 + FTS5)  │    │
│                          │                              │    │
│                          │  ─── 共享 24 pure functions ─│    │
│                          │      (host + webview + test)  │    │
│                          └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 目录布局 · Directory Layout

| 目录 · Folder | 内容 · Contents | 大小 · Size |
|---|---|---|
| `extension/src/` | 宿主：命令、工作区信任、密钥存储、sidecar 生命周期 | ~30k 行 TS |
| `extension/webview/` | React 工作台：5 视图 + Zustand + 8 语言 | ~50k 行 TSX |
| `extension/tests/` | node:test 测试（220 文件 / 1,679 cases）| 73,744 行 |
| `server/app/` | FastAPI 大脑：agent / pedagogy / memory / FSRS / training | ~120k 行 Python |
| `server/tests/` | pytest 测试（159 文件 / 1,649 cases）| 106,422 行 |
| `shared/src/` | **双端共用纯函数 + 24 governance 模块**（host + webview + test 同跑）| ~3k 行 TS |
| `extension/bundled/` | 打包进 VSIX 的 sidecar（PyInstaller onedir）| ~250 MB |

### 单一信封 · One Canonical Envelope

> Trainer 的所有 HTTP 响应（除了 `/health`）都返回**同一个** `WorkbenchSnapshot`（31 字段）。
> All Trainer HTTP responses (except `/health`) return the **same** `WorkbenchSnapshot` (31 fields).

| 字段类别 · Category | 字段示例 · Sample fields | 生产者 · Producer |
|---|---|---|
| 会话 · Session | `messages`, `coaching_state`, `learner_state` | `pedagogy/service.py` |
| 计划 · Plan | `plan`, `global_plan`, `project_plan_link`, `current_task` | `planner/service.py` |
| 记忆 · Memory | `memory`, `selected_teaching_assets`, `next_review_due` | `memory/service.py` |
| 教学 · Teaching | `teaching_decision`, `implementation_guide`, `project_ideas` | `pedagogy/*` |
| 情感 · Affect | `affect_state`, `tone_decision` | `affect/service.py` |
| 训练 · Training | `evaluation`, `review_queue_summary` | `training/*` |
| 元 · Meta | `context_id`, `sidecar_status`, `snapshot_revision`, `active_panel` | `api/runtime.py` |

**为什么一个信封 · Why one envelope:**
- webview 渲染**完全从这一个对象**开始——12 个子系统各写自己的字段，hydrate 一次成图
  Webview renders **entirely from this one object** — 12 subsystems write their fields, hydrate once
- **CRDT-light 增量同步**：每个 snapshot 有 `snapshot_revision`；`GET /snapshot?since_revision=N` 只在 N 过期时返回完整 blob，否则返回 `{unchanged: true}`
  **CRDT-light incremental sync**: each snapshot has a revision; only ships the diff
- 关键代码：`server/app/core/models.py:2304-2336` · `server/app/api/routers.py:11648-11710`

### 共享治理模块 · Shared Governance Modules

> Trainer 的架构核心是 **24 个 pure function 模块**——host、webview、测试三方**跑同一份确定性逻辑**。
> Trainer&apos;s architectural backbone is **24 pure-function governance modules** — host, webview, and test all run the same deterministic logic.

| 模块 · Module | 职责 · Role |
|---|---|
| `planGovernance` · `masterPlanGovernance` | 计划编辑、跨项目主线 |
| `trainingHandoffGovernance` · `trainingRecoveryGovernance` · `trainingReliabilityGovernance` | 训练卡路由、恢复、可靠性 |
| `reviewQueueGovernance` · `reviewArtifactGovernance` | FSRS 队列排序、证据审查 |
| `workspaceAuthority` · `workspaceRecoveryGovernance` | 6 级权限、恢复 |
| `suggestedActionGovernance` · `conversationCandidateGovernance` | 教练建议动作、对话候选仲裁 |
| `transferEvidenceGovernance` · `transferSkillGovernance` | 跨项目证据、可迁移技能晋升 |
| `coachOrientationGovernance` · `resourcesOrientationGovernance` | 教练/资源视图朝向 |
| `settingsCapabilityGovernance` · `operationReliabilityGovernance` | 设置能力门控、操作可靠性 |
| `hostLastTestGovernance` · `providerModelPolicy` | 提供商最后测试、模型策略 |
| `sandboxNetworkCapabilityNarrative` · `projectLaneGovernance` | 沙箱能力叙事、项目通道 |
| `previewAssets` · `materialRecommendationGovernance` | 预览资产分级、素材推荐 |

**好处 · Why:** 同一个 `resolveSuggestedActionGovernance` 在 host 跑一遍、webview 跑一遍、测试跑一遍——**三方一致，无需 round-trip**。
Same `resolveSuggestedActionGovernance` runs in host, webview, and tests — **three-way consistent, no round-trips**.

---

## 安全模型 · Safety Model

- API 密钥存放在 **VS Code SecretStorage**（系统级加密），不进配置文件、不进 git
  API keys live in **VS Code SecretStorage** (OS-level encryption) — never in config files, never in git
- 工作区遵循 **VS Code 原生信任机制**，未信任时写操作全部拒绝
  Workspace follows **native VS Code trust** — all writes are refused while untrusted
- **6 级权限梯度**：INSPECT < ANNOTATE < REORGANIZE < GENERATE < APPLY < DESTRUCTIVE
  **6-tier permission ladder** — read-only by default; write/delete/modify require escalating attestation
- **远程工作区硬锁**：`REORGANIZE+` 在远程/未信任时**强制拒绝**——用户授权也不能突破
  **Remote workspaces are hard-locked below REORGANIZE** — even user grant cannot elevate
- **删除走回收站**：没有 `delete`，只有 `move to <root>/.trash/<timestamp-uuid>/`
  **Delete goes to trash**: no `delete` op, only `move to trash`
- 沙箱预览有严格的**路径治理**：越界路径直接 422 拒绝
  Sandbox previews enforce strict **path governance** — out-of-bounds paths get a flat 422
- 技能分享是**纯数据导入**：字段限长、内置技能优先、只展开成普通对话消息，**没有任何代码执行路径**
  Skill sharing is a **pure-data import** — capped field lengths, built-ins win, **no code path exists**

**关键代码 · Key code:** `server/app/workspace/authority.py:33-962` · `extension/src/provider/providerConfigStore.ts` · `shared/src/skillCatalog.ts:614-764`

---

## 质量门禁 · Quality Gates

> Trainer 把自己的验证体系当成产品来打磨。
> Trainer treats its own verification stack as a product.

| 门禁 · Gate | 数量 · Coverage | 说明 · Notes |
|---|---|---|
| **服务端测试** · Server tests (pytest) | **159 文件 / 1,649 cases / 106,422 行** | 含 6 套 Hypothesis property-based |
| **扩展测试** · Extension tests (node:test) | **220 文件 / 1,679 cases / 73,744 行** | 109 文件是源码守卫 + 111 行为测试 |
| **端到端** · E2E | **11 规格 / 4,335 行** | 含真实 VS Code 实例接入真实模型 |
| **体验矩阵** · Experience matrix | **200 场景 × 2 层** | Preview fixture + 真实 sidecar |
| **VSIX 真机驱动** · VSIX host driver | **33 步** | 装包 → 激活 → 流式 → 验收 → 断言 webview 真实渲染 |
| **静态分析** · Static analysis | ruff + pyright + tsc | 零告警 · zero warnings |
| **协议矩阵** · Protocol matrix | **5 协议** | OpenAI Chat / Responses / Anthropic / Gemini / OpenAI-Compatible |
| **i18n** | **8 语言 × 600+ key** | zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR |
| **bundled sidecar** | **6 平台二进制** | win32-x64 / win32-arm64 / darwin-x64 / darwin-arm64 / linux-x64 / linux-arm64 |

**端到端套件在真实 VS Code 实例中接入真实模型运行**：
The E2E suite runs in a real VS Code instance against a real model:

> 激活打包后的扩展 → 启动内置 sidecar → 保存供应商 → 流式完成教练回合 → 生成并验收训练卡 → 断言 webview **实际渲染**的内容 → 截屏 → 跨工作区重开恢复历史
> Activates the packaged extension → boots bundled sidecar → saves provider → streams full coach turn → generates and verifies a training card → asserts what the webview **actually rendered** → screenshots → reopens across workspaces and recovers history.

**测试自带证据声明 · Tests self-attest their limits:**
每个 E2E 场景都自带 `evidence: { realSidecar: false, limitation: "..." }`——**测试自己声明它不证明什么**。
Each E2E scenario carries `evidence: { realSidecar, limitation }` — **the test declares what it does not prove.**

---

## i18n · Eight Languages

| 语言 · Lang | 代码 · Code | 主翻译 · Primary |
|---|---|---|
| 简体中文 | `zh-CN` | ✅ |
| English | `en-US` | ✅ |
| Español | `es-ES` | ✅ |
| Français | `fr-FR` | ✅ |
| Deutsch | `de-DE` | ✅ |
| 日本語 | `ja-JP` | ✅ |
| 한국어 | `ko-KR` | ✅ |
| Português | `pt-BR` | ✅ |

**退化策略 · Fallback chain:** 用户偏好 > VS Code `env.language` > `zh-CN` (默认)
User preference > VS Code `env.language` > `zh-CN` (default)

**6 表面分覆盖 · 6 surface-scoped overrides:** `resourceView` / `contextRail` / `trainingUi` / `orientationRail` / `composerAccessibility` / `leftoverHonesty`——翻译人员只需补自己负责的块，**不用填 600+ key 全表**。
Translators only fill the surfaces they own — **not the full 600+ key table**.

关键代码：`extension/webview/src/lib/i18n/copy.ts`（5,283 行）

---

## 致谢 · Acknowledgements

> Trainer 站在巨人的肩膀上。
> Trainer stands on the shoulders of giants.

### 🏃 运行时核心 · Runtime Core

| 项目 · Project | 用途 · Purpose | 为什么不可替代 · Why irreplaceable |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | 本地 sidecar 服务框架 | async + Pydantic + 自动 OpenAPI 文档 |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI 服务器 | HTTP/1.1 + WebSocket + 高并发 |
| [Pydantic](https://github.com/pydantic/pydantic) | 数据验证与序列化 | WorkbenchSnapshot 31 字段全靠它 |
| [httpx](https://github.com/encode/httpx) | 异步 HTTP 客户端 | sidecar ↔ LLM 网关的协议路由全用它 |

### 🤖 LLM 协议 · LLM Protocols

| 项目 · Project | 用途 · Purpose |
|---|---|
| [openai-python](https://github.com/openai/openai-python) | OpenAI / Anthropic / Gemini 兼容客户端（5 协议路由） |

### 🧠 训练与记忆 · Training & Memory

| 项目 · Project | 用途 · Purpose |
|---|---|
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | FSRS 遗忘曲线复习调度 · `TrainingCardState` 全包 |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | 语义记忆向量检索（带 sentence-transformer fallback） |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF 解析（资料库 Tier A 预览） |
| [trafilatura](https://github.com/adbar/trafilatura) | 网页正文抽取（资源摄取） |
| [markitdown](https://github.com/microsoft/markitdown) | 文档 → Markdown 转换（资料库 Tier B 预览） |

### ⚛️ 前端核心 · Frontend Core

| 项目 · Project | 用途 · Purpose |
|---|---|
| [React](https://github.com/facebook/react) | 侧边栏工作台 UI |
| [Vite](https://github.com/vitejs/vite) | 构建工具 + 开发服务器 |
| [Zustand](https://github.com/pmndrs/zustand) | 工作台状态管理 |
| [Zod](https://github.com/colinhacks/zod) | 运行时类型校验 |

### 🎨 渲染 · Rendering

| 项目 · Project | 用途 · Purpose |
|---|---|
| [react-markdown](https://github.com/remarkjs/react-markdown) | Markdown 渲染 |
| [remark-gfm](https://github.com/remarkjs/remark-gfm) | GFM 扩展（表格、任务列表） |
| [remark-math](https://github.com/remarkjs/remark-math) · [rehype-katex](https://github.com/remarkjs/rehype-katex) · [KaTeX](https://github.com/KaTeX/KaTeX) | 数学公式渲染 |
| [Shiki](https://github.com/shikijs/shiki) | 代码高亮（VS Code 同款 TextMate 语法） |
| [Mermaid](https://github.com/mermaid-js/mermaid) | 图表与流程图 |
| [@tanstack/react-table](https://github.com/TanStack/table) | 资料库 / 训练队列表格 |

### 📄 预览 · Preview

| 项目 · Project | 用途 · Purpose |
|---|---|
| [mammoth](https://github.com/mwilliamson/mammoth.js) · [docx-preview](https://github.com/VolodymyrBaydalka/docx-preview) | DOCX 富渲染（Tier A） |
| PDF.js (bundled) | PDF 富渲染（Tier A） |

### 🧪 测试与质量 · Testing & Quality

| 项目 · Project | 用途 · Purpose |
|---|---|
| [pytest](https://github.com/pytest-dev/pytest) · [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | 服务端 159 文件 / 1,649 cases |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | 属性测试（planner / evaluator / scheduler） |
| [ruff](https://github.com/astral-sh/ruff) | Python lint + format（E/F/I/B, py312, 100 列） |
| [pyright](https://github.com/microsoft/pyright) | Python 静态类型检查 |
| [TypeScript](https://github.com/microsoft/TypeScript) | strict 模式，零告警 |
| [Playwright](https://github.com/microsoft/playwright) | E2E + 200 场景体验矩阵 |

### 📦 打包与分发 · Packaging & Distribution

| 项目 · Project | 用途 · Purpose |
|---|---|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | sidecar 单二进制冻结（6 平台，manifest sha256 校验） |

### 💡 方法论灵感 · Methodology Inspiration

| 项目 · Project | 启发 · Inspiration |
|---|---|
| [open-spaced-repetition/fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki) | FSRS 算法原始论文与参考实现 |
| [obra/superpowers](https://github.com/obra/superpowers) | "Mandatory workflows, not suggestions" 的教练纪律 |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | "让所有软件变 agent-native" 的范式野心 |

### 🎨 视觉资产 · Visual Assets

| 项目 · Project | 用途 · Purpose |
|---|---|
| [dora-image](https://github.com/AI-yyf/trainer/tree/main/assets) | 本仓库 README 全部配图（详见 `assets/MASCOT.md` / `BANNER_PROMPT.md` / `FEATURE_PROMPTS.md`） |
| DeepSeek 官方二次元娘 | Q 版头身比 / cel-shading 倾向参考 |
| Pieter Bruegel 《通天塔》 | 群像左右阵营构图参考 |
| Rembrandt 《夜巡》 | 7:1 明暗对比参考 |
| Studio Ghibli 角色设计 | 大眼三点高光、表情克制 |

---

## 许可 · License

[MIT](LICENSE)

---

## 引用本项目 · Citing Trainer

如果 Trainer 帮到了你的开发流，欢迎在你的博客 / 论文 / 演讲里引用：

```bibtex
@software{trainer2026,
  title  = {Trainer: A Long-Term Coding Coach Living in Your Editor},
  author = {AI-yyf and contributors},
  year   = {2026},
  url    = {https://github.com/AI-yyf/trainer},
  note   = {v1.0.3}
}
```

---

<div align="center">

**// 训练你的 AI · 与你的 AI 共同成长**
**// Train Your AI · Grow With Your AI**

`v1.0.3` · Made with 咖啡、FSRS、24 个 pure function、3,328 个测试、和一颗不替你写代码的心。

</div>
