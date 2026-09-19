#!/usr/bin/env python3
"""Step 1: generate solo portrait of each character on plain background.
Step 2: use these portraits as --reference-image=reference inputs to compose the hero banner.
We avoid loading 11 harness characters into a single 3840x2160 prompt; instead each is built
cleanly first, then the banner references them so silhouettes stay distinct."""

import argparse, json, os, subprocess, sys, time
from pathlib import Path

SCRIPT = Path.home() / ".agents/skills/dora-image/scripts/generate_dora_image.py"
OUT = Path("/Users/Apple/Desktop/trainer/assets/portraits")
OUT.mkdir(parents=True, exist_ok=True)

# Each prompt is a clean single-character shot on plain background.
# Style locked to DeepSeek official mascot cel-shading + soft gradient background.
PORTRAITS = [
    {
        "id": "cursor",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive eyes with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3) with subtle pink blush (#FCA5A5). "
            "CURSOR girl: chestnut-brown short undercut bob with side-swept bangs, hair color #8B4513. "
            "Hazel eyes (#92400E). Wearing a cropped VS Code-blue (#007ACC) zip hoodie over a black tee, "
            "black cargo pants, white sneakers. Round sunglasses pushed up on her forehead reflecting a small indigo silhouette. "
            "Pose: leaning slightly forward, hands raised mid-air as if typing on an invisible keyboard. "
            "Two translucent monitor rectangles float in front of her, one labeled 'index.tsx', one labeled 'App.tsx'. "
            "Three small 'tab' speech bubbles drift around her head. "
            "Expression: confident, slightly cocky, with one eyebrow raised. "
            "No other characters. No text other than the labels above. No background scenery. "
            "No watermark, no signature, no border. Flat cel-shaded, no painterly strokes, no oil painting, no photorealism. "
            "Three-quarter view, slightly tilted head, character occupies center of frame, generous negative space around edges."
        ),
    },
    {
        "id": "claude-code",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive amber eyes (#B45309) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3) with subtle blush. "
            "CLAUDE CODE girl: auburn (#7C2D12) short pixie cut with side-swept bangs. "
            "Wearing a long black duster coat over a charcoal turtleneck, slim black trousers, Chelsea boots. "
            "Pose: writing with one hand holding a black quill pen on a parchment scroll unrolled at her feet, the other hand tucked in her coat. "
            "A long white paper tape unfurls from under her left arm with the text 'Bash is all you need' printed on it; the tape tangles loosely around her own left ankle. "
            "Expression: literary, slightly smug. "
            "No other characters. No text other than the tape quote. No background scenery. "
            "No watermark, no signature, no border. Flat cel-shaded. "
            "Three-quarter view, character occupies center of frame, generous negative space."
        ),
    },
    {
        "id": "codex",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive pale sky-blue eyes (#7DD3FC) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "CODEX girl: honey-blonde (#D97706) waist-length hair, half-up style, thin gold O-shaped halo clip on top of her head. "
            "Wearing a pure white form-fitting bodysuit with subtle gold piping along the seams. Gold ankle boots. "
            "Pose: arms slightly outstretched, palms up. Five thin floating circle bubbles above her head; four are pale grey labeled 'auto-generated', one is bright gold labeled 'verified ✓'. "
            "Expression: serene, slightly detached. "
            "No other characters. No background scenery. "
            "No watermark, no signature, no border. Flat cel-shaded. "
            "Three-quarter view, character occupies center of frame."
        ),
    },
    {
        "id": "kimi-code",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive cool-grey eyes (#475569) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "KIMI CODE girl: ink-black (#0F172A) waist-length straight hair, center part, one strand falls over her right eye. "
            "Wearing a midnight-blue (#1E293B) qipao with silver embroidery, high collar, slit to mid-thigh. "
            "Pose: one hand resting on the edge of a giant unfurled scroll that spans most of the frame, the other hand holding a reading glass. "
            "The scroll trails down to the floor; tiny text on the scroll's far end reads 'I forget what we discussed last time'. "
            "Expression: scholarly, cold, detached. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
        ),
    },
    {
        "id": "workbuddy",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive amber eyes (#D97706) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "WORKBUDDY girl: warm orange (#FB923C) chin-length bob, no bangs. "
            "Wearing a cream-colored office blazer, navy pencil skirt, nude pumps, a lanyard with a small badge reading 'Office Use Only'. "
            "Pose: shuffling a stack of Word/Excel/PowerPoint paper files nervously. A paper coffee cup with handwritten 'TODO' text in her other hand. "
            "Yellow sticky notes floating around her. "
            "Expression: awkward smile, 'I've walked into the wrong meeting'. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
        ),
    },
    {
        "id": "trae",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive bright-green eyes (#65A30D) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "TRAE girl: orange (#F97316) double-bun odango hairstyle with two orange ribbons. "
            "Wearing an orange track jacket with white stripes on sleeves, white shorts, orange sneakers. "
            "Pose: mid-bite of a hamburger with one hand, fries in the other hand, cheeks puffed out. "
            "The hamburger bun has small sesame seeds spelling 'for free'. "
            "Expression: cheerful, oblivious. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
        ),
    },
    {
        "id": "devin",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive lavender eyes (#A78BFA) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "DEVIN girl: silver-white (#E5E7EB) waist-length hair tied in a low ponytail with a black ribbon. "
            "Wearing a white lab coat over a black turtleneck, slim black pants. Visible brass-jointed mechanical right arm. "
            "Pose: pointing with her mechanical right arm at a floating queue of five PR cards above her head, each card marked 'unmerged' in red. "
            "Expression: clinical, efficient, slightly robotic. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
        ),
    },
    {
        "id": "zcode",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive electric-blue eyes (#0EA5E9) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "ZCODE girl: silver-gray (#94A3B8) chin-length asymmetric cut with a silver Z-shaped hair clip. "
            "Wearing techwear: gray tactical vest over a black long-sleeve shirt, cargo pants with circuit-line prints, platform boots. "
            "Pose: arms crossed, chin up. A holographic terminal display floats beside her showing the text 'zcode run → done' in plain white. "
            "Notably ABSENT: no FSRS rhythm disk visible — the terminal shows no review/recall/verify loop, only a single 'done' state. "
            "Expression: cool, minimalist. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
        ),
    },
    {
        "id": "qoder",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive amber eyes (#B45309) visible behind round wire-framed glasses, with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "QODER girl: deep teal (#0F766E) long hair, bangs parted, round glasses perched on her nose. "
            "Wearing a cream blouse under a deep teal cardigan, brown A-line skirt, oxford shoes. "
            "Pose: hand on chin, reading intently. A thick spec book open on her lap; the visible page reads 'Page 47 — Evaluation criteria: undefined'. "
            "Expression: studious, slightly overwhelmed. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
        ),
    },
    {
        "id": "mimo-code",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive warm-orange eyes (#EA580C) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "MIMO CODE girl: cream-white (#FEF3C7) short fluffy cut, no bangs, hair slightly messy. "
            "Wearing an orange Xiaomi-style hoodie with a small white 'Mi' logo on chest, black leggings, white sneakers. "
            "Pose: gesturing with both hands at three small hourglasses floating beside her labeled 'computation', 'memory', 'evolution' from left to right. "
            "The middle 'memory' hourglass is visibly cracked and spilling golden sand; the sand grains form the word 'Trainer' at the base. "
            "Expression: enthusiastic newcomer. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
        ),
    },
    {
        "id": "codebuddy",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive dark-brown eyes (#78350F) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3). "
            "CODEBUDDY girl: warm yellow (#FCD34D) long wavy hair held with a wooden hair stick. "
            "Wearing a hanfu-inspired cream wrap top with a navy apron-like wrap skirt, dark wide-leg pants. "
            "Pose: cuddling a small penguin plushie against her chest with both hands; a tiny round badge reading 'Trainer' is pinned to the penguin's belly. "
            "A small floating QQ login window outline hovers near her other side. "
            "Expression: cozy, homey. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
        ),
    },
    {
        "id": "trainer",
        "size": "1024x1024",
        "prompt": (
            "Single character portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
            "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
            "Chibi 2.5-head proportions. Large round expressive indigo eyes (#312E81) with three yellow star-shaped highlights (#FCD34D). "
            "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3) with subtle blush (#FCA5A5). "
            "TRAINER girl (the protagonist): indigo short bob with blunt bangs, hair gradient from indigo-950 #1E1B4B at roots to indigo-500 #6366F1 at tips. "
            "One small ahoge pointing upward like a tiny antenna. "
            "Wearing a white single-breasted coach jacket with indigo lapels and four brass buttons, two front flap pockets, small epaulets on shoulders. "
            "Indigo (#4338CA) athletic V-neck vest underneath. Indigo pleated skirt to mid-thigh. "
            "White knee-high socks with two indigo stripes at the top band. Brown leather loafers. "
            "Round brass-framed glasses resting on her nose. "
            "She holds a stopwatch-whip hybrid in her right hand: a brown leather strap ending in a round brass stopwatch face, the strap coiled loosely. "
            "Her left hand is held up palm-out in a gentle wave gesture, revealing a small FSRS curve tattoo on the back of her left hand. "
            "Pose: standing, body three-quarter turned toward the viewer, slight contrapposto. "
            "Expression: warm, focused, encouraging, gentle smile. "
            "No other characters. No background scenery. "
            "Flat cel-shaded, no watermark, signature or border."
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
        spec["size"],
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
        time.sleep(2)  # rate-limit cushion

    if failures:
        print(f"\nFAILED portraits: {failures}")
        sys.exit(1)
    print(f"\nAll {len(targets)} portraits generated under {OUT}")


if __name__ == "__main__":
    main()
