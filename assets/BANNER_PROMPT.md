# Hero Banner Prompt · 4K 3840×2160

> **这是 README 首屏的图，也是整组视觉资产的母版。**
> **This is the hero. Everything else is consistent with this.**

---

## 0. 画面目标 · What this image must do

读者扫一眼图（3 秒内）能接收到 4 件事：

1. **Trainer 不替你写代码** —— Trainer 娘双手背后，不碰键盘
2. **vibe coding 是孤独的** —— 左边开发者剪影抱着头
3. **Trainer 是协作的** —— 右边开发者站立面对 Trainer
4. **同一个开发者从左走到右** —— 同样的发型/衣服/耳机，只是姿态变

读者扫第二眼（10 秒）能读到 4 个细节：

1. **黑板上的代码对比** —— vibe coding 4 行 vs Trainer 4 行
2. **FSRS 曲线被擦掉重画** —— 遗忘变成长
3. **harness 娘们的反应** —— Cursor 摘墨镜、Claude 纸带缠腿、Codex 气泡变 verified
4. **空椅子便签** —— `migrated to Trainer`

---

## 1. 主 Prompt（可直接喂给 dora-image）

```text
[ART DIRECTION]
A 4K masterwork oil painting on linen canvas, chibi 2.5-head 
neoclassical anime-influenced characters, alla prima brushwork 
with visible directional strokes (3-5mm on figures, 10-15mm 
on background), inspired by Pieter Bruegel's "Tower of Babel" 
horizontal split composition. NOT Renaissance dinner tableau. 
Museum print resolution, gallery-grade chiaroscuro.

[COMPOSITION]
Canvas 3840x2160 (16:9), rule-of-thirds grid, golden-ratio 
focal points. Hero focal at (1/3, 1/2) — Trainer 娘 face 
looking toward developer. Secondary focal at (2/3, 1/2) — 
blackboard center text. Negative space: 15% top margin, 10% 
bottom margin for signature band, 5% side margins. Diagonal 
tension line from (0,0) to (W,H) crossing through blackboard — 
divides cold/warm palettes. Foreground depth: harness girls 
at z=0.5 with slight edge blur, blackboard at z=1.0 sharp, 
Trainer + developer at z=1.5 sharpest focus with highest 
contrast.

[LIGHTING]
Primary key: warm directional from upper-left, intensity 0.8. 
Fill: cool ambient from right side, intensity 0.3. Rim: warm 
gold rim from behind subjects, intensity 0.4. Chiaroscuro 
contrast 7:1 between brightest (Trainer's white coat) and 
darkest (code waterfall void). Color temperature: warm side 
3200K, cold side 6500K. Volumetric god-rays radiating outward 
from the blackboard center, density 0.15. No pure black — 
deepest shadows are indigo-950 (#1E1B4B), not #000000.

[PALETTE]
Limited polychromatic harmony:
  Cold zone (left third): vibe-cold-1 #1E293B sky, 
    vibe-cold-2 #475569 mid, vibe-cold-3 #94A3B8 highlight, 
    silver-gray #94A3B8 monitor glow
  Neutral zone (center third): slate-900 #0F172A blackboard, 
    chalk-white #F5F5DC writing
  Warm zone (right third): indigo-950 #1E1B4B deepest, 
    indigo-900 #312E81 hair shadow, indigo-700 #4338CA skirt, 
    indigo-500 #6366F1 hair highlight, gold-500 #F59E0B metal, 
    gold-300 #FCD34D eye highlights, cream-bg #F5F3FF background
  Accents: success #10B981 for verified, danger #EF4444 for 
    unverified, warning #F59E0B for in-progress
  No pure white, no pure black anywhere.

[CHARACTERS — paste from MASCOT.md]
Trainer 娘: indigo short bob with blunt bangs and single ahoge, 
  large round indigo #312E81 eyes with bright yellow #FCD34D 
  star highlights, warm cream #F5E6D3 skin with subtle blush, 
  white coach jacket with indigo lapels and brass buttons over 
  indigo athletic vest, indigo pleated skirt to mid-thigh, 
  white knee-high socks, brown loafers, round brass glasses, 
  holding coach stopwatch-whip hybrid (leather strap with brass 
  stopwatch face), small FSRS curve tattoo on left hand.
  Pose: STANDING with back partially to viewer (3/4 view), 
  one hand pointing at blackboard with the stopwatch-whip, 
  expression: focused and gentle.

Human developer (TWO STATES, same character):
  - LEFT state (corner silhouette): sitting, knees drawn up, 
    head in hands, dark gray hoodie, headphones around neck, 
    short black hair, empty coffee cup on floor beside him, 
    empty notebook open to "Day 1" title page.
  - RIGHT state (standing): SAME hair, SAME hoodie, SAME 
    headphones, but standing facing Trainer, open notebook 
    in one hand, coffee cup half-empty in other, expression 
    alert and tentative.
  CRITICAL CONSISTENCY: these two MUST read as the same 
  person. Identical hair texture, identical hoodie shade, 
  identical headphone model.

11 Harness girls (LEFT side, around long table):
  1. Cursor girl: chestnut brown undercut bob, VS Code-blue 
     #007ACC cropped hoodie, dual 4K monitors, "tab tab tab" 
     speech bubbles. Sunglasses reflect Trainer silhouette.
  2. Claude Code girl: auburn #7C2D12 pixie cut, long black 
     duster coat, quill pen, scroll of parchment, paper tape 
     "Bash is all you need" tangling around her own feet.
  3. Codex girl: honey-blonde #D97706 waist-length with O-shaped 
     halo clip, pure white bodysuit, 5 floating PR bubbles 
     labeled "auto-generated" (one changes to "verified ✓" 
     when she glances right).
  4. Kimi Code girl: ink-black #0F172A waist-length qipao, 
     giant scroll unfurling across table trailing to floor 
     with tiny text "I forget what we discussed last time".
  5. Workbuddy girl: warm orange #FB923C chin-length bob, 
     cream office blazer, stack of Word/Excel files, table 
     placard reads "误入 · Not a Coding Harness", awkward smile.
  6. Trae girl: orange #F97316 double-bun, orange track jacket, 
     hamburger with "for free" sesame-seed writing, fries.
  7. Devin girl: silver-white #E5E7EB low ponytail, white lab 
     coat, mechanical right arm with brass joints, floating 
     queue of 5 PR cards all marked "unmerged" in red.
  8. ZCode girl: silver-gray #94A3B8 asymmetric cut with Z clip, 
     techwear tactical vest, holographic terminal showing 
     "zcode run → done" with no FSRS rhythm disk visible.
  9. Qoder girl: deep teal #0F766E long hair with round glasses, 
     cream blouse under teal cardigan, thick spec book open to 
     page 47 "Evaluation criteria: undefined".
  10. MiMo Code girl: cream-white #FEF3C7 fluffy short cut, 
      orange Xiaomi hoodie with "Mi" logo, 3 hourglasses 
      labeled "computation" / "memory" / "evolution" — 
      the "memory" hourglass is cracked, spilling sand that 
      forms the word "Trainer".
  11. Codebuddy girl: warm yellow #FCD34D long wavy with hair 
      stick, hanfu-inspired cream top with navy wrap, penguin 
      plushie (Tencent joke) with tiny Trainer badge.

[EMPTY CHAIR (right side, far end)]
One knocked-over chair with paper note taped to seat reading 
"migrated to Trainer // see: AGENTS.md". On the chair back: 
a torn .vsix package wrapper.

[CENTER — CHALKBOARD]
Large chalkboard spanning 40% of canvas width, centered. 
Blackboard background: slate-900 #0F172A with subtle wood 
frame in warm brown.

Top half of blackboard: FSRS forgetting curve drawn in chalk-
white #F5F5DC, showing exponential decay. The LEFT half of 
the curve is partially erased (smudged), the RIGHT half is 
freshly redrawn as an ascending curve — the same Trainer hand 
mid-motion erasing and redrawing.

Bottom half of blackboard: TWO CODE BLOCKS side by side in 
chalk-green #86EFAC and chalk-yellow #FDE68A, monospace font 
style, handwritten with chalk dust effect:

  ┌─────────────────────────┐  ┌─────────────────────────┐
  │ // vibe coding          │  │ // Trainer              │
  │ def ship(code):         │  │ def ship(code):         │
  │     ai.write(code)      │  │     you.write(code)     │
  │     # 你懂了吗？        │  │     ai.verify(code)     │
  │     return forget(code) │  │     you.recall(code)    │
  │                         │  │     return grown(code)  │
  └─────────────────────────┘  └─────────────────────────┘

Below code blocks, smaller chalk-white text:
"产出 ≠ 成长    验证 + 复习 = 成长"

Bottom right corner of blackboard: small FSRS curve drawing 
with checkmark "✓ verified".

[FOREGROUND COACHING TABLE — right third]
Small coaching table (NOT long banquet table), warm wood, 
between Trainer 娘 and standing developer:
  - Open FSRS rhythm disk card (round, brass-edged)
  - Red book titled "py-fsrs: open-spaced-repetition" 
    open, page corner folded by Trainer
  - Coffee cup, cream ceramic with FSRS curve printed on side, 
    half-empty
  - Calendar page "Day 1 — Trainer"
  - Notebook open to page with handwriting: 
    "Day 1: 不再 vibe coding"

[WINDOWS IN BACKGROUND — symbolic]
LEFT window: shows VS Code DARK THEME editor with empty file
RIGHT window: shows VS Code LIGHT THEME editor with code being 
typed in real time (cursor blinking)
The same IDE, two different modes — symbolic.

[BOTTOM SIGNATURE BAND]
10% bottom margin reserved for signature:
Centered, in serif italic (Cormorant Garamond Italic):
"// Train Your AI · Grow With Your AI"

Below in smaller serif:
"训练你的 AI · 与你的 AI 共同成长"

Far right corner, tiny:
"v1.0.3"

[TEXTURE & FINISH]
Brushwork: alla prima oil painting, visible directional strokes.
Canvas texture: subtle linen weave at 5% opacity, visible only 
in flat color areas.
Edge treatment: hard edges on character silhouettes, soft 
impasto edges on clothing folds, no antialiased blur.
Color blending: wet-on-wet in transitions, scumbling in shadow 
areas, glazing in highlight areas.
Detail level: HIGH on faces (especially Trainer 娘 eyes with 
three highlights), HIGH on chalkboard text, HIGH on coaching 
table props, MEDIUM on clothing, LOW on background (atmospheric 
perspective).

[NEGATIVE CONSTRAINTS]
NO pure black anywhere. NO pure white anywhere.
NO photorealism — maintain chibi 2.5-head proportions.
NO 3D render, NO vector, NO flat design, NO minimalist.
NO text artifacts except: blackboard text (intentional), 
signature band (intentional), tiny table placard (intentional), 
chair note (intentional).
NO additional characters beyond the 11+1+1 listed.
NO modern tech logos beyond what fits the harness prop.

[QUALITY TAGS]
masterwork, museum-print, 4K UHD, alla prima oil on linen, 
chiaroscuro Rembrandt-influenced, polychromatic harmony, 
golden-ratio composition, visible brushwork, atmospheric 
perspective, volumetric god-rays, cinematic depth of field
```

---

## 2. 生成参数建议（dora-image 调用）

```bash
python3 scripts/generate_dora_image.py \
  --prompt "$(cat assets/BANNER_PROMPT.md | tail -n +30)" \
  --model gpt-image-2 \
  --workflow normal \
  --aspect-ratio 16:9 \
  --target-size 3840x2160 \
  --quality high \
  --generation-mode standard \
  --output-format png \
  --output assets/banner@4k.png

# 之后用 cwebp 压成 webp：
cwebp -q 82 assets/banner@4k.png -o assets/banner.webp
```

---

## 3. 必检 12 项（生成后人工检查）

| # | 检查项 | 通过标准 |
|---|---|---|
| 1 | Trainer 娘眼睛 | 3 点高光，黄色 `#FCD34D` |
| 2 | Trainer 娘手 | 双手不碰键盘，指向黑板 |
| 3 | 12 位 harness 娘 | 都坐/站在长桌侧（LEFT 1/3） |
| 4 | 人类开发者剪影 | 孤独坐姿，双手抱头 |
| 5 | 人类开发者站立 | 与剪影**完全同款**发型/衣服/耳机 |
| 6 | 黑板代码对比 | vibe coding vs Trainer 两块代码并存 |
| 7 | FSRS 曲线 | 左半擦掉、右半重画 |
| 8 | 空椅子便签 | `migrated to Trainer` 文字清晰 |
| 9 | 横批 | `// Train Your AI · Grow With Your AI` 在下沿 |
| 10 | 窗外 | 左暗右亮 VS Code |
| 11 | 色调 | 左冷右暖斜线分隔 |
| 12 | 高级感词 | 至少 5 个高级感关键词实际生效（不是堆砌） |

---

## 4. 失败重做规则

任何一项检查不过 → 整张重做，**不要局部修复**。

理由：4K 局部修复会破坏整体光影与笔触连贯性。重做时只调整 prompt 中失败的那一段描述，其余保留。

常见失败 → 调整方向：

| 失败症状 | 调整 |
|---|---|
| 角色头身比写实 | 加强"chibi 2.5-head"重复 3 次 |
| 黑板字不可读 | 加 "HIGHLY LEGIBLE chalk text, monospace, 64px line height" |
| 色调没有冷暖对比 | 加 "STRICT palette split: 65K left, 3200K right" |
| 笔触太干净像 AI | 加 "visible impasto strokes, no smooth gradients" |
| 人类两个状态不像同一个人 | 加 "EXACT same hair pixels, EXACT same hoodie color" |
| 横批文字缺失 | 加 "MUST include signature band text at bottom 10%" |
| 高光没出现 | 加 "three-point eye highlights, #FCD34D yellow, star-shaped" |
| 构图散了 | 加 "rule-of-thirds strict grid, golden-ratio focal" |

---

## 5. 这张图在 README 中的位置

```markdown
<div align="center">
  <img src="assets/banner.webp" alt="..." width="100%" />
</div>
```

放在 README 第 1 行（hero），下方立即接双语 hook 段。

---

> 这是 Trainer 的脸。每一像素都在为"共同成长"说话。
> This is Trainer&apos;s face. Every pixel argues for growth together.
