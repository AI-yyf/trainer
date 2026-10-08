"""Validate image transport before any model request; never trust client MIME/size."""

from __future__ import annotations

import base64
import binascii
import struct
from io import BytesIO

from PIL import Image

MAX_IMAGE_COUNT = 4
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 16 * 1024 * 1024
MAX_IMAGE_EDGE = 8192
MAX_IMAGE_BASE64_LENGTH = ((MAX_IMAGE_BYTES + 2) // 3) * 4


def _image_header(data: bytes) -> tuple[str, int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", width, height
    if data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "image/gif", width, height
    if data.startswith(b"\xff\xd8\xff"):
        position = 2
        while position + 8 < min(len(data), 128 * 1024):
            if data[position] != 255:
                break
            position += 1
            while position < len(data) and data[position] == 255:
                position += 1
            if position >= len(data):
                break
            marker = data[position]
            position += 1
            if marker in {0xD9, 0xDA}:
                break
            if marker == 0x01 or 0xD0 <= marker <= 0xD7:
                continue
            if position + 2 > len(data):
                break
            length = int.from_bytes(data[position:position + 2], "big")
            if length < 2 or position + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                return "image/jpeg", int.from_bytes(data[position + 5:position + 7], "big"), int.from_bytes(data[position + 3:position + 5], "big")
            position += length
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        kind = data[12:16]
        if kind == b"VP8X":
            return "image/webp", 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            return "image/webp", int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
        if kind == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return "image/webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise ValueError("attachment_image_type_invalid")


def validate_image_payload(encoded: str, mime_type: str, byte_size: int | None) -> int:
    if not encoded or len(encoded) > MAX_IMAGE_BASE64_LENGTH:
        raise ValueError("attachment_image_size_exceeded")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("attachment_image_base64_invalid") from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("attachment_image_size_exceeded")
    mime, width, height = _image_header(data)
    if mime_type != mime:
        raise ValueError("attachment_image_type_mismatch")
    if width <= 0 or height <= 0 or max(width, height) > MAX_IMAGE_EDGE or width * height > MAX_IMAGE_PIXELS:
        raise ValueError("attachment_image_dimensions_exceeded")
    if byte_size is not None and byte_size != len(data):
        raise ValueError("attachment_image_size_mismatch")
    # Header limits precede decode, so a decompression bomb is rejected without
    # allocating its claimed pixels. A correct header alone is not an image.
    try:
        with Image.open(BytesIO(data)) as decoded:
            if decoded.size != (width, height):
                raise ValueError("attachment_image_dimensions_mismatch")
            decoded.verify()
        with Image.open(BytesIO(data)) as decoded:
            decoded.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("attachment_image_decode_failed") from exc
    return len(data)
