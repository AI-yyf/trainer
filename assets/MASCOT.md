# Trainer 视觉资产规范 · Visual Asset Bible

> Trainer 一图一世界。每一张配图都必须从这本圣经出发。
> Trainer speaks one visual language. Every asset starts here.

---

## 0. 字体选型 · Typography

### 0.1 字体家族（dora-image 生成图中嵌入文字时使用）

| 用途 | 中文 | 英文 / 数字 | 风格关键词 |
|---|---|---|---|
| **主标题 · Hero** | 思源宋体 Heavy / Noto Serif SC Black | Cormorant Garamond Bold | 古典衬线、博物馆海报 |
| **副标题 · Subhead** | 思源宋体 SemiBold | Cormorant Garamond SemiBold Italic | 学术斜体 |
| **黑板手写 · Chalkboard** | 演示效果（marker） | 演示效果（chalk） | 手写、非正式、教学现场 |
| **代码块 · Code** | 霞鹜文楷等宽 Mono | JetBrains Mono Bold / Fira Code | 等宽、程序员、终端 |
| **横批 · Banner Signature** | 思源宋体 Light Italic | Cormorant Infant Italic | 古典油画落款 |
| **图边小标注 · Annotation** | 思源黑体 Regular | Inter Medium | 简洁、克制、不抢戏 |
| **彩蛋便签 · Sticky Note** | 演示效果（handwritten） | 演示效果（handwritten） | 手写、贴纸、私密感 |

### 0.2 字体颜色（与画面对比度规则）

- **黑板字**：白垩色 `#F5F5DC`（不用纯白，纯白在深色画布上"漂浮"）
- **代码块字**：终端绿 `#00FF41`（黑客帝国色）或琥珀 `#FFB000`（复古 CRT）
- **横批文字**：与背景对比度 ≥ 7:1（WCAG AAA）
- **便签字**：深棕 `#3E2723`（墨水感）

### 0.3 字号比例（4K 3840x2160 画布）

| 元素 | 像素高度 | 画面占比 |
|---|---|---|
| Hero 主标题 | 180-240px | 5-6% 画面高度 |
| 黑板代码块 | 48-64px / 行 | 3-4% 画面高度 |
| 横批签名 | 36-48px | 1.5% 画面高度 |
| 图边标注 | 24-32px | 1% 画面高度 |
| 便签 | 20-28px | 1% 画面高度 |

---

## 1. 角色一致性卡 · Character Consistency Cards

> 所有 18 张图（1 hero + 17 子图）共用以下角色卡。
> 生成时把"角色一致性前缀"完整粘贴进 prompt。

### 1.0 全局画风基线 · Global Style Baseline (v4 · AI娘 萌娘)

> **风格锚点**：`assets/refs/ai_niang_style_ref.jpeg`（linux.do「AI娘」系列人物介绍卡，
> GPT白发龙娘 / Claude橙发大小姐 / GLM黑发魔女 / DeepSeek鲸鱼娘）。
> 生成时传 `--reference-image assets/refs/ai_niang_style_ref.jpeg --reference-role style`。

```
GLOBAL STYLE BLOCK (paste every time):
High-quality Japanese anime illustration, character-introduction-card style
from the Chinese AI-girl (AI娘/萌娘) fan-art series.
ONE elegant anime girl, NORMAL anime proportions (~6.5-7 heads tall,
NOT chibi, NOT super-deformed), framed knees-up, centered like a card portrait.
Refined bishoujo face: large glossy anime eyes with layered highlights,
small delicate nose, small soft lips.
Detailed strand-level hair with soft shine + signature hair ornament.
Ornate brand-colored outfit mixing Victorian / academy / lolita elements
(ribbons, corset belt, lace, high collar); brand emblem as embroidery or brooch.
Clean delicate lineart, soft cel + airbrush shading, warm soft lighting.
Plain warm off-white paper background (#FAF7F2), no scenery.
```

**已采纳的社区设定（不要改回自创）**：
- **Claude Code 娘** ← Claude娘：橙色长发 + 向日葵发饰 + 奶油白维多利亚上衣 + 黑色束腰 + 琥珀眼
- **ZCode 娘** ← GLM娘（自家模型）：黑长直 + 魔女帽 + 白色 Z 眼罩 + 哥特萝莉黑白裙 + 银铃铛
- **Codex 娘** ← OpenAI 白色系：铂白长发 + 金色光环饰 + 纯白金边裙装
- **Kimi Code 娘** ← 月之暗面意象：蓝黑长直 + 金新月发饰 + 深蓝学院裙（社区无现成设定）
- **DeepSeek** 不在阵容内，仅作画风参考

### 1.0.2 用户口碑 → 人设匹配 · Reputation Persona Matrix (v4.2)

> 2026-09-19 调研 linux.do / 知乎 / V2EX / Reddit / B站 等社区最新用户评价提炼。
> 每位 harness 娘的表情、姿态、彩蛋都必须能讲出一个**真实用户的梗**。

| Harness | 用户口碑（夸 / 吐槽） | 产品调性 | 娘化人设 & 风趣彩蛋 |
|---|---|---|---|
| **Cursor** | 夸：Tab 补全公认最强（"比反重力好不少"）；吐槽：贵，社区天天找平替 | 高冷补全之神，按月割韭菜 | 高冷补全天才少女（黑白+鎏金）。彩蛋：腰间挂 `$20/mo` 小价签；手指悬空做 Tab 按键姿势 |
| **Claude Code** | 夸：最强 agent、实时协作爽；吐槽：又爱又恨、烧钱段子满天飞（月烧 35 万、$200 Max 撞限速、省钱教程齐飞） | 人文天才贵族，账单刺客 | （已定稿）橙发文学少女。彩蛋：古书里夹一张长长 API 账单当书签 |
| **Codex** | 夸：异步放手不管、PR 工作流强；吐槽：慢，"雇了个远程同事，干完活再说" | 从容的远程同事 | 白色系纪律少女。彩蛋：5 个 PR 气泡（4 灰 1 金 verified）；手腕挂 "do not disturb — async" 门牌 |
| **Kimi Code** | 夸：便宜（Claude 1/5）、39 元档、长上下文还能翻页、"平替 85%"；吐槽：细节指令偶尔掉链子 | 性价比卷王 + 长卷宗管理员 | 蓝黑月亮少女。彩蛋：200K 长卷轴末端写 "见第 199,999 页"；腰间挂 `¥39` 小钱袋 |
| **Trae** | 夸：免费白嫖天堂、SOLO 模式领先；吐槽：排队限流"A048 正在呼叫"、Pro $10 额度血亏 | 免费午餐推销员，但要排队叫号 | 霓虹绿活力少女。彩蛋：餐盘卡片 "for free"；发带别着排队号 `A-048` |
| **Devin** | 夸：自主智能体路线获 480 亿投资；吐槽：早期翻车梗王、PR 全 unmerged | 一本正经的自主工程师，常翻车但努力 | 灰黑机械少女。彩蛋：5 张 `unmerged` 单据；胸牌 "Autonomous Engineer (in training)" |
| **ZCode** | 夸：$18 平替之王、94.6% Opus、大碗真香；吐槽：memory problem、稳定性偶尔掉链子 | 便宜大碗睡魔女，偶尔失忆 | （已定稿）GLM娘魔女。彩蛋：Z 眼罩 + 倒扣沙漏（无 FSRS）+ `zcode run → done` 终端 |
| **Qoder** | 夸：Quest+Spec 省 50% 交互、"最牛功能"；吐槽："Spec 就是 Plan 换皮"、学习曲线陡 | 流程控文书魔人 | 紫罗兰文书少女。彩蛋：`Evaluation criteria: undefined`；手持图章 "Spec v0.3（草案）" |
| **MiMo Code（小米）** | 夸：开源 MiMo-7B 推理模型、发烧友性能；口碑核心是小米式性价比信仰 | 为发烧而生的性价比闪电侠 | 白橙少女（白发渐变橙马尾+MI 圆角方发卡）。彩蛋：3 沙漏（中间裂了流成 Trainer） |
| **CodeBuddy** | 夸：全流程真香、微信生态、中文理解深；吐槽：国际版 14 天试用"现出原形" | 亲切 buddy 全能管家 | 蓝紫渐变 buddy 少女。彩蛋：企鹅+QQ 窗；胸牌写着 "试用第 14 天" |
| **WorkBuddy** | 腾讯系办公口碑：夸全流程/微信生态；吐槽：会员彩钻收费体系、"文件已过期"、"请在手机端打开" | 误入会议室的推销型办公管家 | （v4.2 改）精明推销脸：微信绿西装+满襟彩钻会员徽章+工牌"超级会员·试用第14天"，递上平板"该文件已过期" |
| **Trainer** | 自家产品 | 长期主义教练 | 靛蓝教练少女，FSRS 徽章 + 怀表 |

### 1.0.1 官网品牌调性表 · Brand Identity Matrix (v4.1)

> 2026-09-19 从各家官网首页/CSS/Logo 实抓。每位 harness 娘的配色、服饰语言、
> 气质必须对齐此表 —— 让认识该工具的人一眼认出"这是谁"。

| Harness | 官网抓取的品牌色 | Logo 关键元素 | 企业调性 → 娘化人设 |
|---|---|---|---|
| **Cursor** | 近黑 `#1c1c1e`、灰白 `#edecec`、暖米灰 `#cac6be`、鎏金点缀 `#c08532` | 黑白立方体（三角折叠面） | applied-lab 高冷极简、calm confidence → 黑白灰套装配鎏金线，冷静精英，绝不花哨 |
| **Claude Code** | 陶土橘 `#D97757`、奶油米白 `#F0EEE6` | 多瓣星芒 ✳ | 人文文艺、serif 衬线、book-smart → （已定稿）橙发向日葵维多利亚裙 |
| **Codex** | 纯黑白、无彩色 | OpenAI 六瓣纽结 | 工程纪律、极简 → 纯白+黑线分割裙装、纽结徽章、金色仅限 verified |
| **Kimi Code** | 黑底白 K + 一点蓝 | 极简 K 字标 | 「尽管问」直给清爽 → 蓝黑长发+月亮饰（月之暗面）+ 黑蓝学院裙、蓝点耳钉 |
| **Trae** | 暗黑 `#0a0b0d`、霓虹绿 `#32f08c`、蓝紫渐变 `#64b4ff`/`#8e80ff` | 深色圆角块+像素脸 | Ship faster、年轻活力（字节） → 深色科技连衣裙+霓虹绿发光滚边+像素发卡 |
| **Devin** | 单色灰 `#626870`/`#171717` | 三六边形纽结 | 自主工程师、autonomy → 单色灰黑工程师裙+六边形纽结徽章+机械臂 |
| **ZCode** | 墨黑方块 + 白 Z（z.ai） | 粗犷几何 Z | 极简硬核（自家 GLM）→（已定稿）GLM娘魔女+帽上 Z 眼罩 |
| **Qoder** | 暗黑 `#090a0b` + 紫罗兰 `#8b5cf6` | 黑色线条抽象 Q | spec-driven、严谨（阿里） → 黑底紫罗兰饰边的裁剪制服裙+规格文书 |
| **MiMo Code（小米）** | 小米橙 `#FF6900`、纯白、圆角 MI 方块 | 橙白圆角方 tile | 为发烧而生、性价比信仰 → 白裙+橙色圆角方扣、白发渐变橙马尾、3 沙漏保留 |
| **Codebuddy** | 蓝紫渐变、青绿点缀 `#32e6b9` | 圆头渐变机器人 | 亲切 buddy 感（腾讯） → 蓝白配裙+渐变围巾，企鹅玩偶+QQ 窗彩蛋保留 |
| **Workbuddy** | 无强品牌（通用办公） | — | 误入的办公室助手 → 保持办公装 |
| **Trainer（自家）** | 靛蓝 `#4338CA` + 鎏金 | FSRS 曲线徽章 | 教练、长期主义 → 保持靛蓝教练装 |

### 1.1 Trainer 娘（主角 · 白月光教师）

> v4.2 用户定稿：白开水/白月光气质，教师感，白发短发，干练利落又漂亮。

```
TRAINER MASCOT BLOCK (paste every time):
An elegant anime girl (normal proportions, ~7 heads) — a pure "white
moonlight" beauty: pristine, luminous, like the elegant young teacher
everyone remembers.
Hair: completely WHITE (#F8FAFC) short crisp bob, sleek and capable,
slight inward curl at the ends, straight bangs swept barely to one
side, small indigo hairpin at the side.
Skin: fair porcelain-pale.
Eyes: calm indigo (#312E81), gentle and clear.
Slim silver-framed oval glasses.
Outfit: sharply tailored ivory-white long coach coat over a white
high-collar blouse, indigo (#4338CA) slim ribbon tie, tailored white
trousers; indigo FSRS forgetting-curve brooch on the lapel.
Accessories:
  - Brass stopwatch on a slim brown leather strap (the only warm
    gold accent against her white ensemble)
  - FSRS curve brooch
Pose archetype: standing, calm and composed; pointing at a blackboard
(teaching), or holding the stopwatch ready.
Expression palette: serene, gentle, encouraging, quietly radiant —
NEVER smug, NEVER villainous.
Signature mark: the white ensemble + indigo accents read instantly
as "the Teacher".
```

### 1.2 12 位 Harness 娘（配角）

> 每位只换 4 个变量：发色/发型、服装主色、桌面道具、表情倾向。
> 其他解剖结构、头身比、画风保持完全一致。

#### 1.2.1 Cursor 娘
```
Hair: sleek straight black hair with cool gray-white inner streaks, 
  sharp center part, chin-length.
Eyes: smoky gray with one faint gold fleck.
Outfit: impeccably tailored black-and-white ensemble — structured 
  near-black (#1c1c1e) jacket with asymmetric white panel lapels 
  folding like an isometric cube, warm-beige (#cac6be) slim skirt, 
  thin antique-gold (#c08532) collar line, polished-cube brooch.
Prop: dual translucent monochrome monitors `index.tsx` / `App.tsx`, 
  "tab" speech bubbles, right hand frozen mid Tab-press, 
  `$20/mo` price-tag charm on her belt.
Pose: calm level gaze, minimal movement.
Expression: high-cold elite, quietly confident.
Easter egg: the gold accents are the ONLY color on her.
```

#### 1.2.2 Claude Code 娘
```
Hair: long vivid orange (#E8622C) straight with full bangs, 
  large sunflower hair ornament on the left side + small black ribbon.
  (v4: 采纳社区 Claude娘 设定 — 丛雨快乐小窝 AI娘系列)
Eyes: warm amber-gold (#D97706).
Outfit: cream-white Victorian blouse with puffed shoulders, large 
  black ribbon bow at collar, black corset belt with gold buttons, 
  long cream skirt embroidered with small sunflowers.
Prop: hugging an old leather-bound book, black quill pen in one hand, 
  parchment scroll at her feet, a paper tape that reads 
  "Bash is all you need" curling around her left forearm.
Pose: thigh-up card portrait, calm and composed.
Expression: literary, faintly smug.
Easter egg: the paper tape wraps around the Trae girl's leg 
  (3 meters long).
```

#### 1.2.3 Codex 娘
```
Hair: silky platinum-white (#F8FAFC) waist-length, thin gold 
  O-shaped halo clip floating above her head.
  (v4: 采纳 OpenAI 白色系 GPT娘 血统 — 纯白+金)
Eyes: pale sky blue (#7DD3FC), serene half-lidded.
Outfit: pure white elegant high-collar dress-bodysuit with 
  subtle gold piping, gold cord belt, white thigh-high boots.
Prop: 5 thin floating round bubbles arcing above her open palms — 
  4 pale grey labeled "auto-generated", 1 glowing gold "verified ✓".
Pose: arms slightly outstretched, palms up.
Expression: serene, slightly detached.
```

#### 1.2.4 Kimi Code 娘
```
Hair: very long straight black hair (#0F172A) with blue-black sheen 
  reaching knees, golden crescent-moon hair ornament + tiny star pins.
  (v4: 月之暗面月亮意象 — 社区无现成设定，月亮为锚)
Eyes: deep violet (#6D28D9).
Outfit: elegant navy academic dress with white collar, silver star 
  and constellation embroidery, pale-blue sash, black tights.
Prop: an absurdly long parchment scroll unrolling from her hands 
  and trailing across the floor (200K context joke); 
  a small round moon-lantern floats at her side.
Pose: standing, scroll trailing behind.
Expression: calm, confident, slight knowing smile.
Easter egg: scroll's end has tiny text "I forget what we discussed 
  last time".
```

#### 1.2.5 Workbuddy 娘
```
Hair: tea-brown long hair tied in a low side ponytail with a 
  white scrunchie.
Eyes: warm brown.
Outfit: crisp white office blouse with a grey tailored vest and 
  pencil skirt, work ID lanyard with badge reading 
  "Not a Coding Harness", low heels.
Prop: balancing a coffee cup on a clipboard holding meeting notes.
Pose: standing, slightly hunched under the clipboard.
Expression: polite professional smile, slightly tired around 
  the eyes.
Easter egg: badge placard reads "误入 · Not a Coding Harness".
```

#### 1.2.6 Trae 娘
```
Hair: bright peach-pink twin tails tied with big white ribbons, 
  straight bangs.
Eyes: rose-pink (#E11D48).
Outfit: casual white hoodie-dress with mint-green trim shaped 
  like a diner waitress uniform, tiny "$0" price-tag earring.
Prop: presents a lunch tray with a wrapped lunch box and a small 
  card reading "for free"; a tiny coupon ticket flutters beside her.
Pose: offering the tray forward with both hands.
Expression: bright cheerful vendor energy, sparkling eyes.
Easter egg: coupon reads "v0 · forever free".
```

#### 1.2.7 Devin 娘
```
Hair: silver-grey long hair, small mechanical gear hairclip 
  on the right side.
Eyes: steel-blue (#475569).
Outfit: sleek black-and-white engineer dress with faint white 
  circuit-line patterns, polished mechanical gauntlet covering 
  her right forearm.
Prop: small robotic arm rising over her shoulder holding five 
  paper slips, each stamped "unmerged" in red.
Pose: thigh-up card portrait, gauntlet arm visible.
Expression: earnest, slightly overwhelmed, nervous sweat drop.
Easter egg: one slip has a tiny Trainer silhouette stamped on it.
```

#### 1.2.8 ZCode 娘
```
Hair: long straight black hair with full bangs, two small silver 
  bell hairpins.
  (v4: 采纳社区 GLM娘 设定 — 自家模型，丛雨快乐小窝 AI娘系列)
Headwear: large black witch hat with a white sleep mask printed 
  "Z" resting pushed up against the brim.
Eyes: deep burgundy-red (#7F1D1D), sleepy half-lidded gaze.
Outfit: gothic-lolita black-and-white dress — white long-sleeve 
  blouse, black corset skirt, white lace apron, black ribbon 
  choker with a small silver bell.
Prop: black book embossed "GLM" tucked under her left arm; 
  a small dark terminal window floats beside her showing a blinking 
  cursor and "zcode run → done"; an hourglass lies on its side at 
  her feet, sand untouched (无 FSRS).
Pose: one hand raised near her chin.
Expression: sleepy, lazy, faintly smug little smile.
Easter egg: terminal output flickers with "exit 0" but no other 
  feedback.
```

#### 1.2.9 Qoder 娘
```
Hair: ash-lavender long hair with razor-sharp side bangs, 
  black hairband, thin rectangular silver glasses.
Eyes: grey-violet (#7C3AED).
Outfit: crisp white-and-charcoal tailored secretary dress with 
  high collar and dark blue tie, document-print skirt patterned 
  with faint contract text.
Prop: thick stack of spec documents titled "Spec" in her arms, 
  page 47 visible; one loose page floats beside her printed 
  "Evaluation criteria: undefined".
Pose: standing, hugging the stack.
Expression: precise, bureaucratic, tightly controlled smile.
Easter egg: book is open to the only page that's empty.
```

#### 1.2.10 MiMo Code 娘
```
Hair: warm caramel hair in two round twin buns with long trailing 
  strands, orange ribbon ties.
Eyes: amber (#F59E0B).
Outfit: cute cream-and-orange technician dress with gear-shaped 
  buttons, toolbelt worn loose at the hip.
Prop: 3 hourglasses floating in a row in front of her — the middle 
  one is cracked, glowing sand leaking out and pooling into a tiny 
  sign shaped like the word "Trainer".
Pose: gesturing at the 3 hourglasses.
Expression: flustered pout, cheeks puffed.
```

#### 1.2.11 Codebuddy 娘
```
Hair: warm honey-yellow long wavy hair, tiny penguin-shaped 
  hairclip.
Eyes: honey-brown (#B45309).
Outfit: elegant cream hanfu-inspired wrap dress with wide sleeves, 
  deep-blue sash, subtle wave-pattern embroidery.
Prop: cuddling a small round penguin plushie wearing a tiny red 
  scarf; a translucent pale-blue login window floats behind her 
  like a ghost, its single button labeled "QQ".
Pose: hugging the penguin.
Expression: cozy, homey, contented smile.
Easter egg: penguin has a small Trainer badge pinned to it.
```

#### 1.2.12 Grok Build 娘
```
Hair: black with red streaks (#DC2626), messy punk cut, shaved 
  on one side.
Eyes: glowing yellow (#FACC15).
Outfit: black leather jacket with lightning bolt pins, 
  red plaid skirt, combat boots, lightning-bolt earring.
Prop: welding torch in right hand (sparks flying), 
  a half-built contraption on the table.
Pose: welding mid-action, hair blowing back from the heat.
Expression: chaotic energy, "let me just build it".
Easter egg: sparks land on the Cursor girl's sunglasses.
```

### 1.3 人类开发者（剪影 + 全身两版）

#### 1.3.1 左边孤独剪影
```
Hair: short black.
Outfit: dark gray hoodie.
Pose: sitting in corner, knees drawn up, head in hands.
Expression: exhaustion, defeat.
Lighting: cold blue-grey, lit only by monitor glow from harness 
  table.
Detail: empty coffee cup on the floor beside him, empty notebook 
  with only the title page "Day 1" written.
```

#### 1.3.2 右边站立全身
```
Hair: short black (SAME silhouette as the lonely corner one).
Outfit: dark gray hoodie (SAME), headphones around neck.
Pose: standing, facing Trainer 娘, open notebook in one hand, 
  coffee cup (half-empty) in the other.
Expression: alert, engaged, slightly tentative.
Lighting: warm indigo-gold, lit by blackboard glow and Trainer's 
  spotlight.
Detail: notebook page reads "Day 1 — Trainer" in fresh handwriting.
```

**关键一致性**：两个开发者**发型/衣服/耳机完全一致**，只是姿态和光线不同。读者一眼看出"是同一个人从左走到右"。

---

## 2. 设计系统 · Design System

### 2.1 色彩 Token

```
PALETTE BLOCK (paste into every prompt):
--indigo-950: #1E1B4B    /* deepest, linework */
--indigo-900: #312E81    /* Trainer hair shadow */
--indigo-700: #4338CA    /* Trainer skirt */
--indigo-500: #6366F1    /* Trainer hair highlight */
--indigo-300: #A5B4FC    /* light accent */
--indigo-50:  #EEF2FF    /* cream-tinted background warm side */

--gold-500:   #F59E0B    /* Trainer accent metal */
--gold-300:   #FCD34D    /* eye highlights */
--gold-100:   #FEF3C7    /* paper, parchment */

--cream-bg:   #F5F3FF    /* warm canvas */
--slate-900:  #0F172A    /* code text */
--slate-700:  #334155    /* body text */
--slate-500:  #64748B    /* annotations */

--vibe-cold-1: #1E293B   /* left side cold sky */
--vibe-cold-2: #475569   /* left side cold mid */
--vibe-cold-3: #94A3B8   /* left side cold highlight */

--success:    #10B981    /* verified ✓ */
--danger:     #EF4444    /* unverified ✗ */
--warning:    #F59E0B    /* in-progress */

--chalk-white: #F5F5DC   /* blackboard writing (NOT pure white) */
--chalk-yellow: #FDE68A  /* blackboard emphasis */
--chalk-green: #86EFAC   /* blackboard code */
```

### 2.2 4K 渲染规范

| 维度 | 规格 |
|---|---|
| **画布** | 3840 × 2160 px (16:9 4K UHD) |
| **DPI** | 72 (屏幕) / 300 (印刷备用 PNG) |
| **格式** | PNG (无透明) + WebP (压缩) |
| **色彩空间** | sRGB |
| **色深** | 8-bit (WebP) / 16-bit (PNG 印刷版) |
| **命名** | `kebab-case.webp` + `kebab-case@4k.png` 双版本 |
| **最大文件** | 8 MB (WebP) / 50 MB (PNG 4K) |

### 2.3 构图网格（每张图必套）

```
CANVAS GRID BLOCK (paste into every prompt):
Composition: rule-of-thirds grid with golden-ratio focal points.
Hero focal point at (1/3, 1/2) — Trainer 娘 face.
Secondary focal at (2/3, 1/2) — blackboard center text.
Negative space: 15% top margin, 10% bottom margin for signature 
  band, 5% side margins.
Diagonal tension line from (0,0) to (W,H) crossing through 
  the blackboard — divides cold/warm palettes.
Foreground depth: harness 娘s at z=0.5 (slightly blurred edges), 
  blackboard at z=1.0 (sharp), Trainer + developer at z=1.5 
  (sharpest focus, highest contrast).
```

### 2.4 灯光规范

```
LIGHTING BLOCK (paste into every prompt):
Primary light: warm directional from upper-left, key intensity 0.8.
Fill light: cool ambient from right side, intensity 0.3.
Rim light: warm gold rim from behind subjects, intensity 0.4.
Chiaroscuro contrast: 7:1 between brightest (Trainer's white coat) 
  and darkest (code waterfall void).
Color temperature: warm side 3200K, cold side 6500K.
Atmospheric haze: subtle volumetric god-rays from the blackboard 
  outward, density 0.15.
No pure black: deepest shadows are indigo-950, not #000000.
```

### 2.5 笔触与肌理

```
TEXTURE BLOCK (paste into every prompt):
Brushwork: alla prima oil painting, visible directional strokes, 
  3-5mm brush width on figures, 10-15mm on background.
Canvas texture: subtle linen weave at 5% opacity, visible only 
  in flat color areas.
Edge treatment: hard edges on character silhouettes, soft 
  impasto edges on clothing folds, no antialiased blur.
Color blending: wet-on-wet in transitions, scumbling in shadow 
  areas, glazing in highlight areas.
Detail level: high on faces and props, medium on clothing, 
  low on background (atmospheric perspective).
```

---

## 3. 高级 Prompt 工程规范

### 3.1 结构（每个 prompt 必须包含的 6 段）

```
[1] ART DIRECTION (art movement, era, medium, master reference)
[2] COMPOSITION (grid, focal points, negative space, depth)
[3] LIGHTING (key, fill, rim, atmospheric, color temperature)
[4] PALETTE (named colors with hex, warm/cold zones)
[5] CHARACTERS (paste mascot block + per-character variants)
[6] TEXTURE & FINISH (brushwork, canvas, edges, detail level)
```

### 3.2 用词层级（避免廉价词）

| ❌ 不要用 | ✅ 改用 |
|---|---|
| cute | chibi / neotraditional / kawaii-adjacent |
| beautiful | luminous / striking / contemplative |
| cool style | chiaroscuro / cinematic / Rembrandt-influenced |
| high quality | gallery-grade / museum-print / 4K masterwork |
| detailed | alla prima oil painting, alla-prima brushwork visible |
| good lighting | three-point lighting with 7:1 chiaroscuro ratio |
| realistic | semi-illustrative / painterly realism |
| fantasy art | neoclassical oil painting / Renaissance-influenced |
| colorful | polychromatic with limited indigo-gold palette |
| nice background | atmospheric perspective, volumetric haze, soft-focus mid-ground |

### 3.3 必须出现的"高级感"关键词

每个 prompt 必须包含至少 5 个：
- **chiaroscuro** / **Rembrandt lighting**
- **alla prima** / **impasto**
- **Renaissance composition** / **Bruegel-influenced**
- **painterly** / **museum-grade**
- **atmospheric perspective** / **volumetric haze**
- **limited palette** / **polychromatic harmony**
- **cinematic depth of field** / **bokeh background**
- **golden-ratio composition** / **rule of thirds**
- **museum print resolution** / **4K masterwork**
- **visible brushwork** / **canvas texture**

### 3.4 必须避免的"廉价感"关键词

任何 prompt 都不得出现：
- ❌ 3D render
- ❌ cartoon (用 chibi)
- ❌ anime style (用 neoclassical anime-influenced)
- ❌ cute
- ❌ minimalist
- ❌ flat design
- ❌ vector
- ❌ logo
- ❌ icon

---

## 4. 18 张图清单（最终）

| # | 文件名 | 主调 | 关键道具 | 彩蛋数 |
|---|---|---|---|---|
| 1 | `banner.webp` | 群像（12 娘 + 1 人） | 黑板 + 对比代码 | 17 |
| 2 | `feat-verify.webp` | 验证门禁 | 印章 + 当前文件 | 3 |
| 3 | `feat-memory.webp` | 长期记忆 | FSRS 节奏盘 + 卡片 | 4 |
| 4 | `feat-training.webp` | 训练闭环 | 翻卡 + 复习曲线 | 3 |
| 5 | `feat-youwrite.webp` | 你写它教 | 双手背后 + 开发者打字 | 2 |
| 6 | `feat-skills.webp` | $ 技能 | 百宝袋 + prompt 卡片 | 3 |
| 7 | `feat-speed.webp` | 端点测速 | 秒表 + 4 网关赛跑 | 2 |
| 8 | `feat-library.webp` | 资料库 | 书架 + 沙箱 + 回收站 | 3 |
| 9 | `diagrams/agent-loop.webp` | ReAct 双通道 | 工具箱环 + 熔断器 | 2 |
| 10 | `diagrams/snapshot-sync.webp` | Snapshot 同步 | 31 块拼图 + 时钟 | 2 |
| 11 | `diagrams/authority-ladder.webp` | 6 级权限 | 阶梯 + 远程墙 | 3 |
| 12 | `diagrams/handoff-phases.webp` | Handoff 5 相 | LEARN→RETURN 跑道 | 2 |
| 13 | `diagrams/provider-protocols.webp` | 4 协议 | 4 扇门 + 拒入小门 | 2 |
| 14 | `diagrams/workspace-zones.webp` | 工作区 3 域 | workspace/sandbox/trash | 2 |
| 15 | `diagrams/evidence-loop.webp` | 证据闭环 | 转盘 4 段 | 2 |
| 16 | `diagrams/governance-pure.webp` | 治理模块 | 3 人共用地图 | 2 |
| 17 | `diagrams/fsrs-rhythm.webp` | FSRS 节奏 | 曲线 + 卡片 | 2 |
| 18 | `diagrams/i18n-locale.webp` | i18n 8 语言 | 8 国小旗帜 | 2 |

---

## 5. 跨图一致性检查清单（生成前必读）

生成每张图前必须确认：

- [ ] Trainer 娘的发色 `#1E1B4B → #6366F1` 渐变是否一致
- [ ] Trainer 娘的眼睛 `#312E81` + 黄 `#FCD34D` 三点高光是否一致
- [ ] 12 位 harness 娘的发型/服装主色是否与本规范一致
- [ ] 人类开发者在子图中是否保持"剪影 + 站立"两种状态之一
- [ ] 黑板字是否用 `#F5F5DC` 白垩色
- [ ] 代码块是否用 `#FDE68A` 黄绿色（不是纯绿）
- [ ] 横批是否在画面下沿 10% 区域
- [ ] 是否包含至少 5 个"高级感"关键词
- [ ] 是否不包含任何"廉价感"关键词
- [ ] 是否在 3840×2160 画布上构图

---

## 6. 输出格式约定

每张图生成完成后，必须产出：

```
assets/
  ├── banner.webp           # 主图，3840x2160
  ├── banner@4k.png         # 主图 PNG 印刷版
  ├── banner@2k.webp        # 主图压缩版（GitHub README 默认）
  ├── feat-*.webp           # 8 张 feature 卡，1600x900
  ├── feat-*@2x.png         # 2x retina 备用
  ├── diagrams/*.webp       # 8 张原理图，2400x1350
  └── screenshots/*.png     # 5 张 VS Code 实拍（保留原图）
```

每个 webp 必须：
- 启用有损压缩 q=82
- 必须 EXIF 注释：`Trainer · v1.0.3 · CC-BY-SA-4.0`
- 颜色 profile 嵌入 sRGB

---

## 7. 灵感来源声明

本规范的视觉语言参考（不抄袭，致敬）：

| 来源 | 借鉴点 |
|---|---|
| DeepSeek 官方二次元娘 | 头身比、发色明度、cel-shading 倾向 |
| Pieter Bruegel 《通天塔》| 左右阵营 + 中央分界构图 |
| 达·芬奇 《最后的晚餐》| 长桌横向排列（仅构图借鉴） |
| Rembrandt 《夜巡》| 7:1 明暗对比、光源方向 |
| Studio Ghibli 角色设计 | 大眼三点高光、表情克制 |
| Cyberpunk 2077 角色卡 | 黑板代码块字体风格 |

---

## 8. 法律与署名

所有 Trainer 视觉资产采用 **CC-BY-SA-4.0** 协议：

- ✅ 允许二次创作（衍生图必须同样 CC-BY-SA-4.0）
- ✅ 允许商业使用（须保留 Trainer 署名）
- ❌ 禁止单独抽 harness 娘做"harness 官方代言"宣传
- ❌ 禁止用 Trainer 娘形象讽刺具体 LLM 产品

**必填署名**（每张图 EXIF）：
`Trainer v1.0.3 · https://github.com/AI-yyf/trainer`

---

> Trainer 的视觉是一份宣言。
> Trainer&apos;s visuals are a manifesto.
> 每一张图都在说同一句话：你写，我教，我们一起长。
