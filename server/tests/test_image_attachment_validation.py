from __future__ import annotations

import base64
import struct

import fitz
import pytest
from PIL import Image
from pydantic import ValidationError

from app.core.image_attachments import MAX_IMAGE_BASE64_LENGTH, validate_image_payload
from app.core.models import MessageAttachment, SessionMessageRequest
from app.llm.vision_challenge import build_vision_challenge


def png_bytes() -> bytes:
    return base64.b64decode(build_vision_challenge().image_url.split(",", 1)[1])


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "image/gif", "image/webp"])
def test_real_image_bytes_are_decoded_and_size_is_derived(mime: str) -> None:
    data = png_bytes()
    if mime == "image/jpeg":
        data = fitz.Pixmap(data).tobytes("jpeg")
    elif mime == "image/gif":
        data = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
    elif mime == "image/webp":
        data = base64.b64decode("UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoCAAIAAUAmJaQAA3AA/v02aAA=")
    attachment = MessageAttachment.model_validate({
        "mimeType": mime, "dataBase64": base64.b64encode(data).decode(),
    })
    assert attachment.byte_size == len(data)


def test_declared_type_and_size_cannot_override_actual_bytes() -> None:
    data = png_bytes()
    encoded = base64.b64encode(data).decode()
    with pytest.raises(ValueError, match="type_mismatch"):
        validate_image_payload(encoded, "image/jpeg", len(data))
    with pytest.raises(ValueError, match="size_mismatch"):
        validate_image_payload(encoded, "image/png", 1)


def test_oversized_base64_is_rejected_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_decode(*_args: object, **_kwargs: object) -> bytes:
        pytest.fail("oversized transport reached base64 decode")
    monkeypatch.setattr(base64, "b64decode", unexpected_decode)
    with pytest.raises(ValueError, match="size_exceeded"):
        validate_image_payload("A" * (MAX_IMAGE_BASE64_LENGTH + 1), "image/png", None)


def test_bomb_dimensions_are_rejected_before_pixel_allocation(monkeypatch: pytest.MonkeyPatch) -> None:
    data = bytearray(png_bytes())
    data[16:24] = struct.pack(">II", 8192, 8192)
    def unexpected_decode(*_args: object, **_kwargs: object) -> None:
        pytest.fail("oversized dimensions reached image decode")
    monkeypatch.setattr(Image, "open", unexpected_decode)
    with pytest.raises(ValueError, match="dimensions_exceeded"):
        validate_image_payload(base64.b64encode(data).decode(), "image/png", None)


@pytest.mark.parametrize("data", [b"hello", b"\x89PNG\r\n\x1a\n", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 1, 1)])
def test_a_filename_or_header_alone_is_not_an_image(data: bytes) -> None:
    with pytest.raises(ValueError):
        validate_image_payload(base64.b64encode(data).decode(), "image/png", None)


def test_invalid_base64_and_excess_attachment_count_fail_request_validation() -> None:
    with pytest.raises(ValidationError, match="base64_invalid"):
        MessageAttachment.model_validate({"dataBase64": "xx"})
    item = {"dataBase64": base64.b64encode(png_bytes()).decode()}
    with pytest.raises(ValidationError, match="at most 4 items"):
        SessionMessageRequest.model_validate({"message": "inspect", "attachments": [item] * 5})


def test_request_total_uses_validated_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Lower only the request aggregate budget; each item must still decode.
    data = png_bytes()
    monkeypatch.setattr("app.core.models.MAX_TOTAL_IMAGE_BYTES", len(data) * 2 - 1)
    item = {"dataBase64": base64.b64encode(data).decode()}
    with pytest.raises(ValidationError, match="total_size_exceeded"):
        SessionMessageRequest.model_validate({"message": "inspect", "attachments": [item, item]})
