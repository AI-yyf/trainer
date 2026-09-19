#!/usr/bin/env python3
"""Banner v2 — "11 bill-collectors vs 1 teacher".

Story (single scene, one night at the developer's desk):
- Top: deep-night chalkboard carrying the big chalk title "Trainer" whose
  baseline IS a forgetting curve turning into a growth curve.
- Middle: 11 harness girls arc around the developer, each handing him a bill
  (each bill styled after her brand's monetization meme).
- Right: Trainer is the only one NOT taking money — she points at his monitor
  where his own growth curve rises. Warm light on her side only.

All 12 identities come from assets/refs/cast_sheet_ref.png (labeled grid).
Output: assets/banner.png (3840x2160, PNG).
"""

import subprocess, sys, time
from pathlib import Path

SCRIPT = Path.home() / ".agents/skills/dora-image/scripts/generate_dora_image.py"
ASSETS = Path("/Users/Apple/Desktop/trainer/assets")
CAST_SHEET = ASSETS / "refs/cast_sheet_ref.png"
STYLE_REF = ASSETS / "refs/ai_niang_style_ref.jpeg"
OUT_PATH = ASSETS / "banner.png"

PROMPT = (
    "[STYLE] High-quality Japanese anime illustration in the AI-girl character-art style of the supplied style "
    "reference: clean delicate lineart, soft cel shading with gentle airbrush blending, large glossy anime eyes, "
    "detailed strand-level hair. Every character must match the EXACT identity given on the supplied labeled "
    "cast-sheet reference (each portrait is captioned with her name below her face). Night interior scene, "
    "cinematic contrast: cool blue-gray moonlight on the LEFT two-thirds, one single warm golden glow on the "
    "RIGHT. English text only. 4K, 16:9.\n\n"

    "[SCENE — one story, one room] A young developer's room at night. CENTER-LEFT: the developer (short black "
    "hair, dark gray hoodie, headphones around neck) sits at his desk hunched before a glowing monitor. His "
    "left hand holds up an OPEN EMPTY WALLET turned inside-out; paper bills and price tags fly out of it in an "
    "arc toward the girls around him. His head turns right, looking at her.\n\n"

    "[THE ARC OF 11 COLLECTORS] Around the developer — left edge, behind him, upper-left — eleven anime girls "
    "emerge from the screen-glow shadows, each extending toward him a paper bill or price tag (the bill is "
    "hers, styled to her brand), each with her own gesture and easter egg. Their outfits and hair MUST match "
    "their cast-sheet portraits:\n"
    "1. CURSOR girl — sleek black bob, black-and-white tailored outfit with one gold collar line; holds out a "
    "bill printed '$20/mo'; her other hand types mid-air with 'tab tab tab' ghost keystrokes; a tiny wallet is "
    "reflected in her sunglasses.\n"
    "2. CLAUDE CODE girl — long orange hair with sunflower ornament, cream Victorian blouse, black corset; "
    "elegantly hands over an API BILL SCROLL so long it unrolls off the desk and puddles on the floor, printed "
    "'API BILL'.\n"
    "3. CODEX girl — platinum-white hair, gold halo clip, pure white dress; unhurried, holds out a bill already "
    "rubber-stamped 'auto-generated'; a wrist tag reads 'do not disturb — async'; one gold bubble marked "
    "'verified ✓' floats above her palm.\n"
    "4. KIMI CODE girl — blue-black knee-length hair, silver crescent ornament; holds out a price tag "
    "'¥39 SALE' next to an absurdly long scroll of paper.\n"
    "5. TRAE girl — dark twin tails with neon-green glowing rings, black techwear with green piping; cheerfully "
    "offers a big card 'FREE*' with tiny asterisk text '*in queue'; a queue ticket 'A-048' tucked in her ribbon.\n"
    "6. DEVIN girl — silver-gray low ponytail, black-gray engineer dress; her mechanical arm fans out FIVE red-"
    "stamped slips 'UNMERGED'; chest badge 'in training'.\n"
    "7. QODER girl — ash-lavender hair, rectangular glasses, charcoal-violet secretary dress; solemnly presents "
    "a bill stamped 'Spec v0.3 DRAFT' while hugging a stack of spec documents.\n"
    "8. MIMO CODE girl — white-to-orange high ponytail with a rounded-square MI hairpin, white dress with orange "
    "square buttons; holds out an orange price tag '9.9'; three hourglasses float beside her, the middle one "
    "cracked with sand leaking into the word 'Trainer'.\n"
    "9. ZCODE girl — the sleepy witch: long black hair, black witch hat with a white 'Z' sleep mask pushed up, "
    "gothic-lolita black-and-white dress; she is ASLEEP at the end of the arc, her bill slipping from her loose "
    "fingers, a discount tag '-70%' beside her, 'Zzz' in the air, an hourglass lying on its side at her feet.\n"
    "10. WORKBUDDY girl — sleek black long hair, WeChat-green blazer lapels covered in colorful VIP diamond "
    "pins; thrusts forward a tablet showing a chat bubble 'FILE EXPIRED'; lanyard badge 'Day 14'.\n"
    "11. CODEBUDDY girl — blue-to-lavender wavy hair, white-blue dress; cuddles a small penguin plushie with a "
    "red scarf while holding out a 'MEMBERSHIP' flyer; a translucent pale-blue login window with a 'QQ' button "
    "floats behind her.\n\n"

    "[THE ONE TEACHER — RIGHT THIRD] TRAINER girl — the only one NOT reaching for the wallet. From the labeled "
    "cast sheet: completely white short crisp bob, slim silver-framed glasses, calm indigo eyes, sharply "
    "tailored ivory-white long coach coat over a white high-collar blouse with an indigo ribbon tie, small "
    "indigo brooch. She stands beside the developer's chair, bathed in the single warm golden glow of the "
    "scene. She leans slightly toward him: her right hand holds up a brass stopwatch on a leather strap; her "
    "left hand POINTS at his monitor, and golden light particles flow from her fingertip onto the screen. On "
    "the monitor: his own project — a green rising growth curve climbing 'verified ✓' marks, and a tiny green "
    "sprout growing between the keys of his keyboard.\n\n"

    "[TITLE — top band, deep design] The upper quarter of the image is a dark chalkboard wall spanning the full "
    "width. On it, ONE giant elegant hand-chalked serif wordmark: Trainer. The BASELINE of the wordmark is "
    "itself a curve: under the letters 'Tra' a red chalk line decays downward labeled 'forget'; at the letter "
    "i the line bottoms out and reverses; under 'ner' it rises green labeled 'grow' and ends with a small "
    "chalked check mark. The dot of the letter 'i' is a tiny GOLD RING. Beneath the wordmark, one small line "
    "of chalk: 'they want your money — she wants you to grow'. Nothing else is written on the chalkboard.\n\n"

    "[LIGHT] Cool desaturated blue-gray fills the collector arc and the desk; the ONLY warm light is a golden "
    "radius around Trainer on the right, casting rim light on the developer's face as he turns to her. Bills "
    "are desaturated paper-white; her gold particles are the brightest accents in the image.\n\n"

    "[NEGATIVE] No extra characters beyond the 11 girls, the developer, and Trainer. No Chinese characters "
    "anywhere. No watermarks, no frames. Do not duplicate any girl — each appears exactly once. Keep each "
    "girl's small label text small and legible; slightly imperfect handwriting is fine."
)


def main():
    cmd = [
        "python3", str(SCRIPT),
        "--prompt", PROMPT,
        "--model", "gpt-image-2",
        "--workflow", "normal",
        "--aspect-ratio", "16:9",
        "--target-size", "3840x2160",
        "--quality", "high",
        "--generation-mode", "standard",
        "--output-format", "png",
        "--output-path", str(OUT_PATH),
        "--asset-background", "scene",
        "--reference-image", str(CAST_SHEET), "--reference-role", "reference",
        "--reference-image", str(STYLE_REF), "--reference-role", "style",
    ]
    print(f">>> banner v2: refs = cast sheet + style; prompt {len(PROMPT)} chars")
    for attempt in range(3):
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(res.stdout[-1200:])
        if res.returncode == 0 and OUT_PATH.exists():
            print(f">>> OK {OUT_PATH} ({OUT_PATH.stat().st_size/(1024*1024):.1f} MB)")
            return
        print(f"!!! attempt {attempt+1} failed: {res.stderr[-500:]}")
        if attempt < 2:
            time.sleep(90)
    sys.exit(1)


if __name__ == "__main__":
    main()
