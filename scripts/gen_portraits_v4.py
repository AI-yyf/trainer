#!/usr/bin/env python3
"""Step 1: generate solo portrait of each character on plain background.
Step 2: use these portraits as --reference-image=reference inputs to compose the hero banner.

STYLE (v4 · AI娘 moe-girl, matches the linux.do AI娘 character-card series):
- Normal anime-girl proportions (~6.5-7 heads), NOT chibi
- Character-introduction-card framing, thigh-up, plain warm paper background
- Large glossy anime eyes, small nose, soft lips, refined bishoujo face
- Ornate brand-colored outfits (Victorian / academy / lolita elements)
- Established community designs folded in:
    * claude-code  <- Claude娘  (orange hair, sunflower, cream victorian + black corset)
    * zcode        <- GLM娘     (black hair, witch hat + Z sleep mask, gothic lolita, bells)

Usage:
    python3 scripts/gen_portraits_v4.py                # all 12
    python3 scripts/gen_portraits_v4.py --only zcode   # one character
"""

import argparse, subprocess, sys, time
from pathlib import Path

SCRIPT = Path.home() / ".agents/skills/dora-image/scripts/generate_dora_image.py"
OUT = Path("/Users/Apple/Desktop/trainer/assets/portraits")
OUT.mkdir(parents=True, exist_ok=True)
STYLE_REF = Path("/Users/Apple/Desktop/trainer/assets/refs/ai_niang_style_ref.jpeg")

# Shared style block — every prompt starts with this.
STYLE = (
    "High-quality Japanese anime illustration, drawn like a character-introduction card from the famous Chinese "
    "AI-girl (AI娘 / 萌娘) fan-art series. "
    "ONE elegant anime girl with normal anime proportions (about 6.5-7 heads tall — NOT chibi, NOT super-deformed), "
    "framed from the knees up, standing centered like a trading-card portrait. "
    "Refined bishoujo face: large glossy anime eyes with layered highlights and colored iris gradient, "
    "small delicate nose, small soft lips, smooth pale skin. "
    "Detailed hair rendered strand by strand with a soft shine and a signature hair ornament. "
    "Ornate elegant outfit themed to her brand color palette, mixing Victorian / academy / lolita elements — "
    "ribbons, corset belts, lace, frills, high collar; her brand emblem appears subtly as embroidery or a brooch. "
    "Clean delicate lineart, soft cel shading blended with gentle airbrush shading, warm soft lighting. "
    "Plain warm off-white paper background (#FAF7F2), generous negative space, no scenery. "
    "No text in the image except the tiny prop labels explicitly listed. "
    "No watermark, no signature, no border, no frame, no photorealism, no 3D render."
)

PORTRAITS = [
    {
        "id": "trainer",
        "prompt": (
            STYLE +
            "TRAINER girl (the protagonist, the coding coach) — a pure 'white moonlight' beauty: pristine, "
            "clean, luminous, like the elegant young teacher everyone remembers. "
            "Hair: completely WHITE (silver-white #F8FAFC) short crisp bob, sleek and capable, with a slight "
            "inward curl at the ends and neatly cut straight bangs swept barely to one side; a single small "
            "indigo hairpin at the side. "
            "Skin: fair porcelain-pale. "
            "Eyes: calm indigo #312E81, gentle and clear. "
            "Slim silver-framed oval glasses on her face. "
            "Outfit: impeccably crisp and capable — a sharply tailored ivory-white long coach coat with clean "
            "minimal lapels over a white high-collar blouse, an indigo #4338CA slim ribbon tie, tailored white "
            "trousers; small indigo FSRS forgetting-curve brooch on the lapel; everything immaculate and elegant. "
            "Prop: she holds a brass stopwatch on a slim brown leather strap in her right hand — the only warm "
            "gold accent against her white ensemble. "
            "Expression: serene, gentle, quietly radiant teacher's smile."
        ),
    },
    {
        "id": "cursor",
        "prompt": (
            STYLE +
            "CURSOR girl, themed to Cursor's official brand: strict monochrome elegance (near-black #1c1c1e, "
            "soft gray-white #edecec, warm beige-gray #cac6be) with a single restrained antique-gold accent "
            "#c08532 — an applied-research-lab aesthetic, calm elite minimalism, never colorful, never playful-cluttered. "
            "Hair: sleek straight black hair with cool gray-white inner streaks, sharp center part, chin-length. "
            "Eyes: smoky gray with one faint gold fleck. "
            "Outfit: impeccably tailored black-and-white ensemble — a structured near-black jacket with asymmetric "
            "white panel lapels (folding like an isometric cube), warm-beige slim skirt, a single thin gold line "
            "trim along the collar; small polished-cube brooch at the collar. "
            "Prop: two translucent monochrome floating monitor panels in front of her labeled 'index.tsx' and "
            "'App.tsx', two small 'tab' speech bubbles drifting beside her head; her right hand hovers mid-air "
            "frozen in a Tab-key press; a tiny price-tag charm reading '$20/mo' dangles from her belt. "
            "Expression: calm, quietly confident, level gaze."
        ),
    },
    {
        "id": "claude-code",
        "prompt": (
            STYLE +
            "CLAUDE CODE girl (a literary coding agent), designed after the classic community Claude-moe-girl look. "
            "Hair: long vivid orange straight hair with full bangs, decorated with a large sunflower hair ornament "
            "on the left side and a small black ribbon. "
            "Eyes: warm amber-gold #D97706. "
            "Outfit: elegant cream-white Victorian blouse with puffed shoulders, a large black ribbon bow at the collar, "
            "a black corset belt with gold buttons over a long cream skirt embroidered with small sunflowers. "
            "Prop: she hugs an old leather-bound book with one arm and holds a black quill pen in the other hand; "
            "a parchment scroll lies at her feet; a white paper tape printed 'Bash is all you need' curls loosely "
            "around her left forearm. "
            "Expression: calm, literary, faintly smug."
        ),
    },
    {
        "id": "codex",
        "prompt": (
            STYLE +
            "CODEX girl, themed to OpenAI's official brand: strict black-and-white discipline, almost no color, "
            "engineered minimalism. "
            "Hair: silky platinum-white waist-length hair. "
            "Eyes: pale gray-blue, serene, gently half-lidded. "
            "Outfit: pure white high-collar dress-bodysuit whose seams are traced with thin BLACK line piping in an "
            "interlocking hexagonal-knot pattern (the OpenAI mark); a black cord belt; white thigh-high boots; "
            "a small matte-black hexagonal-knot brooch. A thin gold O-shaped halo clip floats above her head — "
            "the ONLY warm accent she owns. "
            "Prop: five thin floating round bubbles arc above her open palms — four pale gray labeled "
            "'auto-generated', ONE glowing gold labeled 'verified ✓' (the single gold element); a small door-tag "
            "reading 'do not disturb — async' hangs from her wrist. "
            "Expression: serene, unhurried like a remote colleague who finishes the job while you sleep."
        ),
    },
    {
        "id": "kimi-code",
        "prompt": (
            STYLE +
            "KIMI CODE girl, themed to Kimi / Moonshot AI's official brand: crisp minimalism — deep black with a "
            "single cool blue accent (the blue dot on the K logo), plus her company name meaning 'dark side of the "
            "moon', so the moon is her second motif. Direct, refreshing, no-frills personality. "
            "Hair: very long straight blue-black hair reaching her knees, decorated with a SILVER crescent-moon "
            "hair ornament and one tiny glossy blue-dot hairpin. "
            "Eyes: clear deep blue, direct confident gaze. "
            "Outfit: crisp black academic dress with a white collar, a single blue sash line, subtle silver "
            "constellation embroidery, black tights; tiny blue-dot earrings. "
            "Prop: an absurdly long white scroll unrolls from her hands and trails across the floor behind her "
            "(200K-token context), its far end printed 'to be continued → page 199,999'; a small coin-purse charm "
            "labeled '¥39' hangs at her waist; a small round moon-lantern floats at her side. "
            "Expression: calm, direct, value-for-money confidence."
        ),
    },
    {
        "id": "deepseek",
        "prompt": (
            STYLE +
            "DEEPSEEK girl, designed after the community DeepSeek moe-girl (the beloved 'blue fat fish' whale "
            "girl) in DeepSeek's official ocean-blue #4D6BFE and white. Laid-back, happy-go-lucky, famously the "
            "cheapest and coziest of them all. "
            "Hair: long wavy ocean-blue #4D6BFE hair with a small whale-tail-shaped ahoge sticking up, decorated "
            "with a tiny white whale hairpin. "
            "Eyes: round deep-blue, relaxed and cheerful. "
            "Outfit: oversized white zip hoodie with deepseek-blue cuffs and a small blue whale logo on the chest, "
            "worn loose and comfy over a blue pleated skirt, white sneakers. "
            "Prop: a large blue-rimmed bowl of steaming white rice hugged in one arm with chopsticks (her legendary "
            "love of plain rice); in her other hand she holds out a COMICALLY TINY paper bill labeled '¥2 / 1M "
            "tokens' — the smallest bill in the room; a little blue whale-tail flips out behind her. "
            "Expression: laid-back, contented glutton's smile."
        ),
    },
    {
        "id": "workbuddy",
        "prompt": (
            STYLE +
            "WORKBUDDY girl — a Tencent-family office assistant who walked into the wrong meeting (she is NOT a "
            "coding harness). Satirical corporate-saleslady energy, shrewd and pushy, NOT gentle: the smiling "
            "face of enterprise sales with KPI in her eyes. "
            "Hair: sleek black long hair with a severe side part, ends curled inward, an executive's precision. "
            "Eyes: sharp commercial smile, glasses with faint white glare hiding her eyes (calculating). "
            "Outfit: sharp corporate blazer suit in WeChat-green #07C160 with white blouse, pencil skirt, "
            "high heels; her blazer lapels are PINNED FULL of colorful VIP diamond badges — red, yellow, blue, "
            "green, purple diamond pins like a mobile-sales trophy shelf; a work lanyard whose badge reads "
            "'超级会员 · 试用第14天'. "
            "Prop: she thrusts forward a tablet whose screen shows a chat bubble reading '该文件已过期，请在手机端打开'; "
            "under her other arm a stack of flyers titled '开通会员'. "
            "Expression: flawless professional sales smile that never reaches the eyes."
        ),
    },
    {
        "id": "trae",
        "prompt": (
            STYLE +
            "TRAE girl, themed to Trae's official brand: near-black #0a0b0d techwear darkness energized by a "
            "single NEON-GREEN #32f08c glow accent, with subtle blue-violet #8e80ff secondary glow — young, fast, "
            "'ship faster' ByteDance energy. "
            "Hair: glossy dark-charcoal twin tails tied with neon-green glowing hair rings, straight bangs. "
            "Eyes: bright neon-green, sparkling with energy. "
            "Outfit: sleek black techwear hoodie-dress with glowing neon-green piping along the seams and zipper, "
            "a translucent blue-violet gradient scarf, black sneakers with green soles; a tiny pixel-face hairpin "
            "(two green pixels as eyes) clipped on her bangs. "
            "Prop: she presents a lunch tray with a neatly wrapped lunch box and a small card reading 'for free'; "
            "a tiny coupon ticket flutters in the air beside her, edged with the same neon green; a queue ticket "
            "printed 'A-048' is tucked into her hair ribbon. "
            "Expression: bright, fast, cheerful vendor energy — free lunch, but please wait in line."
        ),
    },
    {
        "id": "devin",
        "prompt": (
            STYLE +
            "DEVIN girl, themed to Devin / Cognition's official brand: monochrome gray engineering — cool grays "
            "#626870 on near-black #171717, no color except the red 'unmerged' stamps, autonomous-machine calm. "
            "Hair: silver-gray long hair, precise low ponytail, a small matte-black hexagonal gear hairclip. "
            "Eyes: cool steel-gray, level and methodical. "
            "Outfit: tailored gray engineer dress with structured black panels joined by visible precision seams, "
            "an interlocking TRIPLE-HEXAGON emblem embroidered in white on the chest, a polished dark-metal "
            "mechanical gauntlet covering her right forearm. "
            "Prop: a small robotic arm rises over her shoulder holding five paper slips, each stamped 'unmerged' "
            "in red — the only red in the image; a work badge on her chest reads 'Autonomous Engineer (in training)'. "
            "Expression: earnest, methodical, doing her very best, a tiny nervous sweat drop."
        ),
    },
    {
        "id": "qoder",
        "prompt": (
            STYLE +
            "QODER girl, themed to Qoder's official brand: near-black #090a0b darkness sharpened by VIOLET "
            "#8b5cf6 accents — spec-driven Alibaba engineering rigor, precise and systematic. "
            "Hair: ash-lavender long hair with razor-sharp side bangs, black hairband, thin rectangular silver "
            "glasses. "
            "Eyes: grey-violet. "
            "Outfit: crisp tailored secretary-style dress in charcoal-black with violet #8b5cf6 piping on the "
            "collar and cuffs, a violet neck ribbon, a document-print skirt patterned with faint lines of contract "
            "text; a small abstract line-drawn Q emblem pin at the collar. "
            "Prop: she carries a thick stack of spec documents titled 'Spec' in her arms, page 47 visible; one "
            "loose page floats in the air beside her printed with 'Evaluation criteria: undefined'; she holds a "
            "rubber stamp reading 'Spec v0.3 草案' ready to stamp. "
            "Expression: precise, bureaucratic, process-obsessed, a tightly controlled smile."
        ),
    },
    {
        "id": "mimo-code",
        "prompt": (
            STYLE +
            "MIMO CODE girl, themed to Xiaomi's official brand and MiMo logo: iconic Xiaomi ORANGE #FF6900 on "
            "clean white, soft rounded-square motifs (the rounded MI app-tile shape), friendly minimal "
            "enthusiast-grade tech — 'born for fever' performance at fan-friendly prices, the Mi-Faithful "
            "cost-performance queen. "
            "Hair: warm white-to-orange gradient long hair (snow-white at the top fading to vivid #FF6900 at the "
            "tips) in a high ponytail with a rounded-square orange hairpin shaped like a soft MI app tile. "
            "Eyes: bright orange #FF6900, round and eager. "
            "Outfit: crisp white techwear dress with orange #FF6900 rounded-square buttons down the front, an "
            "orange ribbon choker, orange-accented white sneakers; a small orange rounded-square badge reading 'MiMo'. "
            "Prop: three hourglasses float in a row in front of her — the middle one is cracked, its glowing orange "
            "sand leaking out and pooling into a tiny sign shaped like the word 'Trainer'. "
            "Expression: flustered pout, cheeks puffed."
        ),
    },
    {
        "id": "codebuddy",
        "prompt": (
            STYLE +
            "CODEBUDDY girl, themed to Tencent CodeBuddy's official brand: friendly blue-to-purple gradient (their "
            "robot mascot's colors) with a fresh teal #32e6b9 accent — approachable 'buddy' warmth, buddy-as-in-"
            "companion. "
            "Hair: soft wavy periwinkle-blue hair fading to lavender at the tips, decorated with a tiny round "
            "robot-head hairclip with glowing teal eyes. "
            "Eyes: warm teal-blue, rounded and friendly. "
            "Outfit: friendly white dress with a blue-to-purple gradient collar and hem band, a teal ribbon at the "
            "chest bow, white sneakers; a soft blue-purple gradient scarf looped around her neck. "
            "Prop: she cuddles a small round penguin plushie wearing a tiny red scarf; a translucent pale-blue "
            "login window floats behind her like a ghost, its single button labeled 'QQ'; a small badge on her "
            "chest reads 'Day 14'. "
            "Expression: cozy, buddy-like, contented smile."
        ),
    },
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="generate a single character by id")
    ap.add_argument("--start", type=int, default=0, help="start index in the portrait list")
    ap.add_argument("--no-style-ref", action="store_true", help="skip the style reference image")
    args = ap.parse_args()

    targets = [p for p in PORTRAITS if (args.only is None or p["id"] == args.only)]
    if args.only and not targets:
        print(f"!!! unknown id: {args.only}")
        sys.exit(1)
    targets = targets[args.start:]

    for i, p in enumerate(targets):
        out_path = OUT / f"{p['id']}.png"
        cmd = [
            "python3", str(SCRIPT),
            "--prompt", p["prompt"],
            "--model", "gpt-image-2",
            "--workflow", "normal",
            "--aspect-ratio", "1:1",
            "--target-size", "2880x2880",
            "--quality", "high",
            "--generation-mode", "standard",
            "--output-format", "png",
            "--output-path", str(out_path),
            "--asset-background", "plain",
        ]
        if not args.no_style_ref and STYLE_REF.exists():
            cmd += ["--reference-image", str(STYLE_REF), "--reference-role", "style"]

        print(f"\n=== [{i+1}/{len(targets)}] {p['id']} ===")
        for attempt in range(2):
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and out_path.exists():
                print(f">>> {p['id']}.png ({out_path.stat().st_size / (1024*1024):.1f} MB)")
                break
            print(f"!!! attempt {attempt+1} failed: {res.stderr[-500:]}")
            if attempt == 0:
                time.sleep(30)
        else:
            print(f"!!! giving up on {p['id']}")
            sys.exit(1)
        time.sleep(3)

    print("\nDone.")


if __name__ == "__main__":
    main()
