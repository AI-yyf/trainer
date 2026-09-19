#!/usr/bin/env python3
"""Step 2: compose hero banner using the character portraits as reference images.

Style baseline (v4): AI娘 萌娘 — normal-proportioned elegant anime girls,
matching assets/refs/ai_niang_style_ref.jpeg and the v4 portraits.
We pass 5 portrait references (trainer + 4 distinct harness girls) plus the
style reference so the banner reads as one cohesive illustration.
"""

import argparse, subprocess, sys, time
from pathlib import Path

SCRIPT = Path.home() / ".agents/skills/dora-image/scripts/generate_dora_image.py"
PORTRAITS = Path("/Users/Apple/Desktop/trainer/assets/portraits")
STYLE_REF = Path("/Users/Apple/Desktop/trainer/assets/refs/ai_niang_style_ref.jpeg")
OUT = Path("/Users/Apple/Desktop/trainer/assets")
OUT.mkdir(parents=True, exist_ok=True)

BANNER_PROMPT = (
    "[STYLE] High-quality Japanese anime illustration in the AI-girl (AI娘/萌娘) character-art style of the "
    "supplied style reference — clean delicate lineart, soft cel shading with gentle airbrush blending, "
    "large glossy anime eyes, refined bishoujo faces, detailed strand-level hair, ornate brand-colored outfits. "
    "All five harness girls have NORMAL anime proportions (~6.5 heads, NOT chibi) and must look like the exact "
    "same characters as their supplied portrait references: same hair color and style, same outfit, same prop, "
    "same presence. Warm soft lighting, indigo-gold palette (#312E81 #4338CA #F59E0B #FCD34D #F5E6D3) on the "
    "characters, cool slate tones (#1E293B #475569 #94A3B8) on the developer side. "
    "NO photorealism, NO 3D render, NO heavy painterly oil strokes on the characters.\n\n"

    "[COMPOSITION] Canvas 3840x2160 (16:9), 4K UHD, single cohesive illustration, rule of thirds. "
    "Foreground: a long wooden workbench running across the lower third, slightly diagonal. "
    "On the table, left to right: an open notebook titled 'Day 1 — Trainer', a brass stopwatch, a closed red book "
    "titled 'py-fsrs: open-spaced-repetition', a cream ceramic mug printed with an FSRS decay curve and the text "
    "'FSRS', scattered index cards.\n\n"

    "[BACKGROUND] A tall chalkboard (flat dark slate #0F172A with a wood frame) fills the upper half of the canvas "
    "behind everyone. On its left half: a chalk-white #F5F5DC exponential forgetting curve decaying from upper-left "
    "to lower-right, its middle smudged by an eraser. On its right half: a chalk-green #86EFAC ascending curve "
    "rising from the lowest point of the decay up to the right, ending in a small checkmark. "
    "Below the curves in small chalk-yellow handwriting: '// FSRS: forget, recall, grow'. "
    "Bottom-left of the board in chalk: '产出 ≠ 成长'. Bottom-right: '验证 + 复习 = 成长'. "
    "The chalkboard is flat and crisp, not blurred.\n\n"

    "[CHARACTERS]\n"
    "MAIN (right third, largest): TRAINER girl — the protagonist from her portrait reference: a pure white-"
    "moonlight beauty with a completely WHITE short crisp bob, slim silver-framed glasses, calm indigo eyes, "
    "sharply tailored ivory-white long coach coat over a white high-collar blouse with an indigo #4338CA slim "
    "ribbon tie, indigo FSRS-curve brooch. Standing in three-quarter view facing left, holding her brass "
    "stopwatch-on-a-strap toward the chalkboard in one hand, other palm raised in a gentle teaching gesture. "
    "Serene, quietly radiant teacher's smile.\n\n"
    "LEFT (in cool shadow, smaller): a young human developer — NOT a harness girl — sitting hunched on a stool, "
    "knees drawn up, head buried in his hands, dark gray hoodie, headphones around his neck, short black hair, "
    "an empty coffee cup on the floor and an empty notebook titled 'Day 1' on his lap. Rendered in low-contrast "
    "blue-gray, semi-silhouette.\n\n"
    "SECONDARY (mid-ground between them, slightly smaller than Trainer, all glancing toward the chalkboard):\n"
    "  - CLAUDE CODE girl: long vivid orange hair with a sunflower ornament, cream Victorian blouse with a large "
    "black ribbon bow and black corset belt, hugging an old leather book, a paper tape reading 'Bash is all you "
    "need' curling around her arm.\n"
    "  - ZCODE girl: long straight black hair, black witch hat with a white 'Z' sleep mask pushed up on the brim, "
    "gothic-lolita black-and-white dress with silver bells, sleepy half-lidded eyes, holding a black 'GLM' book.\n"
    "  - CODEX girl: platinum-white waist-length hair with a thin gold halo clip, pure white high-collar dress "
    "with gold piping, serene; five small bubbles above her — four grey 'auto-generated', one gold 'verified ✓'.\n\n"
    "BACKGROUND RIGHT corner (smallest): CODEBUDDY girl — honey-yellow wavy hair, cream hanfu-inspired wrap dress "
    "with a blue sash, cuddling a small penguin plushie with a red scarf, cozy smile.\n\n"

    "[NEGATIVE CONSTRAINTS] No additional characters beyond those listed. No chibi, no super-deformation. "
    "No text outside the chalkboard, the notebook, the book, the mug, and the labeled props mentioned above. "
    "No watermark, no signature, no border, no frame, no background scenery beyond the chalkboard and workbench."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-role", default="reference",
                    help="role for the portrait references")
    args = ap.parse_args()

    out_path = OUT / "banner.png"

    refs = []
    for char_id in ["trainer", "claude-code", "zcode", "codex", "codebuddy"]:
        ref_path = PORTRAITS / f"{char_id}.png"
        if ref_path.exists():
            refs.append(str(ref_path))
        else:
            print(f"!!! Missing reference portrait: {ref_path}")
    if not refs:
        print("!!! No reference portraits found, aborting")
        sys.exit(1)

    cmd = [
        "python3", str(SCRIPT),
        "--prompt", BANNER_PROMPT,
        "--model", "gpt-image-2",
        "--workflow", "normal",
        "--aspect-ratio", "16:9",
        "--target-size", "3840x2160",
        "--quality", "high",
        "--generation-mode", "standard",
        "--output-format", "png",
        "--output-path", str(out_path),
        "--asset-background", "scene",
    ]
    for ref in refs:
        cmd += ["--reference-image", ref, "--reference-role", args.ref_role]
    if STYLE_REF.exists():
        cmd += ["--reference-image", str(STYLE_REF), "--reference-role", "style"]

    print(f">>> generating banner with {len(refs)} portrait refs + style ref (role={args.ref_role})")
    print(f">>> prompt length: {len(BANNER_PROMPT)} chars")

    for attempt in range(3):
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(res.stdout[-1500:])
        if res.returncode == 0 and out_path.exists():
            print(f"\n>>> banner generated: {out_path} ({out_path.stat().st_size / (1024*1024):.1f} MB)")
            return
        print(f"!!! attempt {attempt+1} failed: {res.stderr[-600:]}")
        if attempt < 2:
            time.sleep(90)
    sys.exit(1)


if __name__ == "__main__":
    main()
