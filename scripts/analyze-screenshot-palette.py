#!/usr/bin/env python3
"""Report the hue palette of a screenshot (warm-neutral vs blue share).

Used as objective evidence for the "not too blue" visual requirement:

    python3 scripts/analyze-screenshot-palette.py <image> [<image> ...]

Blue share counts pixels in the blue/indigo band (hue 185-265) with enough
saturation to read as a colour; warm share counts tan/brown/amber pixels
(hue 15-60). UI chrome is dark/light grey and has low saturation, so it is not
counted as either.
"""

from __future__ import annotations

import colorsys
import sys
from pathlib import Path

from PIL import Image


def analyze(path: Path) -> dict[str, float | int | str]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        rgb.thumbnail((800, 800))
        pixels = list(rgb.getdata())
    total = len(pixels) or 1
    blue = warm = colored = 0
    for red, green, blue_channel in pixels:
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue_channel / 255)
        if saturation < 0.12 or value < 0.06:
            continue
        colored += 1
        degrees = hue * 360
        if 185 <= degrees <= 265 and saturation >= 0.22:
            blue += 1
        elif 15 <= degrees <= 60 and saturation >= 0.16:
            warm += 1
    return {
        "file": str(path),
        "pixels": total,
        "colored_share": round(colored / total, 4),
        "blue_share_of_colored": round(blue / max(colored, 1), 4),
        "warm_share_of_colored": round(warm / max(colored, 1), 4),
        "blue_pixels": blue,
        "warm_pixels": warm,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    failures = 0
    for raw in argv[1:]:
        path = Path(raw)
        if not path.is_file():
            print(f"missing: {path}")
            failures += 1
            continue
        result = analyze(path)
        print(
            f"{path.name}: blue={result['blue_share_of_colored']:.2%} "
            f"warm={result['warm_share_of_colored']:.2%} "
            f"colored={result['colored_share']:.2%}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
