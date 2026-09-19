# 17 张子图 Prompt 集 · Feature & Diagram Prompts

> 每张子图都是 banner 的"分镜特写"，复用同一角色卡。
> Each sub-image is a "frame" from the banner, reusing the same cast.

**通用前缀（每个 prompt 都粘贴）：**

```text
[STYLE LOCK]
4K masterwork oil painting on linen canvas, chibi 2.5-head 
neoclassical anime-influenced characters, alla prima brushwork 
with visible directional strokes, chiaroscuro Rembrandt lighting, 
limited polychromatic palette (indigo-gold warm + slate cold), 
atmospheric perspective, museum print resolution.

[CHARACTER LOCK — paste TRAINER MASCOT BLOCK from MASCOT.md]
```

---

## 图 2 · feat-verify · 验证门禁

**含义**：训练卡推进到"已实现"必须跑当前文件验收；不存在"标记完成"按钮。

**画面**：Trainer 娘举着金色大印章（"已通过 ✓"），身旁悬着 VS Code 编辑器面板，里面是真实代码 + 红绿诊断条。背景是黑板，上面写着 `verified by current_file ≠ marked_done`。

**Prompt：**

```text
[STYLE LOCK]

Trainer 娘 standing front-3/4 view, holding a large brass stamp 
in her right hand raised triumphantly, the stamp face reads 
"已通过 ✓" in bold red calligraphy. Her left hand holds the 
stopwatch-whip.

Behind her floats a translucent VS Code editor panel (rendered 
as a magic scroll) showing actual Python code with red squiggly 
diagnostic lines turning green after the stamp touches them — 
three lines transition from red to green in sequence.

Background: warm dark slate chalkboard with handwritten text 
in chalk-green #86EFAC:

  verified_by_current_file ≠ marked_done
  // 伪完成是最快的放弃

To the left, a faint silhouette of a smaller character 
(cursor girl) reaching for a "Mark Done" button that's been 
crossed out with red X.

Foreground bottom: a training card with "verified" stamp 
already pressed into it, glowing gold at the edges.

[COMPOSITION]
Canvas 1600x900 (16:9), Trainer 娘 at center, code panel at 
upper-right, chalkboard at upper-left, training card at lower-
center. Rule of thirds. Negative space 15% top, 10% bottom.

[LIGHTING]
Key from upper-left at 0.7 intensity. Rim light gold #F59E0B 
around the stamp. Subtle green #10B981 glow on the lines 
transitioning to verified.

[PALETTE]
indigo-700 #4338CA, gold-500 #F59E0B, chalk-green #86EFAC, 
slate-900 #0F172A, success #10B981, danger #EF4444.

[TEXTURE]
Sharp focus on stamp and code panel. Soft focus on background 
chalkboard. Visible brushwork on Trainer's white jacket.

[NEGATIVE CONSTRAINTS]
NO Mark Done button visible as functional. NO green checkmark 
without current_file context. NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, golden-ratio composition, 
cinematic depth of field
```

---

## 图 3 · feat-memory · 长期记忆

**含义**：掌握度/易错点/复习到期进 SQLite + Qdrant，按 FSRS 曲线调度。

**画面**：Trainer 娘站在一面巨型大脑图书馆前，从书架抽出"复习到期"的卡片，背后是 FSRS 节奏盘（圆形时钟式），3 张卡片正在按节奏飞出。

**Prompt：**

```text
[STYLE LOCK]

Trainer 娘 standing in front of a giant translucent brain-shaped 
library (semi-transparent indigo dome filled with floating shelves 
of glowing cards). She is pulling 3 cards from the "due" shelf 
with her right hand — each card has a brass FSRS rhythm tag.

Behind the brain-library: a large clock-face labeled "FSRS" 
with concentric rings of cards at different orbit distances 
(inner = high mastery, outer = just-learned, marked with 
red "due" tags at 12 o'clock position).

Cards flying outward in golden spiral trails, each card shows 
a different concept symbol (curly brace, async arrow, SQL JOIN).

[BACKGROUND]
Soft bokeh of other cards at deeper distances, atmospheric 
haze density 0.2.

[FOREGROUND]
A small open notebook at lower-left, page reads:
  "Day 1 · async/await    ✓ verified"
  "Day 3 · generator      ✓ verified"
  "Day 7 · asyncio.Task   → due today"

[COMPOSITION]
Canvas 1600x900. Brain-library centered. Trainer 娘 at 2/3 
height pulling cards. Clock-face FSRS disk at right third. 
Notebook at lower-left.

[PALETTE]
indigo-950 #1E1B4B (library dome), gold-300 #FCD34D (card glow), 
chalk-white #F5F5DC (notebook text), success #10B981 (verified 
checks), warning #F59E0B (due tags).

[TEXTURE]
Visible impasto on the brain-library translucent surface. 
Sharp focus on the 3 flying cards. Soft volumetric haze 
throughout.

[NEGATIVE CONSTRAINTS]
NO calendar grid (use rhythm disk instead). NO simple list 
(use 3D orbiting cards). NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, atmospheric perspective, 
volumetric haze
```

---

## 图 4 · feat-training · 训练闭环

**含义**：闪卡/理论演练/场景实验排队；到期出现、验收推进；对话知识缺口一键转卡。

**画面**：Trainer 娘在翻一张闪卡（正面问题、背面答案+绿✓），脚下是一条从"对话"出发、经过"证据"、"训练卡"、"验收"、回到"对话"的环形跑道，三个 harness 娘剪影（半透明）站在跑道外侧围观。

**Prompt：**

```text
[STYLE LOCK]

Trainer 娘 at center, holding a flashcard up with both hands 
at face level — front side shows "Q: 为什么 generator 比 
list 节省内存？" in handwritten chalk, she's mid-flip, 
back side just visible showing "A: lazy evaluation" with 
a green ✓ verified stamp.

She stands at the apex of a circular training loop track 
drawn on the ground in chalk-green #86EFAC:

  对话 → 证据 → 训练卡 → 验收 → (回到对话)

Each loop segment has a small monument:
  - 对话: speech bubble monument
  - 证据: clipboard monument with checkmarks
  - 训练卡: stack of cards monument
  - 验收: stamp monument (same brass stamp from feat-verify)

Outside the loop, three faded harness girl silhouettes 
(cursor, codex, claude code) leaning in to watch the loop, 
their forms semi-transparent indigo #312E81 with 0.3 opacity.

[BACKGROUND]
Soft warm slate with floating question marks and answer marks 
in chalk.

[COMPOSITION]
Canvas 1600x900. Circular loop fills 60% of canvas. Trainer 娘 
at center of loop. Harness silhouettes at outer ring. Rule of 
thirds. Golden ratio.

[LIGHTING]
Key from upper-center (trainer face bright). Rim gold from 
flashcard edges. Soft volumetric haze through loop track.

[PALETTE]
indigo-700 #4338CA, chalk-green #86EFAC, gold-500 #F59E0B, 
cream-bg #F5F3FF, slate-700 #334155 (faded silhouettes).

[TEXTURE]
Sharp focus on Trainer 娘 face and flashcard. Loop track has 
visible chalk texture. Silhouettes have painterly soft edges.

[NEGATIVE CONSTRAINTS]
NO to-do list appearance (it's a loop, not a queue). NO 
checkbox UI (use stamp instead). NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, golden-ratio, 
cinematic depth
```

---

## 图 5 · feat-youwrite · 你写它教

**含义**：教练可读文件/看诊断/搜工作区，但生产代码永远出自你的手。

**画面**：Trainer 娘双手背后站在开发者身后，看着开发者打字（手部特写），桌上代码编辑器里是开发者自己写的代码（不是 AI 写的），旁边一个被划掉的"AI 写代码"按钮。

**Prompt：**

```text
[STYLE LOCK]

OVER-THE-SHOULDER perspective. Foreground: a developer's hands 
typing on a laptop keyboard, code on screen is clearly 
HUMAN-WRITTEN (with imperfect formatting, real typos being 
fixed, comments in natural language). Screen shows:

  def search_users(query: str):
      # TODO: 加边界检查
      return db.query(...)

Behind the developer, standing 3 meters back with hands behind 
her back: Trainer 娘 in 3/4 rear view, watching. Her stopwatch-
whip is tucked into her belt, not in use. She has round glasses 
on, expression calm and patient. A small golden badge on her 
jacket reads "coach-first mode".

To her LEFT: a large red X over a button labeled "AI: write code".
To her RIGHT: a green checkmark on a button labeled "AI: review code".

Above the scene, a banner reads:
  "我读你写。我教你懂。我替你——不写。"
  "I read what you write. I teach you to understand. I write for you — never."

[COMPOSITION]
Canvas 1600x900. Developer's hands + laptop occupy lower 1/3. 
Trainer 娘 at middle 1/3. Banner at top 1/3. Crossed-out button 
at left, checkmark button at right.

[LIGHTING]
Warm desk lamp from upper-right lighting the developer's hands. 
Cool ambient on Trainer 娘. Subtle gold rim on her shoulders.

[PALETTE]
slate-900 #0F172A (laptop screen), indigo-700 #4338CA (her 
silhouette), success #10B981 (right button), danger #EF4444 
(left button X), cream-bg #F5F3FF (background).

[TEXTURE]
Realistic screen glow on developer's face (visible in the 
edge of frame). Painterly brushwork on Trainer 娘's jacket. 
Banner has visible canvas weave.

[NEGATIVE CONSTRAINTS]
NO AI typing visible. NO ghost-text / autocompletion bubbles. 
NO diff comparison (it's just human code). NO photorealism 
on character.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, atmospheric perspective
```

---

## 图 6 · feat-skills · $ 自定义技能

**含义**：内置技能 + 自定义技能，纯数据导入，触发词 `$`，分享即文本。

**画面**：Trainer 娘打开一个发光的百宝袋（背包），里面飞出 6 张 prompt 卡片，每张卡片顶部是触发词（`$explain`、`$review`、`$refactor`、`$plan`、`$debug`、`$summarize`），卡片云在她头顶形成"$" 字符。

**Prompt：**

```text
[STYLE LOCK]

Trainer 娘 with backpack open, both hands holding the open 
top. From the backpack, 6 glowing prompt cards fly upward in 
a swirling spiral, forming a giant "$" shape at the top of 
the canvas.

Each card has a brass trigger-word tag at top:

  1. $explain  → "用三层递进解释这个概念"
  2. $review   → "按 FSRS 节奏给我复习清单"
  3. $refactor → "先讲思路再改代码"
  4. $plan     → "拆成可验收的阶段"
  5. $debug    → "先复现再定位"
  6. $summarize → "三段式总结 + 可验证点"

Cards have handwritten prompt text on them (partially visible, 
intentionally blurry for that "shared as text" feel).

Small "data" icon (a JSON bracket `{ }`) stamped on each 
card corner — emphasizing "pure data, no code execution".

A small handwritten note tucked into one card reads:
"// 分享即文本，导入即 prompt"

[BACKGROUND]
Soft chalkboard with faint text:
"no eval · no Function() · prompt ≤ 4000 chars"

[COMPOSITION]
Canvas 1600x900. Backpack and Trainer 娘 at lower 1/3. Cards 
spiraling up forming "$" at top 1/3.

[LIGHTING]
Key from the backpack interior — warm gold glow. Cards 
catch and reflect this glow. Trainer 娘 face lit from below 
(warm).

[PALETTE]
indigo-700 #4338CA, gold-300 #FCD34D (card highlights), 
gold-500 #F59E0B (trigger tags), slate-900 #0F172A (chalkboard), 
cream-bg #F5F3FF.

[TEXTURE]
Cards have visible impasto highlights on edges. Backpack 
interior has soft volumetric glow. Painterly brushwork on 
Trainer 娘's hands.

[NEGATIVE CONSTRAINTS]
NO code visible on cards (only prompts). NO executable-looking 
icons. NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, golden-ratio, 
volumetric glow
```

---

## 图 7 · feat-speed · 端点测速

**含义**：多服务商端点并行竞速，热身消首包惩罚，500ms 绿/1s 黄。

**画面**：Trainer 娘举秒表（秒表指针在 12 点位置），4 个网关"赛跑小人"从起点冲到终点（带速度线），终点横幅 `Use fastest (42ms)`，前三名是绿色，第四名是黄色。

**Prompt：**

```text
[STYLE LOCK]

Trainer 娘 at center holding a large brass stopwatch raised 
high, her eyes focused on the watch face. Stopwatch hands at 
12 o'clock, ready to time.

BENEATH her: a racetrack drawn in chalk on the ground, four 
lanes, four stylized "gateway runner" figures (small abstract 
chibi robots with brand-colored uniforms) at the starting 
blocks:

  Lane 1: OpenAI uniform (white with gold), mid-stride
  Lane 2: Anthropic uniform (black with copper), mid-stride
  Lane 3: Gemini uniform (rainbow gradient), mid-stride
  Lane 4: Custom relay uniform (gray with circuit pattern), 
          trailing

Finish line banner:
  🏁 Use fastest (42ms)

Below finish line, 4 colored badges:
  🟢 42ms   (Lane 1 — gold)
  🟢 87ms   (Lane 2 — gold)  
  🟡 312ms  (Lane 3 — amber)
  ⚫ timed out (Lane 4 — slate)

On the racetrack ground, chalk dust marks showing the "warm-up 
request" discarded first (drawn as faded footprints).

[BACKGROUND]
Soft slate background with faint dotted lines (DNS/CDN cold 
start metaphor).

[COMPOSITION]
Canvas 1600x900. Trainer 娘 at upper-center holding stopwatch. 
Racetrack at lower 2/3. Lanes horizontal. Finish line at 
right.

[LIGHTING]
Key from upper-left. Lane 1 and 2 have gold rim light (fast). 
Lane 3 has amber rim. Lane 4 has cool gray rim.

[PALETTE]
indigo-700 #4338CA, gold-500 #F59E0B, success #10B981, 
warning #F59E0B, slate-700 #334155.

[TEXTURE]
Sharp focus on stopwatch. Visible motion blur on the runners. 
Chalk dust visible on track.

[NEGATIVE CONSTRAINTS]
NO real brand logos on uniforms (only color coding). NO 
photorealistic stopwatch. NO photorealism on characters.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, motion blur, 
cinematic depth
```

---

## 图 8 · feat-library · 资料库全权

**含义**：上传即索引、全文检索、沙箱分级预览、删除进回收站可恢复。

**画面**：Trainer 娘站在"图书馆"中央，左侧是用户的项目书架（warm wood），右侧是受控沙箱（带栏杆的玻璃柜，里面是上传的 PDF/DOCX/MD 文件），最右侧是回收站（黑色垃圾桶，盖子半开，里面有一张"误删"的纸，纸上有 trainer 印章可恢复）。

**Prompt：**

```text
[STYLE LOCK]

Trainer 娘 standing at center, hands behind back, looking at 
three distinct zones arranged left-to-right:

ZONE 1 (left third): "WORKSPACE" — wooden bookshelf filled 
with project code files (visible filenames like main.py, 
App.tsx, schema.sql). Warm wood texture. Open book on top 
shelf showing a glowing search result.

ZONE 2 (middle third): "SANDBOX" — glass cabinet with brass 
railings, containing uploaded resource files (PDF, DOCX, MD, 
images) suspended in soft gold light. Tier A label on 
glass: "Rich preview · CodeMirror · PDF.js · DOCX". A small 
chalkboard sign on cabinet reads: "for processing only, not 
your project".

ZONE 3 (right third): "TRASH" — black ceramic bin with brass 
lid, lid half-open. Inside, a crumpled paper with a faint 
Trainer stamp visible — labeled "recoverable". A small 
golden arrow above the bin points back toward Zone 1, with 
text "restore within 30 days".

Above the three zones, a curved arrow connecting all three, 
labeled "upload → index → search → preview → recycle → restore".

[COMPOSITION]
Canvas 1600x900. Three zones equal width (33% each). Trainer 娘 
at the boundary of Zone 1 and Zone 2, center vertical line.

[LIGHTING]
Zone 1: warm wood lighting #F5E6D3.
Zone 2: cool gold glow #F59E0B.
Zone 3: cool slate #475569 with a small gold accent on the 
recoverable paper.

[PALETTE]
wood-brown #78350F, glass-blue #7DD3FC, gold-500 #F59E0B, 
slate-700 #334155, cream-bg #F5F3FF.

[TEXTURE]
Visible wood grain on Zone 1. Glass reflection on Zone 2. 
Ceramic texture on Zone 3.

[NEGATIVE CONSTRAINTS]
NO filesystem tree visualization (use bookshelf metaphor). 
NO actual PDFs visible (use abstract document icons). NO 
photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, atmospheric perspective, 
material texture contrast
```

---

## 图 9 · diagram/agent-loop · ReAct 双通道

**含义**：双通道流（visible text + tool calls）+ 相同工具熔断 + 上下文自愈。

**画面**：Trainer 娘站在中央，**两条带子**从她身体流出：一条金色（visible text 流）流向"用户"，一条紫色（tool calls 流）流向"工具箱环"。工具箱环是一个圆环，6 个工具小盒子挂在环上（read_file / diagnostics / search / edit / plan / evaluate）。圆环上一个红色熔断器标识"identical tool streak ≥ 2"。

**Prompt：**

```text
[STYLE LOCK]

Trainer 娘 standing at center, three-quarter front view, 
expression focused.

TWO RIBBONS flow from her body outward:
  - GOLD ribbon (visible text flow) flowing RIGHT toward 
    "USER" label, with chalk text sample: "Let me think..."
  - INDIGO ribbon (tool call flow) flowing LEFT toward a 
    circular TOOL RING

The TOOL RING is a brass circle with 6 tool boxes hanging 
from it, each labeled:
  📖 read_file
  🔍 diagnostics  
  🔎 search
  ✏️ edit
  📋 plan
  ⚖️ evaluate

A RED CIRCUIT BREAKER sits on the ring at 11 o'clock position, 
glowing angry red, with text:
  "identical_tool_streak ≥ 2 → break"

A small self-healing icon at 5 o'clock position:
  "prompt_overflow → compress & resume"

[BACKGROUND]
Soft indigo-950 #1E1B4B with subtle grid pattern (the 
"token grid" the loop navigates).

[COMPOSITION]
Canvas 2400x1350. Trainer 娘 at center. Gold ribbon right. 
Indigo ring left. Rule of thirds.

[LIGHTING]
Key from upper-center. Gold ribbon self-illuminates. Indigo 
ring has brass rim glow. Red circuit breaker pulses.

[PALETTE]
indigo-950 #1E1B4B, gold-300 #FCD34D, indigo-500 #6366F1, 
danger #EF4444, success #10B981 (self-heal icon), cream-bg.

[TEXTURE]
Ribbons have visible silk-like impasto. Tool ring has 
brushed-metal texture. Sharp focus on circuit breaker.

[NEGATIVE CONSTRAINTS]
NO flowchart boxes (use organic ribbon + ring). NO step 
numbers (use positions on ring). NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, organic geometry, 
material texture
```

---

## 图 10 · diagram/snapshot-sync · Snapshot 同步

**含义**：31 字段单一信封 + 修订号增量同步。

**画面**：中央是一面巨大的信封（蜡封+火漆），信封上有 31 块拼图碎片，每块代表一个字段。信封旁边是一座日晷（修订号时钟），日晷上显示"snapshot_revision: 42"。一束光从信封射出，连到右侧的 webview 渲染窗（里面有 5 个 harness 娘剪影在查看同一份状态）。

**Prompt：**

```text
[STYLE LOCK]

A GIANT ENVELOPE occupies left 2/3 of canvas, sealed with 
brass wax stamp "WS" (Workbench Snapshot). The envelope is 
semi-transparent indigo, revealing inside a 31-piece jigsaw 
puzzle assembled together — each piece labeled with a field 
name in tiny chalk text:

  Top row: messages | profile | plan | global_plan | 
           project_plan_link | current_task
  Mid row: evaluation | memory | provider | coaching_state | 
           learner_state | teaching_decision
  Bot row: affect_state | tone_decision | implementation_guide |
           project_ideas | review_queue_summary | next_review_due
  ... (continue to 31)

Beside the envelope (right 1/3): a SUNDIAL on a stone pedestal, 
the gnomon shadow pointing at a brass plate inscribed:
  "snapshot_revision: 42"

From the sundial, a golden light beam shoots RIGHT toward a 
small "WEBVIEW" window frame, inside which 5 small harness 
girl silhouettes (cursor, claude, codex, devin, qoder) peer 
out, all looking at the same envelope — meaning they all 
render from the same single source of truth.

[COMPOSITION]
Canvas 2400x1350. Envelope dominant left. Sundial + webview 
window right. Diagonal flow from envelope → sundial → webview.

[LIGHTING]
Envelope has internal indigo glow (the data). Sundial shadow 
is the gold accent. Webview window has warm light.

[PALETTE]
indigo-950 #1E1B4B, gold-500 #F59E0B (sundial + light beam), 
cream-bg #F5F3FF, slate-700 #334155.

[TEXTURE]
Envelope wax has visible impasto. Puzzle pieces have subtle 
cardboard texture. Sundial stone has visible grain.

[NEGATIVE CONSTRAINTS]
NO JSON tree visualization (use jigsaw metaphor). NO API 
endpoint rectangles (use envelope metaphor). NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, organic geometry, 
diagonal composition
```

---

## 图 11 · diagram/authority-ladder · 6 级权限

**含义**：INSPECT < ANNOTATE < REORGANIZE < GENERATE < APPLY < DESTRUCTIVE；远程工作区硬锁 + trash-only 删除。

**画面**：一座 6 级石阶楼梯，从下到上每一级刻着权限等级名称。楼梯顶上有一道砖墙——"远程墙"，墙上写"REMOTE = LOCKED"。楼梯底部 Trainer 娘站立（默认 INSPECT），手里举着一把钥匙通往 ANNOTATE（绿色）。楼梯最高一级 DESTRUCTIVE 被红绳拦着，红绳上挂着"TRASH ONLY"牌子。

**Prompt：**

```text
[STYLE LOCK]

A STONE STAIRCASE rising from lower-left to upper-right, 6 
steps, each step carved with a level name in brass letters:

  Step 1 (lowest): INSPECT  — pale cream, lit
  Step 2: ANNOTATE — pale green, lit
  Step 3: REORGANIZE — gray, dim
  Step 4: GENERATE — gray, dim
  Step 5: APPLY — slate, darker
  Step 6 (highest): DESTRUCTIVE — red stone, dim

At the TOP of the staircase: a BRICK WALL spanning the upper 
edge of canvas, bricks inscribed with "REMOTE / UNTRUSTED = 
LOCKED". A single keyhole in the wall with no key visible.

At step 6, a red rope across the stair with brass sign:
  "TRASH ONLY"
  "no delete · only move to <root>/.trash/<ts>/"

Trainer 娘 stands at the BOTTOM (step 1), holding a brass 
key labeled "ANNOTATE" — her key only fits steps 1-2. Above 
step 2, keys are different colors (gray, dim, no key given).

The whole staircase has a soft INDIGO GLOW at the bottom 
(Trainer's zone), fading to COLD SLATE at the top (forbidden 
zone).

[COMPOSITION]
Canvas 2400x1350. Staircase diagonal. Trainer 娘 at lower-left. 
Wall at upper-right. Red rope at upper-middle.

[LIGHTING]
Step 1-2: warm gold rim. Step 3+: progressively cooler. Wall: 
shadowy. Red rope: ominous red rim.

[PALETTE]
indigo-500 #6366F1, gold-500 #F59E0B (Trainer), success #10B981 
(steps 1-2), danger #EF4444 (step 6 + rope), slate-900 (wall).

[TEXTURE]
Stone steps have visible chisel marks. Wall has brick texture. 
Rope has woven fiber detail.

[NEGATIVE CONSTRAINTS]
NO permission matrix table (use staircase metaphor). NO 
checkbox UI (use key + rope). NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, diagonal composition, 
material texture contrast
```

---

## 图 12 · diagram/handoff-phases · Handoff 5 相

**含义**：LEARN → TRY → VERIFY → REFLECT → RETURN；可信验证源白名单。

**画面**：一条 5 段跑道，每段是不同颜色：LEARN（蓝）、TRY（黄）、VERIFY（绿）、REFLECT（紫）、RETURN（金）。跑道上是 Trainer 娘的剪影全力冲刺。VERIFY 段中间有一个"可信门"——只有 6 个特定来源能通过（automated_test / evaluator / ide_current_file / server_evaluator / test_runner / verification_service），门上挂着一个红色 X（"manual claim"被拒）。

**Prompt：**

```text
[STYLE LOCK]

A FIVE-LANE TRACK viewed from 3/4 perspective, lanes labeled:

  Lane 1: LEARN     — sky blue #7DD3FC
  Lane 2: TRY       — amber #F59E0B  
  Lane 3: VERIFY    — green #10B981
  Lane 4: REFLECT   — lavender #A78BFA
  Lane 5: RETURN    — gold #FCD34D

Trainer 娘 is mid-sprint between Lane 2 and Lane 3, in 
dynamic action pose, hair flying, stopwatch-whip in hand 
trailing behind.

At the entrance to Lane 3 (VERIFY): a GATE with brass arch, 
gate has 6 small nameplates on it listing the trusted 
verification sources:

  ✓ automated_test
  ✓ evaluator
  ✓ ide_current_file
  ✓ server_evaluator
  ✓ test_runner
  ✓ verification_service

Below the 6 names, a 7th nameplate is crossed out in red:
  ✗ manual_claim

A faint "untrusted claim" ghost figure is being turned away 
at the gate by a brass gatekeeper.

Each lane has a small visual marker:
  LEARN: open book on ground
  TRY: glowing pencil
  VERIFY: brass stamp
  REFLECT: round mirror
  RETURN: golden home plate

[COMPOSITION]
Canvas 2400x1350. Track horizontal, 5 equal lanes. Trainer 
mid-action at lane 2-3 boundary. Gate at lane 3 entrance. 
Rule of thirds.

[LIGHTING]
Key from upper-right. Lane colors self-illuminate. Gate has 
brass glow.

[PALETTE]
sky-blue #7DD3FC, amber #F59E0B, success #10B981, lavender 
#A78BFA, gold-300 #FCD34D, danger #EF4444.

[TEXTURE]
Track has lane-line texture. Gate has brushed metal. 
Trainer has motion blur.

[NEGATIVE CONSTRAINTS]
NO arrow flowchart. NO state diagram. NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, dynamic composition, 
motion blur
```

---

## 图 13 · diagram/provider-protocols · 4 协议路由

**含义**：4 种 wire 协议路由；未知网关不假设 OpenAI 兼容。

**画面**：Trainer 娘站在中央举着 4 把不同钥匙（每把颜色不同），面前是 4 扇门（OpenAI / Anthropic / Gemini / Responses），门后是发光的目的地。旁边第 5 扇门（"未知网关"）被木板钉死，钉子上挂红牌"REJECTED: unknown fingerprint"。

**Prompt：**

```text
[STYLE LOCK]

Trainer 娘 at center, holding 4 distinct keys fanned out:

  Key 1: BRASS with O-shaped bow → "OpenAI Chat Completions"
  Key 2: COPPER with feather bow → "Anthropic Messages"  
  Key 3: IRIDESCENT with gem bow → "Gemini Native"
  Key 4: SILVER with /responses bow → "OpenAI Responses"

In front of her: 4 DOORS, each glowing with the key's color:

  Door 1: open, golden light spilling out
  Door 2: open, copper light spilling out
  Door 3: open, iridescent light spilling out
  Door 4: open, silver light spilling out

To the FAR RIGHT: a 5th door, BOARDED UP with wooden planks 
and nails, red sign reading:
  "REJECTED"
  "Gateway fingerprint: unknown"
  "Trainer will not assume OpenAI-compatible"

A small ghost silhouette stands before the 5th door, head 
shaking "no".

Above the doors, a thin chalkboard label:
  "5 protocols · 1 binding · 0 assumed defaults"

[COMPOSITION]
Canvas 2400x1350. Trainer 娘 center-left. 4 open doors 
center-right (evenly spaced). 5th boarded door far right. 
Rule of thirds.

[LIGHTING]
Each door has its own key-color glow. 5th door is in shadow 
with red rim light from the rejection sign.

[PALETTE]
gold #F59E0B, copper #B45309, iridescent (multi-hue), silver 
#94A3B8, danger #EF4444 (5th door), cream-bg.

[TEXTURE]
Keys have brushed metal. Doors have wood grain + paint. 
5th door has rough plank wood.

[NEGATIVE CONSTRAINTS]
NO API endpoint URL list. NO curl examples. NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, asymmetric composition, 
material contrast
```

---

## 图 14 · diagram/workspace-zones · 工作区 3 域

**含义**：workspace（项目）/ sandbox（处理）/ trash（回收站）三域物理分离。

**画面**：三扇并排的房间门，Trainer 娘站在中间。左侧门"WORKSPACE"（暖木门，开着，里面是开发者的代码），中间门"SANDBOX"（玻璃门，半透明，里面是处理中的资源文件），右侧门"TRASH"（铁门，半开，里面是被删除文件 + 一只手伸出来要恢复）。

**Prompt：**

```text
[STYLE LOCK]

Three ARCHWAYS side by side, each marked with brass plate:

LEFT: WORKSPACE — warm wooden door, open, inside visible:
  - Code editor with project files
  - Wooden bookshelf
  - Warm lamp glow
  
CENTER: SANDBOX — glass door with brass frame, half-transparent, 
inside visible:
  - PDFs and DOCX floating in soft gold light
  - "for processing only, not your project" chalkboard sign
  - Faint brass railing around the interior
  
RIGHT: TRASH — iron door with small window, half-open, 
inside visible:
  - Crumpled papers in a black bin
  - A hand reaching out from inside the bin holding a paper 
    with a Trainer stamp — labeled "RESTORE"
  - 30-day countdown chalk on the wall

Trainer 娘 stands in front of the SANDBOX door (center), 
hands on the brass door handle, looking toward the workspace 
(left) with a slight nod, while her peripheral vision 
includes the trash door (right) — meaning "I'm watching all 
three".

Above the three doors, a curved arrow:
  upload → index → preview → recycle → restore

[COMPOSITION]
Canvas 2400x1350. Three doors equal width. Trainer 娘 at 
center door threshold. Curved arrow above.

[LIGHTING]
Left door: warm wood glow. Center door: cool gold interior. 
Right door: cool slate with one warm accent (the reaching hand).

[PALETTE]
wood-brown #78350F, glass-blue #7DD3FC, slate-900 #0F172A, 
gold-500 #F59E0B (center accent), cream-bg.

[TEXTURE]
Wood grain on left door. Glass reflection on center door. 
Iron texture on right door.

[NEGATIVE CONSTRAINTS]
NO folder tree. NO file icons. NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, triptych composition, 
material texture contrast
```

---

## 图 15 · diagram/evidence-loop · 证据闭环

**含义**：对话 → 证据 → 训练卡 → 验收 → (回到对话)。

**画面**：一个圆形转盘被 4 个拱门分隔成 4 段：对话（黄色）、证据（紫色）、训练卡（蓝色）、验收（金色）。转盘中央站着一个迷你 Trainer 娘正在推动转盘。转盘外圈有金色的小箭头表示循环方向。

**Prompt：**

```text
[STYLE LOCK]

A LARGE CIRCULAR DISK viewed from 3/4 angle, divided into 4 
quadrants by brass arches:

  Top quadrant (12-3 o'clock): 对话 — speech bubble monument
  Right quadrant (3-6): 证据 — clipboard with checkmarks
  Bottom quadrant (6-9): 训练卡 — stack of brass-edged cards
  Left quadrant (9-12): 验收 — brass stamp (same as feat-verify)

A miniature Trainer 娘 stands at the disk's center, hands 
on a brass handle, pushing the disk to rotate clockwise.

Outside the disk, a golden ring of small arrows showing the 
clockwise direction.

Each quadrant has a small chalkboard tag with phase name:
  "对话 · conversation"
  "证据 · evidence"
  "训练卡 · training card"
  "验收 · verification"

In the BACKGROUND: faded silhouettes of 3 harness girls 
(cursor, claude, codex) standing at the perimeter, watching 
the disk rotate. Their forms suggest "we generate, Trainer 
orchestrates".

[COMPOSITION]
Canvas 2400x1350. Disk centered, 70% of canvas. Mini Trainer 
at center. Quadrants labeled. Rule of thirds.

[LIGHTING]
Each quadrant has its own color glow. Disk has brass rim 
light. Mini Trainer has indigo spotlight from above.

[PALETTE]
gold #FCD34D (对话), lavender #A78BFA (证据), sky-blue #7DD3FC 
(训练卡), success #10B981 (验收), indigo-700 #4338CA (Trainer).

[TEXTURE]
Disk surface has brass brushed metal. Quadrant monuments have 
stone texture. Silhouettes have painterly soft edges.

[NEGATIVE CONSTRAINTS]
NO linear arrow flowchart (use circular disk). NO step numbers 
(use clock positions). NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, radial composition, 
material contrast
```

---

## 图 16 · diagram/governance-pure · 治理模块

**含义**：24 个 pure function 模块，host/webview/test 三端共用同一份逻辑。

**画面**：画面中央是一座"真理图书馆"，里面有一本巨大的烫金烫银厚书（共享模块），三个角色站在图书馆外：左侧是宿主（西装革履，工具箱），中间是 webview（休闲装，浏览器窗口），右侧是测试（实验服，试管）。三人各伸出一只手，共同捧起这本书。

**Prompt：**

```text
[STYLE LOCK]

Central: a CIRCULAR LIBRARY READING ROOM with warm brass 
lighting. At the room's center on a stone pedestal: a GIANT 
BOOK with indigo cloth binding and gold-leaf title embossed:

  "shared/governance"
  "24 pure functions"
  "0 side effects"
  "host + webview + test"

Three figures stand OUTSIDE the library at equidistant points, 
each holding one corner of a glowing thread that connects 
back to the central book:

LEFT figure (HOST): wearing dark suit with VS Code-blue 
  pocket square, holding a small toolbox labeled "extension/"
  in one hand, the other hand holding the thread.
  Expression: focused, business-like.

CENTER figure (WEBVIEW): wearing casual hoodie with React 
  atom symbol on chest, holding a browser window frame in 
  one hand (the window shows a translucent webview rendering), 
  other hand holding the thread.
  Expression: friendly, developer-like.

RIGHT figure (TEST): wearing lab coat with brass goggles on 
  forehead, holding a test tube rack with 3 tubes labeled 
  "159 pytest · 220 node · 200 matrix" in one hand, other 
  hand holding the thread.
  Expression: clinical, satisfied.

Behind the central book, a chalkboard lists:
  planGovernance · trainingHandoffGovernance · reviewQueueGovernance
  · workspaceAuthority · suggestedActionGovernance · ...

Each name has a small ✓ next to it.

[COMPOSITION]
Canvas 2400x1350. Library centered. Three figures at 7/5/3 
o'clock positions. Rule of thirds.

[LIGHTING]
Library has warm interior light. Each figure has rim light 
matching their role color: slate for HOST, indigo for WEBVIEW, 
gold for TEST.

[PALETTE]
indigo-950 #1E1B4B (book), gold-500 #F59E0B (book + TEST), 
slate-700 #334155 (HOST), indigo-500 #6366F1 (WEBVIEW), 
cream-bg #F5F3FF.

[TEXTURE]
Book has leather binding texture. Library floor has marble. 
Figures have painterly brushwork.

[NEGATIVE CONSTRAINTS]
NO dependency graph. NO module list as text. NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, trinity composition, 
material texture
```

---

## 图 17 · diagram/fsrs-rhythm · FSRS 节奏

**含义**：FSRS 遗忘曲线 + 流状态抑制 + 主动程优先。

**画面**：一个巨大的沙漏时钟，里面装的不是沙，是"卡片"。沙漏上半部分堆满高耸的待复习卡片（红色边缘），下半部分是已掌握的卡片（绿色边缘）。沙漏旁边有个开关"抑制开关"，标着"流状态时跳过复习"。底座刻着"1d / 3d / 7d / 14d / 30d"。

**Prompt：**

```text
[STYLE LOCK]

A GIANT HOURGLASS standing 80% of canvas height, made of 
translucent indigo glass with brass frame.

TOP half of hourglass: piled high with cards having RED edges 
(labels like "due today", "stale"). Falling down: individual 
cards tumbling through the neck, each card a concept symbol 
(curly brace, async arrow, SQL JOIN).

BOTTOM half: cards have GREEN edges (labels like "mastered", 
"verified"). A few cards at the bottom have GOLD halos 
("verified by current file").

NEXT TO the hourglass: a brass LEVER switch on a stone 
pedestal, labeled:

  "流状态抑制"
  "skip review during active thread"
  "do not disturb flow"

The lever is currently in the OFF position (not pressed), 
suggesting the default is to review, but available when 
needed.

On the hourglass base, brass plaque inscribed:
  "1d · 3d · 7d · 14d · 30d"
  "FSRS rhythm"

Behind the hourglass, soft chalkboard showing a faint 
forgetting curve (exponential decay).

[COMPOSITION]
Canvas 2400x1350. Hourglass dominant center. Lever at right. 
Chalkboard background.

[LIGHTING]
Top of hourglass: warm rim (pending urgency). Bottom: gold 
rim (mastery glow). Lever has subtle red accent.

[PALETTE]
danger #EF4444 (top cards), success #10B981 (bottom cards), 
gold-500 #F59E0B (verified halos), indigo-950 #1E1B4B (glass), 
brass #B45309 (frame), cream-bg.

[TEXTURE]
Glass has subtle refraction. Cards have paper texture. Stone 
pedestal has chisel marks.

[NEGATIVE CONSTRAINTS]
NO calendar UI. NO scheduling table. NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, vertical composition, 
material contrast
```

---

## 图 18 · diagram/i18n-locale · i18n 8 语言

**含义**：8 语言 i18n，600+ key × 8。

**画面**：一个地球仪（或大圆桌），8 个 mini Trainer 娘剪影围绕一圈，每人举着一面小旗帜（zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR）。中央是一个发光的对话气泡，里面是同一段话被翻译成 8 种语言。

**Prompt：**

```text
[STYLE LOCK]

A LARGE ROUND TABLE viewed from 3/4 angle, with 8 chairs 
evenly spaced around it. Each chair has a small brass nameplate 
with a flag pattern (not real flags — abstract color stripes 
suggesting each language):

  1. zh-CN — red + gold stripes (left upper)
  2. en-US — navy + white stripes
  3. es-ES — red + yellow stripes
  4. fr-FR — blue + white + red stripes
  5. de-DE — black + red + gold stripes
  6. ja-JP — white + red dot
  7. ko-KR — white + taegeuk symbol (abstract)
  8. pt-BR — green + yellow + blue

Each chair has a mini Trainer 娘 silhouette (same indigo 
short bob, simplified) holding the flag.

CENTER of the table: a glowing speech bubble showing the same 
phrase in 8 different scripts stacked:

  "你写,我教,我们一起长。"
  "You write, I teach, we grow together."
  "Tú escribes, yo enseño, crecemos juntos."
  ... (all 8 languages, chalk-white text on slate-900)

A small chalkboard at table edge:
  "600+ keys · 8 languages · 0 broken UI"

[COMPOSITION]
Canvas 2400x1350. Round table centered. 8 chairs at clock 
positions. Center bubble at center. Rule of thirds.

[LIGHTING]
Each language has its own subtle accent color glow. Center 
bubble has warm gold rim.

[PALETTE]
Multi-language accents (red/gold/navy/yellow/blue/etc.), 
indigo-950 #1E1B4B (Trainer silhouettes), gold-500 #F59E0B 
(center bubble), cream-bg.

[TEXTURE]
Table has wood grain. Chairs have brass + velvet. Flags 
have fabric texture.

[NEGATIVE CONSTRAINTS]
NO actual country flags (use abstract stripe patterns). 
NO real flag emoji. NO photorealism.

[QUALITY TAGS]
masterwork, museum-print, chiaroscuro, radial composition, 
polyglot harmony
```

---

## 通用生成脚本

每张图用同一脚本生成（改文件名 + prompt 文件路径）：

```bash
python3 scripts/generate_dora_image.py \
  --prompt "$(cat assets/prompts/<name>.md | grep -A 10000 '\[STYLE LOCK\]')" \
  --model gpt-image-2 \
  --workflow normal \
  --aspect-ratio $(case <name> in \
    banner) echo "16:9" ;; \
    feat-*) echo "16:9" ;; \
    diagram-*) echo "16:9" ;; \
  esac) \
  --target-size $(case <name> in \
    banner) echo "3840x2160" ;; \
    feat-*) echo "1600x900" ;; \
    diagram-*) echo "2400x1350" ;; \
  esac) \
  --quality high \
  --generation-mode standard \
  --output-format png \
  --output assets/<name>@4k.png

cwebp -q 82 assets/<name>@4k.png -o assets/<name>.webp
```

---

> 17 张分镜特写 + 1 张群像母版 = 18 张视觉资产。
> 17 close-ups + 1 ensemble = 18 visual assets.
> Trainer 在每一帧里都说着同一句话。
