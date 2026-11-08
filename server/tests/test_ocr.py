"""OCR is optional and must never fabricate text when unavailable."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.resources.ocr import ocr_available, ocr_image_bytes


def test_ocr_reports_missing_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.resources.ocr.shutil.which", lambda _name: None)
    result = ocr_image_bytes(b"image-bytes")
    assert result.text == ""
    assert result.available is False
    assert any("Tesseract is not installed" in warning for warning in result.warnings)


def test_ocr_returns_tesseract_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.resources.ocr.shutil.which", lambda _name: "/usr/bin/tesseract")

    class Completed:
        returncode = 0
        stdout = b"Queue lock protects shared items\n"
        stderr = b""

    monkeypatch.setattr(
        "app.resources.ocr.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )
    result = ocr_image_bytes(b"image-bytes")
    assert result.available is True
    assert result.text == "Queue lock protects shared items"


@pytest.mark.skipif(not ocr_available(), reason="tesseract is not installed")
def test_real_tesseract_reads_rendered_text(tmp_path: Path) -> None:
    image_module = pytest.importorskip("PIL.Image")
    draw_module = pytest.importorskip("PIL.ImageDraw")
    image = image_module.new("RGB", (900, 220), "white")
    draw_module.Draw(image).text((30, 70), "Queue lock protects shared items", fill="black")
    path = tmp_path / "queue.png"
    image.save(path)
    result = ocr_image_bytes(path.read_bytes())
    assert "Queue" in result.text
