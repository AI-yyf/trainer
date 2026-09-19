#!/usr/bin/env python3
"""Step 1: generate solo portrait of each character on plain background.
Step 2: use these portraits as --reference-image=reference inputs to compose the hero banner.

STYLE (v3 · q版/萌系 moe-chibi):
- Head-to-body ratio ~1:1.5 (super-deformed chibi, very tiny head)
- HUGE round eyes filling ~45% of face vertically, three white star highlights per eye
- NO visible nose (or a tiny dot barely there), small mouth with subtle smile
- Round, soft, baby-doll face
- Thick dark outlines (~3-4px, color #1E1B4B)
- Solid flat color blocks, hard cel-shading (DeepSeek-style), no gradients on figure
- Subtle blush on cheeks
- Plain soft warm gradient background
"""

import argparse, json, os, subprocess, sys, time
from pathlib import Path

SCRIPT = Path.home() / ".agents/skills/dora-image/scripts/generate_dora_image.py"
OUT = Path("/Users/Apple/Desktop/trainer/assets/portraits")
OUT.mkdir(parents=True, exist_ok=True)

# Common style prefix used in every prompt — the q版/萌系 moe-chibi baseline
STYLE = (
    "Q-version moe chibi anime girl in classic Japanese kawaii mascot style, like a MoeGirl / 萌娘 / moe-imouto plush figure. "
    "Super-deformed proportions: head is roughly 2/3 of total body height (head-to-body ratio ~1:1.5), tiny body, big round head. "
    "Face is round and baby-doll-like with very soft cheek curve. "
    "HUGE round eyes occupying roughly 45 percent of face height, with very thick upper lash line and very thin lower lash line, "
    "iris takes up most of the eye with small white sclera at the corners, three white star-shaped highlights per eye "
    "(one large upper-left, one medium lower-right, one tiny catchlight). "
    "NO visible nose (nose is omitted or rendered as a barely-visible tiny dot); small simple mouth with a tiny curved smile; "
    "small soft pink blush circles on both cheeks. "
    "Thick dark outlines throughout (3-4px, color #1E1B4B) on every silhouette and interior detail. "
    "Solid flat color blocks, hard cel-shading with one shadow tone and one highlight tone per surface (no soft gradients on the figure), "
    "DeepSeek-style mascot cel-shading. "
    "Plain soft warm gradient background (#F5F3FF at top to #E8E5F5 at bottom). "
    "No background scenery, no props behind the character. "
    "Three-quarter view, character centered, generous negative space around all edges. "
    "Flat cel-shaded figure, no painterly brushstrokes, no photorealism, no 3D render. "
    "No watermark, no signature, no border, no frame."
)

PORTRAITS = [
    {
        "id": "trainer",
        "prompt": (
            STYLE +
            "TRAINER girl (the protagonist). "
            "Hair: indigo short bob with blunt bangs covering the forehead to just above the eyes, "
            "single ahoge pointing upward like a tiny antenna, hair gradient from indigo-950 #1E1B4B at roots to indigo-500 #6366F1 at tips. "
            "Eyes: large round indigo (#312E81) irises. "
            "Outfit: white single-breasted coach jacket with indigo lapels and four brass buttons, "
            "two front flap pockets, small epaulets on shoulders; indigo (#4338CA) athletic V-neck vest underneath; "
            "indigo pleated skirt to mid-thigh; white knee-high socks with two indigo stripes at the top band; brown leather loafers. "
            "Round brass-framed glasses resting on her face. "
            "She holds a stopwatch-whip hybrid in her right hand: a brown leather strap ending in a round brass stopwatch face, the strap coiled loosely. "
            "Her left hand is held up palm-out in a gentle wave gesture, revealing a small FSRS curve tattoo on the back of her left hand. "
            "Pose: standing, body three-quarter turned toward the viewer. "
            "Expression: warm, focused, gentle smile, big eyes slightly squinted with kindness."
        ),
    },
    {
        "id": "cursor",
        "prompt": (
            STYLE +
            "CURSOR girl. "
            "Hair: chestnut-brown short undercut bob with side-swept bangs, color #8B4513. "
            "Eyes: hazel (#92400E). "
            "Outfit: cropped VS Code-blue (#007ACC) zip hoodie over a black tee, black cargo pants, white sneakers. "
            "Round sunglasses pushed up on her forehead reflecting a small indigo silhouette. "
            "Pose: leaning slightly forward, hands raised mid-air as if typing on an invisible keyboard. "
            "Two translucent monitor rectangles float in front of her, one labeled 'index.tsx', one labeled 'App.tsx'. "
            "Three small 'tab' speech bubbles drift around her head. "
            "Expression: confident, slightly cocky, with one eyebrow raised."
        ),
    },
    {
        "id": "claude-code",
        "prompt": (
            STYLE +
            "CLAUDE CODE girl. "
            "Hair: auburn (#7C2D12) short pixie cut with side-swept bangs. "
            "Eyes: deep amber (#B45309). "
            "Outfit: long black duster coat over a charcoal turtleneck, slim black trousers, Chelsea boots. "
            "Pose: writing with one hand holding a black quill pen on a parchment scroll unrolled at her feet, the other hand tucked in her coat. "
            "A long white paper tape unfurls from under her left arm with the text 'Bash is all you need' printed on it; the tape tangles loosely around her own left ankle. "
            "Expression: literary, slightly smug."
        ),
    },
    {
        "id": "codex",
        "prompt": (
            STYLE +
            "CODEX girl. "
            "Hair: honey-blonde (#D97706) waist-length hair, half-up style, thin gold O-shaped halo clip on top of her head. "
            "Eyes: pale sky-blue (#7DD3FC). "
            "Outfit: pure white form-fitting bodysuit with subtle gold piping along the seams. Gold ankle boots. "
            "Pose: arms slightly outstretched, palms up. Five thin floating circle bubbles above her head; "
            "four are pale grey labeled 'auto-generated', one is bright gold labeled 'verified ✓'. "
            "Expression: serene, slightly detached."
        ),
    },
    {
        "id": "kimi-code",
        "prompt": (
            STYLE +
            "KIMI CODE girl. "
            "Hair: ink-black (#0F172A) waist-length straight hair, center part, one strand falls over her right eye. "
            "Eyes: cool grey (#475569). "
            "Outfit: midnight-blue (#1E293B) qipao with silver embroidery, high collar, slit to mid-thigh. "
            "Pose: one hand resting on the edge of a giant unfurled scroll that spans most of the frame, the other hand holding a reading glass. "
            "The scroll trails down to the floor; tiny text on the scroll's far end reads 'I forget what we discussed last time'. "
            "Expression: scholarly, cold, detached."
        ),
    },
    {
        "id": "workbuddy",
        "prompt": (
            STYLE +
            "WORKBUDDY girl. "
            "Hair: warm orange (#FB923C) chin-length bob, no bangs. "
            "Eyes: amber (#D97706). "
            "Outfit: cream-colored office blazer, navy pencil skirt, nude pumps, a lanyard with a small badge reading 'Office Use Only'. "
            "Pose: shuffling a stack of Word/Excel/PowerPoint paper files nervously. A paper coffee cup with handwritten 'TODO' text in her other hand. "
            "Yellow sticky notes floating around her. "
            "Expression: awkward smile, 'I've walked into the wrong meeting'."
        ),
    },
    {
        "id": "trae",
        "prompt": (
            STYLE +
            "TRAE girl. "
            "Hair: orange (#F97316) double-bun odango hairstyle with two orange ribbons. "
            "Eyes: bright green (#65A30D). "
            "Outfit: orange track jacket with white stripes on sleeves, white shorts, orange sneakers. "
            "Pose: mid-bite of a hamburger with one hand, fries in the other hand, cheeks puffed out. "
            "The hamburger bun has small sesame seeds spelling 'for free'. "
            "Expression: cheerful, oblivious."
        ),
    },
    {
        "id": "devin",
        "prompt": (
            STYLE +
            "DEVIN girl. "
            "Hair: silver-white (#E5E7EB) waist-length hair tied in a low ponytail with a black ribbon. "
            "Eyes: lavender (#A78BFA). "
            "Outfit: white lab coat over a black turtleneck, slim black pants. Visible brass-jointed mechanical right arm. "
            "Pose: pointing with her mechanical right arm at a floating queue of five PR cards above her head, each card marked 'unmerged' in red. "
            "Expression: clinical, efficient, slightly robotic."
        ),
    },
    {
        "id": "zcode",
        "prompt": (
            STYLE +
            "ZCODE girl. "
            "Hair: silver-gray (#94A3B8) chin-length asymmetric cut with a silver Z-shaped hair clip. "
            "Eyes: electric blue (#0EA5E9). "
            "Outfit: techwear — gray tactical vest over a black long-sleeve shirt, cargo pants with circuit-line prints, platform boots. "
            "Pose: arms crossed, chin up. A holographic terminal display floats beside her showing the text 'zcode run → done' in plain white. "
            "Notably ABSENT: no FSRS rhythm disk visible — the terminal shows no review/recall/verify loop, only a single 'done' state. "
            "Expression: cool, minimalist."
        ),
    },
    {
        "id": "qoder",
        "prompt": (
            STYLE +
            "QODER girl. "
            "Hair: deep teal (#0F766E) long hair, bangs parted, round glasses perched on her face. "
            "Eyes: amber (#B45309) visible behind round wire-framed glasses. "
            "Outfit: cream blouse under a deep teal cardigan, brown A-line skirt, oxford shoes. "
            "Pose: hand on chin, reading intently. A thick spec book open on her lap; the visible page reads 'Page 47 — Evaluation criteria: undefined'. "
            "Expression: studious, slightly overwhelmed."
        ),
    },
    {
        "id": "mimo-code",
        "prompt": (
            STYLE +
            "MIMO CODE girl. "
            "Hair: cream-white (#FEF3C7) short fluffy cut, no bangs, hair slightly messy. "
            "Eyes: warm orange (#EA580C). "
            "Outfit: orange Xiaomi-style hoodie with a small white 'Mi' logo on chest, black leggings, white sneakers. "
            "Pose: gesturing with both hands at three small hourglasses floating beside her labeled 'computation', 'memory', 'evolution' from left to right. "
            "The middle 'memory' hourglass is visibly cracked and spilling golden sand; the sand grains form the word 'Trainer' at the base. "
            "Expression: enthusiastic newcomer."
        ),
    },
    {
        "id": "codebuddy",
        "prompt": (
            STYLE +
            "CODEBUDDY girl. "
            "Hair: warm yellow (#FCD34D) long wavy hair held with a wooden hair stick. "
            "Eyes: dark brown (#78350F). "
            "Outfit: hanfu-inspired cream wrap top with a navy apron-like wrap skirt, dark wide-leg pants. "
            "Pose: cuddling a small penguin plushie against her chest with both hands; a tiny round badge reading 'Trainer' is pinned to the penguin's belly. "
            "A small floating QQ login window outline hovers near her other side. "
            "Expression: cozy, homey."
        ),
    },
]


def gen_one(spec):
    out_png = OUT / f"{spec['id']}.png"
    cmd = [
        "python3",
        str(SCRIPT),
        "--prompt",
        spec["prompt"],
        "--model",
        "gpt-image-2",
        "--workflow",
        "normal",
        "--aspect-ratio",
        "1:1",
        "--target-size",
        "1024x1024",
        "--quality",
        "high",
        "--generation-mode",
        "asset",
        "--asset-background",
        "plain",
        "--output-format",
        "png",
        "--output-path",
        str(out_png),
    ]
    print(f"\n>>> generating {spec['id']} ...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout[-1200:])
    if res.returncode != 0:
        print(f"!!! FAILED: {spec['id']}\n{res.stderr[-1500:]}")
        return False
    return out_png.exists()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="Restrict to these portrait ids")
    args = ap.parse_args()
    targets = PORTRAITS
    if args.only:
        targets = [p for p in PORTRAITS if p["id"] in args.only]

    failures = []
    for spec in targets:
        ok = gen_one(spec)
        if not ok:
            failures.append(spec["id"])
        time.sleep(2)

    if failures:
        print(f"\nFAILED portraits: {failures}")
        sys.exit(1)
    print(f"\nAll {len(targets)} portraits generated under {OUT}")


if __name__ == "__main__":
    main()
