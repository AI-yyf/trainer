#!/usr/bin/env python3
"""Step 3: generate the 7 feat-* and 10 diagram-* images using the portrait as reference.

Each image is a focused "frame" from the banner, reusing the Trainer portrait
(plus a small number of harness portraits where the prompt calls for them).
We use 1600x900 (16:9) for feat-* and 2400x1350 (16:9) for diagram-* — both
fit the README's content-width nicely.
"""

import argparse, json, subprocess, sys, time
from pathlib import Path

SCRIPT = Path.home() / ".agents/skills/dora-image/scripts/generate_dora_image.py"
PORTRAITS = Path("/Users/Apple/Desktop/trainer/assets/portraits")
OUT = Path("/Users/Apple/Desktop/trainer/assets")
OUT.mkdir(parents=True, exist_ok=True)


# Common style lock injected into every prompt — keeps the visual identity consistent.
STYLE_LOCK = (
    "[STYLE LOCK] "
    "4K masterwork oil painting on linen canvas, chibi 2.5-head neoclassical anime-influenced characters. "
    "Character art must match the cel-shaded flat style of the supplied reference images — flat color blocks with crisp dark outlines, no painterly strokes on the characters. "
    "Soft warm gradient background blending the supplied reference background tones. "
    "Indigo-gold warm palette (#312E81, #4338CA, #F59E0B, #FCD34D, #F5E6D3, #1E1B4B). "
    "Masterwork museum-print resolution, chiaroscuro Rembrandt lighting, volumetric god-rays, atmospheric perspective. "
    "No pure black, no pure white. NO 3D render, NO photorealism, no watercolor, no minimalism. "
    "Brushwork visible only in background, softer on figures. "
    "Each character must retain the EXACT silhouette, hair color, outfit color, and prop from their reference portrait. "
    "No other characters beyond those in the reference set. "
    "No watermark, no signature."
)


# ---------------------------------------------------------------------------
# 7 FEATURE IMAGES (1600x900) — single-character focus on Trainer
# ---------------------------------------------------------------------------

PROMPTS = {
    # 1. feat-verify
    "feat-verify": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 1600x900 (16:9). Trainer girl at center, slightly right of frame, "
        "raised 3/4 view. The brass stamp dominates the right hand. "
        "VS Code editor panel floats in upper-right quadrant. Chalkboard text in upper-left. "
        "Training card at lower-center. Rule of thirds. Negative space 10% top, 8% bottom.\n\n"

        "[CHARACTERS] Trainer girl standing front-3/4 view, holding a large brass stamp in her right "
        "hand raised triumphantly, the stamp face reads '已通过 ✓' in bold red calligraphy. "
        "Her left hand holds the stopwatch-whip. Must match trainer.png reference exactly: "
        "indigo short bob with ahoge, round brass glasses, white coach jacket with indigo lapels, "
        "indigo pleated skirt, white knee socks, brown loafers. "
        "To the left, a faint silhouette of cursor girl reaching for a 'Mark Done' button that's "
        "been crossed out with a red X.\n\n"

        "[BACKGROUND] Warm dark slate chalkboard spans upper-left third with handwritten text in chalk-green #86EFAC:\n"
        "  verified_by_current_file ≠ marked_done\n"
        "  // 伪完成是最快的放弃\n\n"

        "[VS CODE PANEL] Translucent VS Code editor panel (rendered as a magic scroll) "
        "in upper-right, showing actual Python code with three lines transitioning "
        "from red squiggly diagnostic to green checkmark in sequence.\n\n"

        "[FOREGROUND] Bottom-center: a training card with 'verified' stamp already pressed into it, "
        "glowing gold at the edges.\n\n"

        "[LIGHTING] Key from upper-left at 0.7 intensity. Rim light gold #F59E0B around the stamp. "
        "Subtle green #10B981 glow on lines transitioning to verified.\n\n"

        "[PALETTE] indigo-700 #4338CA, gold-500 #F59E0B, chalk-green #86EFAC, slate-900 #0F172A, "
        "success #10B981, danger #EF4444.\n\n"

        "[TEXTURE] Sharp focus on stamp and code panel. Soft focus on background chalkboard. "
        "Visible brushwork on Trainer's white jacket.\n\n"

        "[NEGATIVE CONSTRAINTS] NO Mark Done button visible as functional. NO green checkmark "
        "without current_file context. NO photorealism."
    ),

    # 2. feat-memory
    "feat-memory": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 1600x900 (16:9). Brain-library centered, taking up middle 60% of canvas. "
        "Trainer at lower-right pulling cards. Clock-face FSRS disk at right third. "
        "Notebook at lower-left.\n\n"

        "[CHARACTERS] Trainer girl standing in front of a giant translucent brain-shaped library "
        "(semi-transparent indigo dome filled with floating shelves of glowing cards). She is pulling "
        "3 cards from the 'due' shelf with her right hand — each card has a brass FSRS rhythm tag. "
        "Must match trainer.png reference exactly.\n\n"

        "[BACKGROUND] Behind the brain-library: a large clock-face labeled 'FSRS' with concentric "
        "rings of cards at different orbit distances (inner = high mastery with green halos, "
        "outer = just-learned with red 'due' tags at 12 o'clock position). "
        "Cards fly outward in golden spiral trails — each card shows a different concept symbol "
        "(curly brace, async arrow, SQL JOIN).\n\n"

        "[FOREGROUND] A small open notebook at lower-left, page reads:\n"
        "  Day 1 · async/await    ✓ verified\n"
        "  Day 3 · generator      ✓ verified\n"
        "  Day 7 · asyncio.Task   → due today\n\n"

        "[LIGHTING] Key from upper-center, soft volumetric haze density 0.2.\n\n"

        "[PALETTE] indigo-950 #1E1B4B (library dome), gold-300 #FCD34D (card glow), "
        "chalk-white #F5F5DC (notebook text), success #10B981 (verified checks), warning #F59E0B (due tags).\n\n"

        "[TEXTURE] Visible impasto on the brain-library translucent surface. Sharp focus on the "
        "3 flying cards. Soft volumetric haze throughout.\n\n"

        "[NEGATIVE CONSTRAINTS] NO calendar grid. NO simple list. NO photorealism."
    ),

    # 3. feat-training
    "feat-training": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 1600x900 (16:9). Circular training loop track fills 60% of canvas. "
        "Trainer girl at center of loop. Harness silhouettes at outer ring. Rule of thirds. Golden ratio.\n\n"

        "[CHARACTERS] Trainer girl at center, holding a flashcard up with both hands at face level — "
        "front side shows 'Q: 为什么 generator 比 list 节省内存？' in handwritten chalk, she's mid-flip, "
        "back side just visible showing 'A: lazy evaluation' with a green ✓ verified stamp. "
        "Must match trainer.png reference exactly. "
        "Outside the loop, three faded harness girl silhouettes (cursor, codex, claude code) "
        "leaning in to watch the loop, their forms semi-transparent indigo #312E81 with 0.3 opacity.\n\n"

        "[LOOP TRACK] She stands at the apex of a circular training loop track drawn on the ground "
        "in chalk-green #86EFAC:\n"
        "  对话 → 证据 → 训练卡 → 验收 → (回到对话)\n"
        "Each loop segment has a small monument:\n"
        "  - 对话: speech bubble monument\n"
        "  - 证据: clipboard monument with checkmarks\n"
        "  - 训练卡: stack of cards monument\n"
        "  - 验收: stamp monument (same brass stamp from feat-verify)\n\n"

        "[BACKGROUND] Soft warm slate with floating question marks and answer marks in chalk.\n\n"

        "[LIGHTING] Key from upper-center (trainer face bright). Rim gold from flashcard edges. "
        "Soft volumetric haze through loop track.\n\n"

        "[PALETTE] indigo-700 #4338CA, chalk-green #86EFAC, gold-500 #F59E0B, cream-bg #F5F3FF, "
        "slate-700 #334155 (faded silhouettes).\n\n"

        "[TEXTURE] Sharp focus on Trainer girl face and flashcard. Loop track has visible chalk texture. "
        "Silhouettes have painterly soft edges.\n\n"

        "[NEGATIVE CONSTRAINTS] NO to-do list appearance (it's a loop, not a queue). "
        "NO checkbox UI. NO photorealism."
    ),

    # 4. feat-youwrite
    "feat-youwrite": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 1600x900 (16:9). Developer's hands + laptop occupy lower 1/3. "
        "Trainer girl at middle 1/3. Banner at top 1/3. Crossed-out button at left, "
        "checkmark button at right.\n\n"

        "[CHARACTERS] OVER-THE-SHOULDER perspective. Foreground: a developer's hands typing on a "
        "laptop keyboard, code on screen is clearly HUMAN-WRITTEN (with imperfect formatting, "
        "real typos being fixed, comments in natural language). Screen shows:\n"
        "  def search_users(query: str):\n"
        "      # TODO: 加边界检查\n"
        "      return db.query(...)\n\n"
        "Behind the developer, standing 3 meters back with hands behind her back: Trainer girl in "
        "3/4 rear view, watching. Her stopwatch-whip is tucked into her belt, not in use. "
        "She has round glasses on, expression calm and patient. A small golden badge on her jacket "
        "reads 'coach-first mode'. Must match trainer.png reference exactly.\n\n"

        "[BUTTONS] To her LEFT: a large red X over a button labeled 'AI: write code'. "
        "To her RIGHT: a green checkmark on a button labeled 'AI: review code'.\n\n"

        "[BANNER] Above the scene, a banner reads:\n"
        "  我读你写。我教你懂。我替你——不写。\n"
        "  I read what you write. I teach you to understand. I write for you — never.\n\n"

        "[LIGHTING] Warm desk lamp from upper-right lighting the developer's hands. Cool ambient on "
        "Trainer girl. Subtle gold rim on her shoulders.\n\n"

        "[PALETTE] slate-900 #0F172A (laptop screen), indigo-700 #4338CA (her silhouette), "
        "success #10B981 (right button), danger #EF4444 (left button X), cream-bg #F5F3FF (background).\n\n"

        "[TEXTURE] Realistic screen glow on developer's face (visible in the edge of frame). "
        "Painterly brushwork on Trainer girl's jacket. Banner has visible canvas weave.\n\n"

        "[NEGATIVE CONSTRAINTS] NO AI typing visible. NO ghost-text / autocompletion bubbles. "
        "NO diff comparison. NO photorealism on character."
    ),

    # 5. feat-skills
    "feat-skills": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 1600x900 (16:9). Backpack and Trainer girl at lower 1/3. "
        "Cards spiraling up forming '$' at top 1/3.\n\n"

        "[CHARACTERS] Trainer girl with backpack open, both hands holding the open top. From the "
        "backpack, 6 glowing prompt cards fly upward in a swirling spiral, forming a giant '$' "
        "shape at the top of the canvas. Must match trainer.png reference exactly.\n\n"

        "[CARDS] Each card has a brass trigger-word tag at top:\n"
        "  1. $explain   → '用三层递进解释这个概念'\n"
        "  2. $review    → '按 FSRS 节奏给我复习清单'\n"
        "  3. $refactor  → '先讲思路再改代码'\n"
        "  4. $plan      → '拆成可验收的阶段'\n"
        "  5. $debug     → '先复现再定位'\n"
        "  6. $summarize → '三段式总结 + 可验证点'\n"
        "Cards have handwritten prompt text on them (partially visible, intentionally blurry for "
        "that 'shared as text' feel). Small 'data' icon (a JSON bracket { }) stamped on each card "
        "corner — emphasizing 'pure data, no code execution'. A small handwritten note tucked into "
        "one card reads: '// 分享即文本，导入即 prompt'.\n\n"

        "[BACKGROUND] Soft chalkboard with faint text:\n"
        "  no eval · no Function() · prompt ≤ 4000 chars\n\n"

        "[LIGHTING] Key from the backpack interior — warm gold glow. Cards catch and reflect this "
        "glow. Trainer girl face lit from below (warm).\n\n"

        "[PALETTE] indigo-700 #4338CA, gold-300 #FCD34D (card highlights), gold-500 #F59E0B "
        "(trigger tags), slate-900 #0F172A (chalkboard), cream-bg #F5F3FF.\n\n"

        "[TEXTURE] Cards have visible impasto highlights on edges. Backpack interior has soft "
        "volumetric glow. Painterly brushwork on Trainer girl's hands.\n\n"

        "[NEGATIVE CONSTRAINTS] NO code visible on cards (only prompts). NO executable-looking icons. "
        "NO photorealism."
    ),

    # 6. feat-speed
    "feat-speed": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 1600x900 (16:9). Trainer girl at upper-center holding stopwatch. "
        "Racetrack at lower 2/3. Lanes horizontal. Finish line at right.\n\n"

        "[CHARACTERS] Trainer girl at center holding a large brass stopwatch raised high, her eyes "
        "focused on the watch face. Stopwatch hands at 12 o'clock, ready to time. Must match "
        "trainer.png reference exactly.\n\n"

        "[RACETRACK] BENEATH her: a racetrack drawn in chalk on the ground, four lanes, four "
        "stylized 'gateway runner' figures (small abstract chibi robots with brand-colored uniforms) "
        "at the starting blocks:\n"
        "  Lane 1: OpenAI uniform (white with gold), mid-stride\n"
        "  Lane 2: Anthropic uniform (black with copper), mid-stride\n"
        "  Lane 3: Gemini uniform (rainbow gradient), mid-stride\n"
        "  Lane 4: Custom relay uniform (gray with circuit pattern), trailing\n\n"

        "[FINISH LINE] Finish line banner:\n"
        "  🏁 Use fastest (42ms)\n"
        "Below finish line, 4 colored badges:\n"
        "  🟢 42ms   (Lane 1 — gold)\n"
        "  🟢 87ms   (Lane 2 — gold)\n"
        "  🟡 312ms  (Lane 3 — amber)\n"
        "  ⚫ timed out (Lane 4 — slate)\n\n"

        "[DETAIL] On the racetrack ground, chalk dust marks showing the 'warm-up request' discarded "
        "first (drawn as faded footprints).\n\n"

        "[BACKGROUND] Soft slate background with faint dotted lines (DNS/CDN cold start metaphor).\n\n"

        "[LIGHTING] Key from upper-left. Lane 1 and 2 have gold rim light (fast). Lane 3 has amber rim. "
        "Lane 4 has cool gray rim.\n\n"

        "[PALETTE] indigo-700 #4338CA, gold-500 #F59E0B, success #10B981, warning #F59E0B, slate-700 #334155.\n\n"

        "[TEXTURE] Sharp focus on stopwatch. Visible motion blur on the runners. Chalk dust visible on track.\n\n"

        "[NEGATIVE CONSTRAINTS] NO real brand logos on uniforms (only color coding). "
        "NO photorealistic stopwatch. NO photorealism on characters."
    ),

    # 7. feat-library
    "feat-library": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 1600x900 (16:9). Three zones equal width (33% each). "
        "Trainer girl at the boundary of Zone 1 and Zone 2, center vertical line.\n\n"

        "[CHARACTERS] Trainer girl standing at center, hands behind back, looking at three "
        "distinct zones arranged left-to-right. Must match trainer.png reference exactly.\n\n"

        "[ZONE 1 — WORKSPACE] (left third): wooden bookshelf filled with project code files "
        "(visible filenames like main.py, App.tsx, schema.sql). Warm wood texture. Open book on "
        "top shelf showing a glowing search result.\n\n"

        "[ZONE 2 — SANDBOX] (middle third): glass cabinet with brass railings, containing uploaded "
        "resource files (PDF, DOCX, MD, images) suspended in soft gold light. Tier A label on glass: "
        "'Rich preview · CodeMirror · PDF.js · DOCX'. A small chalkboard sign on cabinet reads: "
        "'for processing only, not your project'.\n\n"

        "[ZONE 3 — TRASH] (right third): black ceramic bin with brass lid, lid half-open. Inside, "
        "a crumpled paper with a faint Trainer stamp visible — labeled 'recoverable'. A small golden "
        "arrow above the bin points back toward Zone 1, with text 'restore within 30 days'.\n\n"

        "[ARROW] Above the three zones, a curved arrow connecting all three, labeled "
        "'upload → index → search → preview → recycle → restore'.\n\n"

        "[LIGHTING] Zone 1: warm wood lighting #F5E6D3. Zone 2: cool gold glow #F59E0B. "
        "Zone 3: cool slate #475569 with a small gold accent on the recoverable paper.\n\n"

        "[PALETTE] wood-brown #78350F, glass-blue #7DD3FC, gold-500 #F59E0B, slate-700 #334155, cream-bg #F5F3FF.\n\n"

        "[TEXTURE] Visible wood grain on Zone 1. Glass reflection on Zone 2. Ceramic texture on Zone 3.\n\n"

        "[NEGATIVE CONSTRAINTS] NO filesystem tree visualization. NO actual PDFs visible. NO photorealism."
    ),

    # 8. diagram-agent-loop
    "diagram-agent-loop": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Trainer girl at center. Gold ribbon right. "
        "Indigo ring left. Rule of thirds.\n\n"

        "[CHARACTERS] Trainer girl standing at center, three-quarter front view, expression focused. "
        "Must match trainer.png reference exactly.\n\n"

        "[RIBBONS] TWO RIBBONS flow from her body outward:\n"
        "  - GOLD ribbon (visible text flow) flowing RIGHT toward 'USER' label, with chalk text sample: 'Let me think...'\n"
        "  - INDIGO ribbon (tool call flow) flowing LEFT toward a circular TOOL RING\n\n"

        "[TOOL RING] The TOOL RING is a brass circle with 6 tool boxes hanging from it, each labeled:\n"
        "  📖 read_file\n"
        "  🔍 diagnostics\n"
        "  🔎 search\n"
        "  ✏️ edit\n"
        "  📋 plan\n"
        "  ⚖️ evaluate\n\n"

        "[CIRCUIT BREAKER] A RED CIRCUIT BREAKER sits on the ring at 11 o'clock position, glowing angry red, "
        "with text:\n"
        "  'identical_tool_streak ≥ 2 → break'\n\n"

        "[SELF-HEAL] A small self-healing icon at 5 o'clock position:\n"
        "  'prompt_overflow → compress & resume'\n\n"

        "[BACKGROUND] Soft indigo-950 #1E1B4B with subtle grid pattern (the 'token grid' the loop navigates).\n\n"

        "[LIGHTING] Key from upper-center. Gold ribbon self-illuminates. Indigo ring has brass rim glow. "
        "Red circuit breaker pulses.\n\n"

        "[PALETTE] indigo-950 #1E1B4B, gold-300 #FCD34D, indigo-500 #6366F1, danger #EF4444, "
        "success #10B981 (self-heal icon), cream-bg.\n\n"

        "[TEXTURE] Ribbons have visible silk-like impasto. Tool ring has brushed-metal texture. "
        "Sharp focus on circuit breaker.\n\n"

        "[NEGATIVE CONSTRAINTS] NO flowchart boxes. NO step numbers. NO photorealism."
    ),

    # 9. diagram-snapshot-sync
    "diagram-snapshot-sync": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Envelope dominant left. Sundial + webview window right. "
        "Diagonal flow from envelope → sundial → webview.\n\n"

        "[CHARACTERS] No main characters. Show 5 small harness girl silhouettes (cursor, claude, "
        "codex, devin, qoder) peering out from the webview window at the right.\n\n"

        "[ENVELOPE] A GIANT ENVELOPE occupies left 2/3 of canvas, sealed with brass wax stamp 'WS' "
        "(Workbench Snapshot). The envelope is semi-transparent indigo, revealing inside a 31-piece "
        "jigsaw puzzle assembled together — each piece labeled with a field name in tiny chalk text:\n"
        "  Top row: messages | profile | plan | global_plan | project_plan_link | current_task\n"
        "  Mid row: evaluation | memory | provider | coaching_state | learner_state | teaching_decision\n"
        "  Bot row: affect_state | tone_decision | implementation_guide | project_ideas | review_queue_summary | next_review_due\n"
        "  ... (continue to 31 pieces)\n\n"

        "[SUNDIAL] Beside the envelope (right 1/3): a SUNDIAL on a stone pedestal, the gnomon shadow "
        "pointing at a brass plate inscribed: 'snapshot_revision: 42'.\n\n"

        "[WEBVIEW WINDOW] From the sundial, a golden light beam shoots RIGHT toward a small 'WEBVIEW' "
        "window frame, inside which 5 small harness girl silhouettes (cursor, claude, codex, devin, "
        "qoder) peer out, all looking at the same envelope — meaning they all render from the same "
        "single source of truth.\n\n"

        "[LIGHTING] Envelope has internal indigo glow (the data). Sundial shadow is the gold accent. "
        "Webview window has warm light.\n\n"

        "[PALETTE] indigo-950 #1E1B4B, gold-500 #F59E0B (sundial + light beam), cream-bg #F5F3FF, slate-700 #334155.\n\n"

        "[TEXTURE] Envelope wax has visible impasto. Puzzle pieces have subtle cardboard texture. "
        "Sundial stone has visible grain.\n\n"

        "[NEGATIVE CONSTRAINTS] NO JSON tree visualization. NO API endpoint rectangles. NO photorealism."
    ),

    # 10. diagram-authority-ladder
    "diagram-authority-ladder": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Staircase diagonal. Trainer girl at lower-left. "
        "Wall at upper-right. Red rope at upper-middle.\n\n"

        "[CHARACTERS] Trainer girl stands at the BOTTOM (step 1), holding a brass key labeled 'ANNOTATE' — "
        "her key only fits steps 1-2. Must match trainer.png reference exactly.\n\n"

        "[STAIRCASE] A STONE STAIRCASE rising from lower-left to upper-right, 6 steps, each step carved "
        "with a level name in brass letters:\n"
        "  Step 1 (lowest): INSPECT    — pale cream, lit\n"
        "  Step 2: ANNOTATE            — pale green, lit\n"
        "  Step 3: REORGANIZE          — gray, dim\n"
        "  Step 4: GENERATE            — gray, dim\n"
        "  Step 5: APPLY               — slate, darker\n"
        "  Step 6 (highest): DESTRUCTIVE — red stone, dim\n\n"

        "[WALL] At the TOP of the staircase: a BRICK WALL spanning the upper edge of canvas, bricks "
        "inscribed with 'REMOTE / UNTRUSTED = LOCKED'. A single keyhole in the wall with no key visible.\n\n"

        "[RED ROPE] At step 6, a red rope across the stair with brass sign:\n"
        "  'TRASH ONLY'\n"
        "  'no delete · only move to <root>/.trash/<ts>/'\n\n"

        "[GLOW] The whole staircase has a soft INDIGO GLOW at the bottom (Trainer's zone), fading to "
        "COLD SLATE at the top (forbidden zone).\n\n"

        "[LIGHTING] Step 1-2: warm gold rim. Step 3+: progressively cooler. Wall: shadowy. "
        "Red rope: ominous red rim.\n\n"

        "[PALETTE] indigo-500 #6366F1, gold-500 #F59E0B (Trainer), success #10B981 (steps 1-2), "
        "danger #EF4444 (step 6 + rope), slate-900 (wall).\n\n"

        "[TEXTURE] Stone steps have visible chisel marks. Wall has brick texture. Rope has woven fiber detail.\n\n"

        "[NEGATIVE CONSTRAINTS] NO permission matrix table. NO checkbox UI. NO photorealism."
    ),

    # 11. diagram-handoff-phases
    "diagram-handoff-phases": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Track horizontal, 5 equal lanes. "
        "Trainer mid-action at lane 2-3 boundary. Gate at lane 3 entrance. Rule of thirds.\n\n"

        "[CHARACTERS] Trainer girl is mid-sprint between Lane 2 and Lane 3, in dynamic action pose, "
        "hair flying, stopwatch-whip in hand trailing behind. Must match trainer.png reference exactly.\n\n"

        "[TRACK] A FIVE-LANE TRACK viewed from 3/4 perspective, lanes labeled:\n"
        "  Lane 1: LEARN    — sky blue #7DD3FC\n"
        "  Lane 2: TRY      — amber #F59E0B\n"
        "  Lane 3: VERIFY   — green #10B981\n"
        "  Lane 4: REFLECT  — lavender #A78BFA\n"
        "  Lane 5: RETURN   — gold #FCD34D\n\n"

        "[GATE] At the entrance to Lane 3 (VERIFY): a GATE with brass arch, gate has 6 small nameplates "
        "on it listing the trusted verification sources:\n"
        "  ✓ automated_test\n"
        "  ✓ evaluator\n"
        "  ✓ ide_current_file\n"
        "  ✓ server_evaluator\n"
        "  ✓ test_runner\n"
        "  ✓ verification_service\n\n"

        "[REJECTED] Below the 6 names, a 7th nameplate is crossed out in red:\n"
        "  ✗ manual_claim\n"
        "A faint 'untrusted claim' ghost figure is being turned away at the gate by a brass gatekeeper.\n\n"

        "[LANE MARKERS] Each lane has a small visual marker:\n"
        "  LEARN: open book on ground\n"
        "  TRY: glowing pencil\n"
        "  VERIFY: brass stamp\n"
        "  REFLECT: round mirror\n"
        "  RETURN: golden home plate\n\n"

        "[LIGHTING] Key from upper-right. Lane colors self-illuminate. Gate has brass glow.\n\n"

        "[PALETTE] sky-blue #7DD3FC, amber #F59E0B, success #10B981, lavender #A78BFA, "
        "gold-300 #FCD34D, danger #EF4444.\n\n"

        "[TEXTURE] Track has lane-line texture. Gate has brushed metal. Trainer has motion blur.\n\n"

        "[NEGATIVE CONSTRAINTS] NO arrow flowchart. NO state diagram. NO photorealism."
    ),

    # 12. diagram-provider-protocols
    "diagram-provider-protocols": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Trainer girl center-left. 4 open doors center-right "
        "(evenly spaced). 5th boarded door far right. Rule of thirds.\n\n"

        "[CHARACTERS] Trainer girl at center, holding 4 distinct keys fanned out. Must match "
        "trainer.png reference exactly.\n\n"

        "[KEYS] Key 1: BRASS with O-shaped bow → 'OpenAI Chat Completions'\n"
        "        Key 2: COPPER with feather bow → 'Anthropic Messages'\n"
        "        Key 3: IRIDESCENT with gem bow → 'Gemini Native'\n"
        "        Key 4: SILVER with /responses bow → 'OpenAI Responses'\n\n"

        "[DOORS] In front of her: 4 DOORS, each glowing with the key's color:\n"
        "  Door 1: open, golden light spilling out\n"
        "  Door 2: open, copper light spilling out\n"
        "  Door 3: open, iridescent light spilling out\n"
        "  Door 4: open, silver light spilling out\n\n"

        "[REJECTED DOOR] To the FAR RIGHT: a 5th door, BOARDED UP with wooden planks and nails, "
        "red sign reading:\n"
        "  'REJECTED'\n"
        "  'Gateway fingerprint: unknown'\n"
        "  'Trainer will not assume OpenAI-compatible'\n"
        "A small ghost silhouette stands before the 5th door, head shaking 'no'.\n\n"

        "[CHALKBOARD] Above the doors, a thin chalkboard label:\n"
        "  '5 protocols · 1 binding · 0 assumed defaults'\n\n"

        "[LIGHTING] Each door has its own key-color glow. 5th door is in shadow with red rim light "
        "from the rejection sign.\n\n"

        "[PALETTE] gold #F59E0B, copper #B45309, iridescent (multi-hue), silver #94A3B8, "
        "danger #EF4444 (5th door), cream-bg.\n\n"

        "[TEXTURE] Keys have brushed metal. Doors have wood grain + paint. 5th door has rough plank wood.\n\n"

        "[NEGATIVE CONSTRAINTS] NO API endpoint URL list. NO curl examples. NO photorealism."
    ),

    # 13. diagram-workspace-zones
    "diagram-workspace-zones": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Three doors equal width. Trainer girl at center "
        "door threshold. Curved arrow above.\n\n"

        "[CHARACTERS] Trainer girl stands in front of the SANDBOX door (center), hands on the brass "
        "door handle, looking toward the workspace (left) with a slight nod, while her peripheral "
        "vision includes the trash door (right). Must match trainer.png reference exactly.\n\n"

        "[LEFT DOOR — WORKSPACE] warm wooden door, open, inside visible:\n"
        "  - Code editor with project files\n"
        "  - Wooden bookshelf\n"
        "  - Warm lamp glow\n\n"

        "[CENTER DOOR — SANDBOX] glass door with brass frame, half-transparent, inside visible:\n"
        "  - PDFs and DOCX floating in soft gold light\n"
        "  - 'for processing only, not your project' chalkboard sign\n"
        "  - Faint brass railing around the interior\n\n"

        "[RIGHT DOOR — TRASH] iron door with small window, half-open, inside visible:\n"
        "  - Crumpled papers in a black bin\n"
        "  - A hand reaching out from inside the bin holding a paper with a Trainer stamp — labeled 'RESTORE'\n"
        "  - 30-day countdown chalk on the wall\n\n"

        "[CURVED ARROW] Above the three doors, a curved arrow:\n"
        "  upload → index → preview → recycle → restore\n\n"

        "[LIGHTING] Left door: warm wood glow. Center door: cool gold interior. "
        "Right door: cool slate with one warm accent (the reaching hand).\n\n"

        "[PALETTE] wood-brown #78350F, glass-blue #7DD3FC, slate-900 #0F172A, gold-500 #F59E0B "
        "(center accent), cream-bg.\n\n"

        "[TEXTURE] Wood grain on left door. Glass reflection on center door. Iron texture on right door.\n\n"

        "[NEGATIVE CONSTRAINTS] NO folder tree. NO file icons. NO photorealism."
    ),

    # 14. diagram-evidence-loop
    "diagram-evidence-loop": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Disk centered, 70% of canvas. Mini Trainer at center. "
        "Quadrants labeled. Rule of thirds.\n\n"

        "[CHARACTERS] A miniature Trainer girl stands at the disk's center, hands on a brass handle, "
        "pushing the disk to rotate clockwise. Must match trainer.png reference exactly.\n\n"

        "[DISK] A LARGE CIRCULAR DISK viewed from 3/4 angle, divided into 4 quadrants by brass arches:\n"
        "  Top quadrant (12-3 o'clock): 对话   — speech bubble monument\n"
        "  Right quadrant (3-6):        证据   — clipboard with checkmarks\n"
        "  Bottom quadrant (6-9):        训练卡 — stack of brass-edged cards\n"
        "  Left quadrant (9-12):        验收   — brass stamp (same as feat-verify)\n\n"

        "[DIRECTION] Outside the disk, a golden ring of small arrows showing the clockwise direction.\n\n"

        "[TAGS] Each quadrant has a small chalkboard tag with phase name:\n"
        "  '对话 · conversation'\n"
        "  '证据 · evidence'\n"
        "  '训练卡 · training card'\n"
        "  '验收 · verification'\n\n"

        "[BACKGROUND] Faded silhouettes of 3 harness girls (cursor, claude, codex) standing at the "
        "perimeter, watching the disk rotate. Their forms suggest 'we generate, Trainer orchestrates'.\n\n"

        "[LIGHTING] Each quadrant has its own color glow. Disk has brass rim light. "
        "Mini Trainer has indigo spotlight from above.\n\n"

        "[PALETTE] gold #FCD34D (对话), lavender #A78BFA (证据), sky-blue #7DD3FC (训练卡), "
        "success #10B981 (验收), indigo-700 #4338CA (Trainer).\n\n"

        "[TEXTURE] Disk surface has brass brushed metal. Quadrant monuments have stone texture. "
        "Silhouettes have painterly soft edges.\n\n"

        "[NEGATIVE CONSTRAINTS] NO linear arrow flowchart. NO step numbers. NO photorealism."
    ),

    # 15. diagram-governance-pure
    "diagram-governance-pure": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Library centered. Three figures at 7/5/3 o'clock "
        "positions. Rule of thirds.\n\n"

        "[CHARACTERS] Three figures stand OUTSIDE the library at equidistant points, each holding one "
        "corner of a glowing thread that connects back to the central book:\n"
        "  LEFT figure (HOST): wearing dark suit with VS Code-blue pocket square, holding a small "
        "    toolbox labeled 'extension/' in one hand, the other hand holding the thread.\n"
        "  CENTER figure (WEBVIEW): wearing casual hoodie with React atom symbol on chest, holding "
        "    a browser window frame in one hand (the window shows a translucent webview rendering), "
        "    other hand holding the thread.\n"
        "  RIGHT figure (TEST): wearing lab coat with brass goggles on forehead, holding a test "
        "    tube rack with 3 tubes labeled '159 pytest · 220 node · 200 matrix' in one hand, "
        "    other hand holding the thread.\n\n"

        "[LIBRARY] Central: a CIRCULAR LIBRARY READING ROOM with warm brass lighting. At the room's "
        "center on a stone pedestal: a GIANT BOOK with indigo cloth binding and gold-leaf title embossed:\n"
        "  'shared/governance'\n"
        "  '24 pure functions'\n"
        "  '0 side effects'\n"
        "  'host + webview + test'\n\n"

        "[CHALKBOARD] Behind the central book, a chalkboard lists:\n"
        "  planGovernance · trainingHandoffGovernance · reviewQueueGovernance\n"
        "  · workspaceAuthority · suggestedActionGovernance · ...\n"
        "Each name has a small ✓ next to it.\n\n"

        "[LIGHTING] Library has warm interior light. Each figure has rim light matching their role "
        "color: slate for HOST, indigo for WEBVIEW, gold for TEST.\n\n"

        "[PALETTE] indigo-950 #1E1B4B (book), gold-500 #F59E0B (book + TEST), slate-700 #334155 "
        "(HOST), indigo-500 #6366F1 (WEBVIEW), cream-bg #F5F3FF.\n\n"

        "[TEXTURE] Book has leather binding texture. Library floor has marble. Figures have painterly brushwork.\n\n"

        "[NEGATIVE CONSTRAINTS] NO dependency graph. NO module list as text. NO photorealism."
    ),

    # 16. diagram-fsrs-rhythm
    "diagram-fsrs-rhythm": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Hourglass dominant center. Lever at right. "
        "Chalkboard background.\n\n"

        "[CHARACTERS] No main character. Show 3 small concept cards (curly brace, async arrow, "
        "SQL JOIN) tumbling through the hourglass neck.\n\n"

        "[HOURGLASS] A GIANT HOURGLASS standing 80% of canvas height, made of translucent indigo "
        "glass with brass frame.\n"
        "  TOP half of hourglass: piled high with cards having RED edges (labels like 'due today', "
        "  'stale'). Falling down: individual cards tumbling through the neck, each card a concept "
        "  symbol (curly brace, async arrow, SQL JOIN).\n"
        "  BOTTOM half: cards have GREEN edges (labels like 'mastered', 'verified'). A few cards "
        "  at the bottom have GOLD halos ('verified by current file').\n\n"

        "[LEVER] NEXT TO the hourglass: a brass LEVER switch on a stone pedestal, labeled:\n"
        "  '流状态抑制'\n"
        "  'skip review during active thread'\n"
        "  'do not disturb flow'\n"
        "The lever is currently in the OFF position (not pressed), suggesting the default is to "
        "review, but available when needed.\n\n"

        "[BASE PLAQUE] On the hourglass base, brass plaque inscribed:\n"
        "  '1d · 3d · 7d · 14d · 30d'\n"
        "  'FSRS rhythm'\n\n"

        "[BACKGROUND] Behind the hourglass, soft chalkboard showing a faint forgetting curve "
        "(exponential decay).\n\n"

        "[LIGHTING] Top of hourglass: warm rim (pending urgency). Bottom: gold rim (mastery glow). "
        "Lever has subtle red accent.\n\n"

        "[PALETTE] danger #EF4444 (top cards), success #10B981 (bottom cards), gold-500 #F59E0B "
        "(verified halos), indigo-950 #1E1B4B (glass), brass #B45309 (frame), cream-bg.\n\n"

        "[TEXTURE] Glass has subtle refraction. Cards have paper texture. Stone pedestal has chisel marks.\n\n"

        "[NEGATIVE CONSTRAINTS] NO calendar UI. NO scheduling table. NO photorealism."
    ),

    # 17. diagram-i18n-locale
    "diagram-i18n-locale": (
        STYLE_LOCK + "\n\n"

        "[COMPOSITION] Canvas 2400x1350 (16:9). Round table centered. 8 chairs at clock positions. "
        "Center bubble at center. Rule of thirds.\n\n"

        "[CHARACTERS] Each chair has a mini Trainer girl silhouette (same indigo short bob, simplified) "
        "holding the flag. Must reference trainer.png silhouette.\n\n"

        "[TABLE] A LARGE ROUND TABLE viewed from 3/4 angle, with 8 chairs evenly spaced around it. "
        "Each chair has a small brass nameplate with a flag pattern (not real flags — abstract color "
        "stripes suggesting each language):\n"
        "  1. zh-CN — red + gold stripes (left upper)\n"
        "  2. en-US — navy + white stripes\n"
        "  3. es-ES — red + yellow stripes\n"
        "  4. fr-FR — blue + white + red stripes\n"
        "  5. de-DE — black + red + gold stripes\n"
        "  6. ja-JP — white + red dot\n"
        "  7. ko-KR — white + taegeuk symbol (abstract)\n"
        "  8. pt-BR — green + yellow + blue\n\n"

        "[CENTER BUBBLE] CENTER of the table: a glowing speech bubble showing the same phrase in "
        "8 different scripts stacked:\n"
        "  '你写,我教,我们一起长。'\n"
        "  'You write, I teach, we grow together.'\n"
        "  'Tú escribes, yo enseño, crecemos juntos.'\n"
        "  ... (all 8 languages, chalk-white text on slate-900)\n\n"

        "[CHALKBOARD] A small chalkboard at table edge:\n"
        "  '600+ keys · 8 languages · 0 broken UI'\n\n"

        "[LIGHTING] Each language has its own subtle accent color glow. Center bubble has warm gold rim.\n\n"

        "[PALETTE] Multi-language accents (red/gold/navy/yellow/blue/etc.), indigo-950 #1E1B4B "
        "(Trainer silhouettes), gold-500 #F59E0B (center bubble), cream-bg.\n\n"

        "[TEXTURE] Table has wood grain. Chairs have brass + velvet. Flags have fabric texture.\n\n"

        "[NEGATIVE CONSTRAINTS] NO actual country flags. NO real flag emoji. NO photorealism."
    ),
}


# Map: which portrait refs each image needs
REF_MAP = {
    "feat-verify":            ["trainer", "cursor"],
    "feat-memory":            ["trainer"],
    "feat-training":          ["trainer", "cursor", "codex", "claude-code"],
    "feat-youwrite":          ["trainer"],
    "feat-skills":            ["trainer"],
    "feat-speed":             ["trainer"],
    "feat-library":           ["trainer"],
    "diagram-agent-loop":     ["trainer"],
    "diagram-snapshot-sync":  ["cursor", "claude-code", "codex", "devin", "qoder"],
    "diagram-authority-ladder": ["trainer"],
    "diagram-handoff-phases": ["trainer"],
    "diagram-provider-protocols": ["trainer"],
    "diagram-workspace-zones": ["trainer"],
    "diagram-evidence-loop":  ["trainer", "cursor", "claude-code", "codex"],
    "diagram-governance-pure": [],
    "diagram-fsrs-rhythm":    [],
    "diagram-i18n-locale":    ["trainer"],
}


# Map: target size for each image
SIZE_MAP = {
    "feat-verify":            "1600x900",
    "feat-memory":            "1600x900",
    "feat-training":          "1600x900",
    "feat-youwrite":          "1600x900",
    "feat-skills":            "1600x900",
    "feat-speed":             "1600x900",
    "feat-library":           "1600x900",
    "diagram-agent-loop":     "2400x1350",
    "diagram-snapshot-sync":  "2400x1350",
    "diagram-authority-ladder": "2400x1350",
    "diagram-handoff-phases": "2400x1350",
    "diagram-provider-protocols": "2400x1350",
    "diagram-workspace-zones": "2400x1350",
    "diagram-evidence-loop":  "2400x1350",
    "diagram-governance-pure": "2400x1350",
    "diagram-fsrs-rhythm":    "2400x1350",
    "diagram-i18n-locale":    "2400x1350",
}


def gen_one(name: str):
    prompt = PROMPTS[name]
    target_size = SIZE_MAP[name]
    out_path = OUT / f"{name}@2x.png"

    refs = []
    for char_id in REF_MAP[name]:
        ref_path = PORTRAITS / f"{char_id}.png"
        if ref_path.exists():
            refs.append(str(ref_path))
        else:
            print(f"!!! Missing reference portrait: {ref_path}")

    cmd = [
        "python3",
        str(SCRIPT),
        "--prompt", prompt,
        "--model", "gpt-image-2",
        "--workflow", "normal",
        "--aspect-ratio", "16:9",
        "--target-size", target_size,
        "--quality", "high",
        "--generation-mode", "standard",
        "--output-format", "png",
        "--output-path", str(out_path),
    ]
    for ref in refs:
        cmd.extend(["--reference-image", ref])

    print(f"\n>>> generating {name} ({target_size}) with {len(refs)} references")
    for r in refs:
        print(f"    {r}")
    print(f">>> prompt length: {len(prompt)} chars")

    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout[-1500:])
    if res.returncode != 0:
        print(f"!!! FAILED for {name}\n{res.stderr[-1500:]}")
        return False

    if out_path.exists():
        size_mb = out_path.stat().st_size / (1024 * 1024)
        print(f">>> {name} generated: {out_path} ({size_mb:.1f} MB)")
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated names to limit generation")
    args = ap.parse_args()

    targets = list(PROMPTS.keys())
    if args.only:
        targets = [n.strip() for n in args.only.split(",") if n.strip() in PROMPTS]

    print(f">>> generating {len(targets)} images: {', '.join(targets)}")

    failures = []
    for name in targets:
        ok = gen_one(name)
        if not ok:
            failures.append(name)

    if failures:
        print(f"\n!!! {len(failures)} failures: {failures}")
        sys.exit(1)
    print("\n>>> all generations done")


if __name__ == "__main__":
    main()
