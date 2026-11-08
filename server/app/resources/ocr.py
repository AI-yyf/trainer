"""Optional OCR for images and scanned PDF pages.

Tesseract is a host capability, not a hard dependency. When it is missing the
caller gets an explicit warning and must keep the resource metadata-only; no
text is invented.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass(slots=True)
class OcrResult:
    text: str = ""
    warnings: list[str] = field(default_factory=list)
    engine: str = "tesseract"
    available: bool = False


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_image_bytes(
    data: bytes,
    *,
    timeout: float = 30.0,
    language: str | None = None,
) -> OcrResult:
    """Run tesseract on encoded image bytes without writing a temp file."""

    if not data:
        return OcrResult(warnings=["OCR skipped: the image payload is empty."])
    binary = shutil.which("tesseract")
    if binary is None:
        return OcrResult(
            warnings=["Tesseract is not installed; OCR and scanned-PDF transcription were skipped."],
            available=False,
        )
    command = [binary, "stdin", "stdout"]
    if language:
        command.extend(["-l", language])
    try:
        completed = subprocess.run(
            command,
            input=data,
            capture_output=True,
            timeout=max(1.0, timeout),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return OcrResult(
            warnings=[f"OCR failed: {exc}."],
            available=True,
        )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        reason = detail[-1] if detail else f"exit {completed.returncode}"
        return OcrResult(
            warnings=[f"OCR failed: {reason}."],
            available=True,
        )
    text = completed.stdout.decode("utf-8", "replace").strip()
    return OcrResult(text=text, available=True)
