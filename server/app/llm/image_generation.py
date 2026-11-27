"""Pedagogical and illustrative image generation for Trainer coach turns."""

from __future__ import annotations

import base64
import html
import logging
import math
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

logger = logging.getLogger("trainer.image_generation")

_SAFE_IMAGE_ID_RE = re.compile(r"^img_[a-z0-9_]{4,40}$")
_TRAINER_IMAGE_REF_RE = re.compile(r"trainer-image://(img_[a-z0-9_]{4,40})")
_SVG_BLOCK_RE = re.compile(r"<svg\b[^>]*>[\s\S]*?</svg>", re.IGNORECASE)
_SVG_DANGEROUS_TAG_RE = re.compile(
    r"<\s*(script|foreignObject|iframe|object|embed)\b[^>]*>[\s\S]*?<\s*/\s*\1\s*>|"
    r"<\s*(script|foreignObject|iframe|object|embed)\b[^>]*/>",
    re.IGNORECASE,
)
_SVG_EVENT_ATTR_RE = re.compile(
    r"\s+on[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)
_SVG_UNSAFE_HREF_RE = re.compile(
    r"(\s+(?:xlink:)?href\s*=\s*)([\"'])\s*(?:javascript:|vbscript:|data:text/html|https?:|//)[^\"']*\2",
    re.IGNORECASE,
)
_SVG_SHAPE_RE = re.compile(
    r"<\s*(rect|circle|ellipse|path|polygon|polyline|line|text|g)\b",
    re.IGNORECASE,
)

_ASPECT_DIMENSIONS: dict[str, tuple[tuple[int, int], str]] = {
    "16:9": ((960, 540), "1536x1024"),
    "4:3": ((960, 720), "1024x1024"),
    "1:1": ((768, 768), "1024x1024"),
    "3:4": ((720, 960), "1024x1536"),
}

_MIME_BY_SUFFIX: dict[str, str] = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

_STYLE_LABELS: dict[str, str] = {
    "diagram": "ARCHITECTURE & FLOW",
    "illustration": "CONCEPT VISUAL",
    "chart": "QUANTITATIVE VIEW",
    "photorealistic": "VISUAL SCENE",
}


def sanitize_generated_svg(svg_text: str) -> str:
    """Return a clean, self-contained `<svg>` string or empty string if unsafe/invalid."""
    raw = str(svg_text or "").strip()
    if not raw:
        return ""
    match = _SVG_BLOCK_RE.search(raw)
    if not match:
        return ""
    cleaned = match.group(0)
    cleaned = _SVG_DANGEROUS_TAG_RE.sub("", cleaned)
    cleaned = _SVG_EVENT_ATTR_RE.sub("", cleaned)
    cleaned = _SVG_UNSAFE_HREF_RE.sub(r"\1\2#\2", cleaned)
    # Reject CSS url(...) injections that point off-document
    cleaned = re.sub(
        r"url\(\s*(['\"]?)(?:https?:|//|javascript:)[^)]*\1\s*\)",
        "none",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not _SVG_SHAPE_RE.search(cleaned):
        return ""

    open_end = cleaned.find(">")
    if open_end < 0:
        return ""
    open_tag = cleaned[:open_end]
    if "xmlns=" not in open_tag:
        open_tag += ' xmlns="http://www.w3.org/2000/svg"'
    if "viewBox=" not in open_tag and "viewbox=" not in open_tag:
        open_tag += ' viewBox="0 0 960 540"'
    if "role=" not in open_tag:
        open_tag += ' role="img"'
    return open_tag + cleaned[open_end:]


def _visual_char_units(ch: str) -> float:
    return 1.8 if ord(ch) > 0x2E7F else 1.0


def _wrap_svg_label(text: str, *, max_units: float = 18.0, max_lines: int = 3) -> list[str]:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return []
    lines: list[str] = []
    current: list[str] = []
    units = 0.0
    for ch in clean:
        w = _visual_char_units(ch)
        if current and units + w > max_units:
            lines.append("".join(current).strip())
            current = [ch] if not ch.isspace() else []
            units = w if current else 0.0
            if len(lines) >= max_lines - 1:
                break
        else:
            current.append(ch)
            units += w
    consumed = sum(len(line) for line in lines) + len(current)
    if len(lines) < max_lines:
        tail = clean[sum(len(line) for line in lines) :].strip()
        if tail:
            if sum(_visual_char_units(c) for c in tail) > max_units + 2:
                trimmed: list[str] = []
                tail_units = 0.0
                for ch in tail:
                    w = _visual_char_units(ch)
                    if tail_units + w > max_units - 1.5:
                        break
                    trimmed.append(ch)
                    tail_units += w
                tail = "".join(trimmed).rstrip() + "…"
            lines.append(tail)
    elif current:
        # Already filled max_lines above; append ellipsis if truncated
        if consumed < len(clean) and lines:
            lines[-1] = lines[-1].rstrip(" .") + "…"
    return lines[:max_lines]


def _extract_prompt_stages(prompt: str, title: str) -> list[str]:
    clean = " ".join(str(prompt or "").split()).strip()
    if not clean:
        return [title or "Input", "Processing", "Output"]
    parts = [
        segment.strip(" .:-•*")
        for segment in re.split(r"(?:\s*(?:->|→|=>|;|；|\n)\s*|[,，、]\s*)", clean)
        if segment.strip(" .:-•*")
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(part)
        if len(deduped) >= 6:
            break
    if len(deduped) >= 2:
        return deduped
    words = clean.split()
    if len(words) >= 6:
        chunk_size = max(2, math.ceil(len(words) / 3))
        return [
            " ".join(words[idx : idx + chunk_size])
            for idx in range(0, len(words), chunk_size)
        ][:4]
    return [clean, "Core Mechanism", "Verified Output"]


def build_structured_fallback_svg(
    title: str,
    prompt: str,
    *,
    style: str = "diagram",
    width: int = 960,
    height: int = 540,
) -> str:
    """Build a crisp deterministic vector diagram when live image synthesis is unavailable."""
    display_title = " ".join(str(title or "").split()).strip() or "Visual Concept Diagram"
    badge_text = _STYLE_LABELS.get(style, "VISUAL DIAGRAM")
    stages = _extract_prompt_stages(prompt, display_title)
    count = max(2, min(len(stages), 6))
    stages = stages[:count]

    cols = count if count <= 4 else math.ceil(count / 2)
    rows = 1 if count <= 4 else 2

    margin_x = 48
    gap_x = 34 if cols <= 4 else 28
    top_y = 112 if rows == 1 else 104
    bottom_pad = 54
    area_w = width - (margin_x * 2)
    area_h = height - top_y - bottom_pad
    gap_y = 36
    card_w = (area_w - gap_x * (cols - 1)) / cols
    card_h = min(230.0 if rows == 1 else 155.0, (area_h - gap_y * (rows - 1)) / rows)
    start_y = top_y + max(0.0, (area_h - (card_h * rows + gap_y * (rows - 1))) / 2.0)

    accents = ["#2563eb", "#0891b2", "#4f46e5", "#0d9488", "#d97706", "#7c3aed"]
    card_nodes: list[str] = []
    arrow_nodes: list[str] = []
    centers: list[tuple[float, float, float, float]] = []

    for idx, stage in enumerate(stages):
        row = idx // cols
        col = idx % cols
        # Count items on this row so a partial second row stays visually centered
        items_in_row = cols if row < rows - 1 else (count - row * cols)
        row_total_w = items_in_row * card_w + max(0, items_in_row - 1) * gap_x
        row_start_x = (width - row_total_w) / 2.0
        x = row_start_x + col * (card_w + gap_x)
        y = start_y + row * (card_h + gap_y)
        centers.append((x, y, card_w, card_h))

        accent = accents[idx % len(accents)]
        lines = _wrap_svg_label(stage, max_units=max(12.0, card_w / 11.5), max_lines=3)
        line_start_y = y + (card_h / 2.0) - ((len(lines) - 1) * 11.0) + 12.0
        text_svg = "\n".join(
            f'<text x="{x + card_w / 2.0:.1f}" y="{line_start_y + line_i * 22:.1f}" '
            f'text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, sans-serif" '
            f'font-size="15" font-weight="600" fill="#0f172a">{html.escape(line)}</text>'
            for line_i, line in enumerate(lines)
        )
        card_nodes.append(
            f"""
  <g>
    <rect x="{x:.1f}" y="{y:.1f}" width="{card_w:.1f}" height="{card_h:.1f}" rx="14"
          fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5" />
    <rect x="{x:.1f}" y="{y:.1f}" width="{card_w:.1f}" height="6" rx="3" fill="{accent}" />
    <circle cx="{x + 24:.1f}" cy="{y + 28:.1f}" r="12" fill="{accent}" fill-opacity="0.12" />
    <text x="{x + 24:.1f}" y="{y + 33:.1f}" text-anchor="middle"
          font-family="ui-sans-serif, system-ui, -apple-system, sans-serif"
          font-size="12" font-weight="700" fill="{accent}">{idx + 1}</text>
    {text_svg}
  </g>"""
        )

    for idx in range(len(centers) - 1):
        x1, y1, w1, h1 = centers[idx]
        x2, y2, w2, h2 = centers[idx + 1]
        same_row = abs(y1 - y2) < 10.0
        if same_row:
            sx = x1 + w1 + 4
            sy = y1 + h1 / 2.0
            ex = x2 - 6
            ey = y2 + h2 / 2.0
            arrow_nodes.append(
                f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
                f'stroke="#64748b" stroke-width="2" marker-end="url(#trainer-arrow)" />'
            )
        else:
            sx = x1 + w1 / 2.0
            sy = y1 + h1 + 4
            ex = x2 + w2 / 2.0
            ey = y2 - 6
            mid_y = (sy + ey) / 2.0
            arrow_nodes.append(
                f'<path d="M {sx:.1f} {sy:.1f} L {sx:.1f} {mid_y:.1f} '
                f'L {ex:.1f} {mid_y:.1f} L {ex:.1f} {ey:.1f}" '
                f'fill="none" stroke="#64748b" stroke-width="2" '
                f'stroke-dasharray="5 4" marker-end="url(#trainer-arrow)" />'
            )

    safe_title = html.escape(_wrap_svg_label(display_title, max_units=52.0, max_lines=1)[0])
    safe_caption = html.escape(
        (_wrap_svg_label(prompt, max_units=78.0, max_lines=1) or [display_title])[0]
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{safe_title}">
  <defs>
    <linearGradient id="trainer-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8fafc" />
      <stop offset="100%" stop-color="#f1f5f9" />
    </linearGradient>
    <marker id="trainer-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 1 1 L 9 5 L 1 9 z" fill="#64748b" />
    </marker>
  </defs>
  <rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="url(#trainer-bg)" stroke="#e2e8f0" stroke-width="1.5" />
  <rect x="36" y="28" width="164" height="24" rx="12" fill="#e0f2fe" />
  <text x="118" y="44" text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="0.06em" fill="#0369a1">{html.escape(badge_text)}</text>
  <text x="36" y="80" font-family="ui-sans-serif, system-ui, -apple-system, sans-serif" font-size="22" font-weight="700" fill="#0f172a">{safe_title}</text>
  {"".join(arrow_nodes)}
  {"".join(card_nodes)}
  <text x="{width / 2.0:.1f}" y="{height - 20}" text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, sans-serif" font-size="12" fill="#475569">{safe_caption}</text>
</svg>"""


def _resolve_images_storage_dir(runtime: Any) -> Path:
    repo = getattr(runtime, "repository", None)
    db_path = getattr(repo, "database_path", None)
    if db_path is not None:
        return Path(db_path).expanduser().resolve(strict=False).parent / "generated-images"
    return Path(tempfile.gettempdir()) / "trainer-generated-images"


def _resolve_library_images_dir(runtime: Any, workspace_id: str) -> tuple[Path, str] | None:
    if runtime is None or not workspace_id:
        return None
    resource_service = getattr(runtime, "resource_service", None)
    if resource_service is None or not hasattr(resource_service, "_resolved_library_root"):
        return None
    library_root_raw = resource_service._resolved_library_root(workspace_id)
    if not library_root_raw:
        return None
    library_root = Path(str(library_root_raw)).expanduser().resolve(strict=False)
    if not library_root.is_dir():
        return None
    project_root_raw = (
        runtime.resolve_workspace_path(workspace_id)
        if hasattr(runtime, "resolve_workspace_path")
        else None
    )
    project_root = (
        Path(str(project_root_raw)).expanduser().resolve(strict=False)
        if project_root_raw
        else None
    )
    if project_root is not None and library_root == project_root:
        carrier_resolver = getattr(runtime, "library_carrier_authority", None)
        carrier: Any = carrier_resolver(workspace_id) if callable(carrier_resolver) else None
        if carrier is None or carrier.destructive_mutation_block_reason() is not None:
            return None
    rel_folder = "Trainer Library/Generated Images"
    return (library_root / "Trainer Library" / "Generated Images", rel_folder)


async def _try_provider_photorealistic_image(
    provider: Any,
    *,
    prompt: str,
    size: str,
) -> tuple[bytes, str] | None:
    config = getattr(provider, "_config", None)
    if config is None:
        return None
    protocol = str(getattr(config, "protocol", "") or "").lower()
    if protocol and "openai" not in protocol:
        return None
    base_url = str(getattr(config, "base_url", "") or "").strip().rstrip("/")
    if not base_url:
        return None
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    normalized_base = base_url
    if not parsed.path.rstrip("/").lower().endswith("/v1") and parsed.path.rstrip("/") in {"", "/"}:
        normalized_base = f"{base_url}/v1"
    endpoint = f"{normalized_base}/images/generations"
    api_key = str(getattr(provider, "_api_key", "") or "").strip()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    request_defaults = getattr(config, "request_defaults", None)
    if isinstance(request_defaults, dict):
        extra_headers = request_defaults.get("extra_headers") or request_defaults.get("extraHeaders")
        if isinstance(extra_headers, dict):
            for header_key, header_val in extra_headers.items():
                if isinstance(header_key, str) and isinstance(header_val, str) and header_key.strip():
                    headers[header_key.strip()] = header_val
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # gpt-image-1 always returns b64_json and rejects `response_format` with HTTP 400.
    payload = {
        "model": "gpt-image-1",
        "prompt": prompt[:2000],
        "size": size,
        "n": 1,
    }
    trust_env = not bool(getattr(config, "ignore_system_proxy", False))
    try:
        async with httpx.AsyncClient(timeout=25.0, trust_env=trust_env) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            if resp.status_code >= 400:
                return None
            data = resp.json()
    except Exception as exc:
        logger.debug("Suppressed exception in image_generation: %s", exc)
        return None
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    b64 = str(first.get("b64_json") or "").strip()
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as exc:
        logger.debug("Suppressed exception in image_generation: %s", exc)
        return None
    if not raw:
        return None
    return raw, "image/png"


async def _try_llm_svg_synthesis(
    provider: Any,
    *,
    prompt: str,
    title: str,
    style: str,
    width: int,
    height: int,
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You generate clean, readable educational SVG diagrams. Reply with ONLY a single "
                f"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 {width} {height}\">...</svg> "
                "document. Use rounded cards, directional arrows, clear concise labels (no overlapping "
                "text), and light readable card contrast (#ffffff/#f8fafc background, #0f172a text). "
                "Do NOT include <script>, <foreignObject>, external URLs, or inline event handlers."
            ),
        },
        {
            "role": "user",
            "content": f"Title: {title or 'Diagram'}\nStyle: {style}\nVisual specification: {prompt}",
        },
    ]
    try:
        if hasattr(provider, "_plain_completion_uses_agent_binding") and provider._plain_completion_uses_agent_binding():
            raw = await provider._completion_via_agent_binding(
                messages,
                temperature=0.25,
                max_tokens=4096,
                prefer_configured_output=False,
                allow_local_empty_fallback=True,
            )
        else:
            from .provider_service import _require_provider_runtime_response

            client = provider._get_client()
            response, _ = await provider._create_chat_completion(
                client=client,
                model=provider._resolve_model(),
                messages=messages,
                temperature=0.25,
                max_tokens=4096,
            )
            raw = _require_provider_runtime_response(
                "openai_chat_completions",
                response,
                api_key=getattr(provider, "_api_key", None),
                allow_local_empty_fallback=True,
            )
    except Exception:
        logger.debug("llm_svg_synthesis_fallback", exc_info=True)
        return ""
    return sanitize_generated_svg(raw)


def _slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", str(value or "").strip()).strip("-")
    return (slug[:42] or "visual").strip("-") or "visual"


async def generate_pedagogical_image(
    context: Any,
    *,
    prompt: str,
    title: str = "",
    style: str = "diagram",
    aspect_ratio: str = "16:9",
    save_to_library: bool = True,
) -> dict[str, Any]:
    """Generate a pedagogical visual image, persist it safely, and return a markdown reference."""
    clean_prompt = " ".join(str(prompt or "").split()).strip()
    if not clean_prompt:
        return {
            "ok": False,
            "error": "missing_prompt",
            "detail": "generate_image requires a visual description prompt.",
        }
    clean_style = str(style or "diagram").strip().lower()
    if clean_style not in _STYLE_LABELS:
        clean_style = "diagram"
    clean_ratio = str(aspect_ratio or "16:9").strip()
    (width, height), raster_size = _ASPECT_DIMENSIONS.get(clean_ratio, ((960, 540), "1536x1024"))
    clean_title = " ".join(str(title or "").split()).strip() or "Concept Diagram"

    runtime = getattr(context, "runtime", None)
    workspace_id = getattr(context, "workspace_id", None)
    workspace_provider = (
        runtime.workspace_provider_service(workspace_id)
        if runtime is not None and callable(getattr(runtime, "workspace_provider_service", None))
        else None
    )
    provider = workspace_provider or getattr(runtime, "provider_service", None)

    image_bytes: bytes | None = None
    mime_type = "image/svg+xml"
    mode = "structured_svg"

    if provider is not None and callable(getattr(provider, "has_usable_credential", None)) and provider.has_usable_credential():
        if clean_style == "photorealistic":
            photorealistic = await _try_provider_photorealistic_image(
                provider,
                prompt=clean_prompt,
                size=raster_size,
            )
            if photorealistic is not None:
                image_bytes, mime_type = photorealistic
                mode = "provider_image"
        if image_bytes is None:
            llm_svg = await _try_llm_svg_synthesis(
                provider,
                prompt=clean_prompt,
                title=clean_title,
                style=clean_style,
                width=width,
                height=height,
            )
            if llm_svg:
                image_bytes = llm_svg.encode("utf-8")
                mime_type = "image/svg+xml"
                mode = "llm_svg"

    if image_bytes is None:
        svg_doc = build_structured_fallback_svg(
            clean_title,
            clean_prompt,
            style=clean_style,
            width=width,
            height=height,
        )
        image_bytes = svg_doc.encode("utf-8")
        mime_type = "image/svg+xml"
        mode = "structured_svg"

    image_id = f"img_{uuid4().hex[:12]}"
    ext = ".png" if mime_type == "image/png" else ".svg"
    storage_dir = _resolve_images_storage_dir(runtime)
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / f"{image_id}{ext}"
    storage_path.write_bytes(image_bytes)

    library_path: str | None = None
    if save_to_library:
        workspace_id = str(getattr(context, "workspace_id", "") or "").strip()
        target_info = _resolve_library_images_dir(runtime, workspace_id)
        if target_info is not None:
            lib_dir, rel_folder = target_info
            lib_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{_slugify_filename(clean_title)}-{image_id[:8]}{ext}"
            lib_file = lib_dir / filename
            lib_file.write_bytes(image_bytes)
            library_path = f"{rel_folder}/{filename}"

    if runtime is not None and hasattr(runtime, "generated_images"):
        runtime.generated_images[image_id] = {
            "image_id": image_id,
            "title": clean_title,
            "mime_type": mime_type,
            "path": str(storage_path),
            "library_path": library_path,
            "style": clean_style,
            "mode": mode,
        }
    if hasattr(context, "extra") and isinstance(context.extra, dict):
        generated_list = context.extra.setdefault("generated_image_ids", [])
        if isinstance(generated_list, list) and image_id not in generated_list:
            generated_list.append(image_id)

    markdown = f"![{clean_title}](trainer-image://{image_id})"
    return {
        "ok": True,
        "image_id": image_id,
        "title": clean_title,
        "mime_type": mime_type,
        "style": clean_style,
        "aspect_ratio": clean_ratio,
        "mode": mode,
        "markdown": markdown,
        "library_path": library_path,
        "note": (
            f"图片已生成，请在回答中保留 `{markdown}` 以便直接渲染。"
            if getattr(context, "response_language", "") and str(context.response_language).lower().startswith("zh")
            else f"Image ready. Keep `{markdown}` in your reply so it renders directly."
        ),
    }


def load_generated_image(runtime: Any, image_id: str) -> tuple[bytes, str, str] | None:
    """Load `(bytes, mime_type, title)` for a validated `img_*` identifier."""
    clean_id = str(image_id or "").strip()
    if not _SAFE_IMAGE_ID_RE.fullmatch(clean_id):
        return None
    record = (
        runtime.generated_images.get(clean_id)
        if runtime is not None and hasattr(runtime, "generated_images")
        else None
    )
    if isinstance(record, dict):
        raw_path = record.get("path")
        if raw_path:
            path = Path(str(raw_path))
            if path.is_file():
                mime = str(record.get("mime_type") or _MIME_BY_SUFFIX.get(path.suffix.lower()) or "image/svg+xml")
                return (path.read_bytes(), mime, str(record.get("title") or "Generated Visual"))

    storage_dir = _resolve_images_storage_dir(runtime)
    if storage_dir.is_dir():
        for suffix, mime in _MIME_BY_SUFFIX.items():
            candidate = storage_dir / f"{clean_id}{suffix}"
            if candidate.is_file():
                return (candidate.read_bytes(), mime, "Generated Visual")
    return None


def resolve_generated_images_in_text(
    text: str,
    runtime: Any,
    generated_ids: list[str] | None = None,
) -> str:
    """Replace `trainer-image://img_*` URLs with portable data URIs and append missing visuals."""
    source = str(text or "")
    referenced: set[str] = set()

    def _replace(match: re.Match[str]) -> str:
        image_id = match.group(1)
        referenced.add(image_id)
        loaded = load_generated_image(runtime, image_id)
        if loaded is None:
            return match.group(0)
        raw_bytes, mime, _title = loaded
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    resolved = _TRAINER_IMAGE_REF_RE.sub(_replace, source)
    missing_blocks: list[str] = []
    for image_id in generated_ids or []:
        if image_id in referenced:
            continue
        loaded = load_generated_image(runtime, image_id)
        if loaded is None:
            continue
        raw_bytes, mime, title = loaded
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        missing_blocks.append(f"![{title}](data:{mime};base64,{encoded})")
    if missing_blocks:
        sep = "\n\n" if resolved.strip() else ""
        resolved = f"{resolved.rstrip()}{sep}" + "\n\n".join(missing_blocks)
    return resolved


__all__ = [
    "build_structured_fallback_svg",
    "generate_pedagogical_image",
    "load_generated_image",
    "resolve_generated_images_in_text",
    "sanitize_generated_svg",
]
