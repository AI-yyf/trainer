from __future__ import annotations

import html
import re
import tempfile
from pathlib import Path

import pymupdf

_FENCE_RE = re.compile(r"^\s*```(?P<lang>[A-Za-z0-9_+-]*)\s*$")
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_UL_RE = re.compile(r"^\s*[-*+]\s+(.+)$")
_OL_RE = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$")


def _format_inline_html(text: str) -> str:
    """Convert inline Markdown spans (code, bold, italic, links) into escaped HTML."""
    tokens: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        idx = len(tokens)
        tokens.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00CODE{idx}\x00"

    protected = re.sub(r"`([^`\n]+)`", _stash_code, text)
    escaped = html.escape(protected, quote=False)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    for idx, replacement in enumerate(tokens):
        escaped = escaped.replace(f"\x00CODE{idx}\x00", replacement)
    return escaped


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def markdown_to_export_html(title: str, markdown_text: str) -> str:
    """Render Markdown notes/materials into a clean, print-ready HTML document."""
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parts: list[str] = []
    if title.strip():
        parts.append(f'<div class="doc-meta">{html.escape(title.strip())}</div>')

    i = 0
    in_ul = False
    in_ol = False

    def _close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            parts.append("</ul>")
            in_ul = False
        if in_ol:
            parts.append("</ol>")
            in_ol = False

    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence:
            _close_lists()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code_html = html.escape("\n".join(code_lines))
            parts.append(f"<pre><code>{code_html}</code></pre>")
            i += 1
            continue

        if (
            "|" in line
            and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1])
        ):
            _close_lists()
            headers = _split_table_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_table_row(lines[i]))
                i += 1
            thead = "".join(f"<th>{_format_inline_html(cell)}</th>" for cell in headers)
            tbody_rows = []
            for row in rows:
                padded = row + [""] * max(0, len(headers) - len(row))
                tds = "".join(f"<td>{_format_inline_html(cell)}</td>" for cell in padded[: len(headers)])
                tbody_rows.append(f"<tr>{tds}</tr>")
            parts.append(
                f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(tbody_rows)}</tbody></table>"
            )
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            _close_lists()
            level = min(6, len(heading.group(1)))
            parts.append(f"<h{level}>{_format_inline_html(heading.group(2))}</h{level}>")
            i += 1
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            _close_lists()
            quote_lines = [quote.group(1)]
            i += 1
            while i < len(lines):
                nxt = _QUOTE_RE.match(lines[i])
                if not nxt:
                    break
                quote_lines.append(nxt.group(1))
                i += 1
            parts.append(f"<blockquote>{_format_inline_html(' '.join(quote_lines))}</blockquote>")
            continue

        ul_match = _UL_RE.match(line)
        if ul_match:
            if in_ol:
                parts.append("</ol>")
                in_ol = False
            if not in_ul:
                parts.append("<ul>")
                in_ul = True
            parts.append(f"<li>{_format_inline_html(ul_match.group(1))}</li>")
            i += 1
            continue

        ol_match = _OL_RE.match(line)
        if ol_match:
            if in_ul:
                parts.append("</ul>")
                in_ul = False
            if not in_ol:
                parts.append("<ol>")
                in_ol = True
            parts.append(f"<li>{_format_inline_html(ol_match.group(1))}</li>")
            i += 1
            continue

        if not line.strip():
            _close_lists()
            i += 1
            continue

        if re.match(r"^\s*([-*_])\1{2,}\s*$", line):
            _close_lists()
            parts.append("<hr />")
            i += 1
            continue

        _close_lists()
        para_lines = [line.strip()]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if (
                not nxt.strip()
                or _FENCE_RE.match(nxt)
                or _HEADING_RE.match(nxt)
                or _UL_RE.match(nxt)
                or _OL_RE.match(nxt)
                or _QUOTE_RE.match(nxt)
                or ("|" in nxt and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]))
            ):
                break
            para_lines.append(nxt.strip())
            i += 1
        parts.append(f"<p>{_format_inline_html(' '.join(para_lines))}</p>")

    _close_lists()

    css = """
    body {
      font-family: "china-s", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
      font-size: 10.5pt;
      line-height: 1.62;
      color: #1e293b;
    }
    .doc-meta {
      font-size: 8.5pt;
      color: #64748b;
      margin-bottom: 10px;
      padding-bottom: 4px;
      border-bottom: 1px solid #e2e8f0;
    }
    h1 { font-size: 17pt; color: #0f172a; margin: 14px 0 8px; padding-bottom: 4px; border-bottom: 1.5px solid #cbd5e1; }
    h2 { font-size: 13.5pt; color: #191642; margin: 12px 0 6px; }
    h3 { font-size: 11.5pt; color: #1e293b; margin: 10px 0 4px; }
    h4, h5, h6 { font-size: 10.5pt; color: #334155; margin: 8px 0 4px; }
    p { margin: 0 0 8px; }
    ul, ol { margin: 4px 0 8px; padding-left: 20px; }
    li { margin-bottom: 3px; }
    blockquote {
      margin: 8px 0;
      padding: 6px 10px;
      border-left: 3px solid #4338ca;
      background-color: #f8fafc;
      color: #334155;
    }
    code {
      font-family: "Menlo", "Consolas", "Courier New", monospace, "china-s";
      font-size: 9pt;
      background-color: #f1f5f9;
      padding: 1px 4px;
    }
    pre {
      font-family: "Menlo", "Consolas", "Courier New", monospace, "china-s";
      font-size: 8.8pt;
      line-height: 1.48;
      background-color: #f8fafc;
      border: 1px solid #cbd5e1;
      padding: 8px 10px;
      margin: 8px 0;
      white-space: pre-wrap;
      word-break: break-word;
    }
    pre code { background-color: transparent; padding: 0; }
    table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 9.5pt; }
    th, td { border: 1px solid #cbd5e1; padding: 5px 7px; text-align: left; vertical-align: top; }
    th { background-color: #f1f5f9; color: #0f172a; font-weight: bold; }
    a { color: #312e81; text-decoration: underline; }
    hr { border: none; border-top: 1px solid #cbd5e1; margin: 10px 0; }
    """
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<style>{css}</style></head><body>{''.join(parts)}</body></html>"
    )


def render_markdown_pdf_bytes(title: str, markdown_text: str) -> bytes:
    """Render a UTF-8 Markdown document into a compact paginated PDF binary."""
    html_doc = markdown_to_export_html(title, markdown_text)
    story = pymupdf.Story(html=html_doc)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (42, 42, -42, -42)
    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_path = Path(tmp_dir) / "rendered.pdf"
        writer = pymupdf.DocumentWriter(str(raw_path))
        more = True
        while more:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev, None)
            writer.end_page()
        writer.close()
        doc = pymupdf.open(str(raw_path))
        try:
            doc.subset_fonts()
            return doc.tobytes(deflate=True, garbage=3)
        finally:
            doc.close()
