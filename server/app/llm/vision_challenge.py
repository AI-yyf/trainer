"""Small randomized visual reading challenge; its answer is never in the prompt."""

from __future__ import annotations

import base64
import json
import secrets
import struct
import zlib
from dataclasses import dataclass

VISION_PROBE_VERSION = "random-grid-v1"

_DIGITS = (
    ("11111", "10001", "10001", "10001", "10001", "10001", "11111"),
    ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    ("11111", "00001", "00001", "11111", "10000", "10000", "11111"),
    ("11111", "00001", "00001", "11111", "00001", "00001", "11111"),
    ("10001", "10001", "10001", "11111", "00001", "00001", "00001"),
    ("11111", "10000", "10000", "11111", "00001", "00001", "11111"),
    ("11111", "10000", "10000", "11111", "10001", "10001", "11111"),
    ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    ("11111", "10001", "10001", "11111", "10001", "10001", "11111"),
    ("11111", "10001", "10001", "11111", "00001", "00001", "11111"),
)
_PROMPT = (
    "Inspect the supplied image. Read the two-digit number in each of the three "
    "panels from left to right. Reply only with a JSON object using the keys "
    '"left", "middle", "right" and string values for the numbers you actually see. '
    "If you cannot read the image, reply UNKNOWN. Do not guess."
)


@dataclass(frozen=True, slots=True)
class VisionChallenge:
    image_url: str
    expected: tuple[str, str, str]
    prompt: str = _PROMPT

    def matches(self, text: str) -> bool:
        try:
            result = json.loads(text.strip())
        except (ValueError, TypeError):
            return False
        if not isinstance(result, dict) or set(result) != {"left", "middle", "right"}:
            return False
        return tuple(result[key] for key in ("left", "middle", "right")) == self.expected


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def build_vision_challenge() -> VisionChallenge:
    """Generate visible six-digit content, without a font or imaging dependency."""
    expected = (
        str(10 + secrets.randbelow(90)),
        str(10 + secrets.randbelow(90)),
        str(10 + secrets.randbelow(90)),
    )
    width, height, scale = 384, 128, 7
    pixels = bytearray(b"\xff" * width * height * 3)

    def pixel(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        offset = (y * width + x) * 3
        pixels[offset:offset + 3] = bytes(rgb)

    colors = ((32, 107, 179), (41, 139, 84), (192, 92, 26))
    for panel, text in enumerate(expected):
        x_origin = panel * 128
        for y in range(12, 116):
            for x in range(x_origin + 8, x_origin + 120):
                if y < 16 or y >= 112 or x < x_origin + 12 or x >= x_origin + 116:
                    pixel(x, y, colors[panel])
        for digit_index, digit in enumerate(text):
            for row, line in enumerate(_DIGITS[int(digit)]):
                for column, bit in enumerate(line):
                    if bit == "1":
                        for dy in range(scale):
                            for dx in range(scale):
                                pixel(
                                    x_origin + 24 + digit_index * 42 + column * scale + dx,
                                    39 + row * scale + dy,
                                    (18, 18, 18),
                                )
    rows = b"".join(b"\0" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )
    return VisionChallenge("data:image/png;base64," + base64.b64encode(png).decode(), expected)
