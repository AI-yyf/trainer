#!/usr/bin/env python3
"""Generate deterministic PDF/EPUB fixtures for installed-GUI grounding checks."""

from __future__ import annotations

import base64
import io
import sys
import zipfile
from pathlib import Path

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "AAIAAAoAAv/lxKUAAAAASUVORK5CYII="
)


def make_pdf(path: Path) -> None:
    import pymupdf

    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), 0)
    pixmap.clear_with(210)
    image_bytes = pixmap.tobytes("png")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Attention Systems Notes\n\nPage one introduces the lock boundary and the diagram.",
        fontsize=12,
    )
    page.insert_image(pymupdf.Rect(72, 120, 172, 220), stream=image_bytes)
    page.insert_text((72, 250), "Formula: E = m c^2", fontsize=12)
    second = document.new_page()
    second.insert_text(
        (72, 72),
        "Quorum acknowledgement\n\nQuorum reads intersect the latest write.\n"
        "Release the lock in a finally block.",
        fontsize=12,
    )
    document.save(path)
    document.close()


def make_epub(path: Path) -> None:
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:language>en</dc:language></metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="img" href="images/diagram.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="ch1"/><itemref idref="ch2"/></spine>
</package>"""
    chapter_one = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Foundations</title></head><body>
<h1>Foundations</h1>
<p>Quorum reads intersect with the latest acknowledged write.</p>
<table><tr><th>Quorum</th><th>Meaning</th></tr>
<tr><td>R + W &gt; N</td><td>Reads see the latest write</td></tr></table>
<img src="images/diagram.png" alt="Quorum diagram"/>
</body></html>"""
    chapter_two = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Formulas</title></head><body>
<h1>Formulas</h1>
<p>The energy relation is <math><mi>E</mi><mo>=</mo><mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></math>.</p>
</body></html>"""
    import pymupdf

    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), 0)
    pixmap.clear_with(210)
    image_bytes = pixmap.tobytes("png")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/ch1.xhtml", chapter_one)
        archive.writestr("OEBPS/ch2.xhtml", chapter_two)
        archive.writestr("OEBPS/images/diagram.png", image_bytes)
    path.write_bytes(buffer.getvalue())


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: generate-grounding-fixtures.py <output-dir>", file=sys.stderr)
        return 2
    output = Path(sys.argv[1]).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    make_pdf(output / "attention-sample.pdf")
    make_epub(output / "systems-sample.epub")
    print(str(output / "attention-sample.pdf"))
    print(str(output / "systems-sample.epub"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
