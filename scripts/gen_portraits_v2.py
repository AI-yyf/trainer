#!/usr/bin/env python3
"""Step 4: regenerate 12 character portraits as 1024x1536 vertical full-body
character sheets — pure figure standing, no scenery, intended as reference
images for later group-shot composition work.

Each portrait uses the same DeepSeek-mascot cel-shading style so the 12 girls
form a coherent visual cast.
"""

import argparse, subprocess, sys, json
from pathlib import Path

SCRIPT = Path.home() / ".agents/skills/dora-image/scripts/generate_dora_image.py"
OUT = Path("/Users/Apple/Desktop/trainer/assets/portraits")
OUT.mkdir(parents=True, exist_ok=True)


# Common style lock — same DeepSeek cel-shading look used in the existing portraits
STYLE_LOCK = (
    "[STYLE LOCK] "
    "Single character full-body portrait on plain soft warm gradient background (#F5F3FF to #E8E5F5). "
    "Clean modern anime cel-shading style matching official DeepSeek mascot art. "
    "Chibi 2.5-head proportions. Large round expressive eyes with three yellow star-shaped highlights (#FCD34D). "
    "Crisp dark outlines (3-4px, color #1E1B4B). Cream skin (#F5E6D3) with subtle blush (#FCA5A5). "
    "Flat color blocks, no painterly strokes, no gradients on the figure itself. "
    "Vertical composition 2:3 (taller than wide). Subject centered, head in upper third, "
    "feet in lower third. Generous negative space around figure for icon use. "
    "No other characters. No background scenery. Flat cel-shaded, no watermark, signature, or border."
)


# Each character prompt — directly transcribed from MASCOT.md sections 1.1 and 1.2
PROMPTS = {
    "trainer": (
        STYLE_LOCK + "\n\n"

        "Subject: TRAINER girl — the protagonist.\n"
        "Hair: indigo short bob with blunt bangs, single ahoge (cowlick) pointing up like a small antenna, "
        "hair gradient from indigo-950 #1E1B4B at roots to indigo-500 #6366F1 at tips.\n"
        "Eyes: large round indigo #312E81 irises with three bright yellow #FCD34D star-shaped highlights "
        "(one large upper-left, one small lower-right, one tiny catchlight).\n"
        "Outfit: white single-breasted coach jacket with indigo lapels and four brass buttons, two front flap "
        "pockets, small epaulets on shoulders. Indigo #4338CA athletic V-neck vest underneath. "
        "Indigo pleated skirt to mid-thigh. White knee-high socks with two indigo stripes at the top band. "
        "Brown leather loafers.\n"
        "Accessories: round brass-framed glasses resting on her nose. "
        "Coach stopwatch-whip hybrid in her right hand — a brown leather strap ending in a round brass stopwatch face, "
        "the strap coiled loosely. Her left hand is held up palm-out in a gentle wave gesture, revealing a small "
        "FSRS curve tattoo on the back of her left hand.\n"
        "Pose: standing, body three-quarter turned toward the viewer, slight contrapposto.\n"
        "Expression: warm, focused, encouraging, gentle smile."
    ),

    "cursor": (
        STYLE_LOCK + "\n\n"

        "Subject: CURSOR girl.\n"
        "Hair: chestnut brown undercut bob, side-swept bangs. Eyes: hazel #92400E.\n"
        "Outfit: cropped VS Code-blue #007ACC hoodie, black cargo pants, white sneakers, "
        "sunglasses pushed up on forehead.\n"
        "Prop: dual translucent 4K monitor rectangles floating beside her showing 'index.tsx' and 'App.tsx'. "
        "Three small 'tab tab tab' speech bubbles around her head.\n"
        "Pose: leaning forward, fingers mid-air typing on invisible keyboard.\n"
        "Expression: confident, slightly cocky."
    ),

    "claude-code": (
        STYLE_LOCK + "\n\n"

        "Subject: CLAUDE CODE girl.\n"
        "Hair: auburn #7C2D12 short pixie cut with side bangs. Eyes: deep amber #B45309.\n"
        "Outfit: long black duster coat over charcoal turtleneck, slim trousers, Chelsea boots.\n"
        "Prop: quill pen in right hand, scroll of parchment tucked under left arm. "
        "A paper tape unfurling from her coat reads 'Bash is all you need' and tangles around her own feet.\n"
        "Pose: writing with one hand, other hand tucked in coat.\n"
        "Expression: literary, slightly smug."
    ),

    "codex": (
        STYLE_LOCK + "\n\n"

        "Subject: CODEX girl.\n"
        "Hair: honey-blonde #D97706 waist-length, half-up with O-shaped halo clip (very subtle, almost transparent). "
        "Eyes: pale sky blue #7DD3FC.\n"
        "Outfit: pure white bodysuit with subtle gold piping, floating disconnected sleeves, gold ankle boots.\n"
        "Prop: 5 floating PR bubbles around her head, each labeled 'auto-generated' (none labeled 'verified').\n"
        "Pose: arms slightly outstretched, palms up.\n"
        "Expression: serene, slightly detached."
    ),

    "kimi-code": (
        STYLE_LOCK + "\n\n"

        "Subject: KIMI CODE girl.\n"
        "Hair: ink-black #0F172A waist-length, straight, center part, one strand falls over right eye. "
        "Eyes: cool gray #475569.\n"
        "Outfit: midnight-blue #1E293B qipao with silver embroidery, high collar, slit to mid-thigh.\n"
        "Prop: a giant scroll unfurling beside her, the end trails onto the floor (long-context joke), "
        "scroll text is too small to read but visible.\n"
        "Pose: one hand on scroll edge, other hand holding reading glass up to eye.\n"
        "Expression: scholarly, cold, detached."
    ),

    "workbuddy": (
        STYLE_LOCK + "\n\n"

        "Subject: WORKBUDDY girl.\n"
        "Hair: warm orange #FB923C chin-length bob, no bangs. Eyes: amber #D97706.\n"
        "Outfit: cream-colored office blazer, navy pencil skirt, nude pumps, lanyard with 'Office Use Only' badge.\n"
        "Prop: stack of Word/Excel/PowerPoint files in one arm, paper coffee cup with 'TODO' written on it in the other. "
        "Sticky notes stuck to her blazer.\n"
        "Pose: shuffling papers nervously.\n"
        "Expression: 'I've walked into the wrong meeting' — awkward smile."
    ),

    "trae": (
        STYLE_LOCK + "\n\n"

        "Subject: TRAE girl.\n"
        "Hair: orange #F97316 double-bun (odango), with orange ribbons. Eyes: bright green #65A30D.\n"
        "Outfit: orange track jacket with white stripes, white shorts, orange sneakers.\n"
        "Prop: hamburger in one hand (with 'for free' written on the bun in sesame seeds), fries in the other.\n"
        "Pose: mid-bite, cheeks puffed.\n"
        "Expression: cheerful, oblivious."
    ),

    "devin": (
        STYLE_LOCK + "\n\n"

        "Subject: DEVIN girl.\n"
        "Hair: silver-white #E5E7EB waist-length, lab coat white, hair tied in low ponytail with black ribbon. "
        "Eyes: lavender #A78BFA.\n"
        "Outfit: white lab coat over black turtleneck, slim black pants, mechanical right arm (visible brass joints).\n"
        "Prop: floating queue of 5 PR cards above her head, each marked 'unmerged' in red.\n"
        "Pose: pointing at the floating cards with mechanical arm.\n"
        "Expression: clinical, efficient, slightly robotic."
    ),

    "zcode": (
        STYLE_LOCK + "\n\n"

        "Subject: ZCODE girl.\n"
        "Hair: silver-gray #94A3B8 chin-length asymmetric cut, silver Z-shaped hair clip. "
        "Eyes: electric blue #0EA5E9.\n"
        "Outfit: techwear — gray tactical vest over black long-sleeve, cargo pants with circuit-line prints, "
        "platform boots.\n"
        "Prop: holographic terminal display showing 'zcode run → done', no FSRS rhythm disk visible.\n"
        "Pose: arms crossed, chin up.\n"
        "Expression: cool, minimalist."
    ),

    "qoder": (
        STYLE_LOCK + "\n\n"

        "Subject: QODER girl.\n"
        "Hair: deep teal #0F766E long with glasses perched on nose. Eyes: amber #B45309 behind round glasses.\n"
        "Outfit: cream blouse under deep teal cardigan, brown A-line skirt, oxford shoes.\n"
        "Prop: thick spec book open in her hands, page 47 reads 'Evaluation criteria: undefined'.\n"
        "Pose: hand on chin, reading intently.\n"
        "Expression: studious, slightly overwhelmed."
    ),

    "mimo-code": (
        STYLE_LOCK + "\n\n"

        "Subject: MIMO CODE girl.\n"
        "Hair: cream-white #FEF3C7 short fluffy cut, no bangs. Eyes: warm orange #EA580C.\n"
        "Outfit: orange Xiaomi-style hoodie with 'Mi' logo on chest, black leggings, white sneakers.\n"
        "Prop: 3 hourglasses floating beside her — labeled 'computation', 'memory', 'evolution'; "
        "the 'memory' hourglass is cracked.\n"
        "Pose: gesturing at the 3 hourglasses with both hands.\n"
        "Expression: enthusiastic newcomer."
    ),

    "codebuddy": (
        STYLE_LOCK + "\n\n"

        "Subject: CODEBUDDY girl.\n"
        "Hair: warm yellow #FCD34D long wavy, half-up with hair stick. Eyes: dark brown #78350F.\n"
        "Outfit: hanfu-inspired cream top with navy apron-like wrap, dark wide-leg pants.\n"
        "Prop: penguin plushie held in her arms (Tencent joke), QQ login window floating beside her.\n"
        "Pose: cuddling the penguin, head tilted.\n"
        "Expression: cozy, homey."
    ),
}


def gen_one(name: str):
    prompt = PROMPTS[name]
    out_path = OUT / f"{name}.png"

    cmd = [
        "python3",
        str(SCRIPT),
        "--prompt", prompt,
        "--model", "gpt-image-2",
        "--workflow", "normal",
        "--generation-mode", "asset",
        "--asset-background", "plain",
        "--aspect-ratio", "2:3",
        "--target-size", "1024x1536",
        "--quality", "high",
        "--output-format", "png",
        "--output-path", str(out_path),
    ]

    print(f"\n>>> generating {name} (1024x1536, 2:3 vertical)")
    print(f">>> prompt length: {len(prompt)} chars")

    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout[-1200:])
    if res.returncode != 0:
        print(f"!!! FAILED for {name}\n{res.stderr[-1200:]}")
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

    print(f">>> regenerating {len(targets)} portraits as 1024x1536 vertical: {', '.join(targets)}")

    failures = []
    for name in targets:
        ok = gen_one(name)
        if not ok:
            failures.append(name)

    if failures:
        print(f"\n!!! {len(failures)} failures: {failures}")
        sys.exit(1)
    print("\n>>> all portrait regenerations done")


if __name__ == "__main__":
    main()
