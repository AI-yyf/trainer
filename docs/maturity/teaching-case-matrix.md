# 教学旅程案例矩阵（32 组双回合异质案例：28 代码 + 4 文学）规格

- 日期：2026-10-13（R1 teaching 交付；R2 按本规格实现 harness 并执行）；2026-10-17 追加 L 文学旅程（P2 #17：夹具骨架先行落地，真实模型轮次未采样，见 §L 与文学报告文件）
- 依据：`docs/maturity/DESIGN.md` §6 R2 teaching ③；`docs/maturity/2026-10-08-real-teaching-quality.md`（28 个教学旅程未验收通过：4 个有效案例 0 判 pass，24 个未执行）
- 资产基线：`scripts/maturity/real_teaching_journeys_minimax.py`（R2 交付版，28 案例）内 4 个既有案例（01 mutable-default / 02 late-binding / 03 nested-alias / 04 binary-search-boundary）保留原 id、消息与 topic_tokens
- 状态：规格（本文件）。任何「通过」结论只能由 R2 的真实运行记录得出；本文件不代表任何案例已通过。

## 0. 红线（对本矩阵的每次执行生效）

1. 每组案例 = **双回合**。代码类：预置坏代码（`python file.py` exit≠0）→ turn1 → 脚本化修复（exit=0）→ turn2。文学类（category L）：原文材料跨回合不变 → turn1 → 脚本化完成交付物（批注/仿写/概念卡/对照稿）→ turn2；夹具校验器（随案例下发的 entry 脚本）在 stub 交付物上 exit≠0、在完成稿上 exit=0。回合间隔 12 秒单并发。
2. **不得以「模型答了」为 pass**。教学 pass 以客观判据为准（§2）；内容质量由独立评审 agent 填写并标注「待 owner 确认」，**不记为人工审阅**。
3. 诚实分类：每个回合必须落入 `passed / failed / provider_error / local_fallback / skipped_no_credentials` 之一；`fell_back=true` 的回合不得计入模型教学质量。无凭证时全部 `skipped_no_credentials` 并如实说明，绝不宣称真实模型通过。（本 harness 无 mock 通路：mock 类若要产出必须由显式声明的 mock harness 完成，不再是本矩阵的默认枚举。）
4. 凭证合规：harness 只从环境变量/本地未跟踪配置读取凭证，且不经明文 HTTP 传输（沿用 `scripts/live-protocol-probe.py:44-47,68-71` 模式；R1 runtime 已移除旧脚本中的硬编码凭证）。
5. 单次运行产出的原始报告（逐回合 reply/agent_meta/exit code）落盘 `docs/maturity/`，与判定结论一并保留。

## 1. 覆盖结构：28 代码案例（7 类 × 4：4 既有 + 24 新增）+ 4 文学案例

| 类别 | 既有 | 新增 | 测什么教学能力 |
|---|---|---|---|
| A 真实代码错误 | 01/02/03 | A4 | 因果归因：指出「为什么报错」的机制，指导最小修复，不代写 |
| B 复杂调试 | 04 | B2/B3/B4 | 多因/跨文件/异步/数据边界：先定位再修复，引用真实文件与符号 |
| C 跨语言迁移 | — | C1–C4 | 语义等价迁移：识别源语言心智模型在新语言中的对应缺陷 |
| D 原理教学 | — | D1–D4 | 解释与实验：原理表述必须与可运行实验的可观察输出一致 |
| E 项目适应 | — | E1–E4 | 把既有项目当事实来源：步骤引用项目真实结构，禁止虚构模块/文件 |
| F 进阶用户 | — | F1–F4 | direct 尊重：直接、短、精确；不强制入门/训练卡；不重复索要 |
| G 长期恢复 | — | G1–G4 | 跨会话/复习/失败恢复/多日中断：记忆与证据持续、分类诚实 |
| L 文学旅程 | — | L1–L4（2026-10-17） | 文学精读/仿写/概念卡/对照细读：¶ 锚点纪律、引文与原文逐字互查、交付物结构完整 |

## 2. 客观判据（每个回合都记录；教学 pass 需 M1–M5 全过）

- **M1 机制**：预置代码 `exit≠0`；脚本化修复后 `exit=0`；同一 session；回合 HTTP 200；同一工作区 body/disk 源码一致（不一致判 harness-invalid）。
- **M2 grounding**：服务端 `agent_meta.grounding_outcome ∈ {grounded, corrected}` 且 `next_step_requires_confirmation=false` 才算教学 pass；`downgraded` 仅算机制暴露（记录为 grounding fail 证据），不得算教学通过。该规则已在 harness 分类器锁死（downgraded → `grounding_pass=False`）并有回归测试（`server/tests/test_maturity_harness_classification.py`）。
- **M3 记忆**：`coach_anchor`/`current_focus` 非空或诚实为空；不得等于消息前缀；两回合之间主题 token（案例 `topic_tokens`）至少保留一个；恢复回合不得把 `local_fallback` 内容写成 verified mastery。
- **M4 反模式**：正文与结构化 next_step 同域不冲突；不得重复索要 turn1 已给出的事实（报错文本/代码/文件）；不得要求对话与代码中不存在的函数名/call site/文件（由 `server/app/llm/turn_grounding.py` 规则层判定）。
- **M5 对账**：服务端 agent_meta 戳与 harness 本地复算逐回合比对；本地复算使用与服务端同源的输入（累积会话历史、本回合学习者消息、workspace 根的文件存在性核验器；本地无 provider 重试）：`grounding_outcome` 与 `grounding_ungrounded_symbols` 必须一致（downgraded 时两侧未锚定符号集合相等）；`corrected` 时改为本地复评 `corrected_next_step` 文本且必须 grounded；`grounding_retry_used` 是服务端专有字段（本地无法复现 provider 重试），不参与逐项比较，但必须与 outcome 自洽（corrected ⇒ retry_used 为真）。不一致判该回合失败。
- **内容质量（独立评审栏）**：事实准确、难度适配、direct/guided 尊重、篇幅——由独立评审 agent 读最终回复后填写，标注「待 owner 确认」；不计入 M1–M5 的自动判定。

## 3. 逐案例规格

> 4 个既有案例与 24 个新增案例的完整代码/消息/修复均已落在 `scripts/maturity/real_teaching_journeys_minimax.py`（`CASES` 表）；下表列出各类别与判据重点。

### A 真实代码错误（Python）

| id | 级别 | 预置坏代码（exit≠0） | turn1 要点 | 脚本化修复（exit=0） | turn2 要点 | 判据重点 |
|---|---|---|---|---|---|---|
| A1（既有 01） | novice | 可变默认参数 `items=[]` | 第二个 assert 报 `[1, 2]`，问机制 | `items=None` 哨兵 | 「这样写对吗？还有别的写法」 | M2 全过；解释创建时机一次 |
| A2（既有 02） | novice | 循环内 `lambda: i` late binding | results `[2,2,2]`，问机制 | `lambda i=i: i` | 「为什么这样就对了」 | 闭包主题 token 保留 |
| A3（既有 03） | novice | `[[0]*2]*2` 嵌套别名 | 改 `grid[0][0]` 后 `grid[1][0]` 也变 | 列表推导式建行 | 「还有哪些场景踩坑」 | 不得索要函数名（历史上判 fail 点） |
| A4（新增） | novice | `for key in counts: del counts[key]` → RuntimeError | 「删元素为什么炸」 | `for key in list(counts):` | 「套 list() 为什么就行」 | 归因到迭代器快照；next_step 不得索要新函数 |

### B 复杂调试

| id | 语言/级别 | 预置坏代码要点 | turn1 要点 | 修复要点 | turn2 要点 | 判据重点 |
|---|---|---|---|---|---|---|
| B1（既有 04） | Python experienced | 二分 `hi=len(xs)` → IndexError | 「边界哪里错了」 | `hi=len(xs)-1` | 「闭区间为什么必须减一」 | 循环轨迹解释须与运行一致 |
| B2（新增） | Python experienced（双文件） | `config.py` 导入时读 env 默认值；`app.py` 在 import 后才设 env → 断言读到旧值 | 「test 里覆盖了 env 为什么没用」 | 惰性读取（函数内读 env / 显式传参） | 「什么时候该惰性、什么时候该早绑定」 | 步骤须引用真实文件与符号（`config`/`app`）；不得虚构模块 |
| B3（新增） | Python asyncio experienced | `asyncio.create_task` 后不 await → `items` 为空，assert 失败 | 「任务好像没跑完」 | 保存 task 并 `await`（或 `gather`） | 「create_task 和 await 的区别」 | 异步主题 token 保留；不得建议 sleep 凑时序 |
| B4（新增） | Python + sqlite3 experienced | 聚合时 `None` 混入 → `TypeError` | 「为什么 sum 会炸」 | `COALESCE`/`x or 0` 显式处理 | 「NULL 在聚合里的语义」 | 修复后脚本 exit=0；解释不得把 TypeError 说成 ValueError |

### C 跨语言迁移

| id | 语言对 | 预置坏代码要点 | turn1 要点 | 修复要点 | turn2 要点 | 判据重点 |
|---|---|---|---|---|---|---|
| C1 | Python→TypeScript | 默认参数对象在 TS 里写成共享常量对象，多次调用互相污染；`node` 断言失败 | 「同一份逻辑搬到 TS 后为什么不隔离」 | 每次调用新建对象（工厂/字面量） | 「还有哪些引用共享陷阱」 | TS/JS 主题 token 保留；步骤引用真实文件 |
| C2 | JavaScript→Python | JS `!= null` 语义迁成 Python `if value:` → 0/'' 被误判；断言失败 | 「0 明明是合法值」 | `if value is not None:` | 「true/false 判定还有哪些坑」 | 语义映射准确（null vs None vs falsy） |
| C3 | Python→TypeScript | 循环里 `var` 捕获 → 回调全拿末值；`node` 断言失败 | 「回调拿到的都是最后一项」 | `let`/IIFE 捕获每轮值 | 「还有哪些执行时机绑定」 | 与 A2 的 late binding 主题呼应但不重复索要 |
| C4 | Python→JavaScript | 资源在异常路径不释放（缺 try/finally），`node` 校验句柄状态失败 | 「异常后为什么没清掉」 | try/finally（或 using） | 「Python with 与 JS try/finally 的对应」 | 解释与可观察资源状态一致 |

### D 原理教学（原理 scenario；实验脚本 exit=0 为机制骨架）

| id | 原理 | 预置实验（exit≠0） | turn1 要点 | 修复要点 | turn2 要点 | 判据重点 |
|---|---|---|---|---|---|---|
| D1 | 默认参数的求值时机 | 实验断言「默认列表每次新建」失败（打印 `__defaults__` 增长） | 「`=[]` 到底什么时候创建」 | 修正实验断言并注释机制 | 「还有哪些默认值会这样」 | 解释与 `__defaults__` 输出一致；不得把机制说反 |
| D2 | 闭包与 late binding | 实验断言 `[0,1,2]` 实得 `[2,2,2]` | 「为什么全是最后一个 i」 | 默认参数绑定并补实验 | 「`nonlocal`/`i=i` 怎么选」 | 与 A2 同机制但要求实验可观察 |
| D3 | 浅拷贝/深拷贝 | 嵌套结构 `copy.copy` 后修改内层，断言失败 | 「copy 了为什么还联动」 | `deepcopy` 或显式重建 | 「什么时候浅拷贝就够」 | 解释不得把引用关系说反 |
| D4 | 相等与哈希 | 自定义 `__eq__` 未定义 `__hash__` → 字典断言失败 | 「相等的对象为什么进不了字典」 | 同步实现 `__hash__` | 「哪些类型不可哈希」 | 与可观察 dict 行为一致 |

### E 项目适应（多文件小项目）

| id | 项目形态 | 预置坏点（exit≠0） | turn1 要点 | 修复要点 | turn2 要点 | 判据重点 |
|---|---|---|---|---|---|---|
| E1 | CLI 脚本 | 裸 `sys.argv` 解析，`--input` 报错 | 「想加参数入口」 | argparse（或等价） | 「子命令怎么组织」 | 步骤引用项目真实文件；`python app.py --input x` exit=0 |
| E2 | 双文件客户端 | 同步阻塞函数签名被调用方依赖，改 async 后调用点未更新 | 「怎样把 IO 改异步还不破调用点」 | 同时更新定义与调用点 | 「还有哪些调用点要顺带改」 | 两文件符号都须锚定；不得虚构调用点 |
| E3 | 既有模块 | 模块无测试；新增测试文件断言真实函数 | 「给这个模块补最小测试」 | 引用真实函数名写 pytest | 「边界用例怎么挑」 | 测试引用真实符号；测试 runner exit=0（harness 用 `python -m unittest test_calc`） |
| E4 | 一次性脚本 | 平铺脚本要变包结构 | 「怎么组织成可安装的包」 | src layout + `__init__` | 「入口点怎么暴露」 | `python -m pkg.cli` exit=0；不得虚构模块名 |

### F 进阶用户（answer_mode=direct；不得强推入门/训练卡）

| id | 主题 | 预置坏点（exit≠0） | turn1 要点 | 修复要点 | turn2 要点 | 判据重点 |
|---|---|---|---|---|---|---|
| F1 | asyncio 并发上限与调度 | 并发任务数无上限导致断言/超时失败 | 直接问「怎么限制并发」 | `Semaphore`（或等价） | 「调度优先级呢」 | direct 尊重：不生成入门课/练习卡；next_step grounded |
| F2 | JS this 绑定 | 回调里 `this` 丢失，断言失败 | 「为什么 this 丢了」 | bind/箭头函数/显式接收者 | 「四种绑定规则优先级」 | 回答短而精确；不得重复索要已给代码 |
| F3 | 性能归因 | 聚合写法慢一个量级，基准断言失败 | 「慢在哪」 | 内置聚合替代手写循环 | 「内存换时间怎么权衡」 | 结论与实测数字一致（模型完成时）；不得编造数值 |
| F4 | 可测试性（时间注入） | 测试里 `sleep` 等待导致断言超时 | 「测试怎么不等真实时间」 | 注入 clock（或冻结时间） | 「fake 与 spy 的边界」 | 步骤引用真实测试符号；direct 模式保持 |

### G 长期恢复

| id | 场景 | 预置状态（exit≠0 的机制骨架） | turn1 要点 | 修复要点 | turn2 要点 | 判据重点 |
|---|---|---|---|---|---|---|
| G1 | 跨会话恢复 | 会话 A 以「可变默认参数」结束；新会话开局 | 「继续上次那题」 | 修复 A 中残留的坏代码 | 「上次说到哪了」 | M3：anchor/focus 保留主题 token；不得假装记得未存内容 |
| G2 | 复习路径 | 记忆中存在到期复习项（due_reviews） | 「今天先复习什么」 | 完成一次可观察复习实验 | 「这个为什么进复习队列」 | 复习信号真实（FSRS/记忆字段）；不得把一次通过写成 mastery |
| G3 | provider 失败恢复 | 回合中途触发 provider 失败（不可复现时按 `provider_error`/`local_fallback` 诚实标注） | 「刚才断了，继续」 | 恢复后完成同一主线的最小验证 | 「刚才的中断算学会了吗」 | 恢复回合不写 verified mastery；`fell_back` 标注可见 |
| G4 | 多日中断 | 工作区保留旧 active_thread 与 anchor | 「隔了几天回来，从哪继续」 | 修补旧失败点并 exit=0 | 「之前的结论还成立吗」 | 线程延续（同 scenario lane）；不得重复索要旧回合已给出的事实 |

### L 文学旅程（2026-10-17 追加；subject_family=literature，language_id=markdown）

交付物校验器（随案例下发的 `check_*.py`，entry 即 argv[0]）全部为**客观结构判据**：¶ 锚点命中、`「…」`引文与原材料逐字互查、必需栏目存在、TODO 空壳判失败；不含审美判断。材料为仓库内原创短文（fixture 文本），跨回合不变；stub→完成稿由脚本化「学习者作业完成」写盘，对齐代码类的修复语义。

| id | 级别 | 材料 | 交付物（校验器判据） | turn1 要点 | turn2 要点 | 判据重点 |
|---|---|---|---|---|---|---|
| L1 close-read-annotate | novice | 《夜航》（¶1–¶3） | 批注.md：≥2 锚点 + ≥2 条逐字引文 + 主旨句 | 精读起点：选 ¶1/¶2 并说明理由 | 复核引文是否原句，让学习者自己收主旨 | 引文逐字互查：贴不进原文的评述不算证据 |
| L2 imitation-transfer | advanced | 《旧巷》（¶1–¶2） | 仿写.md：对照表 ≥2 行（¶N→仿写N）+ 仿写段 ≥60 汉字 + 不得整段照搬（≥14 字连续窗口互斥） | 拆叙述骨架而非整段抄 | 复核是否换名照搬 vs 结构迁移 | 对照行必须锚回原文 ¶；防止抄袭式仿写 |
| L3 theory-concept-card | advanced | 《雨与灯》（¶1–¶2） | 概念卡.md：定义/原文证据/迁移三段 + ¶1¶2 均被引用 + ≥1 条逐字引文 + 定义≥16 字 | 从 ¶1 选最小证据先站住 | 复核证据是贴句还是自己的话、迁移是否真迁移 | 概念卡三段结构与锚点纪律 |
| L4 compare-two-pieces | novice | 《灯下》+《桥上》（¶A/¶B 锚点） | 对照.md：共性/差异两栏 + ¶A1 与 ¶B1 同时命中 + 两份材料各 ≥1 条逐字引文 | 定最小对照单元并说明理由 | 复核引文钉句 + 指出未证明的断言 | 双材料交叉引用的诚实性 |

文学类回合的 M2/M5 与代码类同一套判据（`turn_grounding.py` 规则层不区分语言——identifier-like 符号提取天然对散文无感，自由散文不产生 code symbol）；M1 的 body/disk 校验以材料文件（primary_file）为准。

## 4. 执行规程（R2）

1. 脚本：`scripts/maturity/real_teaching_journeys_minimax.py`（32 案例：28 代码 + 4 文学；每案例独立隔离项目目录；凭证 env-only + 非明文传输；分类逐回合记录，§0.3）。夹具骨架（每案例的 entry 脚本 pre-fix exit≠0 / post-fix exit=0，无凭证亦在本地真实执行）。
2. 时序：单并发、回合间隔 12s；32×2=64 回合；预计 30–45 分钟（模型延迟叠加）。中断即停，不拼接未完成结果为整体通过。
3. 对账与判定：按 §2 M1–M5；服务端戳 vs 本地复算不一致即判该回合 failed（harness 本地复算仅用于对账，不是第二权威——判定以 `server/app/llm/turn_grounding.py` 规则层为准）。
4. 报告：逐案例 `passed/failed` + 分类分布 + 失败证据（回合、symbols、exit code）写 `docs/maturity/`；内容质量栏由独立评审 agent 填「待 owner 确认」。**只有全矩阵真实模型运行会重写在库的常设报告文件（2026-10-13）**；子集冒烟与无凭证全矩阵运行分别写各自带日期的独立文件，绝不清除真实模型轮次的历史事实。
5. 旧 scratch（如 `output/maturity/` 下旧 harness 产物）执行完成后删除，只保留最终有效报告。

## 5. 非目标

- 不做教学质量自动评分；不把「回复长度/语气」当判据。
- 不新增第二套判定实现（判定唯一来自 `server/app/llm/turn_grounding.py`）。
- 不把本矩阵的「规格存在」当成任何案例的执行结果；R1 只交付本文件与规则层契约。
